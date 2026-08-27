"""CLI: copy-only converter from crane's raw flat data folder into a BIDS-shaped output
folder that `gui/crane_bids_crosscheck_gui.py` can point at.

See docs/bids_converter_plan.md. Never touches `input_folder` -- only ever copies into
`output_folder`. Dumps every matching file it finds, duplicates included; picking a
canonical file among duplicates is the crosscheck tool's job, not this converter's ("the
converter should dump, not decide").

Incremental by subject: `output_folder` may already exist and already hold converted
subjects (e.g. from a previous run, possibly already crosschecked/corrected by hand) --
any subject whose `sub-XXX/` folder is already there is left completely alone and skipped,
so re-running against a source folder that's since gained new subjects only ever adds
those, never re-copies or overwrites an existing one.

Dates are never put in a filename (that's not real BIDS) -- instead each copied file gets a
row in its session's `sub-XXX/ses-01/sub-XXX_ses-01_scans.tsv` sidecar (`filename`, `acq_time`
columns), BIDS's own place for a per-scan acquisition date. Those values are carried through
unchanged from the raw filenames' date prefixes -- they're not reliably parseable as real
calendar dates (inconsistent length/format across sessions), so no attempt is made to
normalize them into true ISO8601 here. Use the crosscheck tool's "Correct date..." button to
fix any that are wrong, once they're visible listed per subject.

Output layout, and why it looks the way it does:
- Every file goes in `sub-XXX/ses-01/beh/`, not directly in `sub-XXX/ses-01/` -- mirroring
  FOH's `sub-XXX/eeg/` layout. This isn't cosmetic: `bids_crosscheck.record_task_correction`
  (the crosscheck tool's "Tag as..." action) renames a *file's parent folder* to the
  dataset's datatype folder when tagging -- if files sat directly in `sub-XXX/ses-01/`,
  tagging would rename that whole session folder itself. Placing them under `beh/` up front
  makes that rename a same-name no-op instead.
- `ses-01` is a fixed placeholder, same spirit as `run-001` below -- crane has no real
  multi-session concept today, so this is always "01", not a real session count.
- Every filename includes a `run-001` token -- `record_task_correction` requires one
  (`RUN_TOKEN_PATTERN`) and raises otherwise. Crane doesn't have multi-run semantics today,
  so this is always "001", not a real run count.
- Scan type is identified by *extension* (`.mat`/`.csv`/`.tsv`), not by a keyword in the
  filename stem (`gui/crane_bids_crosscheck_gui.py`'s glob patterns) -- because
  `record_task_correction` replaces everything after the run-<NNN> token with just
  `_<label>`, so a keyword like "_physio" wouldn't survive tagging. Debrief is written
  `.tsv` (not `.csv`, same as behaviour) specifically so all three scan types stay
  distinguishable by extension alone even after a tag rename. `scans.tsv` itself sits one
  level up (in `ses-01/`, not `ses-01/beh/`), so it never collides with that glob-by-extension
  matching.
"""

import csv
import json
import logging
import os
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import click
import pandas as pd
from rich.console import Console
from rich.table import Table

from mooi_toolbox import mobi_logging
from mooi_toolbox.processing.bids_crosscheck import SUBJECT_FOLDER_PREFIX
from mooi_toolbox.processing.crane_debrief_behaviour import (
    GROUP_REDCAP_GLOB,
    crane_raw_debrief_file_schema,
)

logger = logging.getLogger(__name__)

