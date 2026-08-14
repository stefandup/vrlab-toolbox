import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

DECISIONS_FILENAME = "crosscheck.json"
PENDING_SELECTIONS_FILENAME = "crosscheck_pending.json"
JUNK_FOLDER_NAME = "crosscheck_junk"
SUBJECT_FOLDER_PREFIX = "sub-"
BIDSIGNORE_FILENAME = ".bidsignore"
RUN_TOKEN_PATTERN = re.compile(r"run-\d+")

SubjectStatus = Literal["ok", "missing", "duplicate"]


class BidsCrosscheckError(Exception):
    """Raised for invalid crosscheck operations (unknown scan type, bad selection, ...)."""


@dataclass(frozen=True)
class ScanTypeConfig:
    name: str
    glob_patterns: tuple[str, ...]


@dataclass(frozen=True)
class DatasetConfig:
    dataset_name: str
    scan_types: tuple[ScanTypeConfig, ...]
    task_correction_scan_type: str | None = None
    task_correction_label: str = "FOH"
    task_correction_folder_name: str | None = None

    def scan_type_names(self) -> tuple[str, ...]:
        return tuple(scan_type.name for scan_type in self.scan_types)

    def glob_patterns_for(self, scan_type: str) -> tuple[str, ...]:
        for candidate in self.scan_types:
            if candidate.name == scan_type:
                return candidate.glob_patterns
        raise BidsCrosscheckError(
            f"Unknown scan type {scan_type!r} for dataset {self.dataset_name!r}"
        )


@dataclass(frozen=True)
class SubjectScan:
    subject_id: str
    scan_type: str
    files: tuple[Path, ...]

    @property
    def status(self) -> SubjectStatus:
        if not self.files:
            return "missing"
        if len(self.files) > 1:
            return "duplicate"
        return "ok"


@dataclass
class BidsFolderScan:
    bids_folder: Path
    scans: dict[str, dict[str, SubjectScan]]

    def subject_ids(self) -> list[str]:
        return sorted(self.scans)

    def subject_folder(self, subject_id: str) -> Path:
        return self.bids_folder / f"{SUBJECT_FOLDER_PREFIX}{subject_id}"

    def has_issues(self, subject_id: str) -> bool:
        return any(scan.status != "ok" for scan in self.scans[subject_id].values())


def junk_folder(bids_folder: Path) -> Path:
    return bids_folder / JUNK_FOLDER_NAME


def decisions_path(bids_folder: Path) -> Path:
    return bids_folder / DECISIONS_FILENAME


def pending_selections_path(bids_folder: Path) -> Path:
    return bids_folder / PENDING_SELECTIONS_FILENAME


def ensure_bidsignore(bids_folder: Path, extra_patterns: tuple[str, ...] = ()) -> None:
    """Make sure this tool's own files are listed in `.bidsignore`, so a BIDS validator
    doesn't flag them as unexpected. Appends only whatever's missing -- `.bidsignore` is a
    human-maintained file this tool doesn't own, so existing content (and ordering) is left
    alone. Safe to call on every folder load: a no-op once the patterns are already there.
    """
    required = (DECISIONS_FILENAME, PENDING_SELECTIONS_FILENAME, f"{JUNK_FOLDER_NAME}/", *extra_patterns)
    path = bids_folder / BIDSIGNORE_FILENAME
    try:
        existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        missing = [pattern for pattern in required if pattern not in existing_lines]
        if not missing:
            return
        with path.open("a", encoding="utf-8") as bidsignore_file:
            if existing_lines and existing_lines[-1] != "":
                bidsignore_file.write("\n")
            for pattern in missing:
                bidsignore_file.write(f"{pattern}\n")
    except OSError:
        logger.warning("Could not update %s -- continuing without it", path, exc_info=True)


def _iter_subject_folders(bids_folder: Path):
    for entry in sorted(bids_folder.iterdir()):
        if (
            entry.is_dir()
            and entry.name.startswith(SUBJECT_FOLDER_PREFIX)
            and entry.name != JUNK_FOLDER_NAME
        ):
            yield entry.name[len(SUBJECT_FOLDER_PREFIX) :], entry


