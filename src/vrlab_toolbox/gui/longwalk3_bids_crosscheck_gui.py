"""Standalone PySide6 tool: human-in-the-loop crosscheck for the longwalkV3 BIDS folder.

See docs/bids_crosscheck_plan.md and docs/bids_converter_plan.md. LongwalkV3 differs from
crane/longwalk (and FOH) in one important way: it has *no* single canonical file per scan
type per subject. A subject can have up to 3 real sessions, each with its own physiology
`.acq` recording, and each session can have several real events.tsv files (one per
city/run) -- see `processing/longwalk3_bids.py`'s module docstring. Both scan types below
are configured with `ScanTypeConfig.allow_multiple=True` (see
`processing/bids_crosscheck.py`) so the shared framework treats several matching files per
subject as normal, not a "duplicate" needing one to be picked and the rest deleted.

`LongwalkV3CandidateExtras` deliberately does *not* parse physiology `.acq` content -- unlike
crane/longwalk's `.mat` channel checks (via scipy), nothing in this repo currently reads raw
Biopac AcqKnowledge `.acq` files, so a physiology candidate here only ever shows file
presence, not channel/duration info. Events (post-conversion `.tsv`) content is read with
plain pandas -- but only a shallow "did this read, how many rows/columns" check, not a
per-column schema validation, since `longwalk3_bids.combine_events_df_files` suffixes almost
every column with its source `bp_id`, which varies per raw file and isn't something this GUI
tries to predict.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
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

from vrlab_toolbox.gui.bids_crosscheck_common import (
    DEFAULT_CONVERT_BUTTON_TOOLTIP,
    EXTRA_RAW_ACTION_GROUP_RAW,
    CandidateExtras,
    run_bids_crosscheck_app,
)
from vrlab_toolbox.processing.bids_crosscheck import DatasetConfig, ScanTypeConfig
from vrlab_toolbox.processing.longwalk3_bids import (
    RAW_FILENAME_ID_CORRECTIONS_FILENAME,
    LongWalkV3ConversionSummary,
    convert_longwalkv3_to_bids,
    discover_raw_files_for_review,
    explain_unparseable_filename,
    load_raw_filename_id_corrections,
    resolve_subject_id,
    save_raw_filename_id_corrections,
)

logger = logging.getLogger(__name__)

PHYSIOLOGY_SCAN_TYPE = "physiology"
EVENTS_SCAN_TYPE = "events"

LONGWALKV3_DATASET_CONFIG = DatasetConfig(
    dataset_name="longwalkv3",
    scan_types=(
        ScanTypeConfig(name=PHYSIOLOGY_SCAN_TYPE, glob_patterns=("*.acq",), allow_multiple=True),
        ScanTypeConfig(name=EVENTS_SCAN_TYPE, glob_patterns=("*_events.tsv",), allow_multiple=True),
    ),
    # No task_tag_task/task_tag_folder_name -- like crane/longwalk, longwalkV3 has no tagging
    # step: `processing/longwalk3_bids.py` already writes real BIDS suffixes (_physio/_events)
    # itself, so there's no raw collection-software junk left to clean up.
    # longwalkV3's converter records each file's date as a scans.tsv row instead of a filename
    # prefix (see docs/bids_converter_plan.md) -- routes the crosscheck GUI's "Correct
    # date..." button to edit that row instead of renaming the file.
    dates_in_scans_tsv=True,
)

CHECK = "✓"
CROSS = "✗"
CHECK_COLOR = "#2ecc71"
CROSS_COLOR = "#e74c3c"
INFO_CACHE_FILENAME = "crosscheck_info_cache.json"
# Bumped whenever a parser's output shape or derivation changes, so a cached entry that still
# matches the file's mtime/size (nothing to re-read) but was computed by older logic gets
# reparsed anyway instead of silently serving stale info forever.
INFO_SCHEMA_VERSION = 1


@dataclass
class LongwalkV3EventsInfo:
    n_rows: int | None
    n_columns: int | None
    has_onset: bool


def _parse_events_info(file: Path) -> LongwalkV3EventsInfo:
    try:
        df = pd.read_csv(file, sep="\t")
    except Exception:
        logger.warning("Could not read events data from %s", file, exc_info=True)
        return LongwalkV3EventsInfo(n_rows=None, n_columns=None, has_onset=False)

    return LongwalkV3EventsInfo(
        n_rows=len(df), n_columns=len(df.columns), has_onset="onset" in df.columns
    )


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


class LongwalkV3CandidateExtras(CandidateExtras):
    """Advisory longwalkV3 events info; never gates renaming. No physiology content parsing
    -- see module docstring.

    Every parse result is cached on disk (see INFO_CACHE_FILENAME), keyed by the file's path
    relative to the BIDS folder plus its mtime/size, same shape as crane's/longwalk's own
    cache (`crane_bids_crosscheck_gui.py`/`longwalk_bids_crosscheck_gui.py`).
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
        if scan_type != EVENTS_SCAN_TYPE:
            return None
        info = self._events_info(file)
        complete = info.n_rows is not None and info.has_onset
        events_text = (
            f'<span style="color:{CHECK_COLOR if complete else CROSS_COLOR}">'
            f"Events {CHECK if complete else CROSS}</span>"
        )
        parts = []
        if info.n_rows is not None:
            parts.append(f"<b>{info.n_rows} row(s)</b>")
        parts.append(events_text)
        return " &nbsp;&nbsp; ".join(parts)

    def describe_tooltip(self, scan_type: str, file: Path) -> str | None:
        if scan_type != EVENTS_SCAN_TYPE:
            return None
        info = self._events_info(file)
        if info.n_rows is None:
            return "Could not read this file"
        if not info.has_onset:
            return "Readable, but missing the expected 'onset' column"
        return "Readable, with an 'onset' column present"

    def detail(self, scan_type: str, file: Path) -> str | None:
        if scan_type != EVENTS_SCAN_TYPE:
            return None
        info = self._events_info(file)
        if info.n_rows is None:
            return "Could not read this events file"
        onset_text = (
            f'<span style="color:{CHECK_COLOR}">{CHECK} onset column present</span>'
            if info.has_onset
            else f'<span style="color:{CROSS_COLOR}">{CROSS} onset column missing</span>'
        )
        return f"<b>{info.n_rows} row(s)</b>, {info.n_columns} column(s) &nbsp;&nbsp; {onset_text}"

    # No task_tag_available/filename_correction_available overrides -- falls back to
    # CandidateExtras' own defaults (False for both). See LONGWALKV3_DATASET_CONFIG's comment:
    # there's no raw collection-software junk left to tag/clean up here, and no duplicate
    # marker to strip either -- physiology/events both allow_multiple, so nothing here ever
    # goes through the "duplicate -> pick one -> commit" flow that free-text filename
    # correction and duplicate-marker stripping exist for.

    def refreshable(self, scan_type: str) -> bool:
        return scan_type == EVENTS_SCAN_TYPE

    def refresh(self, scan_type: str, file: Path) -> None:
        """Force a reparse for one candidate. Caller batches the disk write via `flush()`."""
        if scan_type == EVENTS_SCAN_TYPE:
            self._events_info(file, force=True)

    def has_warning(self, scan_type: str, file: Path) -> bool:
        if scan_type != EVENTS_SCAN_TYPE:
            return False
        info = self._events_info(file)
        return info.n_rows is None or not info.has_onset

    def _cache_key(self, file: Path) -> str:
        if self._bids_folder is None:
            return file.name
        try:
            return file.relative_to(self._bids_folder).as_posix()
        except ValueError:
            return file.name

    def _events_info(self, file: Path, force: bool = False) -> LongwalkV3EventsInfo:
        key = self._cache_key(file)
        stat = file.stat()
        cached = self._disk_cache.get(key)
        if not force and cached is not None:
            if (
                cached.get("mtime") == stat.st_mtime
                and cached.get("size") == stat.st_size
                and cached.get("info_version") == INFO_SCHEMA_VERSION
            ):
                try:
                    return LongwalkV3EventsInfo(**cached["info"])
                except (TypeError, KeyError):
                    logger.warning("Stale info-cache entry for %s -- reparsing", file)

        info = _parse_events_info(file)
        self._disk_cache[key] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "info_version": INFO_SCHEMA_VERSION,
            "info": asdict(info),
        }
        self._dirty = True
        return info