PHYSIOLOGY_GLOB = "*_CraneOut.mat"
BEHAVIOUR_GLOB = "*_CraneOut.csv"
# See module docstring's "Output layout" section for why these exist.
DATATYPE_FOLDER_NAME = "beh"
SESSION_TOKEN = "ses-01"
RUN_TOKEN = "run-001"
TASK_TOKEN = "task-crane"
SCANS_TSV_COLUMNS = ("filename", "acq_time")
# Real filenames are `{date}_{subject_id}_CraneOut.{ext}`, but: the date prefix isn't always
# there; it's sometimes joined with "-" instead of "_" (e.g. "20267291154-PID5562_CraneOut");
# and a subject id can carry a Windows duplicate-copy marker (" (1)", " (2)", ...) from a file
# accidentally copied twice within the same folder. `biopac.get_subject_id_from_mat`'s naive
# `split("_")[1]` breaks on all three: a 2-token filename with no date puts "CraneOut" itself
# (the suffix) at index 1 instead of the id; a "-"-joined date never gets split off at all; and
# a "(1)"/"(2)" marker gets kept as part of the "id" -- turning one real subject into two
# different (wrong) ones. This regex handles all three, without touching biopac.py (still
# correct for the plain-date-prefixed filenames the real pipeline mostly sees).
_SUBJECT_ID_PATTERN = re.compile(
    r"^(?:(?P<date>\d+)[_-])?(?P<subject_id>.+?)(?:\s*\(\d+\))?_CraneOut$", re.IGNORECASE
)
# Confirmed (by whoever actually enters these IDs) the same real subject gets written
# inconsistently as "PID-1234" and "PID1234" -- consistent about the "PID" prefix and the
# digits, just not about the dash in between. Canonicalized to the no-dash form (arbitrary
# but consistent) wherever a subject id is derived, so e.g. a sub-XXX/ folder name doesn't
# end up depending on which spelling happened to appear in a given source file.
_PID_DASH_PATTERN = re.compile(r"^PID-(\d+)$", re.IGNORECASE)


def canonicalize_subject_id(subject_id: str) -> str:
    match = _PID_DASH_PATTERN.match(subject_id)
    if match:
        return f"PID{match.group(1)}"
    return subject_id


def guess_corrected_subject_id(record_id: str) -> str:
    """Best-effort automatic fix for a mismatched debrief `record_id` -- strips stray
    whitespace and a spurious trailing ".0" (from a numeric-looking id read without a string
    dtype hint, e.g. "10016" -> 10016.0 -> "10016.0"), then applies the same PID-dash
    normalization filename-derived ids already get (`canonicalize_subject_id`). Used by the
    crosscheck GUI's debrief record-id correction dialog as the pre-filled first guess -- an
    id that's merely mis-formatted, not actually wrong, becomes an exact match for free.
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
    """Subject id + date prefix from a raw crane filename's stem, in one pass -- both need
    the same regex, so deriving date_prefix separately (e.g. a naive
    `file.name.split("_")[0]`) would silently disagree with it whenever the date is "-"-joined
    or absent. Returns None if the filename doesn't match the expected
    `[<date>[_-]]<id>[ (N)]_CraneOut` shape at all, rather than guessing -- callers must handle
    None (skip + log), not treat it as a real id.
    """
    match = _SUBJECT_ID_PATTERN.match(file.stem)
    if match is None:
        return None
    return ParsedCraneFilename(
        subject_id=canonicalize_subject_id(match.group("subject_id")),
        date_prefix=match.group("date"),
    )


def extract_subject_id(file: Path) -> str | None:
    """Subject id alone -- see `parse_crane_filename` for the date prefix too."""
    parsed = parse_crane_filename(file)
    return parsed.subject_id if parsed is not None else None


def discover_raw_subject_ids(input_folder: Path) -> set[str]:
    """Every subject id derivable from raw physiology/behaviour filenames, read-only -- the
    same ids `convert_crane_to_bids` would derive, without copying anything. Used by the
    crosscheck GUI's debrief record-id correction dialog to know which subject ids a
    mismatched `record_id` could reasonably be corrected to, without requiring a real
    conversion run first.
    """
    ids: set[str] = set()
    for file in (*input_folder.rglob(PHYSIOLOGY_GLOB), *input_folder.rglob(BEHAVIOUR_GLOB)):
        subject_id = extract_subject_id(file)
        if subject_id is not None:
            ids.add(subject_id)
    return ids


DEBRIEF_ID_CORRECTIONS_FILENAME = "debrief_id_corrections.json"


def _debrief_id_corrections_path(bids_folder: Path) -> Path:
    return bids_folder / DEBRIEF_ID_CORRECTIONS_FILENAME


def load_debrief_id_corrections(bids_folder: Path) -> dict[str, str]:
    """`{original_record_id: corrected_subject_id}`, as saved by the crosscheck GUI's debrief
    record-id correction dialog. Lives in `bids_folder`, not the raw input folder -- this
    module's own docstring guarantees it never touches `input_folder`, and this correction
    file shouldn't become the exception. Empty (not an error) if nothing's been saved yet.
    """
    path = _debrief_id_corrections_path(bids_folder)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as corrections_file:
        return json.load(corrections_file)


def save_debrief_id_corrections(bids_folder: Path, corrections: dict[str, str]) -> None:
    path = _debrief_id_corrections_path(bids_folder)
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as tmp_file:
        json.dump(corrections, tmp_file, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


EXAMPLES_EPILOG = """
Examples:

\\b
  Convert a raw crane data folder into a BIDS-shaped folder the crosscheck tool can point at:
  crane_convert_to_bids C:\\raw\\MscFiles_crane_local C:\\bids\\MscFiles_crane_bids
"""


def _find_debrief_export(input_folder: Path, override: Path | None = None) -> Path | None:
    """Locate the shared REDCAP group export. `override`, if given, is used as-is, no
    searching -- for when auto-detection refuses (multiple candidates) and a human just
    knows which file is the real one. Otherwise searches recursively for
    `GROUP_REDCAP_GLOB`, the same pattern `crane_debrief_behaviour.get_group_debrief_data`
    matches against for the real pipeline's own debrief loading, so a file this converter
    finds is guaranteed to also be the one the pipeline itself would load later.
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
    """Read+filter the shared REDCAP group export -- one already-wide row per subject
    (`record_id` plus `crane_<emotion>_rb`/`_gb` columns), the same shape
    `crane_debrief_behaviour.get_group_debrief_data` loads for the real pipeline. Filtered
    against `crane_raw_debrief_file_schema`'s own column set (not validated against it --
    this converter is meant to dump, not decide) so this converter's debrief columns never
    drift from what the real pipeline expects.
    """
    export_path = _find_debrief_export(input_folder, override)
    if export_path is None:
        return None

    df = pd.read_csv(export_path)
    return df.filter(items=list(crane_raw_debrief_file_schema.columns))


def existing_subject_ids(output_folder: Path) -> set[str]:
    if not output_folder.is_dir():
        return set()
    return {
        entry.name.removeprefix(SUBJECT_FOLDER_PREFIX)
        for entry in output_folder.iterdir()
        if entry.is_dir() and entry.name.startswith(SUBJECT_FOLDER_PREFIX)
    }


def _has_debrief_file(output_folder: Path, subject_id: str) -> bool:
    datatype_folder = (
        output_folder / f"{SUBJECT_FOLDER_PREFIX}{subject_id}" / SESSION_TOKEN / DATATYPE_FOLDER_NAME
    )
    return datatype_folder.is_dir() and any(datatype_folder.glob("*_debrief_events.tsv"))


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


def _read_scans_tsv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as tsv_file:
        return list(csv.DictReader(tsv_file, delimiter="\t"))


