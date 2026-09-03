"""Standalone PySide6 tool: human-in-the-loop crosscheck for the crane BIDS folder.

See docs/bids_crosscheck_plan.md and docs/bids_converter_plan.md. Glob patterns match
`cli/crane_convert_to_bids.py`'s real output by *suffix* (`*.mat`/`*_events.tsv`/
`*_beh.tsv`), not by extension alone -- behaviour and debrief are both `.tsv` now, so a
bare `*.tsv` would also match the session's own `scans.tsv` sidecar as well as conflate
the two scan types with each other. Unlike FOH, crane has no tagging step (see
`CraneCandidateExtras`'s comment on `task_tag_available`) -- the converter already
writes real BIDS suffixes (`_physio`/`_events`/`_beh`) itself, so there's no raw
collection-software junk left for a tag-rename to clean up.

`CraneCandidateExtras` below is the crane analog of `FohCandidateExtras`
(`foh_bids_crosscheck_gui.py`). Its content parsing is best-effort against the *raw* data
formats crane actually produces today (Biopac `.mat` physiology, per-subject behaviour
`.csv`, one shared REDCAP `.csv` group debrief export -- see `processing/biopac.py`,
`processing/crane_behaviour.py`, `processing/crane_debrief_behaviour.py`), not against the
post-conversion BIDS format -- so a parser here can still read a converted file's content
fine, but its column/shape checks describe what the raw pipeline expects, not any
BIDS-specific schema. Every parser below fails soft (logs a warning, reports "couldn't
read") rather than raising, so a format mismatch shows up as an info gap, not a crash.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import scipy.io as sio
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from mooi_toolbox.cli.crane_convert_to_bids import (
    DEBRIEF_ID_CORRECTIONS_FILENAME,
    RAW_FILENAME_ID_CORRECTIONS_FILENAME,
    CraneConversionSummary,
    convert_crane_to_bids,
    debrief_correction_key,
    discover_raw_files_for_review,
    discover_raw_subject_ids,
    existing_subject_ids,
    explain_unparseable_filename,
    guess_corrected_subject_id,
    load_debrief_export,
    load_debrief_id_corrections,
    load_raw_filename_id_corrections,
    resolve_crane_filename,
    save_debrief_id_corrections,
    save_raw_filename_id_corrections,
    strip_duplicate_marker,
)
from mooi_toolbox.gui.bids_crosscheck_common import (
    DEFAULT_CONVERT_BUTTON_TOOLTIP,
    EXTRA_RAW_ACTION_GROUP_OVERRIDE,
    EXTRA_RAW_ACTION_GROUP_RAW,
    CandidateExtras,
    run_bids_crosscheck_app,
)
from mooi_toolbox.processing.bids_crosscheck import DatasetConfig, ScanTypeConfig
from mooi_toolbox.processing.biodata import ACCEPTED_LABEL_PATTERN, CANONICAL_LABEL_SPELLING
from mooi_toolbox.processing.biopac import clean_biopac_labels
from mooi_toolbox.processing.crane_behaviour import build_crane_raw_behav_file_schema
from mooi_toolbox.processing.crane_debrief_behaviour import crane_raw_debrief_file_schema

logger = logging.getLogger(__name__)

CRANE_DATASET_CONFIG = DatasetConfig(
    dataset_name="crane",
    scan_types=(
        ScanTypeConfig(name="physiology", glob_patterns=("*.mat",)),
        # Not a bare "*.tsv" -- that would also match the session's own
        # sub-XXX_ses-01_scans.tsv sidecar (see crane_convert_to_bids.py), and would conflate
        # behaviour with debrief now that both scan types are written tab-delimited.
        ScanTypeConfig(name="behaviour", glob_patterns=("*_events.tsv",)),
        ScanTypeConfig(name="debrief", glob_patterns=("*_beh.tsv",)),
    ),
    # No task_tag_task/task_tag_folder_name -- unlike FOH, crane has no tagging step at all
    # (see CraneCandidateExtras' comment on task_tag_available).
    # Crane's converter records each file's date as a scans.tsv row instead of a filename
    # prefix (see docs/bids_converter_plan.md) -- routes the crosscheck GUI's "Correct
    # date..." button to edit that row instead of renaming the file.
    dates_in_scans_tsv=True,
)

PHYSIOLOGY_SCAN_TYPE = "physiology"
BEHAVIOUR_SCAN_TYPE = "behaviour"
DEBRIEF_SCAN_TYPE = "debrief"

# The crane pipeline only ever processes EDA out of a Biopac recording (see
# processing/crane_pipeline.py's SequentialPhysiologyProcessingSteps, which only lists
# ProcessEdaPhysiologyDataStrategyStep) -- unlike FOH, which needs both EDA and ECG.
EXPECTED_PHYSIO_CHANNELS = ("EDA",)
# The column sets the raw behaviour/debrief data is validated against once it reaches the
# pipeline (processing/crane_behaviour.py, processing/crane_debrief_behaviour.py) -- reused
# here as an advisory "does this look complete" check, not full pandera validation, since a
# stricter check (value ranges, balanced conditions, ...) belongs to the pipeline, not a
# glance-level crosscheck. The debrief schema describes the shared REDCAP group export's
# columns (record_id plus wide crane_<emotion>_rb/_gb columns); a per-subject BIDS debrief
# file keeps the same columns since `crane_convert_to_bids.load_debrief_export` filters
# against this same schema before writing it.
BEHAVIOUR_EXPECTED_COLUMNS = tuple(build_crane_raw_behav_file_schema().columns.keys())
DEBRIEF_EXPECTED_COLUMNS = tuple(crane_raw_debrief_file_schema.columns.keys())

CHECK = "✓"
CROSS = "✗"
WARNING = "❗"
CHECK_COLOR = "#2ecc71"
CROSS_COLOR = "#e74c3c"
WARNING_COLOR = "#f39c12"
INFO_CACHE_FILENAME = "crosscheck_info_cache.json"
# Bumped whenever a parser's output shape or derivation changes, so a cached entry that still
# matches the file's mtime/size (nothing to re-read) but was computed by older logic gets
# reparsed anyway instead of silently serving stale info forever.
INFO_SCHEMA_VERSION = 2


@dataclass
class CranePhysiologyInfo:
    channels: dict[str, bool]
    duration_minutes: float | None
    all_labels: list[str] | None


@dataclass
class CraneBehaviourInfo:
    n_rows: int | None
    columns: list[str] | None
    missing_columns: list[str]


@dataclass
class CraneDebriefInfo:
    n_rows: int | None
    columns: list[str] | None
    missing_columns: list[str]


def _present_physio_channels(labels: list[str]) -> dict[str, bool]:
    """Which of EXPECTED_PHYSIO_CHANNELS appear in `labels`, matched the same way
    `biodata.normalize_data_labels` matches them for the actual pipeline (case-insensitive,
    optional trailing digit) -- so this reports exactly what the pipeline would accept.
    """
    canonical_found = set()
    for label in labels:
        match = ACCEPTED_LABEL_PATTERN.match(label)
        if match is not None:
            canonical_found.add(CANONICAL_LABEL_SPELLING[match.group("base").lower()])
    return {channel: channel in canonical_found for channel in EXPECTED_PHYSIO_CHANNELS}


def _parse_physiology_info(file: Path) -> CranePhysiologyInfo:
    try:
        imported_data = sio.loadmat(str(file))
        labels = clean_biopac_labels(imported_data["labels"])
        isi_seconds = float(imported_data["isi"].squeeze()) / 1000
        n_samples = imported_data["data"].shape[0]
    except Exception:
        logger.warning("Could not read physiology data from %s", file, exc_info=True)
        return CranePhysiologyInfo(
            channels=dict.fromkeys(EXPECTED_PHYSIO_CHANNELS, False),
            duration_minutes=None,
            all_labels=None,
        )

    return CranePhysiologyInfo(
        channels=_present_physio_channels(labels),
        duration_minutes=(n_samples * isi_seconds) / 60,
        all_labels=labels,
    )


def _parse_behaviour_info(file: Path) -> CraneBehaviourInfo:
    try:
        df = pd.read_csv(file, sep="\t")
    except Exception:
        logger.warning("Could not read behaviour data from %s", file, exc_info=True)
        return CraneBehaviourInfo(
            n_rows=None, columns=None, missing_columns=list(BEHAVIOUR_EXPECTED_COLUMNS)
        )

    columns = list(df.columns)
    missing = [column for column in BEHAVIOUR_EXPECTED_COLUMNS if column not in columns]
    return CraneBehaviourInfo(n_rows=len(df), columns=columns, missing_columns=missing)


def _parse_debrief_info(file: Path) -> CraneDebriefInfo:
    try:
        df = pd.read_csv(file, sep="\t")
    except Exception:
        logger.warning("Could not read debrief data from %s", file, exc_info=True)
        return CraneDebriefInfo(
            n_rows=None, columns=None, missing_columns=list(DEBRIEF_EXPECTED_COLUMNS)
        )

    columns = list(df.columns)
    missing = [column for column in DEBRIEF_EXPECTED_COLUMNS if column not in columns]
    return CraneDebriefInfo(n_rows=len(df), columns=columns, missing_columns=missing)


def _info_cache_path(bids_folder: Path) -> Path:
    return bids_folder / INFO_CACHE_FILENAME


def _load_info_cache(bids_folder: Path) -> dict[str, dict]:
    path = _info_cache_path(bids_folder)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read info cache at %s -- starting fresh", path)
        return {}


def _save_info_cache(bids_folder: Path, cache: dict[str, dict]) -> None:
    path = _info_cache_path(bids_folder)
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as tmp_file:
        json.dump(cache, tmp_file, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


class CraneCandidateExtras(CandidateExtras):
    """Advisory crane physiology/behaviour/debrief info; never gates renaming.

    Every parse result is cached on disk (see INFO_CACHE_FILENAME), keyed by the file's
    path relative to the BIDS folder plus its mtime/size, so a fresh launch or re-Browse
    doesn't have to re-parse every "ok" candidate again -- only files that are new or have
    actually changed. Mirrors FohCandidateExtras's cache, generalized across crane's three
    scan types instead of FOH's one.
    """

    def __init__(self) -> None:
        self._bids_folder: Path | None = None
        self._disk_cache: dict[str, dict] = {}
        self._dirty = False

    def on_bids_folder_changed(self, bids_folder: Path) -> None:
        self._bids_folder = bids_folder
        self._disk_cache = _load_info_cache(bids_folder)
        self._dirty = False

    def bidsignore_patterns(self) -> tuple[str, ...]:
        return (INFO_CACHE_FILENAME,)

    def flush(self) -> None:
        if self._dirty and self._bids_folder is not None:
            _save_info_cache(self._bids_folder, self._disk_cache)
        self._dirty = False

    def describe(self, scan_type: str, file: Path) -> str | None:
        """Compact per-candidate info shown inline in the subject list.

        The visible tick is labelled by scan type ("Physiology"/"Behaviour"/"Debrief"), not
        by what it's actually checking underneath (expected channels for physiology,
        expected columns for behaviour/debrief) -- that detail still drives whether it's
        green or red, it's just not spelled out in the compact label. See
        `describe_tooltip`/`detail` for the underlying channel/column breakdown.
        """
        if scan_type == PHYSIOLOGY_SCAN_TYPE:
            info = self._physiology_info(file)
            complete = info.all_labels is not None and all(info.channels.values())
            channels_text = (
                f'<span style="color:{CHECK_COLOR if complete else CROSS_COLOR}">'
                f"Physiology {CHECK if complete else CROSS}</span>"
            )
            parts = []
            if info.duration_minutes is not None:
                parts.append(f"<b>{round(info.duration_minutes)} min</b>")
            parts.append(channels_text)
            return " &nbsp;&nbsp; ".join(parts)

        if scan_type in (BEHAVIOUR_SCAN_TYPE, DEBRIEF_SCAN_TYPE):
            info = self._behaviour_or_debrief_info(scan_type, file)
            complete = info.columns is not None and not info.missing_columns
            label = "Behaviour" if scan_type == BEHAVIOUR_SCAN_TYPE else "Debrief"
            if complete:
                icon, color = CHECK, CHECK_COLOR
            elif scan_type == DEBRIEF_SCAN_TYPE and info.columns is not None:
                # The file exists and is readable but is missing expected columns -- a
                # narrower problem than a completely absent debrief file (which
                # bids_crosscheck_common.py's "missing" status shows as a plain X for
                # instead), so a distinct warning glyph here keeps the two failure modes
                # visually distinguishable at a glance.
                icon, color = WARNING, WARNING_COLOR
            else:
                icon, color = CROSS, CROSS_COLOR
            columns_text = f'<span style="color:{color}">{label} {icon}</span>'
            parts = []
            if info.n_rows is not None:
                row_word = "trials" if scan_type == BEHAVIOUR_SCAN_TYPE else "row(s)"
                parts.append(f"<b>{info.n_rows} {row_word}</b>")
            parts.append(columns_text)
            return " &nbsp;&nbsp; ".join(parts)

        return None

    def describe_tooltip(self, scan_type: str, file: Path) -> str | None:
        if scan_type == PHYSIOLOGY_SCAN_TYPE:
            info = self._physiology_info(file)
            lines = ["Channels the crane pipeline needs:"]
            lines.extend(
                f"{CHECK if present else CROSS} {label}" for label, present in info.channels.items()
            )
            return "\n".join(lines)

        if scan_type in (BEHAVIOUR_SCAN_TYPE, DEBRIEF_SCAN_TYPE):
            info = self._behaviour_or_debrief_info(scan_type, file)
            if info.columns is None:
                return "Could not read this file"
            if not info.missing_columns:
                return "All expected columns present"
            return "Missing columns:\n" + "\n".join(f"{CROSS} {column}" for column in info.missing_columns)

        return None

    def detail(self, scan_type: str, file: Path) -> str | None:
        if scan_type == PHYSIOLOGY_SCAN_TYPE:
            info = self._physiology_info(file)
            channels_text = " ".join(
                f'{label}<span style="color:{CHECK_COLOR if present else CROSS_COLOR}">'
                f"{CHECK if present else CROSS}</span>"
                for label, present in info.channels.items()
            )
            channels_line = f"<b>Channels</b> &nbsp; {channels_text}"
            if info.all_labels is None:
                return f"{channels_line}<br>Could not read this physiology file"
            labels_text = ", ".join(info.all_labels)
            duration_text = (
                f"{info.duration_minutes:.1f} min"
                if info.duration_minutes is not None
                else "duration unavailable"
            )
            return f"{channels_line}<br><b>Labels</b> &nbsp; {labels_text} &nbsp;&nbsp; {duration_text}"

        if scan_type in (BEHAVIOUR_SCAN_TYPE, DEBRIEF_SCAN_TYPE):
            info = self._behaviour_or_debrief_info(scan_type, file)
            if info.columns is None:
                return "Could not read this file"
            row_word = "trials" if scan_type == BEHAVIOUR_SCAN_TYPE else "row(s)"
            rows_text = f"{info.n_rows} {row_word}" if info.n_rows is not None else "row count unavailable"
            if not info.missing_columns:
                return f"{rows_text} &nbsp;&nbsp; all expected columns present"
            missing_text = ", ".join(info.missing_columns)
            return (
                f"{rows_text} &nbsp;&nbsp; "
                f'<span style="color:{CROSS_COLOR}">missing columns: {missing_text}</span>'
            )

        return None

    # No task_tag_available override -- falls back to CandidateExtras' own "False"
    # for every scan type. Tagging (FOH's "Tag as foh") exists to replace non-BIDS free text
    # the *raw collection software* tacks on after the run token; crane_convert_to_bids.py
    # already writes real BIDS suffixes (_physio/_events/_beh) itself, so there's no
    # junk left to clean up, and tagging would instead destroy that distinction (it replaces
    # everything after run-<NNN> with a single generic label, same for all three scan types).
    # See docs/bids_converter_plan.md.
    #
    # No filename_correction_available override either (falls back to CandidateExtras' own
    # "False") -- the one thing crane's converter can leave behind that needs a post-hoc fix,
    # a "-dupN" collision marker (see _resolve_destination in crane_convert_to_bids.py) on
    # whichever duplicate turns out to be the real recording, is handled automatically by
    # duplicate_marker_free_name below instead of a free-text escape hatch: by the time a
    # human resolves a duplicate here, every other part of the name (subject/task/acq/run)
    # is already correct, so there's nothing left a manual retype should ever need to fix.

    def duplicate_marker_free_name(self, scan_type: str, file: Path) -> str | None:
        return strip_duplicate_marker(file.name)

    def refreshable(self, scan_type: str) -> bool:
        return scan_type in (PHYSIOLOGY_SCAN_TYPE, BEHAVIOUR_SCAN_TYPE, DEBRIEF_SCAN_TYPE)

    def refresh(self, scan_type: str, file: Path) -> None:
        """Force a reparse for one candidate. Caller batches the disk write via `flush()`."""
        if scan_type == PHYSIOLOGY_SCAN_TYPE:
            self._physiology_info(file, force=True)
        elif scan_type in (BEHAVIOUR_SCAN_TYPE, DEBRIEF_SCAN_TYPE):
            self._behaviour_or_debrief_info(scan_type, file, force=True)

    def has_warning(self, scan_type: str, file: Path) -> bool:
        if scan_type == PHYSIOLOGY_SCAN_TYPE:
            info = self._physiology_info(file)
            return info.all_labels is not None and not all(info.channels.values())

        if scan_type in (BEHAVIOUR_SCAN_TYPE, DEBRIEF_SCAN_TYPE):
            info = self._behaviour_or_debrief_info(scan_type, file)
            return info.columns is not None and bool(info.missing_columns)

        return False

    def _cache_key(self, file: Path) -> str:
        if self._bids_folder is None:
            return file.name
        try:
            return file.relative_to(self._bids_folder).as_posix()
        except ValueError:
            return file.name

    def _cached(self, kind: str, file: Path, parser, info_cls, force: bool = False):
        key = self._cache_key(file)
        stat = file.stat()
        cached = self._disk_cache.get(key)
        if not force and cached is not None:
            if (
                cached.get("mtime") == stat.st_mtime
                and cached.get("size") == stat.st_size
                and cached.get("info_version") == INFO_SCHEMA_VERSION
                and cached.get("kind") == kind
            ):
                try:
                    return info_cls(**cached["info"])
                except (TypeError, KeyError):
                    logger.warning("Stale info-cache entry for %s -- reparsing", file)

        info = parser(file)
        self._disk_cache[key] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "info_version": INFO_SCHEMA_VERSION,
            "kind": kind,
            "info": asdict(info),
        }
        self._dirty = True
        return info

    def _physiology_info(self, file: Path, force: bool = False) -> CranePhysiologyInfo:
        return self._cached(
            PHYSIOLOGY_SCAN_TYPE, file, _parse_physiology_info, CranePhysiologyInfo, force
        )

    def _behaviour_or_debrief_info(self, scan_type: str, file: Path, force: bool = False):
        if scan_type == BEHAVIOUR_SCAN_TYPE:
            return self._cached(scan_type, file, _parse_behaviour_info, CraneBehaviourInfo, force)
        return self._cached(scan_type, file, _parse_debrief_info, CraneDebriefInfo, force)


class _ListLogHandler(logging.Handler):
    """Captures formatted log records into a list instead of printing them -- used to relay
    `convert_crane_to_bids`'s `logger.info`/`logger.warning` calls into the crosscheck GUI's
    status dialog, since that function reports progress/problems via the standard logger
    rather than a GUI-specific callback (see its own docstring)."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"[{record.levelname}] {self.format(record)}")


