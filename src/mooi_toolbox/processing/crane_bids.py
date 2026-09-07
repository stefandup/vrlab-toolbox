"""Crane-specific raw-to-BIDS conversion logic: parsing crane's raw flat-file naming,
matching the shared REDCAP debrief export to subjects, and orchestrating the copy into a
BIDS-shaped output folder. Generic BIDS mechanics (scans.tsv, filename building, duplicate
collision, JSON correction maps) live in `processing/bids.py` and are reused here.

See docs/bids_converter_plan.md. Never touches `input_folder` -- only ever copies into
`output_folder`. Dumps every matching file it finds, duplicates included; picking a
canonical file among duplicates is the crosscheck tool's job, not this converter's.

Incremental by subject: a subject whose `sub-XXX/` folder already exists in `output_folder`
is left completely alone and skipped, so re-running against a source folder that's since
gained new subjects only ever adds those.

Dates are never put in a filename (not real BIDS) -- each copied file gets a row in its
session's `sub-XXX/ses-01/sub-XXX_ses-01_scans.tsv` sidecar instead. Values are carried
through unchanged from the raw filenames' date prefixes -- not reliably parseable as real
calendar dates, so no attempt is made to normalize them into true ISO8601 here. Use the
crosscheck tool's "Correct date..." button to fix wrong ones.

Output layout:
- Every file goes in `sub-XXX/ses-01/beh/`, mirroring FOH's `sub-XXX/eeg/` layout, so
  `bids_crosscheck.record_task_tag`'s parent-folder rename is a same-name no-op instead of
  renaming the whole session folder.
- `ses-01`/`run-001` are fixed placeholders -- crane has no real multi-session or multi-run
  concept today.
- Scan type is identified by filename *suffix* (`_physio`/`_events`/`_beh`), not extension
  alone, since behaviour and debrief now share `.tsv`. Every filename also carries an
  `acq-<label>` entity naming which raw source it came from.
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table

from mooi_toolbox.processing import bids
from mooi_toolbox.processing.bids_crosscheck import SUBJECT_FOLDER_PREFIX, existing_subject_ids
from mooi_toolbox.processing.crane_debrief_behaviour import (
    GROUP_REDCAP_GLOB,
    crane_raw_debrief_file_schema,
)

logger = logging.getLogger(__name__)

PHYSIOLOGY_GLOB = "*_CraneOut.mat"
BEHAVIOUR_GLOB = "*_CraneOut.csv"
DATATYPE_FOLDER_NAME = "beh"
SESSION_TOKEN = "ses-01"
RUN_TOKEN = "run-001"
TASK_TOKEN = "task-crane"
# Real filenames are `{date}_{subject_id}_CraneOut.{ext}`, but the date prefix isn't always
# there, and is sometimes joined with "-" instead of "_" (e.g. "20267291154-PID5562_CraneOut").
# `biopac.get_subject_id_from_mat`'s naive `split("_")[1]` breaks on both; this regex handles
# both without touching biopac.py.
_SUBJECT_ID_PATTERN = re.compile(
    r"^(?:(?P<date>\d+)[_-])?(?P<subject_id>.+?)_CraneOut$", re.IGNORECASE
)
# A subject id can carry a trailing " (N)" marker -- sometimes a harmless duplicate-copy
# artifact, sometimes two genuinely different subjects sharing a base id. Unresolvable from
# the filename alone, so it's routed to the crosscheck GUI for a human decision instead.
_DUPLICATE_COPY_MARKER_PATTERN = re.compile(r"\(\d+\)\s*$")
# The same real subject gets written inconsistently as "PID-1234" and "PID1234" --
# canonicalized to the no-dash form wherever a subject id is derived.
_PID_DASH_PATTERN = re.compile(r"^PID-(\d+)$", re.IGNORECASE)


def canonicalize_subject_id(subject_id: str) -> str:
    match = _PID_DASH_PATTERN.match(subject_id)
    if match:
        return f"PID{match.group(1)}"
    return subject_id


def guess_corrected_subject_id(record_id: str) -> str:
    """Best-effort auto-fix for a mismatched debrief `record_id` -- strips stray whitespace
    and a spurious trailing ".0" (from a numeric-looking id read without a string dtype
    hint), then canonicalizes. Used as the crosscheck GUI's pre-filled correction guess.
    """
    guess = record_id.strip()
    if guess.endswith(".0") and guess[:-2].isdigit():
        guess = guess[:-2]
    return canonicalize_subject_id(guess)


@dataclass
class ParsedCraneFilename:
    subject_id: str
    date_prefix: str | None


def parse_crane_filename(file: Path) -> ParsedCraneFilename | None:
    """Subject id + date prefix from a raw crane filename's stem, in one pass. Returns None
    if the filename doesn't match the expected shape, or if the id carries an ambiguous
    "(N)" duplicate-copy marker -- callers must handle None (skip + log), not guess.
    """
    match = _SUBJECT_ID_PATTERN.match(file.stem)
    if match is None:
        return None
    subject_id = match.group("subject_id")
    if _DUPLICATE_COPY_MARKER_PATTERN.search(subject_id):
        return None
    return ParsedCraneFilename(
        subject_id=canonicalize_subject_id(subject_id),
        date_prefix=match.group("date"),
    )


def extract_subject_id(file: Path) -> str | None:
    parsed = parse_crane_filename(file)
    return parsed.subject_id if parsed is not None else None


def explain_unparseable_filename(file: Path) -> str:
    """Plain-English reason `parse_crane_filename` returned None, for the crosscheck GUI's
    raw-filename correction dialog.
    """
    stem = file.stem
    if not re.search(r"_CraneOut$", stem, re.IGNORECASE):
        return 'Filename doesn\'t end in "_CraneOut" -- not recognized as crane raw data at all.'
    remainder = re.sub(r"_CraneOut$", "", stem, flags=re.IGNORECASE)
    if not remainder.strip():
        return 'Nothing before "_CraneOut" to use as a subject id.'
    match = _SUBJECT_ID_PATTERN.match(stem)
    if match is not None and _DUPLICATE_COPY_MARKER_PATTERN.search(match.group("subject_id")):
        return (
            'Ends in a "(N)" marker -- could be a harmless duplicate copy of the same '
            "recording, or two different subjects that happen to share a base id. Declare "
            "which below."
        )
    return 'Ends in "_CraneOut" but the id portion still didn\'t match the expected pattern.'


def resolve_crane_filename(
    file: Path, input_folder: Path, corrections: dict[str, str]
) -> ParsedCraneFilename | None:
    """Like `parse_crane_filename`, but checks a human-declared correction first (see
    `load_raw_filename_id_corrections`), keyed by the file's path relative to `input_folder`.
    Still tries to recover a real date prefix even when a correction overrides the subject
    id. `convert_crane_to_bids` falls back to "nodate" only when this still comes back None.
    """
    try:
        key = file.relative_to(input_folder).as_posix()
    except ValueError:
        key = file.name
    corrected_subject_id = corrections.get(key)
    if corrected_subject_id:
        match = _SUBJECT_ID_PATTERN.match(file.stem)
        date_prefix = match.group("date") if match is not None else None
        return ParsedCraneFilename(
            subject_id=canonicalize_subject_id(corrected_subject_id), date_prefix=date_prefix
        )
    return parse_crane_filename(file)


def discover_raw_subject_ids(input_folder: Path) -> set[str]:
    """Every subject id derivable from raw physiology/behaviour filenames, read-only -- used
    by the crosscheck GUI's debrief record-id correction dialog.
    """
    ids: set[str] = set()
    for file in (*input_folder.rglob(PHYSIOLOGY_GLOB), *input_folder.rglob(BEHAVIOUR_GLOB)):
        subject_id = extract_subject_id(file)
        if subject_id is not None:
            ids.add(subject_id)
    return ids


def discover_raw_files_for_review(input_folder: Path) -> list[Path]:
    """Every raw physiology/behaviour file in `input_folder`, read-only, regardless of
    whether it currently resolves to a subject id -- lets the crosscheck GUI's raw-filename
    correction dialog review or override any of them, not only ones that fail to parse.
    """
    return sorted(
        (*input_folder.rglob(PHYSIOLOGY_GLOB), *input_folder.rglob(BEHAVIOUR_GLOB)),
        key=lambda file: file.relative_to(input_folder).as_posix(),
    )


DEBRIEF_ID_CORRECTIONS_FILENAME = "debrief_id_corrections.json"
RAW_FILENAME_ID_CORRECTIONS_FILENAME = "raw_filename_id_corrections.json"


def load_debrief_id_corrections(bids_folder: Path) -> dict[str, str]:
    return bids.load_json_map(bids_folder / DEBRIEF_ID_CORRECTIONS_FILENAME)


def save_debrief_id_corrections(bids_folder: Path, corrections: dict[str, str]) -> None:
    bids.save_json_map(bids_folder / DEBRIEF_ID_CORRECTIONS_FILENAME, corrections)


def load_raw_filename_id_corrections(bids_folder: Path) -> dict[str, str]:
    return bids.load_json_map(bids_folder / RAW_FILENAME_ID_CORRECTIONS_FILENAME)


def save_raw_filename_id_corrections(bids_folder: Path, corrections: dict[str, str]) -> None:
    bids.save_json_map(bids_folder / RAW_FILENAME_ID_CORRECTIONS_FILENAME, corrections)


def debrief_correction_key(record_id: str, occurrence_index: int) -> str:
    """Key into `debrief_id_corrections.json` for one *row* of the debrief export -- plain
    `record_id` for its first occurrence, `"{record_id}#{n}"` for later ones, since two
    different subjects can submit the exact same literal `record_id`.
    """
    return record_id if occurrence_index == 0 else f"{record_id}#{occurrence_index}"


def apply_debrief_id_corrections(
    record_id_column: pd.Series, corrections: dict[str, str]
) -> pd.Series:
    """Corrects each row of `record_id_column` individually, keyed by `debrief_correction_key`
    -- unlike a plain value-keyed replace, this can assign two different corrected subject
    ids to two rows sharing the same literal record_id.
    """
    occurrence_counters: dict[str, int] = {}
    corrected: list[str] = []
    for record_id in record_id_column.astype(str):
        occurrence_index = occurrence_counters.get(record_id, 0)
        occurrence_counters[record_id] = occurrence_index + 1
        key = debrief_correction_key(record_id, occurrence_index)
        corrected.append(corrections.get(key, record_id))
    return pd.Series(corrected, index=record_id_column.index)


def find_debrief_export(input_folder: Path, override: Path | None = None) -> Path | None:
    """Locate the shared REDCAP group export. `override`, given, is used as-is. Otherwise
    searches recursively for `GROUP_REDCAP_GLOB`, the same pattern
    `crane_debrief_behaviour.get_group_debrief_data` matches for the real pipeline.

    Public so `gui/crane_bids_crosscheck_gui.py` can also call it with just `input_folder`,
    to show which file auto-detection currently resolves to.
    """
    if override is not None:
        return override

    candidates = sorted(input_folder.rglob(GROUP_REDCAP_GLOB))
    if not candidates:
        logger.warning(
            "No file matching %r found in %s -- skipping debrief entirely",
            GROUP_REDCAP_GLOB,
            input_folder,
        )
        return None

    if len(candidates) > 1:
        logger.warning(
            "Multiple files matching %r found -- using %s: %s",
            GROUP_REDCAP_GLOB,
            candidates[0].name,
            ", ".join(path.name for path in candidates),
        )
    return candidates[0]


def load_debrief_export(input_folder: Path, override: Path | None = None) -> pd.DataFrame | None:
    """Read+filter the shared REDCAP group export -- one already-wide row per subject.
    Filtered against `crane_raw_debrief_file_schema`'s column set (not validated -- this
    converter dumps, doesn't decide) so its debrief columns never drift from what the real
    pipeline expects.
    """
    export_path = find_debrief_export(input_folder, override)
    if export_path is None:
        return None

    df = pd.read_csv(export_path)
    return df.filter(items=list(crane_raw_debrief_file_schema.columns))


def _has_debrief_file(output_folder: Path, subject_id: str) -> bool:
    subject_folder = output_folder / f"{SUBJECT_FOLDER_PREFIX}{subject_id}"
    datatype_folder = subject_folder / SESSION_TOKEN / DATATYPE_FOLDER_NAME
    return datatype_folder.is_dir() and any(datatype_folder.glob("*_beh.tsv"))


def _session_folder(output_folder: Path, subject_id: str) -> Path:
    folder = output_folder / f"{SUBJECT_FOLDER_PREFIX}{subject_id}" / SESSION_TOKEN
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _datatype_folder(output_folder: Path, subject_id: str) -> Path:
    folder = _session_folder(output_folder, subject_id) / DATATYPE_FOLDER_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _scans_tsv_path(output_folder: Path, subject_id: str) -> Path:
    return _session_folder(output_folder, subject_id) / (
        f"{SUBJECT_FOLDER_PREFIX}{subject_id}_{SESSION_TOKEN}_scans.tsv"
    )


def _existing_acq_date(output_folder: Path, subject_id: str) -> str | None:
    """Best-effort acquisition date for a subject already converted in an earlier run --
    used only for dating a backfilled debrief file's own row consistently with its siblings.
    """
    rows = bids.read_scans_tsv_rows(_scans_tsv_path(output_folder, subject_id))
    return rows[0]["acq_time"] if rows else None


def _bids_filename(subject_id: str, acq: str, suffix: str, extension: str) -> str:
    return bids.build_bids_filename(
        subject_id, SESSION_TOKEN, TASK_TOKEN, RUN_TOKEN, suffix, extension, acq=acq
    )


def _resolve_destination(
    output_folder: Path, subject_id: str, acq: str, suffix: str, extension: str
) -> Path:
    datatype_folder = _datatype_folder(output_folder, subject_id)
    return bids.resolve_collision(
        lambda candidate_suffix: (
            datatype_folder / _bids_filename(subject_id, acq, candidate_suffix, extension)
        ),
        suffix,
    )


def _copy_into_subject_folder(
    source: Path, output_folder: Path, subject_id: str, acq_date: str, acq: str, suffix: str
) -> Path:
    destination = _resolve_destination(output_folder, subject_id, acq, suffix, source.suffix)
    bids.copy_scan(source, destination, _scans_tsv_path(output_folder, subject_id), acq_date)
    return destination


def _copy_into_subject_folder_as_tsv(
    source: Path, output_folder: Path, subject_id: str, acq_date: str, acq: str, suffix: str
) -> Path:
    destination = _resolve_destination(output_folder, subject_id, acq, suffix, ".tsv")
    scans_tsv_path = _scans_tsv_path(output_folder, subject_id)
    bids.write_scan_as_tsv(source, destination, scans_tsv_path, acq_date)
    return destination


@dataclass
class CraneConversionSummary:
    """Everything a caller (the CLI's `main()`, or the crosscheck GUI's "Convert to BIDS..."
    button) needs to report what a `convert_crane_to_bids()` call actually did. Warnings/skips
    are also emitted via the module `logger` as they happen -- this is the end-of-run rollup.
    """

    new_subject_ids: list[str] = field(default_factory=list)
    subject_physiology: dict[str, list[Path]] = field(default_factory=dict)
    subject_behaviour: dict[str, list[Path]] = field(default_factory=dict)
    subject_debrief: dict[str, Path] = field(default_factory=dict)
    already_converted: set[str] = field(default_factory=set)
    skipped_files: int = 0
    unmatched_debrief: list[str] = field(default_factory=list)
    backfilled_debrief_ids: list[str] = field(default_factory=list)
    unparseable_files: list[Path] = field(default_factory=list)


def convert_crane_to_bids(
    input_folder: Path, output_folder: Path, debrief_export: Path | None = None
) -> CraneConversionSummary:
    """Core, UI-agnostic conversion logic -- see module docstring for the output layout.
    Progress/problems go through the standard `logger`, not print/rich, so both the CLI and
    the crosscheck GUI's "Convert to BIDS..." button can drive this and display the result
    their own way.

    `debrief_export`, if given, overrides auto-detection of the shared REDCAP group export --
    for when there's more than one file matching `GROUP_REDCAP_GLOB` in `input_folder`.
    """
    output_folder.mkdir(parents=True, exist_ok=True)
    already_converted = existing_subject_ids(output_folder)

    # Recursive, like every real pipeline lookup this mirrors -- raw files aren't guaranteed
    # to sit directly at input_folder's top level.
    physiology_files = sorted(input_folder.rglob(PHYSIOLOGY_GLOB))
    behaviour_files = sorted(input_folder.rglob(BEHAVIOUR_GLOB))
    debrief_df = load_debrief_export(input_folder, debrief_export)
    debrief_id_corrections: dict[str, str] = {}
    if debrief_df is not None:
        debrief_id_corrections = load_debrief_id_corrections(output_folder)
        if debrief_id_corrections:
            debrief_df["record_id"] = apply_debrief_id_corrections(
                debrief_df["record_id"], debrief_id_corrections
            )

    raw_filename_corrections = load_raw_filename_id_corrections(output_folder)

    subject_physiology: dict[str, list[Path]] = defaultdict(list)
    subject_behaviour: dict[str, list[Path]] = defaultdict(list)
    subject_debrief: dict[str, Path] = {}
    subject_acq_date: dict[str, str] = {}
    skipped_files = 0
    unparseable_files: list[Path] = []

    for mat_file in physiology_files:
        parsed = resolve_crane_filename(mat_file, input_folder, raw_filename_corrections)
        if parsed is None:
            unparseable_files.append(mat_file)
            continue
        if parsed.subject_id in already_converted:
            skipped_files += 1
            continue
        acq_date = parsed.date_prefix or "nodate"
        subject_acq_date.setdefault(parsed.subject_id, acq_date)
        destination = _copy_into_subject_folder(
            mat_file, output_folder, parsed.subject_id, acq_date, "physiology", "physio"
        )
        subject_physiology[parsed.subject_id].append(destination)

    for csv_file in behaviour_files:
        parsed = resolve_crane_filename(csv_file, input_folder, raw_filename_corrections)
        if parsed is None:
            unparseable_files.append(csv_file)
            continue
        if parsed.subject_id in already_converted:
            skipped_files += 1
            continue
        acq_date = parsed.date_prefix or "nodate"
        subject_acq_date.setdefault(parsed.subject_id, acq_date)
        destination = _copy_into_subject_folder_as_tsv(
            csv_file, output_folder, parsed.subject_id, acq_date, "behaviour", "events"
        )
        subject_behaviour[parsed.subject_id].append(destination)

    if unparseable_files:
        logger.warning(
            "Could not extract a subject id from %d filename(s) -- skipped entirely, not "
            "copied: %s",
            len(unparseable_files),
            ", ".join(f.name for f in unparseable_files),
        )

    new_subject_ids = sorted(set(subject_physiology) | set(subject_behaviour))

    if debrief_id_corrections:
        # A corrected record_id that doesn't match any known subject would otherwise vanish
        # silently -- checked against the same known-id set used everywhere else, so a
        # mismatch here is exactly what a human would need to retype to fix.
        known_subject_ids = already_converted | set(new_subject_ids)
        corrected_but_unknown = sorted(
            {
                corrected_id
                for corrected_id in debrief_id_corrections.values()
                if corrected_id not in known_subject_ids
            }
        )
        if corrected_but_unknown:
            logger.warning(
                "%d debrief record id correction(s) point at a subject id that doesn't match "
                "any known subject folder, so they won't be attached this run -- double-check "
                "spelling/casing against the real sub-XXX folder name: %s",
                len(corrected_but_unknown),
                ", ".join(corrected_but_unknown),
            )

    # Debrief backfill: an already-converted subject still gets reconsidered for debrief
    # specifically if they don't have one yet (e.g. a previous run's export didn't match
    # them). Subjects that already have a debrief file are left alone either way.
    backfill_candidate_ids = sorted(
        sid for sid in already_converted if not _has_debrief_file(output_folder, sid)
    )
    debrief_candidate_ids = sorted(set(new_subject_ids) | set(backfill_candidate_ids))
    backfilled_debrief_ids: list[str] = []

    if debrief_df is not None:
        # Exact match on record_id, same as the real pipeline's own
        # `crane_debrief_behaviour.RawDebriefBehaviourData.get_single_subject_data`.
        for subject_id in debrief_candidate_ids:
            subject_rows = debrief_df[debrief_df["record_id"] == subject_id]
            if not subject_rows.empty:
                acq_date = (
                    subject_acq_date.get(subject_id)
                    or _existing_acq_date(output_folder, subject_id)
                    or "nodate"
                )
                destination = _datatype_folder(output_folder, subject_id) / _bids_filename(
                    subject_id, "debrief", "beh", ".tsv"
                )
                subject_rows.to_csv(destination, index=False, sep="\t")
                scans_tsv_path = _scans_tsv_path(output_folder, subject_id)
                relative_name = destination.relative_to(scans_tsv_path.parent).as_posix()
                bids.append_scan_row(scans_tsv_path, relative_name, acq_date)
                subject_debrief[subject_id] = destination
                if subject_id in backfill_candidate_ids:
                    backfilled_debrief_ids.append(subject_id)

    if backfilled_debrief_ids:
        logger.info(
            "Backfilled debrief for %d already-converted subject(s) that didn't have one yet: %s",
            len(backfilled_debrief_ids),
            ", ".join(sorted(backfilled_debrief_ids)),
        )

    if already_converted and skipped_files:
        logger.info(
            "Skipped %d file(s) for %d subject(s) already converted: %s",
            skipped_files,
            len(already_converted),
            ", ".join(sorted(already_converted)),
        )

    unmatched_debrief = [sid for sid in debrief_candidate_ids if sid not in subject_debrief]
    if debrief_df is not None and unmatched_debrief:
        # Sample both ends of the sorted id list, not just the front -- e.g. every "0"-prefixed
        # numeric id sorts before every letter-prefixed one, so "first 15" alone could hide
        # that the other shape exists further in.
        all_values = sorted(debrief_df["record_id"].dropna().unique())
        if len(all_values) <= 20:
            sample_desc = ", ".join(all_values)
        else:
            sample_desc = f"{', '.join(all_values[:10])}, ..., {', '.join(all_values[-10:])}"
        logger.warning(
            "No debrief row found for %d subject(s) -- check whether their record_id in %r "
            "actually matches the ID in their filenames: %s. %d total distinct record_id "
            "value(s) found in the export (first/last 10 shown if more than 20): %s",
            len(unmatched_debrief),
            GROUP_REDCAP_GLOB,
            ", ".join(unmatched_debrief),
            len(all_values),
            sample_desc,
        )

    logger.info(
        "Added %d new subject folder(s) to %s: %d physiology, %d behaviour, %d debrief "
        "file(s) (%d of those backfilled for already-converted subjects). Skipped %d "
        "already-converted subject(s).",
        len(new_subject_ids),
        output_folder,
        sum(len(paths) for paths in subject_physiology.values()),
        sum(len(paths) for paths in subject_behaviour.values()),
        len(subject_debrief),
        len(backfilled_debrief_ids),
        len(already_converted),
    )

    return CraneConversionSummary(
        new_subject_ids=new_subject_ids,
        subject_physiology=dict(subject_physiology),
        subject_behaviour=dict(subject_behaviour),
        subject_debrief=subject_debrief,
        already_converted=already_converted,
        skipped_files=skipped_files,
        backfilled_debrief_ids=backfilled_debrief_ids,
        unmatched_debrief=unmatched_debrief,
        unparseable_files=unparseable_files,
    )


def _cell(paths_by_subject: dict, subject_id: str) -> str:
    value = paths_by_subject.get(subject_id)
    if not value:
        return "(missing)"
    if isinstance(value, list):
        return ", ".join(path.name for path in value)
    return value.name


def print_conversion_summary(summary: CraneConversionSummary) -> None:
    """Rich console/table rendering of a `CraneConversionSummary`, factored out so the CLI's
    `main()` stays a thin wrapper around `convert_crane_to_bids()`.
    """
    console = Console()
    if not summary.new_subject_ids and not summary.backfilled_debrief_ids:
        console.print(
            "No new subjects found -- everything in the source folder is already converted."
        )
        return

    table = Table(title="Crane raw -> BIDS conversion")
    table.add_column("Subject ID")
    table.add_column("Physiology")
    table.add_column("Behaviour")
    table.add_column("Debrief")
    for subject_id in summary.new_subject_ids:
        table.add_row(
            subject_id,
            _cell(summary.subject_physiology, subject_id),
            _cell(summary.subject_behaviour, subject_id),
            _cell(summary.subject_debrief, subject_id),
        )
    for subject_id in summary.backfilled_debrief_ids:
        table.add_row(
            f"{subject_id} (backfill)",
            "(already converted)",
            "(already converted)",
            _cell(summary.subject_debrief, subject_id),
        )
    console.print(table)