def scan_bids_folder(bids_folder: Path, config: DatasetConfig) -> BidsFolderScan:
    """Scan `bids_folder` for every subject x scan-type candidate file.

    Read-only: never moves, renames, or writes anything. The tool's own junk
    folder (see `junk_folder`) is excluded, since it holds files a human has
    already decided not to keep.
    """
    scans: dict[str, dict[str, SubjectScan]] = {}

    for subject_id, subject_folder in _iter_subject_folders(bids_folder):
        scans[subject_id] = {}
        for scan_type_cfg in config.scan_types:
            files: set[Path] = set()
            for pattern in scan_type_cfg.glob_patterns:
                files.update(subject_folder.rglob(pattern))
            scans[subject_id][scan_type_cfg.name] = SubjectScan(
                subject_id=subject_id,
                scan_type=scan_type_cfg.name,
                files=tuple(sorted(files)),
            )

    return BidsFolderScan(bids_folder=bids_folder, scans=scans)


def completeness_summary(scan: BidsFolderScan, config: DatasetConfig) -> dict[str, tuple[int, int]]:
    """scan-type name -> (subjects with exactly one file, total subjects)."""
    total = len(scan.scans)
    return {
        scan_type: (
            sum(
                1
                for subject_scans in scan.scans.values()
                if subject_scans[scan_type].status == "ok"
            ),
            total,
        )
        for scan_type in config.scan_type_names()
    }


def load_decisions(bids_folder: Path) -> dict:
    path = decisions_path(bids_folder)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as decisions_file:
        return json.load(decisions_file)


def _write_json_atomic(path: Path, data: dict) -> None:
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as tmp_file:
        json.dump(data, tmp_file, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def _write_decisions_atomic(bids_folder: Path, decisions: dict) -> None:
    _write_json_atomic(decisions_path(bids_folder), decisions)


def load_pending_selections(bids_folder: Path) -> dict[str, dict[str, str]]:
    """subject_id -> scan_type -> filename, for picks made but not yet committed.

    Kept in a file separate from `crosscheck.json`: these aren't decisions yet (see
    `record_selected_run`) -- just in-progress GUI state, persisted so closing the app
    before clicking "commit" doesn't lose the picks. Filenames only (not full paths),
    since the caller re-resolves them against a fresh scan's actual candidate files.
    """
    path = pending_selections_path(bids_folder)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as pending_file:
        return json.load(pending_file)


def save_pending_selections(bids_folder: Path, pending: dict[str, dict[str, str]]) -> None:
    _write_json_atomic(pending_selections_path(bids_folder), pending)


def _decision_key(subject_id: str, scan_type: str | None = None) -> str:
    return f"{subject_id}_{scan_type}" if scan_type else subject_id


def _crosschecked_key(subject_id: str, scan_type: str) -> str:
    # Deliberately distinct from _decision_key: crosschecked is an independent, human-toggled
    # marker that must not overwrite a selected_run/date_correction/task_correction entry
    # already recorded under the same subject_id/scan_type.
    return f"{_decision_key(subject_id, scan_type)}_crosschecked"


def _subject_junked_key(subject_id: str) -> str:
    # Deliberately distinct from _decision_key(subject_id) -- that bare key is already used by
    # record_id_correction's id_correction entries; junking a subject must not collide with an
    # existing ID-correction record for the same subject_id.
    return f"{subject_id}_junked"


def _move_to_junk(bids_folder: Path, file: Path) -> Path:
    destination = junk_folder(bids_folder) / file.relative_to(bids_folder)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(file), str(destination))
    return destination


def _restore_entry(bids_folder: Path, entry: Path, junk: Path, restored: list[Path]) -> None:
    destination = bids_folder / entry.relative_to(junk)
    if entry.is_dir() and destination.exists():
        # The mirrored folder already exists in bids_folder (e.g. record_selected_run junked
        # only some of this subject's duplicate files, not the whole subject via
        # record_subject_junked) -- merge by restoring its contents individually instead of
        # moving the folder itself, which would collide with the existing one.
        for child in sorted(entry.iterdir()):
            _restore_entry(bids_folder, child, junk, restored)
        try:
            entry.rmdir()
        except OSError:
            pass
        return
    if destination.exists():
        raise BidsCrosscheckError(f"{destination} already exists -- resolve manually")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(entry), str(destination))
    restored.append(destination)