def _append_scans_tsv_row(
    output_folder: Path, subject_id: str, scan_file: Path, acq_date: str
) -> None:
    """Record one copied file's date as a row in its session's `scans.tsv` -- BIDS's own place
    for a per-scan acquisition date, now that dates are never part of a filename (see module
    docstring). `acq_date` is carried through as-is, same as the old filename date prefix was.
    """
    path = _scans_tsv_path(output_folder, subject_id)
    relative_name = scan_file.relative_to(path.parent).as_posix()
    rows = _read_scans_tsv_rows(path)
    rows.append({"filename": relative_name, "acq_time": acq_date})
    with path.open("w", newline="", encoding="utf-8") as tsv_file:
        writer = csv.DictWriter(tsv_file, fieldnames=SCANS_TSV_COLUMNS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _existing_acq_date(output_folder: Path, subject_id: str) -> str | None:
    """Best-effort acquisition date for a subject already converted in an earlier run, read
    back off whatever's already in their `scans.tsv` -- used only for dating a backfilled
    debrief file's own row consistently with its siblings, since that subject's date was never
    derived this run (see subject_acq_date, only populated for files copied in this call).
    """
    rows = _read_scans_tsv_rows(_scans_tsv_path(output_folder, subject_id))
    return rows[0]["acq_time"] if rows else None


def _bids_filename(subject_id: str, suffix: str, extension: str) -> str:
    return (
        f"{SUBJECT_FOLDER_PREFIX}{subject_id}_{SESSION_TOKEN}_{TASK_TOKEN}_{RUN_TOKEN}_"
        f"{suffix}{extension}"
    )


def _copy_into_subject_folder(
    source: Path, output_folder: Path, subject_id: str, acq_date: str, suffix: str
) -> Path:
    destination = _datatype_folder(output_folder, subject_id) / _bids_filename(
        subject_id, suffix, source.suffix
    )
    if destination.exists():
        # Two different source files landed on the same destination name -- e.g. a Windows
        # duplicate-copy pair ("... (1)_CraneOut.mat" / "... (2)_CraneOut.mat") that share a
        # date once the "(N)" marker is stripped from the subject id. Both are real candidate
        # files the crosscheck tool should let a human pick between, so disambiguate rather
        # than silently overwrite one with shutil.copy2's default behaviour.
        counter = 2
        candidate = destination
        while candidate.exists():
            candidate = _datatype_folder(output_folder, subject_id) / _bids_filename(
                subject_id, f"{suffix}-dup{counter}", source.suffix
            )
            counter += 1
        destination = candidate
    shutil.copy2(source, destination)
    _append_scans_tsv_row(output_folder, subject_id, destination, acq_date)
    return destination


@dataclass
class CraneConversionSummary:
    """Everything a caller (the CLI's `main()` below, or the crosscheck GUI's "Convert to
    BIDS..." button) needs to report what a `convert_crane_to_bids()` call actually did.
    Warnings/skips are also emitted via the module `logger` as they happen -- this is the
    end-of-run rollup, not a replacement for that.
    """

    new_subject_ids: list[str] = field(default_factory=list)
    subject_physiology: dict[str, list[Path]] = field(default_factory=dict)
    subject_behaviour: dict[str, list[Path]] = field(default_factory=dict)
    subject_debrief: dict[str, Path] = field(default_factory=dict)
    already_converted: set[str] = field(default_factory=set)
    skipped_files: int = 0
    unmatched_debrief: list[str] = field(default_factory=list)
    backfilled_debrief_ids: list[str] = field(default_factory=list)


def convert_crane_to_bids(
    input_folder: Path, output_folder: Path, debrief_export: Path | None = None
) -> CraneConversionSummary:
    """Core, UI-agnostic conversion logic -- see module docstring for the "why" behind the
    output layout. Progress/problems are reported via the standard `logger` (info for
    routine skips, warning for anything worth a human's attention), not print/rich, so both
    the CLI below and the crosscheck GUI's "Convert to BIDS..." button can drive this and
    display the result their own way -- attach a `logging.Handler` to this module's logger
    around the call to capture those messages for display elsewhere.

    `debrief_export`, if given, overrides auto-detection of the shared REDCAP group export --
    for when there's more than one file matching `GROUP_REDCAP_GLOB` in `input_folder`
    (auto-detection refuses rather than guessing between them), or when auto-detection would
    otherwise pick the wrong one.
    """
    output_folder.mkdir(parents=True, exist_ok=True)
    already_converted = existing_subject_ids(output_folder)

    # Recursive (like every real pipeline lookup this mirrors -- input_data.py's
    # from_physiology_data, behaviour.py, vrlab_crane_process.py -- all use rglob), since raw
    # files aren't guaranteed to sit directly at input_folder's top level.
    physiology_files = sorted(input_folder.rglob(PHYSIOLOGY_GLOB))
    behaviour_files = sorted(input_folder.rglob(BEHAVIOUR_GLOB))
    debrief_df = load_debrief_export(input_folder, debrief_export)
    if debrief_df is not None:
        # Human-declared record_id -> subject_id fixes from the crosscheck GUI's debrief
        # correction dialog (see load_debrief_id_corrections) -- applied here, not in
        # load_debrief_export, so that function stays a pure read of the raw export.
        corrections = load_debrief_id_corrections(output_folder)
        if corrections:
            debrief_df["record_id"] = debrief_df["record_id"].replace(corrections)

    subject_physiology: dict[str, list[Path]] = defaultdict(list)
    subject_behaviour: dict[str, list[Path]] = defaultdict(list)
    subject_debrief: dict[str, Path] = {}
    subject_acq_date: dict[str, str] = {}
    skipped_files = 0
    unparseable_files: list[Path] = []

    for mat_file in physiology_files:
        parsed = parse_crane_filename(mat_file)
        if parsed is None:
            unparseable_files.append(mat_file)
            continue
        if parsed.subject_id in already_converted:
            skipped_files += 1
            continue
        acq_date = parsed.date_prefix or "nodate"
        subject_acq_date.setdefault(parsed.subject_id, acq_date)
        destination = _copy_into_subject_folder(
            mat_file, output_folder, parsed.subject_id, acq_date, "physio"
        )
        subject_physiology[parsed.subject_id].append(destination)

    for csv_file in behaviour_files:
        parsed = parse_crane_filename(csv_file)
        if parsed is None:
            unparseable_files.append(csv_file)
            continue
        if parsed.subject_id in already_converted:
            skipped_files += 1
            continue
        acq_date = parsed.date_prefix or "nodate"
        subject_acq_date.setdefault(parsed.subject_id, acq_date)
        destination = _copy_into_subject_folder(
            csv_file, output_folder, parsed.subject_id, acq_date, "beh"
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

    # Debrief backfill: an already-converted subject (physiology/behaviour skipped above,
    # untouched by design) still gets reconsidered for debrief specifically if they don't
    # have one yet -- e.g. a previous run's debrief export didn't match them, and this run
    # was given a corrected/different one via debrief_export. Subjects that already have a
    # debrief file are left alone either way -- never overwritten, same as everything else
    # this converter touches.
    backfill_candidate_ids = sorted(
        sid for sid in already_converted if not _has_debrief_file(output_folder, sid)
    )
    debrief_candidate_ids = sorted(set(new_subject_ids) | set(backfill_candidate_ids))
    backfilled_debrief_ids: list[str] = []

    if debrief_df is not None:
        # Exact match on record_id, same as the real pipeline's own
        # `crane_debrief_behaviour.RawDebriefBehaviourData.get_single_subject_data` -- record_id
        # is expected to already be the canonical subject id, not a value needing case
        # normalization the way the old Subject_ID-based workbook did.
        for subject_id in debrief_candidate_ids:
            subject_rows = debrief_df[debrief_df["record_id"] == subject_id]
            if not subject_rows.empty:
                acq_date = (
                    subject_acq_date.get(subject_id)
                    or _existing_acq_date(output_folder, subject_id)
                    or "nodate"
                )
                destination = _datatype_folder(output_folder, subject_id) / _bids_filename(
                    subject_id, "debrief_events", ".tsv"
                )
                subject_rows.to_csv(destination, index=False, sep="\t")
                _append_scans_tsv_row(output_folder, subject_id, destination, acq_date)
                subject_debrief[subject_id] = destination
                if subject_id in backfill_candidate_ids:
                    backfilled_debrief_ids.append(subject_id)

    if backfilled_debrief_ids:
        logger.info(
            "Backfilled debrief for %d already-converted subject(s) that didn't have one "
            "yet: %s",
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
        # Sampling naively from the front of a sorted list is misleading here: e.g. every
        # "0"-prefixed numeric id sorts before every letter-prefixed one, so "first 15" alone
        # could show only one shape and hide entirely that the other shape exists further
        # in. Showing both ends (plus the total count) avoids that blind spot.
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
    )


def _cell(paths_by_subject: dict, subject_id: str) -> str:
    value = paths_by_subject.get(subject_id)
    if not value:
        return "(missing)"
    if isinstance(value, list):
        return ", ".join(path.name for path in value)
    return value.name


def print_conversion_summary(summary: CraneConversionSummary) -> None:
    """Rich console/table rendering of a `CraneConversionSummary` -- the CLI's own output
    format, factored out so `main()` stays a thin wrapper around `convert_crane_to_bids()`.
    """
    console = Console()
    if not summary.new_subject_ids and not summary.backfilled_debrief_ids:
        console.print("No new subjects found -- everything in the source folder is already converted.")
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


@click.command(epilog=EXAMPLES_EPILOG)
@click.version_option(package_name="mooi-toolbox")
@click.argument(
    "input_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path), required=True
)
@click.argument("output_folder", type=click.Path(path_type=Path), required=True)
@click.option(
    "--debrief-export",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Override the shared REDCAP group export auto-detection -- use when there's more "
    "than one file matching GROUP_REDCAP_GLOB.",
)
@click.option("--verbose", is_flag=True, help="Give verbose output")
def main(
    input_folder: Path, output_folder: Path, debrief_export: Path | None, verbose: bool
) -> None:
    """Copy-only converter: raw crane data folder -> BIDS-shaped output folder.

    Incremental: subjects that already have a sub-XXX/ folder under output_folder are
    skipped entirely (not re-copied, not touched) -- safe to re-run against a source folder
    that's gained new subjects since the last run.
    """
    summary = convert_crane_to_bids(input_folder, output_folder, debrief_export)
    print_conversion_summary(summary)


if __name__ == "__main__":
    mobi_logging.init(__file__)
    main()
