import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

DECISIONS_FILENAME = "crosscheck.json"
PENDING_SELECTIONS_FILENAME = "crosscheck_pending.json"
JUNK_FOLDER_NAME = "crosscheck_junk"
SUBJECT_FOLDER_PREFIX = "sub-"

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


def _move_to_junk(bids_folder: Path, file: Path) -> Path:
    destination = junk_folder(bids_folder) / file.relative_to(bids_folder)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(file), str(destination))
    return destination


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

    destination = file.with_name(corrected_name)
    file.rename(destination)
    return destination


def record_id_correction(bids_folder: Path, original_id: str, corrected_id: str) -> Path:
    """Rename every file for `original_id`, then its `sub-XXX/` folder, to `corrected_id`."""
    original_folder = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{original_id}"
    if not original_folder.is_dir():
        raise BidsCrosscheckError(f"No subject folder for {original_id!r}")

    original_token = f"{SUBJECT_FOLDER_PREFIX}{original_id}"
    corrected_token = f"{SUBJECT_FOLDER_PREFIX}{corrected_id}"

    renames: list[tuple[Path, str]] = [
        (file, file.name.replace(original_token, corrected_token))
        for file in sorted(original_folder.rglob("*"))
        if file.is_file() and original_token in file.name
    ]

    decisions = load_decisions(bids_folder)
    decisions[_decision_key(original_id)] = {
        "type": "id_correction",
        "original_id": original_id,
        "corrected_id": corrected_id,
        "renamed_files": [str(file.relative_to(bids_folder)) for file, _new_name in renames],
    }
    _write_decisions_atomic(bids_folder, decisions)

    for file, new_name in renames:
        file.rename(file.with_name(new_name))

    corrected_folder = bids_folder / corrected_token
    original_folder.rename(corrected_folder)
    return corrected_folder


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
    """Rename `file` to include `label`, always available regardless of stream detection."""
    if f"_{label}" in file.stem:
        raise BidsCrosscheckError(f"{file.name} already carries the {label!r} label")

    corrected_name = f"{file.stem}_{label}{file.suffix}"

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

    destination = file.with_name(corrected_name)
    file.rename(destination)
    return destination


def remove_task_correction(
    bids_folder: Path,
    subject_id: str,
    scan_type: str,
    file: Path,
    label: str = "FOH",
) -> Path:
    """Reverse `record_task_correction`: strip a trailing `_{label}` tag from `file`'s name."""
    suffix_tag = f"_{label}"
    if not file.stem.endswith(suffix_tag):
        raise BidsCrosscheckError(f"{file.name} does not carry a trailing {label!r} tag")

    corrected_name = f"{file.stem[: -len(suffix_tag)]}{file.suffix}"

    decisions = load_decisions(bids_folder)
    decisions[_decision_key(subject_id, scan_type)] = {
        "type": "task_correction_removed",
        "subject_id": subject_id,
        "scan_type": scan_type,
        "original_filename": file.name,
        "corrected_filename": corrected_name,
        "label": label,
    }
    _write_decisions_atomic(bids_folder, decisions)

    destination = file.with_name(corrected_name)
    file.rename(destination)
    return destination
