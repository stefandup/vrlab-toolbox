import csv
import json
import logging
import os
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

DECISIONS_FILENAME = "crosscheck.json"
PENDING_SELECTIONS_FILENAME = "crosscheck_pending.json"
EXCLUDED_SUBJECTS_FILENAME = "excluded_subjects.json"
STUDY_ID_FILENAME = "study_id.json"
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
    task_tag_scan_type: str | None = None
    # The BIDS `task-<task>` entity value to insert (e.g. "foh"), the BIDS suffix to rename
    # the trailing free text to (e.g. "beh"), and an optional `acq-<acq>` entity (e.g. "lsl")
    # -- see record_task_tag for how these combine into the actual filename.
    task_tag_task: str = "foh"
    task_tag_suffix: str = "beh"
    task_tag_acq: str | None = None
    task_tag_folder_name: str | None = None
    # True for datasets (e.g. crane) that record each file's acquisition date as a row in a
    # `scans.tsv` sidecar (see processing/crane_bids.py) instead of a leading filename
    # date prefix -- gates whether the crosscheck GUI's "Correct date..." button edits that
    # row (record_scans_tsv_date_correction) or renames the file (record_date_correction).
    dates_in_scans_tsv: bool = False

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


def decisions_path(bids_folder: Path) -> Path:
    return bids_folder / DECISIONS_FILENAME


def pending_selections_path(bids_folder: Path) -> Path:
    return bids_folder / PENDING_SELECTIONS_FILENAME


def excluded_subjects_path(bids_folder: Path) -> Path:
    return bids_folder / EXCLUDED_SUBJECTS_FILENAME


def study_id_path(bids_folder: Path) -> Path:
    return bids_folder / STUDY_ID_FILENAME


def load_study_id(bids_folder: Path) -> str | None:
    """The short study id previously saved for this BIDS folder (see `save_study_id`), or
    None if none has been set yet. Lives inside `bids_folder` itself, not app settings, so
    it travels with the folder if it's ever copied or moved elsewhere.
    """
    path = study_id_path(bids_folder)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as study_id_file:
        return json.load(study_id_file).get("study_id")


def save_study_id(bids_folder: Path, study_id: str) -> None:
    _write_json_atomic(study_id_path(bids_folder), {"study_id": study_id})


def _is_real_collision(destination: Path, source: Path) -> bool:
    """True if `destination` exists and isn't just `source` itself under a different case.

    Windows (NTFS) and macOS (default APFS) are case-insensitive filesystems -- renaming
    `foo_FOH.xdf` to `foo_foh.xdf` makes `destination.exists()` true even though nothing is
    actually in the way, since it resolves to the very file being renamed. `os.path.samefile`
    checks file identity (device + inode/file-index), not the path string, so a pure case
    change is correctly treated as safe while a genuine collision still isn't.
    """
    if not destination.exists():
        return False
    if source.exists() and os.path.samefile(destination, source):
        return False
    return True


def ensure_bidsignore(bids_folder: Path, extra_patterns: tuple[str, ...] = ()) -> None:
    """Make sure this tool's own files are listed in `.bidsignore`, so a BIDS validator
    doesn't flag them as unexpected. Appends only whatever's missing -- `.bidsignore` is a
    human-maintained file this tool doesn't own, so existing content (and ordering) is left
    alone. Safe to call on every folder load: a no-op once the patterns are already there.
    """
    required = (
        DECISIONS_FILENAME,
        PENDING_SELECTIONS_FILENAME,
        EXCLUDED_SUBJECTS_FILENAME,
        STUDY_ID_FILENAME,
        *extra_patterns,
    )
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


def iter_subject_folders(bids_folder: Path):
    for entry in sorted(bids_folder.iterdir()):
        if entry.is_dir() and entry.name.startswith(SUBJECT_FOLDER_PREFIX):
            yield entry.name[len(SUBJECT_FOLDER_PREFIX) :], entry


def load_excluded_subjects(bids_folder: Path) -> dict[str, str | None]:
    """`{subject_id: reason}` for every subject a human has removed from BIDS (reason may be
    None). See `record_subject_excluded`."""
    path = excluded_subjects_path(bids_folder)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as excluded_file:
        return json.load(excluded_file)


def save_excluded_subjects(bids_folder: Path, excluded: dict[str, str | None]) -> None:
    _write_json_atomic(excluded_subjects_path(bids_folder), excluded)


