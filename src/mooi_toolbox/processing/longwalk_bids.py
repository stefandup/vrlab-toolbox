import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from mooi_toolbox.processing import bids

DECISIONS_FILENAME = "crosscheck.json"
EXCLUDED_SUBJECTS_FILENAME = "excluded_subjects.json"
SUBJECT_FOLDER_PREFIX = "sub-"
RAW_FILENAME_ID_CORRECTIONS_FILENAME = "raw_filename_id_corrections.json"
PHYSIOLOGY_GLOB = "*.mat"

DATATYPE_FOLDER_NAME = "beh"
SESSION_TOKEN = "ses-01"
RUN_TOKEN = "run-001"
TASK_TOKEN = "task-longwalk"

# The same real subject gets written inconsistently as "PID-1234" and "PID1234" --
# canonicalized to the no-dash form wherever a subject id is derived.
_PID_DASH_PATTERN = re.compile(r"^PID-(\d+)$", re.IGNORECASE)

# Real filenames are `{subject_id}_{date}.{ext}`, but the date prefix isn't always
# there, and is sometimes joined with "-" instead of "_" (e.g. "PID5562-20267291154").
# `biopac.get_subject_id_from_mat`'s naive `split("_")[1]` breaks on both; this regex handles
# both without touching biopac.py.
_SUBJECT_ID_PATTERN = re.compile(r"^(?:(?P<subject_id>.+?)[_-])?(?P<date>\d+)$", re.IGNORECASE)

# A subject id can carry a trailing " (N)" marker -- sometimes a harmless duplicate-copy
# artifact, sometimes two genuinely different subjects sharing a base id. Unresolvable from
# the filename alone, so it's routed to the crosscheck GUI for a human decision instead.
_DUPLICATE_COPY_MARKER_PATTERN = re.compile(r"\(\d+\)\s*$")


logger = logging.getLogger(__name__)


# TODO: Move to BIDS
def decisions_path(bids_folder: Path) -> Path:
    return bids_folder / DECISIONS_FILENAME


# TODO: Move to BIDS
def excluded_subjects_path(bids_folder: Path) -> Path:
    return bids_folder / EXCLUDED_SUBJECTS_FILENAME


# TODO: Move to BIDS
def load_decisions(bids_folder: Path) -> dict[str, list[dict]]:
    """`{key: [entry, ...]}`, oldest first per key -- see `_append_decision`.

    Transparently upgrades a key still in the older on-disk shape (`{key: entry}`, from before
    history was tracked) to `[entry]` in memory. Non-destructive: the file itself isn't rewritten
    until something else records a new decision for that key, so a `crosscheck.json` already in
    real use keeps working without a separate migration step.
    """
    path = decisions_path(bids_folder)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as decisions_file:
        decisions = json.load(decisions_file)
    return {key: value if isinstance(value, list) else [value] for key, value in decisions.items()}


def load_raw_filename_id_corrections(bids_folder: Path) -> dict[str, str]:
    return bids.load_json_map(bids_folder / RAW_FILENAME_ID_CORRECTIONS_FILENAME)


# TODO: Move to BIDS
def iter_subject_folders(bids_folder: Path):
    for entry in sorted(bids_folder.iterdir()):
        if entry.is_dir() and entry.name.startswith(SUBJECT_FOLDER_PREFIX):
            yield entry.name[len(SUBJECT_FOLDER_PREFIX) :], entry


# TODO: Move to BIDS
def load_excluded_subjects(bids_folder: Path) -> dict[str, str | None]:
    """`{subject_id: reason}` for every subject a human has removed from BIDS (reason may be
    None). See `record_subject_excluded`."""
    path = excluded_subjects_path(bids_folder)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as excluded_file:
        return json.load(excluded_file)


# TODO: Move to BIDS - All functions here likley would benefit from centrally being in bids.py
def existing_subject_ids(bids_folder: Path) -> set[str]:
    """Track which subject IDs are already handled to prevent duplicate re-imports.

    Considers a subject ID "handled" if: (1) its `sub-XXX/` folder still exists,
    (2) it was excluded (folder deleted), or (3) it was renamed away. Without tracking
    (2) and (3), the next import would silently re-copy subjects from raw data that
    parse to the original ID, creating duplicates alongside the renamed/excluded versions.

    Shared by all raw-to-BIDS importers (`crane_bids.py`, `foh_import_to_bids.py`)
    as part of the incremental copy-only strategy.
    """
    renamed_away = {
        latest["original_id"]
        for entries in load_decisions(bids_folder).values()
        if (latest := entries[-1]).get("type") == "id_correction"
    }
    if not bids_folder.is_dir():
        return set(load_excluded_subjects(bids_folder)) | renamed_away
    present = {subject_id for subject_id, _ in iter_subject_folders(bids_folder)}
    return present | set(load_excluded_subjects(bids_folder)) | renamed_away


