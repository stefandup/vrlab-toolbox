"""Standalone PySide6 tool: human-in-the-loop crosscheck for the longwalk BIDS folder.

See docs/bids_crosscheck_plan.md and docs/bids_converter_plan.md. Longwalk is the simplest
dataset this pattern covers so far: a single `physiology` scan type (raw Biopac `.mat`
files -- see `processing/longwalk_bids.py`), no per-subject task tagging (the converter
already writes a fixed `task-longwalk`/`run-001` at copy time, same reasoning as crane's
"no tagging" case -- see `CraneCandidateExtras`'s comment in `crane_bids_crosscheck_gui.py`),
and dates recorded as a `scans.tsv` sidecar row rather than a filename prefix (also like
crane).

`LongwalkCandidateExtras` below is the longwalk analog of `CraneCandidateExtras` -- same
best-effort, fails-soft `.mat` parsing (Biopac physiology only; no behaviour/debrief data
exists for longwalk), scoped to just the `EDA` channel the longwalk pipeline actually reads
(see `processing/longwalk_pipeline.py`).
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

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

from mooi_toolbox.gui.bids_crosscheck_common import (
    DEFAULT_CONVERT_BUTTON_TOOLTIP,
    EXTRA_RAW_ACTION_GROUP_RAW,
    CandidateExtras,
    run_bids_crosscheck_app,
)
from mooi_toolbox.processing.bids import strip_duplicate_marker
from mooi_toolbox.processing.bids_crosscheck import DatasetConfig, ScanTypeConfig
from mooi_toolbox.processing.biodata import ACCEPTED_LABEL_PATTERN, CANONICAL_LABEL_SPELLING
from mooi_toolbox.processing.biopac import clean_biopac_labels
from mooi_toolbox.processing.longwalk_bids import (
    RAW_FILENAME_ID_CORRECTIONS_FILENAME,
    LongWalkConversionSummary,
    convert_longwalk_to_bids,
    discover_raw_files_for_review,
    explain_unparseable_filename,
    load_raw_filename_id_corrections,
    resolve_biopac_filename,
    save_raw_filename_id_corrections,
)

logger = logging.getLogger(__name__)

LONGWALK_DATASET_CONFIG = DatasetConfig(
    dataset_name="longwalk",
    scan_types=(ScanTypeConfig(name="physiology", glob_patterns=("*.mat",)),),
    # No task_tag_task/task_tag_folder_name -- like crane, longwalk has no tagging step at
    # all: `processing/longwalk_bids.py` already writes a real BIDS suffix (task-longwalk/
    # run-001/_physio) itself at copy time, so there's no raw collection-software junk left
    # to clean up.
    # Longwalk's converter records each file's date as a scans.tsv row instead of a filename
    # prefix (see docs/bids_converter_plan.md) -- routes the crosscheck GUI's "Correct
    # date..." button to edit that row instead of renaming the file.
    dates_in_scans_tsv=True,
)

PHYSIOLOGY_SCAN_TYPE = "physiology"

# The longwalk pipeline only ever processes EDA out of a Biopac recording (see
# processing/longwalk_pipeline.py) -- unlike FOH, which needs both EDA and ECG.
EXPECTED_PHYSIO_CHANNELS = ("EDA",)

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
class LongwalkPhysiologyInfo:
    channels: dict[str, bool]
    duration_minutes: float | None
    all_labels: list[str] | None


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


def _parse_physiology_info(file: Path) -> LongwalkPhysiologyInfo:
    try:
        imported_data = sio.loadmat(str(file))
        labels = clean_biopac_labels(imported_data["labels"])
        isi_seconds = float(imported_data["isi"].squeeze()) / 1000
        n_samples = imported_data["data"].shape[0]
    except Exception:
        logger.warning("Could not read physiology data from %s", file, exc_info=True)
        return LongwalkPhysiologyInfo(
            channels=dict.fromkeys(EXPECTED_PHYSIO_CHANNELS, False),
            duration_minutes=None,
            all_labels=None,
        )

    return LongwalkPhysiologyInfo(
        channels=_present_physio_channels(labels),
        duration_minutes=(n_samples * isi_seconds) / 60,
        all_labels=labels,
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


class LongwalkCandidateExtras(CandidateExtras):
    """Advisory longwalk physiology info; never gates renaming.

    Every parse result is cached on disk (see INFO_CACHE_FILENAME), keyed by the file's path
    relative to the BIDS folder plus its mtime/size, so a fresh launch or re-Browse doesn't
    have to re-parse every "ok" candidate again -- only files that are new or have actually
    changed. Mirrors `CraneCandidateExtras`'s cache (`crane_bids_crosscheck_gui.py`), scoped
    to longwalk's one scan type instead of crane's three.
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
        if scan_type != PHYSIOLOGY_SCAN_TYPE:
            return None
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

    def describe_tooltip(self, scan_type: str, file: Path) -> str | None:
        if scan_type != PHYSIOLOGY_SCAN_TYPE:
            return None
        info = self._physiology_info(file)
        lines = ["Channels the longwalk pipeline needs:"]
        lines.extend(
            f"{CHECK if present else CROSS} {label}" for label, present in info.channels.items()
        )
        return "\n".join(lines)

    def detail(self, scan_type: str, file: Path) -> str | None:
        if scan_type != PHYSIOLOGY_SCAN_TYPE:
            return None
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

    # No task_tag_available override -- falls back to CandidateExtras' own "False". See
    # LONGWALK_DATASET_CONFIG's comment: there's no raw collection-software junk left to
    # tag/clean up here, unlike FOH.
    #
    # No filename_correction_available override either -- the one thing longwalk's converter
    # can leave behind that needs a post-hoc fix, a "-dupN" collision marker (see
    # `bids.resolve_collision`) on whichever duplicate turns out to be the real recording, is
    # handled automatically by duplicate_marker_free_name below instead of a free-text escape
    # hatch, same reasoning as crane.

    def duplicate_marker_free_name(self, scan_type: str, file: Path) -> str | None:
        return strip_duplicate_marker(file.name)

    def refreshable(self, scan_type: str) -> bool:
        return scan_type == PHYSIOLOGY_SCAN_TYPE

    def refresh(self, scan_type: str, file: Path) -> None:
        """Force a reparse for one candidate. Caller batches the disk write via `flush()`."""
        if scan_type == PHYSIOLOGY_SCAN_TYPE:
            self._physiology_info(file, force=True)

    def has_warning(self, scan_type: str, file: Path) -> bool:
        if scan_type != PHYSIOLOGY_SCAN_TYPE:
            return False
        info = self._physiology_info(file)
        return info.all_labels is not None and not all(info.channels.values())

    def _cache_key(self, file: Path) -> str:
        if self._bids_folder is None:
            return file.name
        try:
            return file.relative_to(self._bids_folder).as_posix()
        except ValueError:
            return file.name

    def _physiology_info(self, file: Path, force: bool = False) -> LongwalkPhysiologyInfo:
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
                    return LongwalkPhysiologyInfo(**cached["info"])
                except (TypeError, KeyError):
                    logger.warning("Stale info-cache entry for %s -- reparsing", file)

        info = _parse_physiology_info(file)
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
    `convert_longwalk_to_bids`'s `logger.info`/`logger.warning` calls into the crosscheck
    GUI's status dialog, since that function reports progress/problems via the standard
    logger rather than a GUI-specific callback (see its own docstring)."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"[{record.levelname}] {self.format(record)}")