def _format_conversion_summary(summary: CraneConversionSummary) -> str:
    if not summary.new_subject_ids and not summary.backfilled_debrief_ids:
        return "No new subjects found -- everything in the raw folder is already converted."

    lines = []
    if summary.new_subject_ids:
        lines += [f"Added {len(summary.new_subject_ids)} new subject(s):", ""]
        for subject_id in summary.new_subject_ids:
            physiology = ", ".join(p.name for p in summary.subject_physiology.get(subject_id, []))
            behaviour = ", ".join(p.name for p in summary.subject_behaviour.get(subject_id, []))
            debrief = summary.subject_debrief.get(subject_id)
            lines.append(f"sub-{subject_id}")
            lines.append(f"    physiology: {physiology or '(missing)'}")
            lines.append(f"    behaviour:  {behaviour or '(missing)'}")
            lines.append(f"    debrief:    {debrief.name if debrief else '(missing)'}")

    if summary.backfilled_debrief_ids:
        if lines:
            lines.append("")
        lines.append(
            f"Backfilled debrief for {len(summary.backfilled_debrief_ids)} already-converted "
            "subject(s) that didn't have one yet:"
        )
        lines.append("")
        for subject_id in summary.backfilled_debrief_ids:
            debrief = summary.subject_debrief.get(subject_id)
            lines.append(f"sub-{subject_id}")
            lines.append(f"    debrief: {debrief.name if debrief else '(missing)'}")

    return "\n".join(lines)