# TODO: Can be renamed to ParsedFilename?
@dataclass
class ParsedCraneFilename:
    subject_id: str
    date_prefix: str | None


def canonicalize_subject_id(subject_id: str) -> str:
    match = _PID_DASH_PATTERN.match(subject_id)
    if match:
        return f"PID{match.group(1)}"
    return subject_id


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


# TODO: This can be renamed if it works
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


def _session_folder(output_folder: Path, subject_id: str) -> Path:
    folder = output_folder / f"{SUBJECT_FOLDER_PREFIX}{subject_id}" / SESSION_TOKEN
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _datatype_folder(output_folder: Path, subject_id: str) -> Path:
    folder = _session_folder(output_folder, subject_id) / DATATYPE_FOLDER_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


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


def _scans_tsv_path(output_folder: Path, subject_id: str) -> Path:
    return _session_folder(output_folder, subject_id) / (
        f"{SUBJECT_FOLDER_PREFIX}{subject_id}_{SESSION_TOKEN}_scans.tsv"
    )


def _copy_into_subject_folder(
    source: Path, output_folder: Path, subject_id: str, acq_date: str, acq: str, suffix: str
) -> Path:
    destination = _resolve_destination(output_folder, subject_id, acq, suffix, source.suffix)
    bids.copy_scan(source, destination, _scans_tsv_path(output_folder, subject_id), acq_date)
    return destination


# TODO: This can be biopac conversion summary. However there are additional crane ones.
@dataclass
class CraneConversionSummary:
    """Everything a caller (the CLI's `main()`, or the crosscheck GUI's "Convert to BIDS..."
    button) needs to report what a `convert_crane_to_bids()` call actually did. Warnings/skips
    are also emitted via the module `logger` as they happen -- this is the end-of-run rollup.
    """

    new_subject_ids: list[str] = field(default_factory=list)
    subject_physiology: dict[str, list[Path]] = field(default_factory=dict)
    already_converted: set[str] = field(default_factory=set)
    skipped_files: int = 0
    unparseable_files: list[Path] = field(default_factory=list)


def convert_biopac_to_bids(
    input_folder: Path, output_folder: Path, debrief_export: Path | None = None
) -> CraneConversionSummary:
    """
    CLI or "Convert to BIDS" crosscheck drivable BIDS conversion for biopac style folders.
    I.e. csv and mat based data.
    """
    output_folder.mkdir(parents=True, exist_ok=True)
    already_converted = existing_subject_ids(output_folder)

    # Recursive, like every real pipeline lookup this mirrors -- raw files aren't guaranteed
    # to sit directly at input_folder's top level.
    physiology_files = sorted(input_folder.rglob(PHYSIOLOGY_GLOB))
    raw_filename_corrections = load_raw_filename_id_corrections(output_folder)

    subject_physiology: dict[str, list[Path]] = defaultdict(list)
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

    if unparseable_files:
        logger.warning(
            "Could not extract a subject id from %d filename(s) -- skipped entirely, not "
            "copied: %s",
            len(unparseable_files),
            ", ".join(f.name for f in unparseable_files),
        )

    new_subject_ids = sorted(set(subject_physiology))

    if already_converted and skipped_files:
        logger.info(
            "Skipped %d file(s) for %d subject(s) already converted: %s",
            skipped_files,
            len(already_converted),
            ", ".join(sorted(already_converted)),
        )

    logger.info(
        "Added %d new subject folder(s) to %s: %d physiology, Skipped %d "
        "already-converted subject(s).",
        len(new_subject_ids),
        output_folder,
        sum(len(paths) for paths in subject_physiology.values()),
        len(already_converted),
    )

    return CraneConversionSummary(
        new_subject_ids=new_subject_ids,
        subject_physiology=dict(subject_physiology),
        already_converted=already_converted,
        skipped_files=skipped_files,
        unparseable_files=unparseable_files,
    )