class _ListLogHandler(logging.Handler):
    """Captures formatted log records into a list instead of printing them -- used to relay
    `convert_longwalkv3_to_bids`'s `logger.info`/`logger.warning` calls into the crosscheck
    GUI's status panel, since that function reports progress/problems via the standard logger
    rather than a GUI-specific callback (see its own docstring)."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"[{record.levelname}] {self.format(record)}")


def _format_conversion_summary(summary: LongWalkV3ConversionSummary) -> str:
    if not summary.new_subject_ids:
        return "No new subjects found -- everything in the raw folder is already converted."

    lines = [f"Added {len(summary.new_subject_ids)} new subject(s):", ""]
    for subject_id in summary.new_subject_ids:
        physiology = ", ".join(p.name for p in summary.subject_physiology.get(subject_id, []))
        events = ", ".join(p.name for p in summary.subject_events.get(subject_id, []))
        lines.append(f"sub-{subject_id}")
        lines.append(f"    physiology: {physiology or '(missing)'}")
        lines.append(f"    events:     {events or '(missing)'}")

    if summary.unparseable_files:
        lines.append("")
        lines.append(f"Could not parse {len(summary.unparseable_files)} raw filename(s):")
        lines.extend(f"    {file.name}" for file in summary.unparseable_files)

    return "\n".join(lines)


class RawFilenameCorrectionDialog(QDialog):
    """Lets a human declare "this raw filename really belongs to this subject" for *any* raw
    physiology/behaviour/actor-log file, not just ones that fail to parse a subject id at all.
    Corrections are saved to their own JSON
    (`longwalk3_bids.save_raw_filename_id_corrections`, in the BIDS folder) and applied the
    next time "Refresh BIDS" runs (`longwalk3_bids.resolve_subject_id`). Same shape as
    crane's/longwalk's `RawFilenameCorrectionDialog`, scoped to longwalkV3's raw physiology
    `.acq` plus every raw csv (behaviour.csv and its sibling actor-location logs).

    The bottom pane explains why the selected filename failed to parse, or what it currently
    resolves to if it didn't (`explain_unparseable_filename`/`resolve_subject_id`), and shows
    any matching line from the last "Refresh BIDS" run's captured log output
    (`parent.last_conversion_log_lines`) -- both reuse existing machinery rather than building
    a new diagnostic path.
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
            layout.addWidget(
                QLabel("No physiology/behaviour/actor-log raw files found in the raw folder.")
            )
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            return

        info_label = QLabel(
            "Every raw physiology (.acq) and behaviour/actor-log (.csv) file, with the "
            "subject id it currently resolves to. Type a corrected subject id for any row "
            "that's wrong -- whether the filename didn't parse at all, or parsed fine but to "
            "the wrong id. Leave blank to make no change. This never renames the raw file; "
            'corrections are saved separately and applied the next time you click "Refresh '
            'BIDS".'
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

            resolved = resolve_subject_id(file, raw_folder, self._existing_corrections)
            resolved_item = QTableWidgetItem(resolved if resolved else "(unparseable)")
            resolved_item.setFlags(resolved_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if resolved is None:
                resolved_item.setForeground(QBrush(QColor(CROSS_COLOR)))
            self.table.setItem(row, 1, resolved_item)

            self.table.setItem(row, 2, QTableWidgetItem(self._existing_corrections.get(key, "")))
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, 1)

        # Persistent bottom pane -- always visible below the table, updated for whichever row
        # is currently selected, same spirit as bids_crosscheck_common.py's "Last conversion"
        # status panel (fixed-height QTextEdit, not a popup).
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
        resolved = resolve_subject_id(file, self.raw_folder, self._existing_corrections)
        if resolved is None:
            detail = explain_unparseable_filename(file)
        else:
            detail = f"Currently resolves to subject id {resolved!r} from the filename."
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
    """The longwalkV3-specific `extra_raw_actions` callback for the "Fix raw filenames..."
    button -- see `RawFilenameCorrectionDialog`.
    """
    RawFilenameCorrectionDialog(raw_folder, bids_folder, parent).exec()


def _run_longwalkv3_conversion(
    raw_folder: Path, bids_folder: Path, debrief_export: Path | None
) -> list[str]:
    """The longwalkV3-specific `raw_converter` callback `BidsCrosscheckWindow` calls when the
    "Refresh BIDS" button is clicked. Captures `convert_longwalkv3_to_bids`'s own log output
    (info/warning messages about skipped subjects, unparseable filenames, ...) alongside the
    final summary, so both show up together in the status panel. `debrief_export` is unused --
    longwalkV3 has no debrief/override-file step yet (see `longwalk3_bids.py`'s module
    docstring); this GUI never wires up an override-file picker, so it's always None here.
    """
    handler = _ListLogHandler()
    converter_logger = logging.getLogger("vrlab_toolbox.processing.longwalk3_bids")
    converter_logger.addHandler(handler)
    try:
        summary = convert_longwalkv3_to_bids(raw_folder, bids_folder)
    finally:
        converter_logger.removeHandler(handler)

    return [*handler.lines, "", _format_conversion_summary(summary)]


def main() -> None:
    run_bids_crosscheck_app(
        LONGWALKV3_DATASET_CONFIG,
        "LongwalkV3 BIDS Crosscheck",
        LongwalkV3CandidateExtras(),
        settings_app_name="LongwalkV3BidsCrosscheck",
        raw_converter=_run_longwalkv3_conversion,
        extra_raw_actions=[
            (
                "Fix Filenames in Raw Folder",
                "Review every raw physiology/behaviour/actor-log filename and, if needed, "
                "declare its correct subject id. Saved separately -- never renames the raw "
                "file.",
                _on_fix_raw_filenames,
                EXTRA_RAW_ACTION_GROUP_RAW,
            ),
        ],
        convert_button_tooltip=DEFAULT_CONVERT_BUTTON_TOOLTIP,
        extra_backup_filenames=(RAW_FILENAME_ID_CORRECTIONS_FILENAME,),
    )


if __name__ == "__main__":
    main()