def existing_subject_ids(bids_folder: Path) -> set[str]:
    """Every subject id that should be treated as already handled: either it still has a
    `sub-XXX/` folder in `bids_folder`, it's been removed from BIDS via
    `record_subject_excluded` (whose folder is deleted, not kept), or it's been renamed away
    via `record_id_correction` (whose folder is renamed, not kept under the original id) --
    without either of the latter two, that original id would look brand new to a raw-to-BIDS
    importer (raw filenames still parse to it -- renaming only touches `bids_folder`, never
    the raw source) and get silently re-copied back in on the very next refresh, sitting
    alongside the renamed subject as a duplicate. A reverted rename naturally drops back out
    of this set, since `revert_all_decisions` clears `decisions.json` entirely.

    Shared by every raw-to-BIDS importer (`processing/crane_bids.py`,
    `cli/foh_import_to_bids.py`) to decide which subjects to skip -- copy-only,
    incremental-by-subject is the common contract across datasets (see
    docs/bids_converter_plan.md), even though what counts as "a subject's data" differs
    per dataset.
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


def scan_bids_folder(bids_folder: Path, config: DatasetConfig) -> BidsFolderScan:
    """Scan `bids_folder` for every subject x scan-type candidate file.

    Read-only: never moves, renames, or writes anything. A subject a human has excluded (see
    `record_subject_excluded`) simply isn't found here, since its folder no longer exists.
    """
    scans: dict[str, dict[str, SubjectScan]] = {}

    for subject_id, subject_folder in iter_subject_folders(bids_folder):
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
    # marker that must not overwrite a selected_run/date_correction/task_tag entry already
    # recorded under the same subject_id/scan_type.
    return f"{_decision_key(subject_id, scan_type)}_crosschecked"


def _append_decision(decisions: dict, key: str, entry: dict) -> None:
    """Add `entry` to `key`'s history, oldest first -- never overwrites a previous entry, so a
    chain of corrections on the same subject/scan-type (e.g. date-corrected, then later tagged)
    is fully preserved instead of only the latest step surviving. See `_latest_decision` for the
    common case of only caring about the current state.
    """
    decisions.setdefault(key, []).append(entry)


def _latest_decision(decisions: dict, key: str) -> dict | None:
    """The most recent entry in `key`'s history, or None if it has none -- the read-side
    counterpart to `_append_decision` for callers that only care about current state, not the
    full chain (most callers; `revert_all_decisions` and `rebuild_from_raw` are the exceptions
    that need the whole history).
    """
    entries = decisions.get(key)
    return entries[-1] if entries else None


def record_subject_excluded(bids_folder: Path, subject_id: str, reason: str | None = None) -> Path:
    """Remove a whole subject's `sub-<id>/` folder from BIDS -- e.g. a test recording, or
    someone who was never really a participant.

    Deletes outright rather than moving anywhere (unlike the old `crosscheck_junk/`): no
    importer/converter in this project ever touches the raw folder, so it's still the
    authoritative, recoverable copy -- keeping a second copy inside BIDS was redundant.
    `reason`, if given, is recorded alongside the exclusion (`excluded_subjects.json`) so it
    stays auditable. See `restore_all_from_bids` to undo -- it clears the exclusion and lets
    the next raw-to-BIDS refresh re-derive the subject fresh from raw.
    """
    original_folder = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{subject_id}"
    if not original_folder.is_dir():
        raise BidsCrosscheckError(f"No subject folder for {subject_id!r}")

    shutil.rmtree(original_folder)
    excluded = load_excluded_subjects(bids_folder)
    excluded[subject_id] = reason
    save_excluded_subjects(bids_folder, excluded)
    return original_folder


def _restore_subjects(bids_folder: Path, subject_ids: set[str] | None) -> tuple[list[str], list[str]]:
    """Shared implementation behind `restore_all_from_bids` (`subject_ids=None`) and
    `restore_subjects_from_bids` (a specific set) -- see either for why this can't just move
    something back. Resilient at the subject level: one failure doesn't block the rest.
    Returns (restored_subject_ids, error_messages).
    """
    restored: set[str] = set()
    errors: list[str] = []

    excluded = load_excluded_subjects(bids_folder)
    to_clear = {sid for sid in excluded if subject_ids is None or sid in subject_ids}
    if to_clear:
        restored.update(to_clear)
        save_excluded_subjects(
            bids_folder, {sid: reason for sid, reason in excluded.items() if sid not in to_clear}
        )

    decisions = load_decisions(bids_folder)
    # A committed duplicate pick can be followed later by a further correction on the same
    # key (e.g. the surviving file gets date-corrected or tagged afterward) -- searching the
    # whole history, not just the latest entry, so a subject with a selected_run buried earlier
    # in its key's chain still gets found and restored. Deduped by key (a dict, not a list of
    # pairs): a key could in principle carry more than one selected_run over time (a rename
    # creating a fresh collision, resolved again), and each key is only deleted once below.
    selected_run_keys: dict[str, dict] = {}
    for key, entries in decisions.items():
        for entry in entries:
            if entry.get("type") == "selected_run" and (
                subject_ids is None or entry.get("subject_id") in subject_ids
            ):
                selected_run_keys[key] = entry
                break
    changed = False
    for key, selected_run_entry in selected_run_keys.items():
        subject_id = selected_run_entry["subject_id"]
        folder = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{subject_id}"
        try:
            if folder.is_dir():
                shutil.rmtree(folder)
            del decisions[key]
            changed = True
            restored.add(subject_id)
        except OSError as error:
            errors.append(f"sub-{subject_id}: {error}")
    if changed:
        _write_decisions_atomic(bids_folder, decisions)

    return sorted(restored), errors


def restore_all_from_bids(bids_folder: Path) -> tuple[list[str], list[str]]:
    """Undo every subject exclusion and every committed duplicate pick, so the next
    raw-to-BIDS refresh re-derives all of it fresh from the never-touched raw folder.

    There's no per-file restore: neither an excluded subject's folder
    (`record_subject_excluded`) nor a non-selected duplicate candidate (`record_selected_run`)
    is kept anywhere inside `bids_folder` once removed -- both are deleted outright, on the
    guarantee that the raw folder still has the original. Restoring therefore can't just move
    something back; for an excluded subject it clears the exclusion record, and for a
    committed pick it deletes what's left of that subject's folder too, so the next refresh
    re-derives the WHOLE subject (every scan type, not just the one that had a duplicate) --
    any other decision already made for that subject (date corrections, crosschecked marks,
    other scan types' picks) goes with it. Bulk: every removed/deduped subject in the folder,
    at once. See `restore_subjects_from_bids` for the same thing scoped to specific subjects.
    """
    return _restore_subjects(bids_folder, None)


def restore_subjects_from_bids(bids_folder: Path, subject_ids: Iterable[str]) -> tuple[list[str], list[str]]:
    """Same as `restore_all_from_bids`, scoped to just `subject_ids` -- every other subject's
    exclusion/duplicate-pick decisions are left untouched. Only reaches a subject that's still
    visible in the crosscheck GUI's subject table (i.e. it currently has a committed duplicate
    pick to undo) -- a fully excluded subject has no folder left to select a row for, so it
    isn't reachable this way yet; `restore_all_from_bids` remains the only way to bring one of
    those back.
    """
    return _restore_subjects(bids_folder, set(subject_ids))


def record_selected_run(
    bids_folder: Path,
    subject_id: str,
    scan_type: str,
    selected_file: Path,
    candidate_files: tuple[Path, ...],
) -> None:
    """Pick `selected_file` as canonical among `candidate_files`; delete the rest outright.

    Deleted, not moved aside (unlike the old `crosscheck_review/`) -- no importer/converter
    in this project ever touches the raw folder, so a non-selected duplicate is always still
    recoverable from there. See `restore_all_from_bids` to undo (re-derives the whole
    subject fresh on the next refresh, not just this one file).
    """
    if selected_file not in candidate_files:
        raise BidsCrosscheckError(f"{selected_file} is not among the candidate files")

    decisions = load_decisions(bids_folder)
    _append_decision(decisions, _decision_key(subject_id, scan_type), {
        "type": "selected_run",
        "subject_id": subject_id,
        "scan_type": scan_type,
        "selected_file": selected_file.name,
        "non_selected_files": [f.name for f in candidate_files if f != selected_file],
    })
    _write_decisions_atomic(bids_folder, decisions)

    for file in candidate_files:
        if file != selected_file:
            _remove_scans_tsv_row(bids_folder, file)
            file.unlink()


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
    if _is_real_collision(destination, file):
        # Path.rename() only raises on an existing target on Windows -- on macOS/Linux it
        # silently replaces it. Checking explicitly makes the failure the same on every OS
        # instead of relying on that platform difference to catch it.
        raise BidsCrosscheckError(f"{destination} already exists -- resolve manually")

    decisions = load_decisions(bids_folder)
    _append_decision(decisions, _decision_key(subject_id, scan_type), {
        "type": "date_correction",
        "subject_id": subject_id,
        "scan_type": scan_type,
        "original_filename": original_name,
        "original_date": original_date,
        "corrected_date": corrected_date,
        "corrected_filename": corrected_name,
    })
    _write_decisions_atomic(bids_folder, decisions)

    file.rename(destination)
    return destination


def record_filename_correction(
    bids_folder: Path,
    subject_id: str,
    scan_type: str,
    file: Path,
    corrected_name: str,
) -> Path:
    """Rename `file` to `corrected_name` verbatim, within the same folder -- a general escape
    hatch for fixing any part of a BIDS filename a human spots as wrong (a stray "-dupN"
    collision marker left over from a naming clash, a wrong `task-`/`acq-` entity, ...), not
    just the specific pieces `record_date_correction`/`record_task_tag` already cover.
    Revertible the same way as those (see `_REVERTIBLE_RENAME_TYPES`).
    """
    if corrected_name == file.name:
        raise BidsCrosscheckError("New filename is the same as the current one")
    destination = file.with_name(corrected_name)
    if _is_real_collision(destination, file):
        raise BidsCrosscheckError(f"{destination} already exists -- resolve manually")

    decisions = load_decisions(bids_folder)
    _append_decision(decisions, _decision_key(subject_id, scan_type), {
        "type": "filename_correction",
        "subject_id": subject_id,
        "scan_type": scan_type,
        "original_filename": file.name,
        "corrected_filename": corrected_name,
        "original_parent_folder": file.parent.name,
        "corrected_parent_folder": file.parent.name,
    })
    _write_decisions_atomic(bids_folder, decisions)

    file.rename(destination)
    _sync_scans_tsv_filename(bids_folder, file, destination)
    return destination


def _find_scans_tsv(bids_folder: Path, file: Path) -> Path | None:
    """The `*_scans.tsv` sidecar that should list `file`, if this dataset uses one -- walks up
    from `file`'s own folder looking for one, rather than assuming a fixed depth, since only
    crane uses this layout today and its exact nesting shouldn't need to be hardcoded here too.
    Returns None if there isn't one (e.g. FOH, which doesn't use `scans.tsv` at all) by the
    time it reaches `bids_folder`.
    """
    folder = file.parent
    while True:
        matches = sorted(folder.glob("*_scans.tsv"))
        if matches:
            return matches[0]
        if folder == bids_folder or folder == folder.parent:
            return None
        folder = folder.parent


def _read_scans_tsv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as tsv_file:
        return list(csv.DictReader(tsv_file, delimiter="\t"))


def _write_scans_tsv_rows(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as tsv_file:
        writer = csv.DictWriter(tsv_file, fieldnames=["filename", "acq_time"], delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _sync_scans_tsv_filename(bids_folder: Path, old_file: Path, new_file: Path) -> None:
    """Keep a `scans.tsv` sidecar's `filename` column pointed at `new_file` after
    `record_task_tag`/`remove_task_tag`/`revert_all_decisions` renames a file
    (and possibly its parent datatype folder) -- otherwise the sidecar silently keeps listing
    the file under a name that no longer exists. No-op for datasets without one (e.g. FOH).
    """
    scans_tsv = _find_scans_tsv(bids_folder, new_file)
    if scans_tsv is None:
        return
    old_relative = old_file.relative_to(scans_tsv.parent).as_posix()
    new_relative = new_file.relative_to(scans_tsv.parent).as_posix()
    if old_relative == new_relative:
        return
    rows = _read_scans_tsv_rows(scans_tsv)
    changed = False
    for row in rows:
        if row.get("filename") == old_relative:
            row["filename"] = new_relative
            changed = True
    if changed:
        _write_scans_tsv_rows(scans_tsv, rows)


def _remove_scans_tsv_row(bids_folder: Path, file: Path) -> None:
    """Drop `file`'s own row from its `scans.tsv` sidecar, if it has one -- used when a
    non-selected duplicate candidate is deleted outright (`record_selected_run`) so the
    sidecar doesn't keep listing a file that no longer exists. No-op for datasets without one
    (e.g. FOH).
    """
    scans_tsv = _find_scans_tsv(bids_folder, file)
    if scans_tsv is None:
        return
    relative_name = file.relative_to(scans_tsv.parent).as_posix()
    rows = _read_scans_tsv_rows(scans_tsv)
    remaining = [row for row in rows if row.get("filename") != relative_name]
    if len(remaining) != len(rows):
        _write_scans_tsv_rows(scans_tsv, remaining)


def read_scans_tsv_date(bids_folder: Path, file: Path) -> str | None:
    """Current `acq_time` value for `file`'s row in its `scans.tsv`, if any -- used by the
    crosscheck GUI to pre-fill its "Correct date..." dialog for datasets with
    `DatasetConfig.dates_in_scans_tsv` set, the same way `file.name.split("_")[0]` pre-fills it
    for filename-prefix datasets.
    """
    scans_tsv = _find_scans_tsv(bids_folder, file)
    if scans_tsv is None:
        return None
    relative_name = file.relative_to(scans_tsv.parent).as_posix()
    for row in _read_scans_tsv_rows(scans_tsv):
        if row.get("filename") == relative_name:
            return row.get("acq_time")
    return None


def record_scans_tsv_date_correction(
    bids_folder: Path,
    subject_id: str,
    scan_type: str,
    file: Path,
    corrected_date: str,
) -> Path:
    """Crane counterpart to `record_date_correction`, for datasets that record each file's
    acquisition date as a row in a `scans.tsv` sidecar (BIDS's own place for it) instead of a
    leading filename prefix -- see docs/bids_converter_plan.md. Rewrites the matching row's
    `acq_time` value in place; `file` itself is never renamed, so this returns `file` unchanged
    (there's nothing for a caller to follow, unlike `record_date_correction`'s rename).
    """
    scans_tsv = _find_scans_tsv(bids_folder, file)
    if scans_tsv is None:
        raise BidsCrosscheckError(f"No scans.tsv found for {file.name} -- nothing to correct")

    relative_name = file.relative_to(scans_tsv.parent).as_posix()
    rows = _read_scans_tsv_rows(scans_tsv)
    matching_rows = [row for row in rows if row.get("filename") == relative_name]
    if not matching_rows:
        raise BidsCrosscheckError(f"No {relative_name!r} row found in {scans_tsv}")

    original_date = matching_rows[0].get("acq_time", "")

    decisions = load_decisions(bids_folder)
    _append_decision(decisions, _decision_key(subject_id, scan_type), {
        "type": "scans_tsv_date_correction",
        "subject_id": subject_id,
        "scan_type": scan_type,
        "scans_tsv": scans_tsv.relative_to(bids_folder).as_posix(),
        "filename": relative_name,
        "original_date": original_date,
        "corrected_date": corrected_date,
    })
    _write_decisions_atomic(bids_folder, decisions)

    for row in matching_rows:
        row["acq_time"] = corrected_date
    _write_scans_tsv_rows(scans_tsv, rows)
    return file


def list_scans_tsv_rows(bids_folder: Path, subject_id: str) -> list[dict[str, str]] | None:
    """Every row of `subject_id`'s `scans.tsv` sidecar (`filename`, `acq_time`), for the
    crosscheck GUI's scans.tsv pane -- unlike `read_scans_tsv_date`, which only looks up one
    file's row, this lists everything the sidecar currently tracks for the subject, including
    rows for files a duplicate pick has since made ineffective. Returns None if the subject has
    no scans.tsv at all (e.g. not converted yet, or a dataset that doesn't use one -- see
    `DatasetConfig.dates_in_scans_tsv`).
    """
    subject_folder = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{subject_id}"
    matches = sorted(subject_folder.glob("**/*_scans.tsv"))
    if not matches:
        return None
    return _read_scans_tsv_rows(matches[0])


def record_scans_tsv_row_date_correction(
    bids_folder: Path,
    subject_id: str,
    relative_filename: str,
    corrected_date: str,
) -> None:
    """Corrects one scans.tsv row's `acq_time` by its `filename` column value directly, for the
    crosscheck GUI's scans.tsv pane (which edits any row it lists, not just whichever file is
    currently effective per scan type -- see `record_scans_tsv_date_correction` for that
    narrower, scan-type-keyed counterpart used by "Correct date..." on the scan-type panes
    above). Reuses the same `scans_tsv_date_correction` decision type -- keyed by the filename
    rather than a scan type, since a scans.tsv row doesn't always correspond to one -- so
    `revert_all_decisions` already knows how to undo this too.
    """
    subject_folder = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{subject_id}"
    matches = sorted(subject_folder.glob("**/*_scans.tsv"))
    if not matches:
        raise BidsCrosscheckError(f"No scans.tsv found for subject {subject_id!r}")
    scans_tsv = matches[0]

    rows = _read_scans_tsv_rows(scans_tsv)
    matching_rows = [row for row in rows if row.get("filename") == relative_filename]
    if not matching_rows:
        raise BidsCrosscheckError(f"No {relative_filename!r} row found in {scans_tsv}")

    original_date = matching_rows[0].get("acq_time", "")

    decisions = load_decisions(bids_folder)
    _append_decision(decisions, _decision_key(subject_id, f"scans_tsv:{relative_filename}"), {
        "type": "scans_tsv_date_correction",
        "subject_id": subject_id,
        "scan_type": f"scans_tsv:{relative_filename}",
        "scans_tsv": scans_tsv.relative_to(bids_folder).as_posix(),
        "filename": relative_filename,
        "original_date": original_date,
        "corrected_date": corrected_date,
    })
    _write_decisions_atomic(bids_folder, decisions)

    for row in matching_rows:
        row["acq_time"] = corrected_date
    _write_scans_tsv_rows(scans_tsv, rows)


def record_id_correction(bids_folder: Path, original_id: str, corrected_id: str) -> Path:
    """Rename every file for `original_id`, then its `sub-XXX/` folder, to `corrected_id`."""
    original_folder = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{original_id}"
    if not original_folder.is_dir():
        raise BidsCrosscheckError(f"No subject folder for {original_id!r}")

    original_token = f"{SUBJECT_FOLDER_PREFIX}{original_id}"
    corrected_token = f"{SUBJECT_FOLDER_PREFIX}{corrected_id}"
    corrected_folder = bids_folder / corrected_token
    if _is_real_collision(corrected_folder, original_folder):
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
        if _is_real_collision(destination, file):
            raise BidsCrosscheckError(f"{destination} already exists -- resolve manually")

    # A `scans.tsv` (crane's DatasetConfig.dates_in_scans_tsv layout) lists other renamed
    # files by name in its own `filename` column -- renaming the files on disk above doesn't
    # touch that column, so without this it'd silently go stale, still pointing at the old
    # subject id. No-op for datasets without one (e.g. FOH): scans_tsv_renames is just empty.
    scans_tsv_renames = [
        (file, new_name) for file, new_name in renames if new_name.endswith("_scans.tsv")
    ]

    decisions = load_decisions(bids_folder)
    _append_decision(decisions, _decision_key(original_id), {
        "type": "id_correction",
        "original_id": original_id,
        "corrected_id": corrected_id,
        # .as_posix(), not str(): keeps this record's separator consistent regardless of
        # which OS wrote it, since the data folder itself may be shared across platforms.
        "renamed_files": [
            file.relative_to(bids_folder).as_posix() for file, _new_name in renames
        ],
    })
    _write_decisions_atomic(bids_folder, decisions)

    for file, new_name in renames:
        file.rename(file.with_name(new_name))

    original_folder.rename(corrected_folder)

    for file, new_name in scans_tsv_renames:
        relative_dir = file.parent.relative_to(original_folder)
        scans_tsv = corrected_folder / relative_dir / new_name
        rows = _read_scans_tsv_rows(scans_tsv)
        for row in rows:
            if row.get("filename") and original_token in row["filename"]:
                row["filename"] = row["filename"].replace(original_token, corrected_token)
        _write_scans_tsv_rows(scans_tsv, rows)

    return corrected_folder


def crosschecked_scan_types(bids_folder: Path) -> set[tuple[str, str]]:
    """(subject_id, scan_type) pairs a human has manually marked as crosschecked.

    One `load_decisions` call for the whole folder, so callers (e.g. the GUI's
    subject list) can check membership per subject/scan-type without re-reading
    the JSON file each time.
    """
    decisions = load_decisions(bids_folder)
    return {
        (latest["subject_id"], latest["scan_type"])
        for entries in decisions.values()
        if (latest := entries[-1]).get("type") == "crosschecked" and latest.get("crosschecked")
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
    _append_decision(decisions, _crosschecked_key(subject_id, scan_type), {
        "type": "crosschecked",
        "subject_id": subject_id,
        "scan_type": scan_type,
        "crosschecked": crosschecked,
    })
    _write_decisions_atomic(bids_folder, decisions)


def _task_tag_marker(task: str) -> str:
    return f"task-{task}"


# Raw FOH recordings sometimes already carry a `task-<label>` entity of their own (e.g. the
# recording software's own default, `task-Default`) -- record_task_tag replaces an existing
# one in place rather than inserting a second, colliding `task-` token next to it.
_TASK_ENTITY_PATTERN = re.compile(r"task-[A-Za-z0-9]+")
_ACQ_ENTITY_PATTERN = re.compile(r"acq-[A-Za-z0-9]+")


def record_task_tag(
    bids_folder: Path,
    subject_id: str,
    scan_type: str,
    file: Path,
    task: str,
    suffix: str,
    acq: str | None = None,
    datatype_folder_name: str | None = None,
) -> Path:
    """Rename `file` to `..._task-<task>[_acq-<acq>]_run-<NNN>_<suffix>{extension}`, replacing
    an existing `task-`/`acq-` entity in place if the raw filename already carries one (e.g.
    the collection software's own `task-Default`), or inserting one fresh if not -- and
    replacing whatever the collection software put after the run number (e.g. `_eeg_philani`)
    with a real BIDS suffix, since free text there isn't valid BIDS. Always available
    regardless of stream detection.

    If `datatype_folder_name` is given and differs from `file`'s current parent folder name,
    that whole parent folder is renamed to it too, carrying along anything else still in it
    (e.g. not-yet-resolved duplicate candidates) -- e.g. FOH's raw folders are literally named
    "eeg" regardless of what the recording actually contains, which is misleading once a file's
    been confirmed and tagged.
    """
    marker = _task_tag_marker(task)
    # Case-insensitive: a file already tagged under a different casing of this marker still
    # counts as tagged -- Windows/macOS's case-insensitive filesystems would treat re-tagging
    # it as a collision with itself anyway (see _is_real_collision).
    if marker.lower() in file.stem.lower():
        raise BidsCrosscheckError(f"{file.name} already carries the {marker!r} tag")

    run_token = RUN_TOKEN_PATTERN.search(file.stem)
    if run_token is None:
        raise BidsCrosscheckError(f"{file.name} has no run-<NNN> token to tag from")

    prefix = file.stem[: run_token.start()]
    if _TASK_ENTITY_PATTERN.search(prefix):
        prefix = _TASK_ENTITY_PATTERN.sub(marker, prefix, count=1)
    else:
        prefix = f"{prefix}{marker}_"
    if acq:
        acq_token = f"acq-{acq}"
        if _ACQ_ENTITY_PATTERN.search(prefix):
            prefix = _ACQ_ENTITY_PATTERN.sub(acq_token, prefix, count=1)
        else:
            # Right after the (now-current) task- entity -- real BIDS entity order is
            # sub-ses-task-acq-...-run-suffix.
            prefix = _TASK_ENTITY_PATTERN.sub(lambda m: f"{m.group()}_{acq_token}", prefix, count=1)

    corrected_name = f"{prefix}{run_token.group()}_{suffix}{file.suffix}"
    destination = file.with_name(corrected_name)
    if _is_real_collision(destination, file):
        # See record_date_correction for why this is checked explicitly rather than relying
        # on Path.rename()'s own (Windows-only) FileExistsError.
        raise BidsCrosscheckError(f"{destination} already exists -- resolve manually")

    original_parent_name = file.parent.name
    new_parent = None
    if datatype_folder_name and original_parent_name != datatype_folder_name:
        new_parent = file.parent.with_name(datatype_folder_name)
        if _is_real_collision(new_parent, file.parent):
            raise BidsCrosscheckError(f"{new_parent} already exists -- resolve manually")

    decisions = load_decisions(bids_folder)
    _append_decision(decisions, _decision_key(subject_id, scan_type), {
        "type": "task_tag",
        "subject_id": subject_id,
        "scan_type": scan_type,
        "original_filename": file.name,
        "corrected_filename": corrected_name,
        "task": task,
        "acq": acq,
        "suffix": suffix,
        "original_parent_folder": original_parent_name,
        "corrected_parent_folder": new_parent.name if new_parent else original_parent_name,
    })
    _write_decisions_atomic(bids_folder, decisions)

    file.rename(destination)
    if new_parent is not None:
        old_parent = destination.parent
        old_parent.rename(new_parent)
        destination = new_parent / destination.name
    _sync_scans_tsv_filename(bids_folder, file, destination)
    return destination


def remove_task_tag(
    bids_folder: Path,
    subject_id: str,
    scan_type: str,
    file: Path,
    task: str,
    suffix: str,
    acq: str | None = None,
) -> Path:
    """Reverse `record_task_tag`: rename `file` back to its recorded original name.

    Can't be computed structurally from `file`'s current name alone in general --
    record_task_tag inserts the task-/acq- entity and replaces everything after the run-<NNN>
    token, so the original free text (e.g. `_eeg_philani`) isn't recoverable from the tagged
    name by itself. Falls back to a best-effort structural strip (losing the original free
    text) only if no matching recorded decision exists -- e.g. the file was tagged outside this
    tool entirely. The same fallback applies to the parent folder: it's only renamed back if the
    matching decision recorded what it was renamed from (see `record_task_tag`).
    """
    marker = _task_tag_marker(task)
    if marker.lower() not in file.stem.lower():
        raise BidsCrosscheckError(f"{file.name} does not carry a {marker!r} tag")

    decisions = load_decisions(bids_folder)
    key = _decision_key(subject_id, scan_type)
    # Searches the whole history, not just the latest entry: a later decision on the same key
    # that doesn't rename the file further (e.g. a fresh duplicate turning up and getting
    # resolved in this file's favor via selected_run) can still sit on top of the task_tag
    # entry. There's at most one match -- record_task_tag refuses to double-tag a file that
    # already carries the marker.
    recorded = next(
        (
            entry
            for entry in reversed(decisions.get(key, []))
            if entry.get("type") == "task_tag"
            and entry.get("corrected_filename", "").lower() == file.name.lower()
        ),
        None,
    )
    original_parent_folder = None
    if recorded is not None:
        corrected_name = recorded["original_filename"]
        original_parent_folder = recorded.get("original_parent_folder")
    else:
        run_token = RUN_TOKEN_PATTERN.search(file.stem)
        if run_token is None:
            raise BidsCrosscheckError(f"{file.name} has no run-<NNN> token to untag from")
        acq_part = f"_acq-{acq}" if acq else ""
        inserted = f"{marker}{acq_part}_"
        prefix = file.stem[: run_token.start()]
        if not prefix.lower().endswith(inserted.lower()):
            raise BidsCrosscheckError(f"{file.name} doesn't match the expected tagged shape")
        corrected_name = f"{prefix[: -len(inserted)]}{run_token.group()}{file.suffix}"
    destination = file.with_name(corrected_name)
    if _is_real_collision(destination, file):
        # See record_date_correction for why this is checked explicitly rather than relying
        # on Path.rename()'s own (Windows-only) FileExistsError.
        raise BidsCrosscheckError(f"{destination} already exists -- resolve manually")

    original_parent_name = file.parent.name
    new_parent = None
    if original_parent_folder and original_parent_name != original_parent_folder:
        new_parent = file.parent.with_name(original_parent_folder)
        if _is_real_collision(new_parent, file.parent):
            raise BidsCrosscheckError(f"{new_parent} already exists -- resolve manually")

    _append_decision(decisions, _decision_key(subject_id, scan_type), {
        "type": "task_tag_removed",
        "subject_id": subject_id,
        "scan_type": scan_type,
        "original_filename": file.name,
        "corrected_filename": corrected_name,
        "task": task,
        "acq": acq,
        "suffix": suffix,
        "original_parent_folder": original_parent_name,
        "corrected_parent_folder": new_parent.name if new_parent else original_parent_name,
    })
    _write_decisions_atomic(bids_folder, decisions)

    file.rename(destination)
    if new_parent is not None:
        old_parent = destination.parent
        old_parent.rename(new_parent)
        destination = new_parent / destination.name
    _sync_scans_tsv_filename(bids_folder, file, destination)
    return destination


_REVERTIBLE_RENAME_TYPES = (
    "date_correction",
    "task_tag",
    "task_tag_removed",
    "filename_correction",
)


def revert_all_decisions(bids_folder: Path) -> tuple[list[Path], list[str]]:
    """Reverse every recorded rename-type decision's effect, best-effort, then clear the
    decisions record (`crosscheck.json`) and any pending, uncommitted picks.

    Walks each key's full history newest-to-oldest, reversing every step -- not just the
    latest. Each rename-type reversal restores the file to its *previous* name, so undoing a
    `task_tag` first exposes the date-corrected name underneath, and the next (older)
    `date_correction` reversal then finds that name and restores the true original -- a file
    corrected more than once now reverts all the way back, not just to its first-corrected
    state.

    Excluded subjects and committed duplicate picks are untouched here -- see
    `restore_all_from_bids` for those; run that first if you want renames reverted *and*
    excluded/committed subjects back before reverting them too.
    """
    decisions = load_decisions(bids_folder)
    reverted: list[Path] = []
    errors: list[str] = []

    for key, entries in decisions.items():
        for entry in reversed(entries):
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
                    # date_correction entries never set this field, so this is a no-op for
                    # them -- only task_tag/task_tag_removed can carry a parent-folder rename.
                    original_parent_folder = entry.get("original_parent_folder")
                    if (
                        original_parent_folder
                        and destination.parent.name != original_parent_folder
                    ):
                        new_parent = destination.parent.with_name(original_parent_folder)
                        if not new_parent.exists():
                            destination.parent.rename(new_parent)
                            destination = new_parent / destination.name
                    _sync_scans_tsv_filename(bids_folder, corrected_file, destination)
                    reverted.append(destination)
                elif entry_type == "scans_tsv_date_correction":
                    scans_tsv = bids_folder / entry["scans_tsv"]
                    if not scans_tsv.is_file():
                        continue
                    rows = _read_scans_tsv_rows(scans_tsv)
                    matching_rows = [
                        row for row in rows if row.get("filename") == entry["filename"]
                    ]
                    if not matching_rows:
                        continue
                    for row in matching_rows:
                        row["acq_time"] = entry["original_date"]
                    _write_scans_tsv_rows(scans_tsv, rows)
                    reverted.append(scans_tsv)
                elif entry_type == "id_correction":
                    corrected_folder = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{entry['corrected_id']}"
                    if not corrected_folder.is_dir():
                        continue
                    reverted.append(
                        record_id_correction(
                            bids_folder, entry["corrected_id"], entry["original_id"]
                        )
                    )
            except (BidsCrosscheckError, OSError) as error:
                errors.append(f"{key}: {error}")

    _write_json_atomic(decisions_path(bids_folder), {})
    _write_json_atomic(pending_selections_path(bids_folder), {})
    return reverted, errors


BACKUP_FILENAMES = (
    DECISIONS_FILENAME,
    EXCLUDED_SUBJECTS_FILENAME,
    PENDING_SELECTIONS_FILENAME,
    STUDY_ID_FILENAME,
)


def backup_decisions(
    bids_folder: Path, backup_folder: Path, extra_filenames: tuple[str, ...] = ()
) -> list[Path]:
    """Copy this BIDS folder's crosscheck record files -- decisions, exclusions, and
    uncommitted pending picks -- into `backup_folder`, so they survive the BIDS folder itself
    being lost or corrupted. Nothing else in a BIDS folder needs backing up this way by
    default: the raw data is already safe in the raw folder (never touched by this tool), and
    everything else the crosscheck tool writes -- `crosscheck_info_cache.json` included -- is
    a re-derivable cache, not a decision record.

    `extra_filenames`, if given, adds dataset-specific files living alongside these (also
    resolved relative to `bids_folder`) -- e.g. crane's `debrief_id_corrections.json`/
    `raw_filename_id_corrections.json` (`processing/crane_bids.py`), which aren't
    `record_*`-style decisions but are still human-entered input a from-raw rebuild would
    otherwise lose. See `restore_backup_files`/`rebuild_from_raw` to restore from a backup
    made here.
    """
    backup_folder.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for filename in (*BACKUP_FILENAMES, *extra_filenames):
        source = bids_folder / filename
        if source.exists():
            destination = backup_folder / filename
            shutil.copy2(source, destination)
            copied.append(destination)
    return copied


def restore_backup_files(
    backup_folder: Path, bids_folder: Path, filenames: tuple[str, ...]
) -> list[Path]:
    """Copy each of `filenames` from `backup_folder` into `bids_folder` verbatim, if present.

    For dataset-specific files that a raw-to-BIDS *converter* itself reads as input (e.g.
    crane's debrief/raw-filename id corrections) rather than files `rebuild_from_raw` replays
    after the fact -- these need to already be sitting in `bids_folder` *before* the converter
    runs, so the next conversion resolves ids exactly as it originally would have, not only
    being recoverable for the decisions made afterward. Called ahead of the `raw_converter`
    hook, before `rebuild_from_raw`.
    """
    bids_folder.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for filename in filenames:
        source = backup_folder / filename
        if source.exists():
            destination = bids_folder / filename
            shutil.copy2(source, destination)
            copied.append(destination)
    return copied


def _replay_decision(bids_folder: Path, entry: dict) -> str | None:
    """Reapply one decision entry's filesystem effect against `bids_folder`, as if it were
    being made fresh right now. Returns None on success, or a short description of what's
    missing on failure -- used by `rebuild_from_raw`'s retry loop, since a failure here often
    just means some *other* entry (this key's own earlier step, or an unrelated `id_correction`
    another key depends on) hasn't been replayed yet and will resolve this one on a later pass.

    Deliberately doesn't call the matching `record_*` function: those recompute names from
    scratch and would each append a fresh decision entry, neither of which is wanted here -- the
    entry is already correct; this only needs to make the filesystem match it. The one
    exception is `id_correction`: its entry stores the *original* relative paths plus the
    original/corrected id strings, not each file's new name, so the same token-replacement rule
    `record_id_correction` uses is reapplied here too -- not a guess, just the one recorded rule.
    """
    entry_type = entry.get("type")
    try:
        if entry_type in _REVERTIBLE_RENAME_TYPES:
            subject_folder = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{entry['subject_id']}"
            if not subject_folder.is_dir():
                return f"sub-{entry['subject_id']} not found"
            original_file = next(subject_folder.rglob(entry["original_filename"]), None)
            if original_file is None:
                return f"{entry['original_filename']} not found"
            destination = original_file.with_name(entry["corrected_filename"])
            if _is_real_collision(destination, original_file):
                return f"{destination.name} already exists -- resolve manually"
            original_file.rename(destination)
            corrected_parent_folder = entry.get("corrected_parent_folder")
            if corrected_parent_folder and destination.parent.name != corrected_parent_folder:
                new_parent = destination.parent.with_name(corrected_parent_folder)
                if not _is_real_collision(new_parent, destination.parent):
                    destination.parent.rename(new_parent)
                    destination = new_parent / destination.name
            _sync_scans_tsv_filename(bids_folder, original_file, destination)
            return None
        if entry_type == "selected_run":
            subject_folder = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{entry['subject_id']}"
            if not subject_folder.is_dir():
                return f"sub-{entry['subject_id']} not found"
            for filename in entry["non_selected_files"]:
                candidate = next(subject_folder.rglob(filename), None)
                if candidate is not None:
                    _remove_scans_tsv_row(bids_folder, candidate)
                    candidate.unlink()
            return None
        if entry_type == "id_correction":
            original_folder = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{entry['original_id']}"
            if not original_folder.is_dir():
                return f"sub-{entry['original_id']} not found"
            original_token = f"{SUBJECT_FOLDER_PREFIX}{entry['original_id']}"
            corrected_token = f"{SUBJECT_FOLDER_PREFIX}{entry['corrected_id']}"
            corrected_folder = bids_folder / corrected_token
            if _is_real_collision(corrected_folder, original_folder):
                return f"{corrected_token} already exists -- resolve manually"
            for relative_name in entry["renamed_files"]:
                file = bids_folder / relative_name
                if file.exists():
                    file.rename(file.with_name(file.name.replace(original_token, corrected_token)))
            original_folder.rename(corrected_folder)
            return None
        if entry_type == "scans_tsv_date_correction":
            scans_tsv = bids_folder / entry["scans_tsv"]
            if not scans_tsv.is_file():
                return f"{entry['scans_tsv']} not found"
            rows = _read_scans_tsv_rows(scans_tsv)
            matching_rows = [row for row in rows if row.get("filename") == entry["filename"]]
            if not matching_rows:
                return f"{entry['filename']!r} row not found in {entry['scans_tsv']}"
            for row in matching_rows:
                row["acq_time"] = entry["corrected_date"]
            _write_scans_tsv_rows(scans_tsv, rows)
            return None
        # "crosschecked" is a marker with no filesystem effect -- nothing to replay.
        return None
    except OSError as error:
        return str(error)


def rebuild_from_raw(
    bids_folder: Path,
    decisions: dict[str, list[dict]],
    excluded: dict[str, str | None],
) -> tuple[list[str], list[str]]:
    """Reapply every recorded decision's filesystem effect onto `bids_folder`, assuming it has
    just been freshly (re-)populated straight from raw -- e.g. via the same `raw_converter`
    hook "Refresh BIDS" already uses, pointed at an empty destination. Meant for disaster
    recovery: if the BIDS folder itself is lost or corrupted but the raw folder and a backed-up
    `crosscheck.json`/`excluded_subjects.json` (see `backup_decisions`) survive, this rebuilds
    an equivalent BIDS folder without a human re-clicking every pick/tag/correction by hand.

    `decisions`/`excluded` are passed in explicitly (typically loaded from a backup copy via
    `load_decisions`/`load_excluded_subjects` pointed at the backup folder) rather than read
    from `bids_folder` itself, since the whole point is `bids_folder` may not have its own
    copies anymore. Only fit for a freshly-imported, otherwise-untouched `bids_folder` -- not a
    tool for merging recorded decisions into a folder that already has its own, different state.

    Every entry across every key is retried, pass after pass, until a pass makes no further
    progress -- not a single ordered walk. Two things can make one entry temporarily unable to
    resolve on an earlier pass: it's not the oldest step in its own key's chain yet (e.g. a
    `task_tag` recorded after a `date_correction` needs that correction applied first so its
    `original_filename` exists to find), or it depends on an `id_correction` recorded under a
    *different* key finishing first (e.g. a later decision for the same subject was recorded
    under their corrected id). Both resolve themselves naturally once the entry they were
    waiting on succeeds in an earlier pass. Whatever still can't resolve once no pass makes
    progress is reported unresolved rather than guessed at, matching this tool's existing
    "never guess, surface it to a human" philosophy.

    Returns (resolved_keys, unresolved_descriptions).
    """
    for subject_id in excluded:
        folder = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{subject_id}"
        if folder.is_dir():
            shutil.rmtree(folder)

    # A decision recorded for a subject before they were excluded (e.g. a filename fix, made
    # before "Remove Subject Folder from BIDS" cleared them out) is never removed from
    # `decisions` -- record_subject_excluded only ever adds to excluded_subjects.json, it
    # doesn't touch decisions. Left in, every one of those entries would permanently fail to
    # resolve below (their subject's folder is deleted above, on purpose) and clutter the
    # unresolved report forever. Skipped by `subject_id` only, not `id_correction`'s
    # `original_id`/`corrected_id` -- that type renames a folder into existence, and the
    # exclusion sweep above only runs once, before any renames happen, so an id_correction
    # entry can still be the one thing standing between a stale original-id folder and the
    # excluded id it should end up under; skipping it here could leave that stale folder
    # behind instead of cleaning it up.
    pending = [
        (key, entry)
        for key, entries in decisions.items()
        for entry in entries
        if entry.get("type") == "id_correction" or entry.get("subject_id") not in excluded
    ]
    resolved: list[str] = []
    unresolved: list[str] = []

    while pending:
        progressed = False
        still_pending: list[tuple[str, dict]] = []
        pass_errors: list[str] = []
        for key, entry in pending:
            error = _replay_decision(bids_folder, entry)
            if error is None:
                resolved.append(key)
                progressed = True
            else:
                still_pending.append((key, entry))
                pass_errors.append(f"{key}: {error}")
        pending = still_pending
        unresolved = pass_errors
        if not progressed:
            break

    _write_decisions_atomic(bids_folder, decisions)
    save_excluded_subjects(bids_folder, excluded)
    return resolved, unresolved