class DebriefRecordIdCorrectionDialog(QDialog):
    """Lets a human declare "this messy debrief record_id really means this subject",
    without ever touching the raw REDCAP export -- corrections are saved to their own JSON
    (`crane_convert_to_bids.save_debrief_id_corrections`, in the BIDS folder) and applied the
    next time "Refresh BIDS" runs (`crane_convert_to_bids.apply_debrief_id_corrections`). A
    plain editable table with freeform text, not a dropdown-matched picker -- same correction
    style as `bids_crosscheck_common.py`'s existing "Correct date..."/"Rename subject ID..."
    `QInputDialog.getText` dialogs, just extended to handle more than one row at a time.

    Listed *per row*, not per unique record_id value: two different rows can legitimately
    share the exact same literal record_id (e.g. two subjects who both typed "0001" into
    REDCap -- the debrief-side counterpart of a raw filename's "(N)" duplicate-copy marker,
    see `RawFilenameCorrectionDialog`). A value-keyed correction can't tell those apart, so
    each row gets its own key (`debrief_correction_key`).

    Every row from the export is listed, in export order, not just the mismatched/ambiguous
    ones -- same "show everything, mark what's wrong" shape as `RawFilenameCorrectionDialog`,
    so fixing one row shows up as its own tick turning green rather than the row quietly
    disappearing from view (which reads as "did that even work?"). A duplicated record_id is
    still never auto-guessed, since guessing the same subject for two different rows would
    just recreate the ambiguity it's meant to resolve.
    """

    def __init__(self, raw_folder: Path, bids_folder: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.bids_folder = bids_folder
        self.setWindowTitle("Fix debrief record IDs")
        self.resize(760, 560)

        layout = QVBoxLayout(self)
        self._rows: list[tuple[str, str]] = []  # (record_id, correction_key) per listed row
        self._known_subject_ids: set[str] = set()

        existing_corrections = load_debrief_id_corrections(bids_folder)
        debrief_df = load_debrief_export(raw_folder)
        if debrief_df is None:
            layout.addWidget(QLabel("No debrief export found in the raw folder."))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            return

        self._known_subject_ids = discover_raw_subject_ids(raw_folder) | existing_subject_ids(
            bids_folder
        )
        record_id_column = debrief_df["record_id"].astype(str)
        value_counts = record_id_column.value_counts()

        occurrence_counters: dict[str, int] = {}
        self._duplicate_counts: dict[str, int] = {}
        occurrence_by_key: dict[str, int] = {}
        for record_id in record_id_column:
            occurrence_index = occurrence_counters.get(record_id, 0)
            occurrence_counters[record_id] = occurrence_index + 1
            key = debrief_correction_key(record_id, occurrence_index)
            occurrence_by_key[key] = occurrence_index
            self._rows.append((record_id, key))
            self._duplicate_counts[key] = int(value_counts[record_id])

        info_label = QLabel(
            "Every row from the debrief export, with the subject id it currently "
            f"resolves to. {CHECK} means that id matches a known subject; {CROSS} means "
            "it doesn't -- double-check it, or this subject may genuinely have no "
            "debrief data yet. Non-ambiguous rows are pre-filled with a best-effort "
            "guess (stray whitespace/PID-dash fixes); rows that share their record_id "
            "with another row (ambiguous -- could be two different subjects who both "
            "entered the same id) are left blank for you to assign individually. Type a "
            "corrected subject id for any row that's wrong, or clear a box to leave it "
            "unmatched. This never changes the raw export; corrections are saved "
            'separately and applied the next time you click "Refresh BIDS".'
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.table = QTableWidget(len(self._rows), 3)
        self.table.setHorizontalHeaderLabels(
            ["record_id (from export)", "Matched", "Corrected subject id"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeaderItem(1).setToolTip(
            f"{CHECK} matches a known subject id\n"
            f"{CROSS} doesn't match any known subject id -- double-check it, or this subject "
            "may genuinely have no debrief data yet"
        )
        self.table.verticalHeader().setVisible(False)
        for row, (record_id, key) in enumerate(self._rows):
            duplicate_count = self._duplicate_counts[key]
            label = (
                f"{record_id}  ({occurrence_by_key[key] + 1} of {duplicate_count})"
                if duplicate_count > 1
                else record_id
            )
            record_item = QTableWidgetItem(label)
            record_item.setFlags(record_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if duplicate_count > 1:
                record_item.setToolTip(
                    "Ambiguous: another row in the export shares this exact record_id -- "
                    "assign each occurrence to its own subject below."
                )
            self.table.setItem(row, 0, record_item)
            match_item = QTableWidgetItem("")
            match_item.setFlags(match_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, match_item)
            if key in existing_corrections:
                guess = existing_corrections[key]
            elif duplicate_count > 1:
                # Ambiguous -- guessing the same subject for more than one occurrence would
                # just recreate the collision this dialog exists to resolve.
                guess = ""
            else:
                guess = guess_corrected_subject_id(record_id)
            self.table.setItem(row, 2, QTableWidgetItem(guess))
            self._update_match_icon(row)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_match_icon(self, row: int) -> None:
        item = self.table.item(row, 2)
        text = item.text().strip() if item is not None else ""
        if not text:
            icon, tooltip = "", ""
        elif text in self._known_subject_ids:
            icon, tooltip = CHECK, "Matches a known subject id"
        else:
            icon, tooltip = (
                CROSS,
                "Doesn't match any known subject id -- double-check it, or this subject may "
                "genuinely have no debrief data yet",
            )
        match_item = self.table.item(row, 1)
        if match_item is not None:
            match_item.setText(icon)
            match_item.setToolTip(tooltip)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 2:
            self._update_match_icon(item.row())

    def _on_save(self) -> None:
        corrections = load_debrief_id_corrections(self.bids_folder)
        for row, (_record_id, key) in enumerate(self._rows):
            item = self.table.item(row, 2)
            corrected_id = item.text().strip() if item is not None else ""
            if corrected_id:
                corrections[key] = corrected_id
            else:
                corrections.pop(key, None)
        save_debrief_id_corrections(self.bids_folder, corrections)
        self.accept()


def _on_fix_debrief_record_ids(raw_folder: Path, bids_folder: Path, parent: QWidget) -> None:
    """The crane-specific `extra_raw_actions` callback for the "Fix debrief record IDs..."
    button -- see `DebriefRecordIdCorrectionDialog`.
    """
    DebriefRecordIdCorrectionDialog(raw_folder, bids_folder, parent).exec()


class RawFilenameCorrectionDialog(QDialog):
    """Lets a human declare "this raw filename really belongs to this subject" for *any* raw
    physiology/behaviour file, not just ones `parse_crane_filename` couldn't extract a
    subject id from at all -- a filename can just as easily resolve to a *wrong* id without
    ever failing to parse (e.g. a "(N)" duplicate-copy marker that could mean either a
    harmless double-copy of the same recording or two different subjects sharing a base id;
    see `parse_crane_filename`'s own docstring). Corrections are saved to their own JSON
    (`crane_convert_to_bids.save_raw_filename_id_corrections`, in the BIDS folder) and
    applied the next time "Refresh BIDS" runs (`crane_convert_to_bids.resolve_crane_filename`).
    Same shape as `DebriefRecordIdCorrectionDialog`: self-contained (works without a prior
    conversion run), plain editable table -- deliberately *not* pre-filled with a guess the
    way the debrief dialog's "Corrected subject id" column is, so nothing here is auto-
    corrected without a human explicitly typing it (see the "Currently resolves to" column
    below).

    The bottom pane explains why the selected filename failed to parse, or what it currently
    resolves to if it didn't (`explain_unparseable_filename`, grounded in the same regex that
    decides both), and shows any matching line from the last "Refresh BIDS" run's captured log
    output (`parent.last_conversion_log_lines`) -- both reuse existing machinery rather than
    building a new diagnostic path.
    """

    def __init__(self, raw_folder: Path, bids_folder: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.raw_folder = raw_folder
        self.bids_folder = bids_folder
        self._log_lines: list[str] = getattr(parent, "last_conversion_log_lines", [])
        self.setWindowTitle("Fix raw filenames")
        self.resize(760, 560)

        layout = QVBoxLayout(self)
        self._existing_corrections = load_raw_filename_id_corrections(bids_folder)
        self._files = discover_raw_files_for_review(raw_folder)

        if not self._files:
            layout.addWidget(QLabel("No physiology/behaviour raw files found in the raw folder."))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            return

        info_label = QLabel(
            "Every raw physiology/behaviour file, with the subject id it currently resolves "
            "to. Type a corrected subject id for any row that's wrong -- whether the filename "
            'didn\'t parse at all, or parsed fine but to the wrong id (e.g. two subjects '
            'sharing a "(N)" marker). Leave blank to make no change. This never renames the '
            'raw file; corrections are saved separately and applied the next time you click '
            '"Refresh BIDS".'
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.table = QTableWidget(len(self._files), 3)
        self.table.setHorizontalHeaderLabels(
            ["Filename", "Currently resolves to", "Corrected subject id"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 180)
        self.table.verticalHeader().setVisible(False)
        for row, file in enumerate(self._files):
            key = self._key(file)
            name_item = QTableWidgetItem(key)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, name_item)

            resolved = resolve_crane_filename(file, raw_folder, self._existing_corrections)
            resolved_item = QTableWidgetItem(resolved.subject_id if resolved else "(unparseable)")
            resolved_item.setFlags(resolved_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if resolved is None:
                resolved_item.setForeground(QBrush(QColor(CROSS_COLOR)))
            self.table.setItem(row, 1, resolved_item)

            self.table.setItem(row, 2, QTableWidgetItem(self._existing_corrections.get(key, "")))
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, 1)

        # Persistent bottom pane -- always visible below the table, updated for whichever
        # row is currently selected, same spirit as bids_crosscheck_common.py's "Last
        # conversion" status panel (fixed-height QTextEdit, not a popup).
        reason_group = QGroupBox("Details")
        reason_layout = QVBoxLayout(reason_group)
        self.reason_text = QTextEdit()
        self.reason_text.setReadOnly(True)
        self.reason_text.setFont(QFont("Courier New"))
        self.reason_text.setMaximumHeight(140)
        self.reason_text.setPlainText("Select a row above to see details.")
        reason_layout.addWidget(self.reason_text)
        layout.addWidget(reason_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _key(self, file: Path) -> str:
        try:
            return file.relative_to(self.raw_folder).as_posix()
        except ValueError:
            return file.name

    def _on_selection_changed(self) -> None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        if not rows:
            self.reason_text.setPlainText("Select a row above to see details.")
            return
        file = self._files[min(rows)]
        resolved = resolve_crane_filename(file, self.raw_folder, self._existing_corrections)
        if resolved is None:
            detail = explain_unparseable_filename(file)
        else:
            detail = f"Currently resolves to subject id {resolved.subject_id!r} from the filename."
        relevant_lines = [line for line in self._log_lines if file.name in line]
        if relevant_lines:
            log_text = "\n".join(relevant_lines)
        else:
            log_text = (
                '(no matching line from the last "Refresh BIDS" run in this session -- run '
                "it again to see one)"
            )
        self.reason_text.setPlainText(f"{detail}\n\nFrom the last conversion run:\n{log_text}")

    def _on_save(self) -> None:
        corrections = load_raw_filename_id_corrections(self.bids_folder)
        for row, file in enumerate(self._files):
            key = self._key(file)
            item = self.table.item(row, 2)
            corrected_id = item.text().strip() if item is not None else ""
            if corrected_id:
                corrections[key] = corrected_id
            else:
                corrections.pop(key, None)
        save_raw_filename_id_corrections(self.bids_folder, corrections)
        self.accept()


def _on_fix_raw_filenames(raw_folder: Path, bids_folder: Path, parent: QWidget) -> None:
    """The crane-specific `extra_raw_actions` callback for the "Fix raw filenames..." button
    -- see `RawFilenameCorrectionDialog`.
    """
    RawFilenameCorrectionDialog(raw_folder, bids_folder, parent).exec()


def _run_crane_conversion(
    raw_folder: Path, bids_folder: Path, debrief_export: Path | None
) -> list[str]:
    """The crane-specific `raw_converter` callback `BidsCrosscheckWindow` calls when the
    "Refresh BIDS" button is clicked. Captures `convert_crane_to_bids`'s own log output
    (info/warning messages about skipped subjects, unmatched debrief rows, ...) alongside
    the final summary, so both show up together in the status panel. `debrief_export` comes
    straight from the window's optional override-file picker -- None unless the user has
    explicitly picked one, in which case it overrides this function's own auto-detection of
    the shared REDCAP group export.
    """
    handler = _ListLogHandler()
    converter_logger = logging.getLogger("mooi_toolbox.cli.crane_convert_to_bids")
    converter_logger.addHandler(handler)
    try:
        summary = convert_crane_to_bids(raw_folder, bids_folder, debrief_export)
    finally:
        converter_logger.removeHandler(handler)

    return [*handler.lines, "", _format_conversion_summary(summary)]


def main() -> None:
    run_bids_crosscheck_app(
        CRANE_DATASET_CONFIG,
        "Crane BIDS Crosscheck",
        CraneCandidateExtras(),
        settings_app_name="CraneBidsCrosscheck",
        raw_converter=_run_crane_conversion,
        override_file_label="Debrief export",
        override_file_filter="CSV files (*.csv)",
        extra_raw_actions=[
            (
                "Fix Record IDs in Debrief Export",
                "Declare corrected subject ids for debrief record_id values that don't match "
                "any known subject. Saved separately -- never edits the raw debrief export.",
                _on_fix_debrief_record_ids,
                EXTRA_RAW_ACTION_GROUP_OVERRIDE,
            ),
            (
                "Fix Filenames in Raw Folder",
                "Review every raw physiology/behaviour filename and, if needed, declare its "
                "correct subject id -- for filenames that don't parse at all, or ones that "
                'parse fine but to the wrong id (e.g. two subjects sharing a "(N)" '
                "duplicate-copy marker). Saved separately -- never renames the raw file.",
                _on_fix_raw_filenames,
                EXTRA_RAW_ACTION_GROUP_RAW,
            ),
        ],
        convert_button_tooltip=(
            f"{DEFAULT_CONVERT_BUTTON_TOOLTIP} Also backfills a missing debrief file for an "
            "already-converted subject, if one wasn't matched on an earlier run."
        ),
        extra_backup_filenames=(
            DEBRIEF_ID_CORRECTIONS_FILENAME,
            RAW_FILENAME_ID_CORRECTIONS_FILENAME,
        ),
    )


if __name__ == "__main__":
    main()