def _format_conversion_summary(summary: LongWalkConversionSummary) -> str:
    if not summary.new_subject_ids:
        return "No new subjects found -- everything in the raw folder is already converted."

    lines = [f"Added {len(summary.new_subject_ids)} new subject(s):", ""]
    for subject_id in summary.new_subject_ids:
        physiology = ", ".join(p.name for p in summary.subject_physiology.get(subject_id, []))
        lines.append(f"sub-{subject_id}")
        lines.append(f"    physiology: {physiology or '(missing)'}")

    return "\n".join(lines)


class RawFilenameCorrectionDialog(QDialog):
    """Lets a human declare "this raw filename really belongs to this subject" for *any* raw
    physiology file, not just ones `parse_biopac_filename` couldn't extract a subject id from
    at all -- a filename can just as easily resolve to a *wrong* id without ever failing to
    parse (e.g. a "(N)" duplicate-copy marker that could mean either a harmless double-copy
    of the same recording or two different subjects sharing a base id; see
    `parse_biopac_filename`'s own docstring). Corrections are saved to their own JSON
    (`longwalk_bids.save_raw_filename_id_corrections`, in the BIDS folder) and applied the
    next time "Refresh BIDS" runs (`longwalk_bids.resolve_biopac_filename`). Same shape as
    crane's `RawFilenameCorrectionDialog` (`crane_bids_crosscheck_gui.py`), scoped to
    longwalk's one raw file type instead of crane's two.

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
            layout.addWidget(QLabel("No physiology raw files found in the raw folder."))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            return

        info_label = QLabel(
            "Every raw physiology file, with the subject id it currently resolves to. Type "
            "a corrected subject id for any row that's wrong -- whether the filename didn't "
            'parse at all, or parsed fine but to the wrong id (e.g. two subjects sharing a '
            '"(N)" marker). Leave blank to make no change. This never renames the raw file; '
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

            resolved = resolve_biopac_filename(file, raw_folder, self._existing_corrections)
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
        resolved = resolve_biopac_filename(file, self.raw_folder, self._existing_corrections)
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
    """The longwalk-specific `extra_raw_actions` callback for the "Fix raw filenames..."
    button -- see `RawFilenameCorrectionDialog`.
    """
    RawFilenameCorrectionDialog(raw_folder, bids_folder, parent).exec()


def _run_longwalk_conversion(
    raw_folder: Path, bids_folder: Path, debrief_export: Path | None
) -> list[str]:
    """The longwalk-specific `raw_converter` callback `BidsCrosscheckWindow` calls when the
    "Refresh BIDS" button is clicked. Captures `convert_longwalk_to_bids`'s own log output
    (info/warning messages about skipped subjects, unparseable filenames, ...) alongside the
    final summary, so both show up together in the status panel. `debrief_export` is unused --
    longwalk has no debrief/override-file step (`convert_longwalk_to_bids` accepts the
    parameter but doesn't act on it yet); this GUI never wires up an override-file picker, so
    it's always None here.
    """
    handler = _ListLogHandler()
    converter_logger = logging.getLogger("mooi_toolbox.processing.longwalk_bids")
    converter_logger.addHandler(handler)
    try:
        summary = convert_longwalk_to_bids(raw_folder, bids_folder)
    finally:
        converter_logger.removeHandler(handler)

    return [*handler.lines, "", _format_conversion_summary(summary)]


def main() -> None:
    run_bids_crosscheck_app(
        LONGWALK_DATASET_CONFIG,
        "Longwalk BIDS Crosscheck",
        LongwalkCandidateExtras(),
        settings_app_name="LongwalkBidsCrosscheck",
        raw_converter=_run_longwalk_conversion,
        extra_raw_actions=[
            (
                "Fix Filenames in Raw Folder",
                "Review every raw physiology filename and, if needed, declare its correct "
                "subject id -- for filenames that don't parse at all, or ones that parse "
                'fine but to the wrong id (e.g. two subjects sharing a "(N)" duplicate-copy '
                "marker). Saved separately -- never renames the raw file.",
                _on_fix_raw_filenames,
                EXTRA_RAW_ACTION_GROUP_RAW,
            ),
        ],
        convert_button_tooltip=DEFAULT_CONVERT_BUTTON_TOOLTIP,
        extra_backup_filenames=(RAW_FILENAME_ID_CORRECTIONS_FILENAME,),
    )


if __name__ == "__main__":
    main()