def restore_all_from_junk(bids_folder: Path) -> tuple[list[Path], list[str]]:
    """Move everything currently in `crosscheck_junk/` back to where it came from.

    Junked files and folders mirror the path they came from (see `_move_to_junk` and
    `record_subject_junked`), so restoring is a direct reverse of that mirror -- no need to
    interpret which decision put something there. There's no selective, per-subject restore
    in this version (see docs/foh-crosscheck.md) -- it's everything in the junk folder, or
    nothing. Resilient at the file level, though: one entry that can't be restored (e.g.
    something already sitting at its destination) doesn't block the rest -- returns
    (restored_paths, error_messages) so the caller can report both.
    """
    junk = junk_folder(bids_folder)
    if not junk.is_dir():
        return [], []
    restored: list[Path] = []
    errors: list[str] = []
    for entry in sorted(junk.iterdir()):
        try:
            _restore_entry(bids_folder, entry, junk, restored)
        except (BidsCrosscheckError, OSError) as error:
            errors.append(f"{entry.relative_to(junk)}: {error}")
    return restored, errors


def record_selected_run(
    bids_folder: Path,
    subject_id: str,
    scan_type: str,
    selected_file: Path,
    candidate_files: tuple[Path, ...],
) -> None:
    """Pick `selected_file` as canonical among `candidate_files`; move the rest to junk."""
    if selected_file not in candidate_files:
        raise BidsCrosscheckError(f"{selected_file} is not among the candidate files")

    decisions = load_decisions(bids_folder)
    decisions[_decision_key(subject_id, scan_type)] = {
        "type": "selected_run",
        "subject_id": subject_id,
        "scan_type": scan_type,
        "selected_file": selected_file.name,
        "non_selected_files": [f.name for f in candidate_files if f != selected_file],
    }
    _write_decisions_atomic(bids_folder, decisions)

    for file in candidate_files:
        if file != selected_file:
            _move_to_junk(bids_folder, file)


def record_date_correction(
    bids_folder: Path,
    subject_id: str,
    scan_type: str,
    file: Path,
    corrected_date: str,
) -> Path:
    """Rewrite `file`'s leading date prefix (the part before the first `_`) to `corrected_date`.

    The decision is written before the rename, not after: a crash between the
    two steps must not be able to lose the mapping from the corrected
    filename back to the original one.
    """
    original_name = file.name
    original_date = original_name.split("_")[0]
    corrected_name = corrected_date + original_name[len(original_date) :]
    destination = file.with_name(corrected_name)
    if destination.exists():
        # Path.rename() only raises on an existing target on Windows -- on macOS/Linux it
        # silently replaces it. Checking explicitly makes the failure the same on every OS
        # instead of relying on that platform difference to catch it.
        raise BidsCrosscheckError(f"{destination} already exists -- resolve manually")

    decisions = load_decisions(bids_folder)
    decisions[_decision_key(subject_id, scan_type)] = {
        "type": "date_correction",
        "subject_id": subject_id,
        "scan_type": scan_type,
        "original_filename": original_name,
        "original_date": original_date,
        "corrected_date": corrected_date,
        "corrected_filename": corrected_name,
    }
    _write_decisions_atomic(bids_folder, decisions)

    file.rename(destination)
    return destination


def record_id_correction(bids_folder: Path, original_id: str, corrected_id: str) -> Path:
    """Rename every file for `original_id`, then its `sub-XXX/` folder, to `corrected_id`."""
    original_folder = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{original_id}"
    if not original_folder.is_dir():
        raise BidsCrosscheckError(f"No subject folder for {original_id!r}")

    original_token = f"{SUBJECT_FOLDER_PREFIX}{original_id}"
    corrected_token = f"{SUBJECT_FOLDER_PREFIX}{corrected_id}"
    corrected_folder = bids_folder / corrected_token
    if corrected_folder.exists():
        raise BidsCrosscheckError(f"{corrected_folder} already exists -- resolve manually")

    renames: list[tuple[Path, str]] = [
        (file, file.name.replace(original_token, corrected_token))
        for file in sorted(original_folder.rglob("*"))
        if file.is_file() and original_token in file.name
    ]
    # Path.rename() only raises on an existing target on Windows -- on macOS/Linux it
    # silently replaces it. Checking every destination up front, before any rename starts,
    # makes the failure the same on every OS and avoids a half-renamed subject folder.
    for file, new_name in renames:
        destination = file.with_name(new_name)
        if destination.exists():
            raise BidsCrosscheckError(f"{destination} already exists -- resolve manually")

    decisions = load_decisions(bids_folder)
    decisions[_decision_key(original_id)] = {
        "type": "id_correction",
        "original_id": original_id,
        "corrected_id": corrected_id,
        # .as_posix(), not str(): keeps this record's separator consistent regardless of
        # which OS wrote it, since the data folder itself may be shared across platforms.
        "renamed_files": [
            file.relative_to(bids_folder).as_posix() for file, _new_name in renames
        ],
    }
    _write_decisions_atomic(bids_folder, decisions)

    for file, new_name in renames:
        file.rename(file.with_name(new_name))

    original_folder.rename(corrected_folder)
    return corrected_folder


def record_subject_junked(bids_folder: Path, subject_id: str, reason: str | None = None) -> Path:
    """Move a whole subject's `sub-<id>/` folder to junk, decision recorded first.

    Unlike `record_selected_run` (which junks non-selected duplicate files, one scan type at a
    time), this removes the subject from the crosscheck view entirely -- e.g. a test recording,
    or someone who was never really a participant. `reason`, if given, is recorded alongside the
    decision so `crosscheck_junk/` stays auditable rather than an unexplained pile of folders.
    """
    original_folder = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{subject_id}"
    if not original_folder.is_dir():
        raise BidsCrosscheckError(f"No subject folder for {subject_id!r}")

    destination = junk_folder(bids_folder) / original_folder.name
    if destination.exists():
        raise BidsCrosscheckError(f"{destination} already exists -- resolve manually")

    decisions = load_decisions(bids_folder)
    decisions[_subject_junked_key(subject_id)] = {
        "type": "subject_junked",
        "subject_id": subject_id,
        "junked_reason": reason,
    }
    _write_decisions_atomic(bids_folder, decisions)

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(original_folder), str(destination))
    return destination


def crosschecked_scan_types(bids_folder: Path) -> set[tuple[str, str]]:
    """(subject_id, scan_type) pairs a human has manually marked as crosschecked.

    One `load_decisions` call for the whole folder, so callers (e.g. the GUI's
    subject list) can check membership per subject/scan-type without re-reading
    the JSON file each time.
    """
    decisions = load_decisions(bids_folder)
    return {
        (entry["subject_id"], entry["scan_type"])
        for entry in decisions.values()
        if entry.get("type") == "crosschecked" and entry.get("crosschecked")
    }


def set_crosschecked(
    bids_folder: Path, subject_id: str, scan_type: str, crosschecked: bool
) -> None:
    """Manually mark (or unmark) a subject/scan-type as reviewed, independent of file status.

    This is an override a human can set regardless of the automatic ok/missing/duplicate
    status -- e.g. to acknowledge a duplicate that's fine to leave as-is, or simply to record
    that they've looked at it. Toggling it off (calling again with `crosschecked=False`)
    removes the mark.
    """
    decisions = load_decisions(bids_folder)
    decisions[_crosschecked_key(subject_id, scan_type)] = {
        "type": "crosschecked",
        "subject_id": subject_id,
        "scan_type": scan_type,
        "crosschecked": crosschecked,
    }
    _write_decisions_atomic(bids_folder, decisions)


def record_task_correction(
    bids_folder: Path,
    subject_id: str,
    scan_type: str,
    file: Path,
    label: str = "FOH",
) -> Path:
    """Rename `file` to `..._run-<NNN>_{label}{suffix}`, replacing whatever the collection
    software put after the run number (e.g. `_eeg_philani`) -- BIDS suffixes are a fixed
    vocabulary, and free text there isn't valid BIDS. Always available regardless of stream
    detection.
    """
    if f"_{label}" in file.stem:
        raise BidsCrosscheckError(f"{file.name} already carries the {label!r} label")

    run_token = RUN_TOKEN_PATTERN.search(file.stem)
    if run_token is None:
        raise BidsCrosscheckError(f"{file.name} has no run-<NNN> token to rename from")
    corrected_name = f"{file.stem[: run_token.end()]}_{label}{file.suffix}"
    destination = file.with_name(corrected_name)
    if destination.exists():
        # See record_date_correction for why this is checked explicitly rather than relying
        # on Path.rename()'s own (Windows-only) FileExistsError.
        raise BidsCrosscheckError(f"{destination} already exists -- resolve manually")

    decisions = load_decisions(bids_folder)
    decisions[_decision_key(subject_id, scan_type)] = {
        "type": "task_correction",
        "subject_id": subject_id,
        "scan_type": scan_type,
        "original_filename": file.name,
        "corrected_filename": corrected_name,
        "label": label,
    }
    _write_decisions_atomic(bids_folder, decisions)

    file.rename(destination)
    return destination


def remove_task_correction(
    bids_folder: Path,
    subject_id: str,
    scan_type: str,
    file: Path,
    label: str = "FOH",
) -> Path:
    """Reverse `record_task_correction`: rename `file` back to its recorded original name.

    Can't be computed structurally from `file`'s current name alone -- record_task_correction
    replaces everything after the run-<NNN> token, so the original suffix (e.g.
    `_eeg_philani`) isn't recoverable from `..._FOH` by itself. Falls back to stripping just
    the tag (losing the original suffix) only if no matching recorded decision exists -- e.g.
    the file was tagged outside this tool, or a later, different decision overwrote the record
    at that key.
    """
    suffix_tag = f"_{label}"
    if not file.stem.endswith(suffix_tag):
        raise BidsCrosscheckError(f"{file.name} does not carry a trailing {label!r} tag")

    decisions = load_decisions(bids_folder)
    recorded = decisions.get(_decision_key(subject_id, scan_type))
    if (
        recorded is not None
        and recorded.get("type") == "task_correction"
        and recorded.get("corrected_filename") == file.name
    ):
        corrected_name = recorded["original_filename"]
    else:
        corrected_name = f"{file.stem[: -len(suffix_tag)]}{file.suffix}"
    destination = file.with_name(corrected_name)
    if destination.exists():
        # See record_date_correction for why this is checked explicitly rather than relying
        # on Path.rename()'s own (Windows-only) FileExistsError.
        raise BidsCrosscheckError(f"{destination} already exists -- resolve manually")

    decisions[_decision_key(subject_id, scan_type)] = {
        "type": "task_correction_removed",
        "subject_id": subject_id,
        "scan_type": scan_type,
        "original_filename": file.name,
        "corrected_filename": corrected_name,
        "label": label,
    }
    _write_decisions_atomic(bids_folder, decisions)

    file.rename(destination)
    return destination


_REVERTIBLE_RENAME_TYPES = ("date_correction", "task_correction", "task_correction_removed")


def revert_all_decisions(bids_folder: Path) -> tuple[list[Path], list[str]]:
    """Reverse every recorded rename-type decision's effect, best-effort, then clear the
    decisions record (`crosscheck.json`) and any pending, uncommitted picks.

    Only reverses the *latest* recorded decision for each subject/scan-type key: each new
    decision overwrites the previous entry at that key (see `_decision_key`), so
    `crosscheck.json` never holds more than one step of history per key. A file corrected
    twice (e.g. its date fixed, then later tagged FOH) can only be reverted back to its
    *first-corrected* state, not all the way to its original name -- the earlier correction's
    record is already gone by the time this runs. There's no selective, per-decision revert in
    this version (see docs/foh-crosscheck.md) -- it's everything recorded, or nothing.

    Junked files/subjects are untouched here -- see `restore_all_from_junk` for those; run
    that first if you want renames reverted *and* junked files back before reverting them too.
    """
    decisions = load_decisions(bids_folder)
    reverted: list[Path] = []
    errors: list[str] = []

    for key, entry in decisions.items():
        entry_type = entry.get("type")
        try:
            if entry_type in _REVERTIBLE_RENAME_TYPES:
                subject_folder = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{entry['subject_id']}"
                corrected_file = next(subject_folder.rglob(entry["corrected_filename"]), None)
                if corrected_file is None:
                    continue
                destination = corrected_file.with_name(entry["original_filename"])
                if destination.exists():
                    errors.append(f"{key}: {destination} already exists -- skipped")
                    continue
                corrected_file.rename(destination)
                reverted.append(destination)
            elif entry_type == "id_correction":
                corrected_folder = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{entry['corrected_id']}"
                if not corrected_folder.is_dir():
                    continue
                reverted.append(
                    record_id_correction(bids_folder, entry["corrected_id"], entry["original_id"])
                )
        except (BidsCrosscheckError, OSError) as error:
            errors.append(f"{key}: {error}")

    _write_json_atomic(decisions_path(bids_folder), {})
    _write_json_atomic(pending_selections_path(bids_folder), {})
    return reverted, errors
