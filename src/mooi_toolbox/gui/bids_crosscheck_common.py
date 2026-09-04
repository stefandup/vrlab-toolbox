"""Shared master-detail PySide6 window for the BIDS crosscheck tools.

Dataset-specific entry points (`crane_bids_crosscheck_gui.py`,
`foh_bids_crosscheck_gui.py`) supply a `DatasetConfig` and an optional
`CandidateExtras` and call `run_bids_crosscheck_app`. See
docs/bids_crosscheck_plan.md for the design.
"""

import json
import logging
import textwrap
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QSettings, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from rich.progress import Progress

from mooi_toolbox import __version__
from mooi_toolbox.processing.bids_crosscheck import (
    SUBJECT_FOLDER_PREFIX,
    BidsCrosscheckError,
    BidsFolderScan,
    DatasetConfig,
    SubjectScan,
    backup_decisions,
    completeness_summary,
    crosschecked_scan_types,
    ensure_bidsignore,
    list_scans_tsv_rows,
    load_decisions,
    load_excluded_subjects,
    load_pending_selections,
    load_study_id,
    read_scans_tsv_date,
    rebuild_from_raw,
    record_date_correction,
    record_filename_correction,
    record_id_correction,
    record_scans_tsv_date_correction,
    record_scans_tsv_row_date_correction,
    record_selected_run,
    record_subject_excluded,
    record_task_tag,
    remove_task_tag,
    restore_backup_files,
    restore_subjects_from_bids,
    save_pending_selections,
    save_study_id,
    scan_bids_folder,
    set_crosschecked,
)

logger = logging.getLogger(__name__)

STATUS_ICON = {"ok": "●", "missing": "○", "duplicate": "⚠"}
CROSSCHECKED_ICON = "☑"
PENDING_ICON = "⏳"
NEEDS_TAG_ICON = "🏷"
WARNING_ICON = "❗"
SCANS_TSV_DATE_ISSUE_ICON = "✗"
PLEASE_SELECT_COLOR = "#f39c12"
PENDING_COLOR = "#9b59b6"
UNCROSSCHECKED_COLOR = "#e74c3c"
FOUND_EVERYWHERE_COLOR = "#2ecc71"
SUBJECT_ID_ROLE = Qt.ItemDataRole.UserRole
SETTINGS_ORGANIZATION = "MooiToolbox"
LAST_BIDS_FOLDER_SETTINGS_KEY = "last_bids_folder"
LAST_RAW_FOLDER_SETTINGS_KEY = "last_raw_folder"
# Every study id this app has ever seen, across every BIDS folder -- app-wide (unlike the
# study id itself, which lives inside each BIDS folder via `save_study_id`), so the study id
# combo box has something to suggest for a brand-new folder that doesn't have one yet.
KNOWN_STUDY_IDS_SETTINGS_KEY = "known_study_ids"
# Which group box an `extra_raw_actions` button belongs beside -- see `run_bids_crosscheck_app`'s
# docstring on `extra_raw_actions`.
EXTRA_RAW_ACTION_GROUP_RAW = "raw"
EXTRA_RAW_ACTION_GROUP_OVERRIDE = "override"
CROSSCHECK_DATA_BACKUP_DIRNAME = "crosscheck_backups"
AUTOSAVE_ENABLED_SETTINGS_KEY = "autosave_enabled"
AUTOSAVE_INTERVAL_MINUTES_SETTINGS_KEY = "autosave_interval_minutes"
DEFAULT_AUTOSAVE_INTERVAL_MINUTES = 10
MIN_AUTOSAVE_INTERVAL_MINUTES = 1
MAX_AUTOSAVE_INTERVAL_MINUTES = 60
# Qt's plain-text QToolTip never wraps on its own -- a long tooltip string renders as one
# unbroken line stretching off-screen unless it already contains manual line breaks. Kept
# narrow enough to read as a compact box rather than a nearly-full-width banner.
TOOLTIP_WRAP_WIDTH = 68
# Explicit-primary-button palette -- shared by the crosscheck (green) and dataset-specific
# "Fix ..." (grey) buttons, see `_primary_action_stylesheet`. Different colors so the two
# stay visually distinguishable: marking something reviewed vs. repairing raw data are
# different kinds of action, even when both deserve equal visual weight.
CROSSCHECK_PRIMARY_HOVER_COLOR = "#27ae60"
FIX_ACTION_COLOR = "#7f8c8d"
FIX_ACTION_HOVER_COLOR = "#6c7a7d"
PRIMARY_BUTTON_DISABLED_BG = "#555555"
PRIMARY_BUTTON_DISABLED_FG = "#999999"
PATH_LABEL_FONT_POINT_INCREASE = 2


def _primary_action_stylesheet(base_color: str, hover_color: str) -> str:
    """Stylesheet for an "explicit primary action" button -- bold, padded, filled with
    `base_color` -- used for whichever single button in a row is the main thing to click
    (e.g. "Mark selected crosschecked", "Fix Filenames in Raw Folder"), so it reads as a
    real call to action rather than sitting flush with plain Browse/Reveal-style buttons.
    """
    return (
        f"QPushButton {{ font-weight: bold; font-size: 13px; padding: 6px 20px; "
        f"background-color: {base_color}; color: white; border-radius: 4px; border: none; }}"
        f"QPushButton:hover {{ background-color: {hover_color}; }}"
        f"QPushButton:disabled {{ background-color: {PRIMARY_BUTTON_DISABLED_BG}; "
        f"color: {PRIMARY_BUTTON_DISABLED_FG}; }}"
    )


def wrap_tooltip(text: str, width: int = TOOLTIP_WRAP_WIDTH) -> str:
    """Hard-wraps `text` into paragraph "boxes" instead of one unbroken line -- see
    `TOOLTIP_WRAP_WIDTH`. Splits on blank-line paragraph breaks ("\\n\\n") and wraps each one
    independently; a paragraph that already contains its own manual line breaks (e.g. an
    icon legend, one entry per line) is left exactly as written, since that's already
    deliberately structured rather than one long run-on sentence.
    """
    paragraphs = text.split("\n\n")
    wrapped = [
        paragraph if "\n" in paragraph else "\n".join(textwrap.wrap(paragraph, width=width))
        for paragraph in paragraphs
    ]
    return "\n\n".join(wrapped)


def _style_path_label(label: QLabel) -> None:
    """Bumps a folder/file path value's font size -- these are the thing a user most needs
    to read clearly at a glance (which BIDS/raw folder am I even looking at?), unlike the
    "Path:" caption beside it or the buttons around it.
    """
    font = label.font()
    font.setPointSize(font.pointSize() + PATH_LABEL_FONT_POINT_INCREASE)
    label.setFont(font)


_INVALID_PATH_CHARACTERS = '<>:"/\\|?*'


def _sanitize_for_filesystem(text: str) -> str:
    """`text` with characters invalid in a Windows/macOS/Linux folder name replaced with
    "_", and surrounding whitespace/dots stripped -- turns a free-typed study id into a safe
    folder name for `_crosscheck_data_dir`. Falls back to "study" if nothing usable is left
    (e.g. the study id was pure punctuation), so a save/restore never lands in an empty- or
    dot-named folder.
    """
    cleaned = "".join("_" if char in _INVALID_PATH_CHARACTERS else char for char in text.strip())
    cleaned = cleaned.strip(" .")
    return cleaned or "study"


STATUS_ICON_TOOLTIP = (
    f"{STATUS_ICON['ok']} complete -- exactly one file found\n"
    f"{STATUS_ICON['missing']} missing -- no file found\n"
    f"{STATUS_ICON['duplicate']} duplicate -- more than one candidate, pick one\n"
    f"{CROSSCHECKED_ICON} crosschecked -- manually marked as reviewed\n"
    f"{PENDING_ICON} picked but not committed yet\n"
    f"{NEEDS_TAG_ICON} the currently selected file hasn't been tagged yet\n"
    f"{WARNING_ICON} the currently selected file has a dataset-specific issue -- "
    "see its detail panel"
)
DEFAULT_CONVERT_BUTTON_TOOLTIP = wrap_tooltip(
    "Safe to run any time, including repeatedly. Only ever adds new subjects -- never "
    "re-copies, overwrites, or touches a subject/file already in the BIDS folder below, "
    "and never touches the raw folder at all."
)
TAG_COLUMN_TOOLTIP = wrap_tooltip(
    "Whether the currently-effective recording has been tagged yet, and with what. Blank "
    "for a scan type that doesn't use tagging, or with nothing effective yet."
)
DATATYPE_COLUMN_TOOLTIP = wrap_tooltip(
    "BIDS's own term for the eeg/beh/func/... subfolder a recording lives in. Hover a "
    "value in this column for what it means and whether it'll change."
)
# BIDS's own vocabulary for its datatype folders -- used to gloss a folder name in plain
# English wherever one's shown (e.g. "beh" -> "behavioural"). Not exhaustive, just the ones
# likely to come up; an unrecognized folder name is shown without a gloss rather than guessed.
BIDS_DATATYPE_NAMES = {
    "anat": "anatomical",
    "beh": "behavioural",
    "dwi": "diffusion-weighted imaging",
    "eeg": "electroencephalography",
    "fmap": "field map",
    "func": "functional MRI",
    "ieeg": "intracranial EEG",
    "meg": "magnetoencephalography",
    "motion": "motion capture",
    "nirs": "near-infrared spectroscopy",
    "perf": "perfusion",
    "pet": "positron emission tomography",
}


SCANS_TSV_DATE_FORMAT = "%Y%m%d%H%M"
SCANS_TSV_DATE_QT_FORMAT = "yyyyMMddHHmm"
# Separators here are purely cosmetic -- they make the HH/mm section visually distinct so a
# user notices it's editable, rather than reading as one undifferentiated block of 12 digits
# next to the date. The stored/returned value still uses SCANS_TSV_DATE_QT_FORMAT (no
# separators), since that's the strict format scans.tsv itself requires.
SCANS_TSV_DATE_QT_DISPLAY_FORMAT = "yyyy-MM-dd HH:mm"


def _parse_scans_tsv_date(value: str | None) -> datetime | None:
    """Parses a scans.tsv `acq_time` value as the strict YYYYMMDDHHMM format the scans.tsv
    pane checks every row against. Crane's converter itself just writes whatever digit string
    it can scrape from a raw filename (see cli/crane_convert_to_bids.py) -- neither this format
    nor a consistent length -- so most existing values are expected to fail this until a human
    corrects them via the pane.
    """
    if not value:
        return None
    try:
        return datetime.strptime(value, SCANS_TSV_DATE_FORMAT)
    except ValueError:
        return None


def _scans_tsv_reference_date(rows: list[dict[str, str]]) -> datetime | None:
    """The majority `acq_time` value among a subject's own scans.tsv rows -- there's nothing
    else in a scans.tsv to compare against, so one outlier among several agreeing rows is a
    much more useful signal than "no rows agree with anything". Shared by the scans.tsv pane's
    per-row tick/cross (`_build_scans_tsv_row`) and the master subject list's at-a-glance
    SCANS_TSV_DATE_ISSUE_ICON (`_scans_tsv_has_date_issue`), so the two never disagree about
    what counts as an issue.
    """
    valid_dates = [
        parsed
        for parsed in (_parse_scans_tsv_date(row.get("acq_time")) for row in rows)
        if parsed is not None
    ]
    return Counter(valid_dates).most_common(1)[0][0] if valid_dates else None


class ScansTsvDateCorrectionDialog(QDialog):
    """Lets a human pick a corrected `acq_time` for one scans.tsv row. A single QDateTimeEdit
    gives both a directly-editable date and HH:mm field (each section clickable/typable/
    spinnable on its own, per SCANS_TSV_DATE_QT_DISPLAY_FORMAT) and a calendar popup (its
    trailing calendar-icon button) for picking the date visually, so there's exactly one value
    to keep in sync rather than a free-text box plus a separate picker -- and since
    QDateTimeEdit only ever holds a valid date/time, whatever it returns is guaranteed
    well-formed. The displayed format is cosmetic only; `corrected_date()` still returns the
    strict YYYYMMDDHHMM scans.tsv requires. Defaults to today when the row's existing value
    doesn't parse (see `_parse_scans_tsv_date`), so correcting an unparseable/missing value
    starts from a sensible point rather than a blank or invalid one.
    """

    def __init__(self, filename: str, current_date: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Correct acquisition date")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Acquisition date for {filename}:"))

        self.date_edit = QDateTimeEdit()
        self.date_edit.setDisplayFormat(SCANS_TSV_DATE_QT_DISPLAY_FORMAT)
        self.date_edit.setCalendarPopup(True)
        parsed = _parse_scans_tsv_date(current_date)
        self.date_edit.setDateTime(parsed or datetime.now())
        layout.addWidget(self.date_edit)

        today_button = QPushButton("Today")
        today_button.setToolTip("Reset the field above to right now.")
        today_button.clicked.connect(lambda: self.date_edit.setDateTime(datetime.now()))
        layout.addWidget(today_button)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def corrected_date(self) -> str:
        return self.date_edit.dateTime().toString(SCANS_TSV_DATE_QT_FORMAT)


class CandidateExtras:
    """Hook for dataset-specific per-candidate UI. Crane uses the no-op default."""

    def describe(self, scan_type: str, file: Path) -> str | None:
        return None

    def describe_tooltip(self, scan_type: str, file: Path) -> str | None:
        """Tooltip for the `describe()` label, if there's anything worth explaining."""
        return None

    def detail(self, scan_type: str, file: Path) -> str | None:
        """Extended info for the currently selected candidate of `scan_type`, if any."""
        return None

    def task_tag_available(self, scan_type: str) -> bool:
        return False

    def filename_correction_available(self, scan_type: str) -> bool:
        """True to show a free-text "Correct filename..." action for this scan type's
        effective candidate -- a general escape hatch for fixing any part of a filename a
        human spots as wrong (a wrong entity, a stray "-dupN" collision marker, ...), for
        datasets without a narrower, structured correction for that kind of mistake.
        """
        return False

    def duplicate_marker_free_name(self, scan_type: str, file: Path) -> str | None:
        """The corrected filename `file` should be renamed to now that it's the sole
        surviving candidate for `scan_type` (a duplicate pick was just committed), or None
        if it doesn't need one. Checked once, right after a commit -- see
        `_commit_pending_selections` -- so a dataset whose converter can leave a
        collision marker on a survivor (crane's `-dupN`, see
        `crane_convert_to_bids._resolve_destination`) gets it stripped automatically,
        without a human retyping the filename by hand. Most datasets (the no-op default
        here) never produce a marker like this in the first place.
        """
        return None

    def has_warning(self, scan_type: str, file: Path) -> bool:
        """True if this candidate has a dataset-specific issue worth flagging at a glance."""
        return False

    def refreshable(self, scan_type: str) -> bool:
        """True if `refresh()` does something useful for this scan type."""
        return False

    def refresh(self, scan_type: str, file: Path) -> None:
        """Force this candidate's info to be recomputed, bypassing any cache."""
        return None

    def on_bids_folder_changed(self, bids_folder: Path) -> None:
        """Called once when a BIDS folder is (re)loaded, before any candidates are scanned."""
        return None

    def flush(self) -> None:
        """Called after a full subject-list population, so cache writes can be batched."""
        return None

    def bidsignore_patterns(self) -> tuple[str, ...]:
        """Extra `.bidsignore` patterns this dataset's extras need beyond the shared ones
        (crosscheck.json, crosscheck_pending.json, excluded_subjects.json) -- e.g. an info
        cache filename. Crane's no-op default needs none."""
        return ()


class BidsCrosscheckWindow(QMainWindow):
    def __init__(
        self,
        dataset_config: DatasetConfig,
        window_title: str,
        extras: CandidateExtras | None = None,
        settings_app_name: str | None = None,
        raw_converter: Callable[[Path, Path, Path | None], list[str]] | None = None,
        override_file_label: str | None = None,
        override_file_filter: str = "All files (*)",
        override_file_autodetect: Callable[[Path], Path | None] | None = None,
        extra_raw_actions: list[tuple[str, str, Callable[[Path, Path, QWidget], None], str]]
        | None = None,
        convert_button_tooltip: str = DEFAULT_CONVERT_BUTTON_TOOLTIP,
        extra_backup_filenames: tuple[str, ...] = (),
    ):
        """`raw_converter`, if given, adds a "Raw Folder" group box and a "Refresh BIDS"
        button in the "BIDS Folder" group box below it -- optional, dataset-specific (crane
        and FOH both supply one today). Called as `raw_converter(raw_folder, bids_folder,
        override_file)`, expected to do its own writing into `bids_folder` and return
        human-readable lines describing what it did, for display in the Activity Log; a
        raised exception is caught and shown as an error there instead. This window never
        imports the dataset-specific converter itself -- it only ever calls whatever
        callable it's handed.

        `convert_button_tooltip`, if given, overrides the "Refresh BIDS" button's default
        tooltip -- for a dataset-specific detail worth calling out beyond the generic
        "only ever adds new subjects" guarantee (e.g. crane's debrief backfill behavior).

        `override_file_label`, if given (only meaningful alongside `raw_converter`), adds a
        third, optional single-file selector, in its own group box titled with this label --
        e.g. crane's "Debrief export" ("override which workbook counts as the debrief
        source" when auto-detection can't tell). `override_file` is None unless the user has
        picked one; the callable decides what None means (typically: fall back to its own
        auto-detection). `override_file_filter` is the QFileDialog filter string for that
        picker (e.g. "Excel files (*.xlsx)") -- this window has no opinion on what kind of
        file it is, only that the dataset-specific converter does.

        `override_file_autodetect`, if given (only meaningful alongside
        `override_file_label`), is called as `override_file_autodetect(raw_folder)` to show
        the human *which* file auto-detection would actually pick, so they can confirm it's
        the right one rather than trusting a bare "(auto-detect)" placeholder -- e.g. crane's
        `find_debrief_export`. Only used for display; the actual conversion still resolves
        this itself via `raw_converter`. None (the default) keeps the old placeholder-only
        behavior.

        `extra_raw_actions`, if given (only meaningful alongside `raw_converter`), adds one
        more button per entry -- each `(button_label, tooltip, callback, group)`, called as
        `callback(raw_folder, bids_folder, self)` once both are set. `group` is
        `EXTRA_RAW_ACTION_GROUP_RAW` to place the button in the "Raw Folder" group box, or
        `EXTRA_RAW_ACTION_GROUP_OVERRIDE` to place it in the `override_file_label` group box
        instead -- e.g. crane's "Fix Filenames in Raw Folder" (raw) and "Fix Record IDs in
        Debrief Export" (override) dialogs. Same "this window doesn't know what the callback
        does" contract as `raw_converter`.

        `extra_backup_filenames`, if given, names dataset-specific files living alongside
        `crosscheck.json` that "Save Crosscheck Data"/"Restore Saved Crosscheck Data" should
        also cover -- e.g. crane's `debrief_id_corrections.json`/
        `raw_filename_id_corrections.json`, which an `extra_raw_actions` dialog writes and
        `raw_converter` itself reads as input on the next conversion. This window doesn't
        know what these files mean, only that they need to travel with a backup the same way
        `crosscheck.json` does.
        """
        super().__init__()
        self.dataset_config = dataset_config
        self.extras = extras or CandidateExtras()
        self.raw_converter = raw_converter
        self.override_file_label = override_file_label
        self.override_file_filter = override_file_filter
        self.override_file_autodetect = override_file_autodetect
        self.extra_raw_actions = extra_raw_actions or []
        self.convert_button_tooltip = convert_button_tooltip
        self.extra_backup_filenames = extra_backup_filenames
        self.bids_folder: Path | None = None
        self.raw_folder: Path | None = None
        self.override_file: Path | None = None
        # Lines captured from the last "Refresh BIDS" run's log output (see
        # _update_conversion_status_panel) -- exposed as a public attribute so an
        # extra_raw_actions callback (e.g. crane's unparseable-filename dialog) can show
        # relevant excerpts from it without this window needing to know what "relevant"
        # means for any particular dataset.
        self.last_conversion_log_lines: list[str] = []
        self.scan: BidsFolderScan | None = None
        self._crosschecked: set[tuple[str, str]] = set()
        self._pending_selections: dict[str, dict[str, Path]] = {}
        self.detail_extra_layout: QVBoxLayout | None = None
        self._settings = QSettings(
            SETTINGS_ORGANIZATION,
            settings_app_name or f"BidsCrosscheck-{dataset_config.dataset_name}",
        )

        self.setWindowTitle(f"{window_title} (v{__version__})")
        self.resize(1100, 650)
        self._build_ui()
        self._restore_last_bids_folder()
        self._restore_last_raw_folder()

    def _restore_last_bids_folder(self) -> None:
        stored = self._settings.value(LAST_BIDS_FOLDER_SETTINGS_KEY, "")
        if stored and Path(stored).is_dir():
            self.load_bids_folder(Path(stored))

    def _restore_last_raw_folder(self) -> None:
        if self.raw_converter is None:
            return
        stored = self._settings.value(LAST_RAW_FOLDER_SETTINGS_KEY, "")
        if stored and Path(stored).is_dir():
            self.raw_folder = Path(stored)
            self.raw_folder_label.setText(str(self.raw_folder))
            self._update_convert_button_enabled()
            self._update_override_file_label()

    def _task_tag_display_marker(self) -> str:
        """The `task-<task>[_acq-<acq>]` entity text a tagged file carries, for tooltips."""
        marker = f"task-{self.dataset_config.task_tag_task}"
        if self.dataset_config.task_tag_acq:
            marker += f"_acq-{self.dataset_config.task_tag_acq}"
        return marker

    def _task_tag_tooltip(self) -> str:
        target = self.dataset_config.task_tag_folder_name
        tooltip = (
            f"Adds a real BIDS {self._task_tag_display_marker()!r} tag to every subject's "
            "currently selected recording (replacing whatever free text the collection "
            f"software left after run-<NNN> with the real {self.dataset_config.task_tag_suffix!r} "
            "suffix), skipping any already tagged."
        )
        if target:
            target_meaning = BIDS_DATATYPE_NAMES.get(target)
            tooltip += f' Also moves each one into the "{target}" datatype folder'
            if target_meaning:
                tooltip += f" ({target_meaning})"
            tooltip += "."
        tooltip += " This can't be undone from within the tool."
        return wrap_tooltip(tooltip)

    def _add_extra_action_buttons(self, button_row: QHBoxLayout, group: str) -> None:
        """Appends every `extra_raw_actions` entry tagged with `group`
        (`EXTRA_RAW_ACTION_GROUP_RAW`/`EXTRA_RAW_ACTION_GROUP_OVERRIDE`) to the *front* of
        `button_row` -- e.g. crane's "Fix Filenames in Raw Folder" leftmost in the Raw
        Folder group's button row, "Fix Record IDs in Debrief Export" leftmost in the
        Debrief Export one. Styled as an explicit primary action (grey, not the crosscheck
        green) so a dataset-specific repair button reads as something to actually click,
        distinct from the plain Browse/Reveal buttons that follow it in the same row.
        No-op if no entry is tagged for this `group`.
        """
        for label, tooltip, callback, action_group in self.extra_raw_actions:
            if action_group != group:
                continue
            button = QPushButton(label)
            button.setToolTip(wrap_tooltip(tooltip))
            button.setEnabled(False)
            button.setMinimumHeight(30)
            button.setStyleSheet(
                _primary_action_stylesheet(FIX_ACTION_COLOR, FIX_ACTION_HOVER_COLOR)
            )
            button.clicked.connect(
                lambda _checked=False, callback=callback: self._on_extra_raw_action(callback)
            )
            button_row.addWidget(button)
            self.extra_raw_action_buttons.append(button)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        self.extra_raw_action_buttons: list[QPushButton] = []

        # Folder pickers stacked in a left column, with the Activity Log beside them (not
        # below the subject detail panes, its old spot) -- fills what would otherwise be
        # dead space to their right, and keeps that log visible without pushing Subject
        # Actions/the subject list further down the page.
        top_row = QHBoxLayout()
        folders_column = QVBoxLayout()

        if self.raw_converter is not None:
            raw_group = QGroupBox("Raw Folder")
            raw_group_layout = QVBoxLayout(raw_group)
            raw_group_layout.setSpacing(4)
            raw_path_row = QHBoxLayout()
            raw_path_row.setSpacing(6)
            raw_path_row.addWidget(QLabel("Path:"))
            self.raw_folder_label = QLabel("No raw folder selected")
            _style_path_label(self.raw_folder_label)
            raw_path_row.addWidget(self.raw_folder_label, 1)
            raw_group_layout.addLayout(raw_path_row)

            raw_button_row = QHBoxLayout()
            raw_button_row.setSpacing(6)
            self._add_extra_action_buttons(raw_button_row, EXTRA_RAW_ACTION_GROUP_RAW)
            raw_browse_button = QPushButton("Browse...")
            raw_browse_button.setToolTip(
                "Pick the raw data folder to convert into the BIDS folder below."
            )
            raw_browse_button.clicked.connect(self._on_browse_raw_folder)
            raw_button_row.addWidget(raw_browse_button)
            self.reveal_raw_button = QPushButton("Reveal Raw Folder")
            self.reveal_raw_button.setToolTip(
                wrap_tooltip(
                    "Open the raw folder in the system file browser, so you can look at the "
                    "raw files yourself."
                )
            )
            self.reveal_raw_button.setEnabled(False)
            self.reveal_raw_button.clicked.connect(self._on_reveal_raw_folder)
            raw_button_row.addWidget(self.reveal_raw_button)
            raw_button_row.addStretch(1)
            raw_group_layout.addLayout(raw_button_row)
            folders_column.addWidget(raw_group)

            if self.override_file_label is not None:
                override_group = QGroupBox(self.override_file_label.title())
                override_group_layout = QVBoxLayout(override_group)
                override_group_layout.setSpacing(4)
                override_path_row = QHBoxLayout()
                override_path_row.setSpacing(6)
                override_path_row.addWidget(QLabel("Path:"))
                self.override_file_label_widget = QLabel("(auto-detect)")
                _style_path_label(self.override_file_label_widget)
                override_path_row.addWidget(self.override_file_label_widget, 1)
                override_group_layout.addLayout(override_path_row)

                override_button_row = QHBoxLayout()
                override_button_row.setSpacing(6)
                self._add_extra_action_buttons(override_button_row, EXTRA_RAW_ACTION_GROUP_OVERRIDE)
                override_browse_button = QPushButton("Browse...")
                override_browse_button.setToolTip(
                    wrap_tooltip(
                        f"Pick a specific file to use as the {self.override_file_label.lower()}, "
                        "overriding auto-detection."
                    )
                )
                override_browse_button.clicked.connect(self._on_browse_override_file)
                override_button_row.addWidget(override_browse_button)
                override_clear_button = QPushButton("Clear")
                override_clear_button.setToolTip("Go back to auto-detection.")
                override_clear_button.clicked.connect(self._on_clear_override_file)
                override_button_row.addWidget(override_clear_button)
                override_button_row.addStretch(1)
                override_group_layout.addLayout(override_button_row)
                folders_column.addWidget(override_group)

        bids_group = QGroupBox("BIDS Folder")
        bids_group_layout = QVBoxLayout(bids_group)
        bids_group_layout.setSpacing(4)
        bids_path_row = QHBoxLayout()
        bids_path_row.setSpacing(6)
        bids_path_row.addWidget(QLabel("Path:"))
        self.folder_label = QLabel("No BIDS folder selected")
        _style_path_label(self.folder_label)
        bids_path_row.addWidget(self.folder_label, 1)
        bids_group_layout.addLayout(bids_path_row)

        bids_study_row = QHBoxLayout()
        bids_study_row.setSpacing(6)
        bids_study_row.addWidget(QLabel("Study ID:"))
        self.study_id_combo = QComboBox()
        self.study_id_combo.setEditable(True)
        self.study_id_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.study_id_combo.setToolTip(
            wrap_tooltip(
                "A short id for this study -- saved inside this BIDS folder, so it's "
                "remembered next time you open it, and used to name its saved crosscheck "
                "data (see \"Save Crosscheck Data\" below) so that stays identifiable by a "
                "human. Pick an existing one from the dropdown if you're pointing this tool "
                "at a different copy of a study you've already worked on."
            )
        )
        self.study_id_combo.lineEdit().editingFinished.connect(self._on_study_id_committed)
        self.study_id_combo.activated.connect(lambda _index: self._on_study_id_committed())
        bids_study_row.addWidget(self.study_id_combo, 1)
        bids_group_layout.addLayout(bids_study_row)

        bids_button_row = QHBoxLayout()
        bids_button_row.setSpacing(6)
        if self.raw_converter is not None:
            # The primary action in this box -- same explicit-button treatment as the "Fix
            # ..." buttons above, and leftmost for the same reason.
            self.convert_button = QPushButton("Refresh BIDS")
            self.convert_button.setToolTip(wrap_tooltip(self.convert_button_tooltip))
            self.convert_button.setEnabled(False)
            self.convert_button.setMinimumHeight(30)
            self.convert_button.setStyleSheet(
                _primary_action_stylesheet(FIX_ACTION_COLOR, FIX_ACTION_HOVER_COLOR)
            )
            self.convert_button.clicked.connect(self._on_convert_to_bids)
            bids_button_row.addWidget(self.convert_button)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.setToolTip("Pick the top-level BIDS folder to scan for subjects.")
        self.browse_button.clicked.connect(self._on_browse)
        bids_button_row.addWidget(self.browse_button)
        self.reveal_bids_button = QPushButton("Reveal BIDS Folder")
        self.reveal_bids_button.setToolTip(
            wrap_tooltip(
                "Open the BIDS folder in the system file browser, so you can look at what's "
                "actually on disk yourself."
            )
        )
        self.reveal_bids_button.setEnabled(False)
        self.reveal_bids_button.clicked.connect(self._on_reveal_bids_folder)
        bids_button_row.addWidget(self.reveal_bids_button)
        bids_button_row.addStretch(1)
        bids_group_layout.addLayout(bids_button_row)

        bids_summary_row = QHBoxLayout()
        bids_summary_row.setSpacing(6)
        bids_summary_row.addWidget(QLabel("Summary:"))
        self.summary_label = QLabel("")
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        self.summary_label.setWordWrap(True)
        bids_summary_row.addWidget(self.summary_label, 1)
        bids_group_layout.addLayout(bids_summary_row)
        folders_column.addWidget(bids_group)

        top_row.addLayout(folders_column, 1)

        if self.raw_converter is not None:
            # Persistent running log -- beside the folder pickers rather than below the
            # subject detail panes, so it stays visible regardless of which subject is
            # selected (nothing shown here is about any one subject) without eating into
            # that scrollable space. Covers "Refresh BIDS" results plus every plain
            # informational message this window would otherwise pop up as a dialog (saves,
            # restores, auto-saves, ...) -- see `_log_activity`.
            self.activity_log_group = QGroupBox("Activity Log")
            activity_log_layout = QVBoxLayout(self.activity_log_group)
            self.activity_log_text = QTextEdit()
            self.activity_log_text.setReadOnly(True)
            self.activity_log_text.setFont(QFont("Courier New"))
            self.activity_log_text.setPlaceholderText("No activity yet.")
            activity_log_layout.addWidget(self.activity_log_text)
            top_row.addWidget(self.activity_log_group, 1)

        root_layout.addLayout(top_row)

        general_actions_group = QGroupBox("General Actions")
        summary_bar = QHBoxLayout(general_actions_group)
        summary_bar.setSpacing(6)
        self.commit_all_button = QPushButton()
        self.commit_all_button.setToolTip(
            wrap_tooltip(
                "Keeps every pick you've made. Removes every OTHER candidate for it from "
                "BIDS, for every pending pick at once -- still safe in the raw folder, which "
                "this tool never touches, but there's no in-app bulk restore for it; treat "
                "it as permanent, or re-run the raw-to-BIDS setup by hand.\n\n"
                "Picking a candidate alone doesn't remove anything yet -- files stay exactly "
                "where they are until you click this.\n\n"
                "Not the same as removing a whole subject -- that's \"Remove from BIDS\" "
                "below."
            )
        )
        self.commit_all_button.clicked.connect(self._on_commit_all)
        summary_bar.addWidget(self.commit_all_button)
        self._task_tag_supported = any(
            self.extras.task_tag_available(scan_type)
            for scan_type in self.dataset_config.scan_type_names()
        )
        self._refresh_supported = any(
            self.extras.refreshable(scan_type)
            for scan_type in self.dataset_config.scan_type_names()
        )
        self.rename_all_button = QPushButton()
        self.rename_all_button.setToolTip(self._task_tag_tooltip())
        self.rename_all_button.clicked.connect(self._on_rename_all_selected)
        self.rename_all_button.setVisible(self._task_tag_supported)
        summary_bar.addWidget(self.rename_all_button)

        self.save_crosscheck_data_button = QPushButton("Save Crosscheck Data")
        self.save_crosscheck_data_button.setToolTip(
            wrap_tooltip(
                "Copy this BIDS folder's recorded decisions (crosscheck.json, "
                "excluded_subjects.json, and pending picks -- plus any other correction "
                "files this dataset's tool uses) into this app's own local data folder, "
                "keyed to this BIDS folder -- no folder picker needed. Together with your "
                "raw folder (already safe -- this tool never touches it), this is enough to "
                "recreate a fully crosschecked BIDS folder with \"Restore Saved Crosscheck "
                "Data\" if this BIDS folder is ever lost or corrupted -- everything else in "
                "it is either raw data or re-derivable by re-running this tool."
            )
        )
        self.save_crosscheck_data_button.clicked.connect(self._on_save_crosscheck_data)
        summary_bar.addWidget(self.save_crosscheck_data_button)

        self.autosave_checkbox = QCheckBox("Auto-save")
        self.autosave_checkbox.setToolTip(
            wrap_tooltip(
                "Periodically does the same thing as \"Save Crosscheck Data\" above, on its "
                "own, without a popup -- results show up in the Activity Log instead. Needs "
                "a BIDS folder and a study ID set, same as the manual button."
            )
        )
        self.autosave_checkbox.setChecked(
            self._settings.value(AUTOSAVE_ENABLED_SETTINGS_KEY, True, type=bool)
        )
        self.autosave_checkbox.stateChanged.connect(self._on_autosave_settings_changed)
        summary_bar.addWidget(self.autosave_checkbox)

        self.autosave_interval_spinbox = QSpinBox()
        self.autosave_interval_spinbox.setRange(
            MIN_AUTOSAVE_INTERVAL_MINUTES, MAX_AUTOSAVE_INTERVAL_MINUTES
        )
        self.autosave_interval_spinbox.setSuffix(" min")
        self.autosave_interval_spinbox.setToolTip(
            wrap_tooltip("How often auto-save runs, in minutes -- same idea as Word's autosave.")
        )
        self.autosave_interval_spinbox.setValue(
            int(
                self._settings.value(
                    AUTOSAVE_INTERVAL_MINUTES_SETTINGS_KEY, DEFAULT_AUTOSAVE_INTERVAL_MINUTES
                )
            )
        )
        self.autosave_interval_spinbox.valueChanged.connect(self._on_autosave_settings_changed)
        summary_bar.addWidget(self.autosave_interval_spinbox)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._on_autosave_tick)

        self.restore_crosscheck_data_button = QPushButton("Restore Saved Crosscheck Data")
        self.restore_crosscheck_data_button.setToolTip(
            wrap_tooltip(
                "Disaster recovery: puts back any dataset-specific correction files from "
                "this BIDS folder's saved data (see \"Save Crosscheck Data\"), re-imports "
                "this BIDS folder from raw, then automatically replays the saved "
                "crosscheck.json/excluded_subjects.json so every past pick, tag, and "
                "correction is reapplied without redoing it by hand. Only for a BIDS folder "
                "that's empty or was just freshly (re-)created -- not for merging saved data "
                "into one that already has its own, different state."
            )
        )
        self.restore_crosscheck_data_button.setVisible(self.raw_converter is not None)
        self.restore_crosscheck_data_button.setEnabled(False)
        self.restore_crosscheck_data_button.clicked.connect(self._on_restore_saved_crosscheck_data)
        summary_bar.addWidget(self.restore_crosscheck_data_button)

        summary_bar.addStretch(1)
        root_layout.addWidget(general_actions_group)
        self._update_commit_all_button()
        self._update_rename_all_button()
        self._update_crosscheck_data_buttons_enabled()
        self._update_autosave_timer()

        self.progress_bar = QProgressBar()
        self.progress_bar.setFormat("Loading %v / %m subjects...")
        self.progress_bar.setVisible(False)
        root_layout.addWidget(self.progress_bar)

        splitter = QSplitter()
        root_layout.addWidget(splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        self.issues_only_checkbox = QCheckBox("Issues only")
        self.issues_only_checkbox.stateChanged.connect(self._refresh_subject_list)
        left_layout.addWidget(self.issues_only_checkbox)
        self.subject_table = QTableWidget(0, 4)
        self.subject_table.setHorizontalHeaderLabels(["Subject", "Tag", "Datatype", "Info"])
        self.subject_table.horizontalHeaderItem(1).setToolTip(TAG_COLUMN_TOOLTIP)
        self.subject_table.horizontalHeaderItem(2).setToolTip(DATATYPE_COLUMN_TOOLTIP)
        self.subject_table.verticalHeader().setVisible(False)
        self.subject_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.subject_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.subject_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.subject_table.horizontalHeader().setStretchLastSection(True)
        self.subject_table.setColumnWidth(0, 140)
        self.subject_table.setColumnWidth(1, 70)
        self.subject_table.setColumnWidth(2, 90)
        self.subject_table.itemSelectionChanged.connect(self._on_subject_selected)
        left_layout.addWidget(self.subject_table, 1)
        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Persistent, fixed in place regardless of selection -- populated in place by
        # _refresh_subject_actions_group() rather than rebuilt/reinserted on every selection
        # change, so it doesn't appear/disappear/reflow the rest of the window as you click
        # around. Blank (no buttons) when nothing's selected, not hidden.
        self.subject_actions_group = QGroupBox("Subject Actions")
        QHBoxLayout(self.subject_actions_group)
        right_layout.addWidget(self.subject_actions_group)

        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_container = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_container)
        self.detail_layout.addStretch(1)
        self.detail_scroll.setWidget(self.detail_container)
        right_layout.addWidget(self.detail_scroll, 1)

        splitter.addWidget(right_panel)

        splitter.setSizes([500, 700])

    def _on_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select BIDS folder")
        if folder:
            self.load_bids_folder(Path(folder))

    def load_bids_folder(self, bids_folder: Path) -> None:
        self.bids_folder = bids_folder
        self.folder_label.setText(str(bids_folder))
        self.reveal_bids_button.setEnabled(True)
        self._settings.setValue(LAST_BIDS_FOLDER_SETTINGS_KEY, str(bids_folder))
        ensure_bidsignore(bids_folder, self.extras.bidsignore_patterns())
        self.extras.on_bids_folder_changed(bids_folder)
        self._load_study_id_for_current_folder()
        self._rescan(reload_pending=True)
        self._update_convert_button_enabled()

    def _on_browse_raw_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select raw data folder")
        if folder:
            self.raw_folder = Path(folder)
            self.raw_folder_label.setText(str(self.raw_folder))
            self._settings.setValue(LAST_RAW_FOLDER_SETTINGS_KEY, str(self.raw_folder))
            self._update_convert_button_enabled()
            self._update_override_file_label()

    def _on_browse_override_file(self) -> None:
        file, _ = QFileDialog.getOpenFileName(
            self, f"Select {self.override_file_label}", "", self.override_file_filter
        )
        if file:
            self.override_file = Path(file)
            self._update_override_file_label()

    def _on_clear_override_file(self) -> None:
        self.override_file = None
        self._update_override_file_label()

    def _update_override_file_label(self) -> None:
        """Shows the actual file this window is about to use -- either the human's explicit
        pick, or, when nothing's been picked, whatever `override_file_autodetect` currently
        resolves to (marked "(auto-detected)" so it's clear it wasn't a manual choice). A
        bare "(auto-detect)" placeholder alone made it easy to commit to a wrong file
        without ever seeing which one auto-detection actually meant.
        """
        if self.override_file_label is None:
            return
        if self.override_file is not None:
            self.override_file_label_widget.setText(str(self.override_file))
            return
        detected = None
        if self.override_file_autodetect is not None and self.raw_folder is not None:
            try:
                detected = self.override_file_autodetect(self.raw_folder)
            except OSError:
                detected = None
        if detected is not None:
            self.override_file_label_widget.setText(f"{detected}  (auto-detected)")
        elif self.raw_folder is not None:
            self.override_file_label_widget.setText("(auto-detect -- no file found yet)")
        else:
            self.override_file_label_widget.setText("(auto-detect)")

    def _update_convert_button_enabled(self) -> None:
        if self.raw_converter is None:
            return
        both_selected = self.raw_folder is not None and self.bids_folder is not None
        self.convert_button.setEnabled(both_selected)
        for button in self.extra_raw_action_buttons:
            button.setEnabled(both_selected)
        self.reveal_raw_button.setEnabled(self.raw_folder is not None)
        self._update_crosscheck_data_buttons_enabled()

    def _current_study_id(self) -> str:
        return self.study_id_combo.currentText().strip()

    def _known_study_ids(self) -> list[str]:
        """Every study id this app has ever seen, across every BIDS folder -- see
        `KNOWN_STUDY_IDS_SETTINGS_KEY`."""
        raw = self._settings.value(KNOWN_STUDY_IDS_SETTINGS_KEY, "[]")
        try:
            return list(json.loads(raw))
        except (TypeError, ValueError):
            return []

    def _refresh_study_id_combo_items(self) -> None:
        """Repopulates the dropdown from `_known_study_ids()` without disturbing whatever
        text is currently shown -- `addItems`/`clear` don't fire `editingFinished`/
        `activated` (the only signals `study_id_combo` is connected to), so this never
        triggers a spurious save."""
        current_text = self.study_id_combo.currentText()
        self.study_id_combo.clear()
        self.study_id_combo.addItems(self._known_study_ids())
        self.study_id_combo.setCurrentText(current_text)

    def _load_study_id_for_current_folder(self) -> None:
        if self.bids_folder is None:
            return
        self._refresh_study_id_combo_items()
        self.study_id_combo.setCurrentText(load_study_id(self.bids_folder) or "")
        self._update_crosscheck_data_buttons_enabled()

    def _on_study_id_committed(self) -> None:
        study_id = self._current_study_id()
        if self.bids_folder is not None and study_id:
            save_study_id(self.bids_folder, study_id)
            if study_id not in self._known_study_ids():
                known = [*self._known_study_ids(), study_id]
                known.sort(key=str.casefold)
                self._settings.setValue(KNOWN_STUDY_IDS_SETTINGS_KEY, json.dumps(known))
                self._refresh_study_id_combo_items()
        self._update_crosscheck_data_buttons_enabled()

    def _update_crosscheck_data_buttons_enabled(self) -> None:
        """Save/Restore Crosscheck Data both need a study id (see `_crosscheck_data_dir`) --
        Restore additionally needs the raw_converter hook and a raw folder, same as Refresh
        BIDS, since it re-imports from raw before replaying decisions.
        """
        has_study_id = bool(self._current_study_id())
        self.save_crosscheck_data_button.setEnabled(
            self.bids_folder is not None and has_study_id
        )
        self.restore_crosscheck_data_button.setEnabled(
            self.raw_converter is not None
            and self.raw_folder is not None
            and self.bids_folder is not None
            and has_study_id
        )

    def _on_reveal_raw_folder(self) -> None:
        if self.raw_folder is None:
            return
        if not self.raw_folder.is_dir():
            QMessageBox.warning(self, "Folder not found", f"{self.raw_folder} doesn't exist.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.raw_folder)))

    def _on_reveal_bids_folder(self) -> None:
        if self.bids_folder is None:
            return
        if not self.bids_folder.is_dir():
            QMessageBox.warning(self, "Folder not found", f"{self.bids_folder} doesn't exist.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.bids_folder)))

    def _on_extra_raw_action(
        self, callback: Callable[[Path, Path, QWidget], None]
    ) -> None:
        if self.raw_folder is None or self.bids_folder is None:
            return
        callback(self.raw_folder, self.bids_folder, self)

    def _on_convert_to_bids(self) -> None:
        if self.raw_converter is None or self.raw_folder is None or self.bids_folder is None:
            return
        self.convert_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            lines = self.raw_converter(self.raw_folder, self.bids_folder, self.override_file)
            error = None
        except Exception as error_raised:  # noqa: BLE001 -- arbitrary converter, shown not swallowed
            logger.exception("Raw-to-BIDS conversion failed")
            lines = []
            error = str(error_raised)
        finally:
            QApplication.restoreOverrideCursor()
            self.convert_button.setEnabled(True)

        self._update_conversion_status_panel(lines, error)
        if error is None:
            self.load_bids_folder(self.bids_folder)

    def _update_conversion_status_panel(self, lines: list[str], error: str | None) -> None:
        """Logs the outcome of a "Refresh BIDS" run to the Activity Log -- not a popup, so
        it doesn't block on being dismissed, and appended rather than overwritten so an
        earlier run's result (or an unrelated save/restore message) doesn't just vanish."""
        self.last_conversion_log_lines = lines
        if error:
            self._log_activity(f"Refresh BIDS failed:\n{error}", is_error=True)
        else:
            message = "\n".join(lines) if lines else "Finished with nothing to report."
            self._log_activity(f"Refresh BIDS:\n{message}")

    def _log_activity(self, message: str, *, is_error: bool = False) -> None:
        """Appends one timestamped entry to the Activity Log -- the shared home for
        "Refresh BIDS" results and every plain informational message this window used to
        show as a QMessageBox.information popup (saves, restores, auto-saves, ...). Warnings
        and confirmation dialogs stay real popups; only the purely-informational ones moved
        here, so nothing that actually needs an explicit dismissal got silently downgraded.
        """
        if self.raw_converter is None:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"{WARNING_ICON} " if is_error else ""
        if self.activity_log_text.toPlainText():
            self.activity_log_text.append("")
        self.activity_log_text.append(f"[{timestamp}] {prefix}{message}")

    def _rescan(self, reload_pending: bool = False) -> None:
        if self.bids_folder is None:
            return
        self.scan = scan_bids_folder(self.bids_folder, self.dataset_config)
        self._crosschecked = crosschecked_scan_types(self.bids_folder)
        if reload_pending:
            # Replaces self._pending_selections wholesale -- correct both for a fresh folder
            # (nothing stored -> empty) and for reloading the same one (restore what's on disk).
            self._pending_selections = self._resolve_pending_selections(
                load_pending_selections(self.bids_folder)
            )
        self._update_commit_all_button()
        self._update_rename_all_button()
        self._refresh_summary()
        self._refresh_subject_list()

    def _resolve_pending_selections(
        self, stored: dict[str, dict[str, str]]
    ) -> dict[str, dict[str, Path]]:
        """Match persisted {subject_id: {scan_type: filename}} against the current scan.

        A stored filename that no longer matches any current candidate (deleted, renamed
        outside the tool, or the subject/scan-type no longer exists) is silently dropped
        rather than raising -- the persisted pending state is best-effort, not a decision.
        """
        resolved: dict[str, dict[str, Path]] = {}
        if self.scan is None:
            return resolved
        for subject_id, picks in stored.items():
            subject_scans = self.scan.scans.get(subject_id)
            if subject_scans is None:
                continue
            for scan_type, filename in picks.items():
                subject_scan = subject_scans.get(scan_type)
                if subject_scan is None:
                    continue
                match = next((f for f in subject_scan.files if f.name == filename), None)
                if match is not None:
                    resolved.setdefault(subject_id, {})[scan_type] = match
        return resolved

    def _persist_pending_selections(self) -> None:
        if self.bids_folder is None:
            return
        serializable = {
            subject_id: {scan_type: file.name for scan_type, file in picks.items()}
            for subject_id, picks in self._pending_selections.items()
            if picks
        }
        save_pending_selections(self.bids_folder, serializable)

    def _follow_rename_in_pending(
        self, subject_id: str, scan_type: str, old_file: Path, new_file: Path
    ) -> None:
        """Keep a pending (uncommitted) pick pointed at its file after that file gets renamed.

        `_resolve_pending_selections` matches a persisted pick back to a file by filename --
        rename the picked file itself (date-correct or task-tag it before committing) and the
        old filename no longer exists, so the match would otherwise silently fail and the pick
        just vanishes (radio unchecks, "Please select correct file" reappears) even though the
        right file is still sitting right there under its new name.
        """
        if self._pending_selections.get(subject_id, {}).get(scan_type) == old_file:
            self._pending_selections[subject_id][scan_type] = new_file
            self._persist_pending_selections()

    def _follow_id_correction_in_pending(
        self, subject_id: str, corrected_id: str, corrected_folder: Path
    ) -> None:
        """Same idea as `_follow_rename_in_pending`, but for `record_id_correction`: every file
        in the subject's folder can be renamed at once (and the subject_id key itself changes),
        so a pending pick has to be re-keyed and re-pointed rather than just re-pointed."""
        picks = self._pending_selections.pop(subject_id, None)
        if not picks:
            return
        original_token = f"{SUBJECT_FOLDER_PREFIX}{subject_id}"
        corrected_token = f"{SUBJECT_FOLDER_PREFIX}{corrected_id}"
        self._pending_selections[corrected_id] = {
            scan_type: corrected_folder / file.name.replace(original_token, corrected_token)
            for scan_type, file in picks.items()
        }
        self._persist_pending_selections()

    def _refresh_summary(self) -> None:
        if self.scan is None:
            return
        summary = completeness_summary(self.scan, self.dataset_config)
        total = len(self.scan.scans)
        parts = [f"{total} subjects"]
        for scan_type, (ok, scan_total) in summary.items():
            part = f"{scan_type}: {ok}/{scan_total}"
            # Found for every subject -- a positive confirmation worth calling out, not just
            # a fraction to eyeball (e.g. "debrief: 83/83" is easy to misread at a glance as
            # "still missing some" without doing the arithmetic).
            if scan_total and ok == scan_total:
                part += f' <span style="color:{FOUND_EVERYWHERE_COLOR}">✓</span>'
            parts.append(part)
        text = " | ".join(parts)

        # A subject still "needs crosschecking" if any of its scan types hasn't been marked
        # reviewed -- same any-scan-type-flagged rule _subject_has_issues already uses.
        uncrosschecked = sum(
            1
            for subject_id in self.scan.subject_ids()
            if any(
                (subject_id, scan_type) not in self._crosschecked
                for scan_type in self.dataset_config.scan_type_names()
            )
        )
        if uncrosschecked:
            text += (
                f' | <b style="color:{UNCROSSCHECKED_COLOR}">{uncrosschecked} still need '
                "crosschecking</b>"
            )
        self.summary_label.setText(text)

    def _refresh_subject_list(self) -> None:
        if self.scan is None:
            return
        previously_selected = self._selected_subject_ids()
        issues_only = self.issues_only_checkbox.isChecked()
        subject_ids = [
            subject_id
            for subject_id in self.scan.subject_ids()
            # `or subject_id in previously_selected`: an action that resolves a subject's
            # last remaining issue (e.g. tagging its last untagged recording) would otherwise
            # evict it from an Issues-only view mid-action, yanking the selection away right
            # when you're working on it. Keeping it visible while it's still selected means it
            # only drops out of view once you navigate to something else yourself.
            if not issues_only
            or self._subject_has_issues(subject_id)
            or subject_id in previously_selected
        ]

        # Building each row can be slow (e.g. FOH parses every "ok" recording's xdf for its
        # duration/stream indicators). If the window is already on screen, show the Qt progress
        # bar. But the very first load -- auto-restoring the last folder from _restore_last_bids_
        # folder(), called from __init__ before run_bids_crosscheck_app()'s window.show() -- runs
        # while the window is still invisible, so that bar would never be seen; fall back to a
        # terminal rich.Progress bar then, matching the CLIs (e.g. mobi_FOH_assess_data.py).
        self.subject_table.blockSignals(True)
        self.subject_table.setRowCount(0)
        try:
            if self.isVisible():
                self._populate_subject_rows_with_gui_progress(subject_ids)
            else:
                self._populate_subject_rows_with_cli_progress(subject_ids)
        finally:
            self.subject_table.blockSignals(False)
            self.extras.flush()

        self._restore_subject_selection(previously_selected)

    def _populate_subject_rows_with_gui_progress(self, subject_ids: list[str]) -> None:
        self.browse_button.setEnabled(False)
        self.issues_only_checkbox.setEnabled(False)
        self.subject_table.setEnabled(False)
        self.progress_bar.setRange(0, len(subject_ids))
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(bool(subject_ids))
        try:
            for index, subject_id in enumerate(subject_ids, start=1):
                self._add_subject_row(subject_id)
                self.progress_bar.setValue(index)
                QApplication.processEvents()
        finally:
            self.progress_bar.setVisible(False)
            self.subject_table.setEnabled(True)
            self.issues_only_checkbox.setEnabled(True)
            self.browse_button.setEnabled(True)

    def _populate_subject_rows_with_cli_progress(self, subject_ids: list[str]) -> None:
        with Progress() as progress:
            task = progress.add_task("Loading BIDS folder...", total=len(subject_ids))
            for subject_id in subject_ids:
                self._add_subject_row(subject_id)
                progress.advance(task)

    def _add_subject_row(self, subject_id: str) -> None:
        row = self.subject_table.rowCount()
        self.subject_table.insertRow(row)

        id_item = QTableWidgetItem(f"sub-{subject_id}   {self._status_icons(subject_id)}")
        id_item.setData(SUBJECT_ID_ROLE, subject_id)
        id_item.setToolTip(self._status_icon_tooltip())
        self.subject_table.setItem(row, 0, id_item)

        tag_widget = self._build_subject_tag_widget(subject_id)
        self.subject_table.setCellWidget(row, 1, tag_widget)

        datatype_widget = self._build_subject_datatype_widget(subject_id)
        self.subject_table.setCellWidget(row, 2, datatype_widget)

        info_widget = self._build_subject_info_widget(subject_id)
        self.subject_table.setCellWidget(row, 3, info_widget)
        self.subject_table.setRowHeight(row, info_widget.sizeHint().height())

    def _status_icons(self, subject_id: str) -> str:
        pending_for_subject = self._pending_selections.get(subject_id, {})
        icons = []
        for scan_type in self.dataset_config.scan_type_names():
            if (subject_id, scan_type) in self._crosschecked:
                icon = CROSSCHECKED_ICON
            else:
                icon = STATUS_ICON[self.scan.scans[subject_id][scan_type].status]
            if pending_for_subject.get(scan_type) is not None:
                icon += PENDING_ICON
            if self._needs_task_tag(subject_id, scan_type):
                icon += NEEDS_TAG_ICON
            if self._has_candidate_warning(subject_id, scan_type):
                icon += WARNING_ICON
            icons.append(icon)
        icons_text = " ".join(icons)
        if self.dataset_config.dates_in_scans_tsv and self._scans_tsv_has_date_issue(subject_id):
            icons_text += f" {SCANS_TSV_DATE_ISSUE_ICON}"
        return icons_text

    def _scans_tsv_has_date_issue(self, subject_id: str) -> bool:
        """True if any of this subject's scans.tsv rows fails the scans.tsv pane's own
        tick/cross check -- doesn't parse as YYYYMMDDHHMM, or disagrees with the subject's
        other rows (see `_build_scans_tsv_row`). Powers the master subject list's at-a-glance
        SCANS_TSV_DATE_ISSUE_ICON, so a date problem is visible without opening the subject.
        """
        if self.bids_folder is None:
            return False
        rows = list_scans_tsv_rows(self.bids_folder, subject_id)
        if not rows:
            return False
        reference_date = _scans_tsv_reference_date(rows)
        for row in rows:
            parsed = _parse_scans_tsv_date(row.get("acq_time"))
            if parsed is None or (reference_date is not None and parsed != reference_date):
                return True
        return False

    def _status_icon_tooltip(self) -> str:
        tooltip = STATUS_ICON_TOOLTIP
        if self.dataset_config.dates_in_scans_tsv:
            tooltip += (
                f"\n{SCANS_TSV_DATE_ISSUE_ICON} this subject's scans.tsv has a row that "
                "doesn't parse as YYYYMMDDHHMM, or disagrees with its other rows -- see the "
                "scans.tsv pane below"
            )
        return tooltip

    def _has_candidate_warning(self, subject_id: str, scan_type: str) -> bool:
        """True if the file currently in effect for this scan type has a flagged issue.

        Mirrors `_needs_task_tag`: checks the effective candidate only, so a duplicate
        with no pick made yet doesn't get judged before there's anything to judge.
        """
        if self.scan is None:
            return False
        subject_scan = self.scan.scans[subject_id][scan_type]
        file = self._effective_candidate_file(subject_id, scan_type, subject_scan)
        if file is None:
            return False
        return self.extras.has_warning(scan_type, file)

    def _needs_task_tag(self, subject_id: str, scan_type: str) -> bool:
        """True if a file counts as "the one" for this scan type but hasn't been tagged yet.

        Deliberately independent of crosschecked/duplicate status: a subject can be marked
        reviewed, or have only a single "ok" candidate, and still have nobody having confirmed
        it's actually the tagged recording -- this is what makes that omission visible instead
        of silently passing as complete.
        """
        if self.scan is None or not self.extras.task_tag_available(scan_type):
            return False
        subject_scan = self.scan.scans[subject_id][scan_type]
        file = self._effective_candidate_file(subject_id, scan_type, subject_scan)
        if file is None:
            return False
        # Case-insensitive -- see record_task_tag for why (legacy data tagged under a
        # different casing of this marker must still count as tagged).
        return self._task_tag_marker().lower() not in file.stem.lower()

    def _task_tag_marker(self) -> str:
        return f"task-{self.dataset_config.task_tag_task}"

    def _subject_has_issues(self, subject_id: str) -> bool:
        if self.scan.has_issues(subject_id):
            return True
        return any(
            self._needs_task_tag(subject_id, scan_type)
            or self._has_candidate_warning(subject_id, scan_type)
            for scan_type in self.dataset_config.scan_type_names()
        )

    def _build_subject_tag_widget(self, subject_id: str) -> QWidget:
        """One label per tag-eligible scan type showing whether its currently-effective file
        has been tagged yet, and with what -- blank for a scan type that doesn't support
        tagging, or with nothing effective yet (missing, or an unresolved duplicate)."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(4, 2, 4, 2)

        marker = self._task_tag_marker()
        for scan_type in self.dataset_config.scan_type_names():
            if not self.extras.task_tag_available(scan_type):
                continue
            subject_scan = self.scan.scans[subject_id][scan_type]
            file = self._effective_candidate_file(subject_id, scan_type, subject_scan)
            if file is None:
                continue
            tagged = marker.lower() in file.stem.lower()
            tag_label = QLabel()
            tag_label.setTextFormat(Qt.TextFormat.RichText)
            if tagged:
                tag_label.setText(self.dataset_config.task_tag_task)
                tag_label.setToolTip(f"Tagged {self._task_tag_display_marker()!r}.")
            else:
                tag_label.setText(f'<span style="color:{PLEASE_SELECT_COLOR}">✗</span>')
                tag_label.setToolTip(
                    wrap_tooltip(
                        f'Not tagged yet -- click "Tag with {self.dataset_config.task_tag_task} '
                        'BIDS tags" in the recording pane to add it.'
                    )
                )
            row_layout.addWidget(tag_label)

        row_layout.addStretch(1)
        return row

    def _build_subject_datatype_widget(self, subject_id: str) -> QWidget:
        """One label per scan type showing the BIDS datatype folder its currently-effective
        file lives in right now (e.g. "eeg") -- blank for a scan type with nothing effective
        yet (missing, or an unresolved duplicate), *and* for a scan type whose file sits
        directly in the subject's own folder rather than a datatype subfolder underneath it
        (`file.parent.name` would otherwise just repeat "sub-XXX", which isn't a datatype and
        reads as a bug rather than "no datatype folder in use for this dataset yet"). See
        `_datatype_tooltip` for what hovering a value explains."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(4, 2, 4, 2)

        for scan_type in self.dataset_config.scan_type_names():
            subject_scan = self.scan.scans[subject_id][scan_type]
            file = self._effective_candidate_file(subject_id, scan_type, subject_scan)
            if file is None:
                continue
            folder_name = file.parent.name
            if folder_name == f"{SUBJECT_FOLDER_PREFIX}{subject_id}":
                continue
            label = QLabel(folder_name)
            label.setToolTip(self._datatype_tooltip(scan_type, folder_name))
            row_layout.addWidget(label)

        row_layout.addStretch(1)
        return row

    def _datatype_tooltip(self, scan_type: str, folder_name: str) -> str:
        tooltip = f'This recording currently lives in BIDS\'s "{folder_name}" datatype folder.'
        target = self.dataset_config.task_tag_folder_name
        if target and target != folder_name and self.extras.task_tag_available(scan_type):
            target_meaning = BIDS_DATATYPE_NAMES.get(target)
            tooltip += f'\n\nOnce tagged {self._task_tag_display_marker()!r}, it moves to "{target}"'
            if target_meaning:
                tooltip += f" -- BIDS's own term for {target_meaning} data"
            tooltip += "."
        return wrap_tooltip(tooltip)

    def _build_subject_info_widget(self, subject_id: str) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(4, 2, 4, 2)

        pending_for_subject = self._pending_selections.get(subject_id, {})

        for scan_type in self.dataset_config.scan_type_names():
            subject_scan = self.scan.scans[subject_id][scan_type]

            extra_html = None
            extra_tooltip = None
            if subject_scan.status == "missing":
                # Otherwise a completely missing scan type (e.g. no debrief data at all for
                # this subject) shows nothing here -- easy to misread as "nothing to report"
                # rather than "genuinely absent". _build_scan_type_group (the detail pane)
                # already shows "MISSING" for this same case; this is the compact row's
                # equivalent. Plain X (not STATUS_ICON["missing"]'s "○") to read consistently
                # with the ✓/✗ each dataset's own describe() already uses for the "ok" case.
                extra_html = (
                    f'<span style="color:{UNCROSSCHECKED_COLOR}">{scan_type.capitalize()} ✗</span>'
                )
                extra_tooltip = f"No {scan_type} file found for this subject."
            elif subject_scan.status == "ok":
                extra_html = self.extras.describe(scan_type, subject_scan.files[0])
                extra_tooltip = self.extras.describe_tooltip(scan_type, subject_scan.files[0])
            elif subject_scan.status == "duplicate":
                pending_file = pending_for_subject.get(scan_type)
                if pending_file is not None:
                    # Radio-picked but not yet committed (the commit button removes the
                    # non-selected candidate(s) from BIDS) -- preview the pick's info now.
                    # The PENDING_ICON next to the status icon (see _status_icons) is what
                    # signals "not yet saved"; no need to repeat that in text here too.
                    extra_html = self.extras.describe(scan_type, pending_file)
                    extra_tooltip = self.extras.describe_tooltip(scan_type, pending_file)
                else:
                    extra_html = (
                        f'<span style="color:{PLEASE_SELECT_COLOR}">'
                        "Please select correct file</span>"
                    )
                    extra_tooltip = (
                        "Multiple candidate files were found for this subject/scan type -- "
                        "open it and pick the correct one with the radio button."
                    )

            if extra_html:
                extra_label = QLabel(extra_html)
                extra_label.setTextFormat(Qt.TextFormat.RichText)
                if extra_tooltip:
                    extra_label.setToolTip(wrap_tooltip(extra_tooltip))
                row_layout.addWidget(extra_label)

        row_layout.addStretch(1)
        return row

    def _refresh_subject_row(self, subject_id: str) -> None:
        for row in range(self.subject_table.rowCount()):
            item = self.subject_table.item(row, 0)
            if item is not None and item.data(SUBJECT_ID_ROLE) == subject_id:
                item.setText(f"sub-{subject_id}   {self._status_icons(subject_id)}")
                tag_widget = self._build_subject_tag_widget(subject_id)
                self.subject_table.setCellWidget(row, 1, tag_widget)
                datatype_widget = self._build_subject_datatype_widget(subject_id)
                self.subject_table.setCellWidget(row, 2, datatype_widget)
                info_widget = self._build_subject_info_widget(subject_id)
                self.subject_table.setCellWidget(row, 3, info_widget)
                self.subject_table.setRowHeight(row, info_widget.sizeHint().height())
                break

    def _restore_subject_selection(self, previously_selected: list[str]) -> None:
        # selectRow() resolves its selection command from mouse/keyboard modifier state, which
        # doesn't exist in a programmatic call outside a real click -- looping it reliably
        # collapses to just the last row instead of accumulating. Selecting through the model
        # directly, with an explicit Select|Rows flag per row, avoids that ambiguity. And
        # setCurrentCell() itself is no better: it does its own ClearAndSelect internally, so
        # calling it *after* building the multi-row selection would immediately wipe it back
        # down to one row -- setCurrentIndex(..., NoUpdate) moves the cursor without touching
        # the selection already built above.
        self.subject_table.blockSignals(True)
        self.subject_table.clearSelection()
        selection_model = self.subject_table.selectionModel()
        model = self.subject_table.model()
        restored_rows = [
            row
            for row in range(self.subject_table.rowCount())
            if (item := self.subject_table.item(row, 0)) is not None
            and item.data(SUBJECT_ID_ROLE) in previously_selected
        ]
        rows_to_select = restored_rows or ([0] if self.subject_table.rowCount() else [])
        for row in rows_to_select:
            selection_model.select(
                model.index(row, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
        if rows_to_select:
            selection_model.setCurrentIndex(
                model.index(rows_to_select[0], 0), QItemSelectionModel.SelectionFlag.NoUpdate
            )
        self.subject_table.blockSignals(False)
        self._on_subject_selected()

    def _selected_subject_ids(self) -> list[str]:
        ids = []
        for index in self.subject_table.selectionModel().selectedRows():
            item = self.subject_table.item(index.row(), 0)
            if item is not None:
                ids.append(item.data(SUBJECT_ID_ROLE))
        return ids

    def _on_subject_selected(self) -> None:
        subject_ids = self._selected_subject_ids()
        self._render_detail(subject_ids)
        self._refresh_subject_actions_group(subject_ids)

    def _clear_detail_layout(self) -> None:
        # takeAt() only detaches the item from layout *management* -- the widget stays a
        # visible child of detail_container until deleteLater()'s queued event actually runs,
        # which isn't guaranteed before the next render. setParent(None) removes it from the
        # visible tree immediately, so stale content (e.g. "Pick one:" for a scan type that's
        # since been resolved) can't linger on screen.
        while self.detail_layout.count() > 1:
            item = self.detail_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

    def _render_detail(self, subject_ids: list[str]) -> None:
        self._clear_detail_layout()
        self.detail_extra_layout = None
        if len(subject_ids) == 1 and self.scan is not None:
            self._render_single_subject_detail(subject_ids[0])

    def _render_single_subject_detail(self, subject_id: str) -> None:
        self._pending_selections.setdefault(subject_id, {})
        for scan_type in self.dataset_config.scan_type_names():
            subject_scan = self.scan.scans[subject_id][scan_type]
            self.detail_layout.insertWidget(
                self.detail_layout.count() - 1,
                self._build_scan_type_group(subject_id, subject_scan),
            )

        if self.dataset_config.dates_in_scans_tsv:
            scans_tsv_group = self._build_scans_tsv_group(subject_id)
            if scans_tsv_group is not None:
                self.detail_layout.insertWidget(self.detail_layout.count() - 1, scans_tsv_group)

        detail_extra_container = QWidget()
        self.detail_extra_layout = QVBoxLayout(detail_extra_container)
        self.detail_extra_layout.setContentsMargins(0, 8, 0, 0)
        self.detail_layout.insertWidget(self.detail_layout.count() - 1, detail_extra_container)
        self._refresh_selected_detail(subject_id)

    def _refresh_selected_detail(self, subject_id: str) -> None:
        if self.detail_extra_layout is None or self.scan is None:
            return
        while self.detail_extra_layout.count():
            item = self.detail_extra_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        for scan_type in self.dataset_config.scan_type_names():
            subject_scan = self.scan.scans[subject_id][scan_type]
            file = self._effective_candidate_file(subject_id, scan_type, subject_scan)
            if file is None:
                continue
            detail_html = self.extras.detail(scan_type, file)
            if not detail_html:
                continue
            detail_label = QLabel(detail_html)
            detail_label.setTextFormat(Qt.TextFormat.RichText)
            detail_label.setWordWrap(True)
            self.detail_extra_layout.addWidget(detail_label)

    def _update_commit_all_button(self) -> None:
        total_pending = sum(len(picks) for picks in self._pending_selections.values())
        if total_pending:
            plural = "s" if total_pending != 1 else ""
            self.commit_all_button.setText(
                f"Remove non selected files from BIDS ({total_pending} pick{plural})"
            )
            self.commit_all_button.setStyleSheet(f"font-weight: bold; color: {PENDING_COLOR};")
        else:
            self.commit_all_button.setText("Remove non selected files from BIDS")
            self.commit_all_button.setStyleSheet("")
        self.commit_all_button.setEnabled(bool(total_pending))

    def _effective_candidate_file(
        self, subject_id: str, scan_type: str, subject_scan: SubjectScan
    ) -> Path | None:
        """The file currently in effect for this scan type: the sole "ok" file, or whichever
        candidate is radio-picked (possibly still pending commit) for a duplicate."""
        if subject_scan.status == "ok":
            return subject_scan.files[0]
        if subject_scan.status == "duplicate":
            return self._pending_selections.get(subject_id, {}).get(scan_type)
        return None

    def _pending_task_tag_file(self, subject_id: str, scan_type: str) -> Path | None:
        if self.scan is None or not self.extras.task_tag_available(scan_type):
            return None
        subject_scan = self.scan.scans[subject_id][scan_type]
        file = self._effective_candidate_file(subject_id, scan_type, subject_scan)
        if file is None:
            return None
        if self._task_tag_marker().lower() in file.stem.lower():
            return None
        return file

    def _rename_all_candidates(self) -> list[tuple[str, str, Path]]:
        if self.scan is None:
            return []
        candidates = []
        for subject_id in self.scan.subject_ids():
            for scan_type in self.dataset_config.scan_type_names():
                file = self._pending_task_tag_file(subject_id, scan_type)
                if file is not None:
                    candidates.append((subject_id, scan_type, file))
        return candidates

    def _update_rename_all_button(self) -> None:
        if not self._task_tag_supported:
            return
        task = self.dataset_config.task_tag_task
        pending = len(self._rename_all_candidates())
        if pending:
            plural = "s" if pending != 1 else ""
            self.rename_all_button.setText(
                f"Tag all selected with {task} BIDS tags ({pending} file{plural})"
            )
            self.rename_all_button.setStyleSheet(f"font-weight: bold; color: {PENDING_COLOR};")
        else:
            self.rename_all_button.setText(f"Tag all selected with {task} BIDS tags")
            self.rename_all_button.setStyleSheet("")
        self.rename_all_button.setEnabled(bool(pending))

    def _record_task_tag_for(self, subject_id: str, scan_type: str, file: Path) -> Path:
        return record_task_tag(
            self.bids_folder,
            subject_id,
            scan_type,
            file,
            self.dataset_config.task_tag_task,
            self.dataset_config.task_tag_suffix,
            self.dataset_config.task_tag_acq,
            self.dataset_config.task_tag_folder_name,
        )

    def _on_rename_all_selected(self) -> None:
        if self.bids_folder is None:
            return
        candidates = self._rename_all_candidates()
        if not candidates:
            return
        task = self.dataset_config.task_tag_task
        subject_count = len({subject_id for subject_id, _scan_type, _file in candidates})
        confirm = QMessageBox.question(
            self,
            f"Tag all selected with {task} BIDS tags",
            f"This will add real BIDS {self._task_tag_display_marker()!r} tags to "
            f"{len(candidates)} file(s) across {subject_count} subject(s). This cannot be "
            "undone from within this tool. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        errors = []
        for subject_id, scan_type, file in candidates:
            try:
                destination = self._record_task_tag_for(subject_id, scan_type, file)
                self._follow_rename_in_pending(subject_id, scan_type, file, destination)
            except (BidsCrosscheckError, OSError) as error:
                errors.append(f"{file.name}: {error}")
        if errors:
            QMessageBox.warning(self, "Some files could not be renamed", "\n".join(errors))
        # reload_pending=True: a renamed file that was someone's pending duplicate-pick would
        # otherwise leave a dangling Path in self._pending_selections -- see
        # _on_rename_selected_to_task_label for the crash that caused when this was missed.
        self._rescan(reload_pending=True)

    def _on_restore_subjects_from_bids(self, subject_ids: list[str]) -> None:
        """Undo a committed duplicate pick for just `subject_ids`, leaving every other
        subject's decisions untouched -- see `restore_subjects_from_bids`."""
        if self.bids_folder is None or not subject_ids:
            return
        title = "Restore from raw" if len(subject_ids) == 1 else "Restore selected from raw"
        confirm = QMessageBox.question(
            self,
            title,
            "This will undo the committed duplicate pick for: "
            f"{', '.join(f'sub-{s}' for s in subject_ids)}. Nothing is moved back -- this "
            "clears the bookkeeping so the next Refresh BIDS re-derives their whole record "
            "fresh from the raw folder; run that afterward to actually get the data back. "
            "Any other correction already made for them (date fixes, crosschecked marks) "
            "goes with it too. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        restored, errors = restore_subjects_from_bids(self.bids_folder, subject_ids)
        if errors:
            QMessageBox.warning(self, "Some subjects could not be restored", "\n".join(errors))
        elif not restored:
            self._log_activity(
                "Nothing to restore -- none of the selected subject(s) have a committed "
                "duplicate pick to undo."
            )
        self._rescan(reload_pending=True)

    def _crosscheck_data_dir(self, study_id: str) -> Path:
        """Where "Save Crosscheck Data"/"Restore Saved Crosscheck Data" read and write --
        the app's own standard local-data location, named after `study_id` (see the "Study
        ID" field beside the BIDS folder path) rather than the folder's own path, so the
        saved copy stays findable and identifiable by a human even if the BIDS folder itself
        later moves. Keyed by this app's own name too (`self._settings`' app name, e.g.
        "CraneBidsCrosscheck"), so FOH and crane never collide even if someone reuses the
        same study id for both.
        """
        app_data_location = QStandardPaths.StandardLocation.AppDataLocation
        app_data_root = Path(QStandardPaths.writableLocation(app_data_location))
        return (
            app_data_root
            / SETTINGS_ORGANIZATION
            / self._settings.applicationName()
            / CROSSCHECK_DATA_BACKUP_DIRNAME
            / _sanitize_for_filesystem(study_id)
        )

    def _save_crosscheck_data(self, study_id: str) -> tuple[list[Path], Path]:
        """Copies this BIDS folder's recorded decisions into its crosscheck data folder --
        the shared core of both the manual "Save Crosscheck Data" button and the periodic
        auto-save timer (see `_on_save_crosscheck_data`/`_on_autosave_tick`). Caller is
        responsible for checking `self.bids_folder`/`study_id` first.
        """
        destination = self._crosscheck_data_dir(study_id)
        destination.mkdir(parents=True, exist_ok=True)
        copied = backup_decisions(self.bids_folder, destination, self.extra_backup_filenames)
        return copied, destination

    def _on_save_crosscheck_data(self) -> None:
        if self.bids_folder is None:
            return
        study_id = self._current_study_id()
        if not study_id:
            QMessageBox.warning(self, "No study ID set", "Enter a study ID above before saving.")
            return
        copied, destination = self._save_crosscheck_data(study_id)
        if not copied:
            self._log_activity("Nothing to save -- no crosscheck records exist yet for this BIDS folder.")
            return
        self._log_activity(f"Saved crosscheck data: copied {len(copied)} file(s) to {destination}.")

    def _on_autosave_settings_changed(self) -> None:
        self._settings.setValue(
            AUTOSAVE_ENABLED_SETTINGS_KEY, self.autosave_checkbox.isChecked()
        )
        self._settings.setValue(
            AUTOSAVE_INTERVAL_MINUTES_SETTINGS_KEY, self.autosave_interval_spinbox.value()
        )
        self._update_autosave_timer()

    def _update_autosave_timer(self) -> None:
        self._autosave_timer.stop()
        if self.autosave_checkbox.isChecked():
            self._autosave_timer.start(self.autosave_interval_spinbox.value() * 60_000)

    def _on_autosave_tick(self) -> None:
        if self.bids_folder is None:
            return
        study_id = self._current_study_id()
        if not study_id:
            return
        copied, destination = self._save_crosscheck_data(study_id)
        if copied:
            self._log_activity(f"Auto-saved crosscheck data: {len(copied)} file(s) to {destination}.")

    def _on_restore_saved_crosscheck_data(self) -> None:
        """Disaster recovery: re-import from raw, then replay this BIDS folder's saved
        crosscheck.json/excluded_subjects.json (see `_on_save_crosscheck_data`) onto the
        fresh import -- see `rebuild_from_raw`. Requires the same raw_converter hook
        "Refresh BIDS" already uses, so it's only offered when that's configured.
        """
        if self.raw_converter is None or self.raw_folder is None or self.bids_folder is None:
            return
        study_id = self._current_study_id()
        if not study_id:
            QMessageBox.warning(self, "No study ID set", "Enter a study ID above before restoring.")
            return
        backup_folder = self._crosscheck_data_dir(study_id)
        decisions = load_decisions(backup_folder)
        excluded = load_excluded_subjects(backup_folder)
        if not decisions and not excluded:
            QMessageBox.warning(
                self,
                "No saved crosscheck data found",
                "No crosscheck data has been saved for this BIDS folder yet -- use "
                '"Save Crosscheck Data" first.',
            )
            return

        confirm = QMessageBox.question(
            self,
            "Restore saved crosscheck data",
            "This re-imports this BIDS folder from raw, then replays every saved decision "
            f"from {backup_folder} -- picks, tags, and corrections alike -- to reconstruct "
            "the same crosschecked state, without redoing it by hand. Only use this on a "
            "BIDS folder that's empty or was just freshly created -- it isn't a merge into "
            "one that already has its own, different state. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            # Dataset-specific pre-conversion correction files (e.g. crane's debrief/raw-
            # filename id corrections) must already be in place *before* the converter runs,
            # so the next conversion resolves ids the same way it originally did -- unlike
            # crosscheck.json's decisions, which are replayed afterward.
            restore_backup_files(backup_folder, self.bids_folder, self.extra_backup_filenames)
            self.raw_converter(self.raw_folder, self.bids_folder, self.override_file)
            resolved, unresolved = rebuild_from_raw(self.bids_folder, decisions, excluded)
        except Exception as error_raised:  # noqa: BLE001 -- arbitrary converter, shown not swallowed
            logger.exception("Restore from saved crosscheck data failed")
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Restore failed", str(error_raised))
            return
        QApplication.restoreOverrideCursor()

        if unresolved:
            QMessageBox.warning(
                self,
                "Restore finished with some items unresolved",
                f"Reapplied {len(resolved)} decision(s). {len(unresolved)} could not be "
                "auto-replayed and need a manual look:\n\n" + "\n".join(unresolved),
            )
        else:
            self._log_activity(f"Restore complete: reapplied {len(resolved)} decision(s) from saved data.")
        self.load_bids_folder(self.bids_folder)

    def _build_scan_type_group(self, subject_id: str, subject_scan: SubjectScan) -> QGroupBox:
        file_word = "file" if len(subject_scan.files) == 1 else "files"
        group = QGroupBox(f"{subject_scan.scan_type} ({len(subject_scan.files)} {file_word})")
        layout = QVBoxLayout(group)

        if subject_scan.status == "missing":
            layout.addWidget(QLabel("MISSING"))
        elif subject_scan.status == "ok":
            layout.addWidget(
                self._build_candidate_row(
                    subject_id, subject_scan.scan_type, subject_scan.files[0], None
                )
            )
        else:
            layout.addWidget(QLabel("Pick one:"))
            radio_group = QButtonGroup(group)
            for file in subject_scan.files:
                layout.addWidget(
                    self._build_candidate_row(subject_id, subject_scan.scan_type, file, radio_group)
                )

        return group

    def _build_candidate_row(
        self, subject_id: str, scan_type: str, file: Path, radio_group: QButtonGroup | None
    ) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)

        if radio_group is not None:
            radio = QRadioButton(file.name)
            pending = self._pending_selections.get(subject_id, {}).get(scan_type)
            radio.setChecked(pending == file)
            radio.toggled.connect(
                lambda checked, f=file: self._on_candidate_picked(subject_id, scan_type, f, checked)
            )
            radio_group.addButton(radio)
            row_layout.addWidget(radio)
            # Only the picked candidate counts as "the one" -- renaming/date-correcting one of
            # its still-unresolved duplicate siblings would silently act on a file nobody's
            # confirmed is correct, so those buttons aren't shown until this row is the pick.
            is_effective_candidate = pending == file
        else:
            row_layout.addWidget(QLabel(f"✓ {file.name}"))
            is_effective_candidate = True

        extra_text = self.extras.describe(scan_type, file)
        if extra_text:
            extra_label = QLabel(extra_text)
            extra_label.setTextFormat(Qt.TextFormat.RichText)
            extra_tooltip = self.extras.describe_tooltip(scan_type, file)
            if extra_tooltip:
                extra_label.setToolTip(wrap_tooltip(extra_tooltip))
            row_layout.addWidget(extra_label)

        reveal_button = QPushButton("Reveal subject folder")
        reveal_button.setToolTip(
            wrap_tooltip(
                "Open this subject's folder in the system file browser, so you can look at "
                "the raw files yourself."
            )
        )
        reveal_button.clicked.connect(lambda: self._on_reveal_subject_folder(subject_id))
        row_layout.addWidget(reveal_button)

        if is_effective_candidate:
            date_button = QPushButton("Correct date...")
            if self.dataset_config.dates_in_scans_tsv:
                date_tooltip = (
                    "Rewrite this file's acquisition date in scans.tsv if it doesn't match "
                    "when the recording actually happened."
                )
            else:
                date_tooltip = (
                    "Rewrite this file's leading date prefix (the part before the first '_') "
                    "if it doesn't match when the recording actually happened."
                )
            date_button.setToolTip(wrap_tooltip(date_tooltip))
            date_button.clicked.connect(lambda: self._on_correct_date(subject_id, scan_type, file))
            row_layout.addWidget(date_button)

            if self.extras.task_tag_available(scan_type):
                task = self.dataset_config.task_tag_task
                tagged = self._task_tag_marker().lower() in file.stem.lower()
                task_button = QPushButton(
                    f"Remove {task} BIDS tags" if tagged else f"Tag with {task} BIDS tags"
                )
                if tagged:
                    tooltip = (
                        f"Remove the {self._task_tag_display_marker()!r} tag from this file's "
                        "name -- use this if it was tagged by mistake."
                    )
                else:
                    tooltip = (
                        f"Rename this file to add a real BIDS {self._task_tag_display_marker()!r} "
                        f"tag, replacing whatever free text the collection software left after "
                        f"run-<NNN> with the real {self.dataset_config.task_tag_suffix!r} suffix."
                    )
                    target = self.dataset_config.task_tag_folder_name
                    if target:
                        target_meaning = BIDS_DATATYPE_NAMES.get(target)
                        tooltip += f' Also moves it into the "{target}" datatype folder'
                        if target_meaning:
                            tooltip += f" ({target_meaning})"
                        tooltip += "."
                task_button.setToolTip(wrap_tooltip(tooltip))
                task_button.clicked.connect(
                    lambda: self._on_task_tag(subject_id, scan_type, file, tagged)
                )
                row_layout.addWidget(task_button)

            if self.extras.filename_correction_available(scan_type):
                filename_button = QPushButton("Correct filename...")
                filename_button.setToolTip(
                    wrap_tooltip(
                        "Rename this file directly -- fixes any part of it (a wrong "
                        "task-/acq- entity, a stray \"-dupN\" collision marker, ...) that "
                        "the more specific correction buttons here don't cover."
                    )
                )
                filename_button.clicked.connect(
                    lambda: self._on_correct_filename(subject_id, scan_type, file)
                )
                row_layout.addWidget(filename_button)

        row_layout.addStretch(1)
        return row

    def _build_scans_tsv_group(self, subject_id: str) -> QGroupBox | None:
        """`scans.tsv` sidecar pane: every row (filename, acq_time) this subject's sidecar
        currently tracks -- not just the one file "Correct date..." can reach per scan type
        above, since a scans.tsv can outlive a resolved duplicate or list a file that's since
        stopped matching any scan type's glob. Each row gets a green tick if its acq_time
        parses as YYYYMMDDHHMM *and* agrees with the subject's other rows, a red cross
        otherwise (unparseable, or disagrees) -- see `_build_scans_tsv_row`. None if this
        subject has no scans.tsv yet (e.g. not converted).
        """
        rows = list_scans_tsv_rows(self.bids_folder, subject_id)
        if rows is None:
            return None

        row_word = "row" if len(rows) == 1 else "rows"
        group = QGroupBox(f"scans.tsv ({len(rows)} {row_word})")
        layout = QVBoxLayout(group)

        reference_date = _scans_tsv_reference_date(rows)

        for row in rows:
            layout.addWidget(self._build_scans_tsv_row(subject_id, row, reference_date))

        return group

    def _build_scans_tsv_row(
        self, subject_id: str, row: dict[str, str], reference_date: datetime | None
    ) -> QWidget:
        relative_filename = row.get("filename", "")
        raw_date = row.get("acq_time", "")
        parsed = _parse_scans_tsv_date(raw_date)
        if parsed is None:
            icon, color = "✗", UNCROSSCHECKED_COLOR
            tooltip = f"{raw_date or '(empty)'!r} doesn't parse as YYYYMMDDHHMM"
        elif reference_date is not None and parsed != reference_date:
            icon, color = "✗", UNCROSSCHECKED_COLOR
            tooltip = (
                f"{raw_date} doesn't match this subject's other scans.tsv rows "
                f"({reference_date.strftime(SCANS_TSV_DATE_FORMAT)})"
            )
        else:
            icon, color = "✓", FOUND_EVERYWHERE_COLOR
            tooltip = "Parses as YYYYMMDDHHMM and matches this subject's other rows"

        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)

        status_label = QLabel(icon)
        status_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        status_label.setToolTip(tooltip)
        row_layout.addWidget(status_label)

        text_label = QLabel(f"{relative_filename}  —  {raw_date or '(empty)'}")
        text_label.setToolTip(tooltip)
        row_layout.addWidget(text_label, 1)

        edit_button = QPushButton("Edit date...")
        edit_button.setToolTip(
            wrap_tooltip(
                "Correct this row's acquisition date -- type YYYYMMDDHHMM directly, use the "
                "calendar button to pick it, or click Today."
            )
        )
        edit_button.clicked.connect(
            lambda: self._on_edit_scans_tsv_date(subject_id, relative_filename, raw_date)
        )
        row_layout.addWidget(edit_button)

        return row_widget

    def _on_edit_scans_tsv_date(
        self, subject_id: str, relative_filename: str, current_date: str
    ) -> None:
        if self.bids_folder is None:
            return
        dialog = ScansTsvDateCorrectionDialog(relative_filename, current_date, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        corrected_date = dialog.corrected_date()
        if corrected_date == current_date:
            return
        try:
            record_scans_tsv_row_date_correction(
                self.bids_folder, subject_id, relative_filename, corrected_date
            )
        except BidsCrosscheckError as error:
            QMessageBox.warning(self, "Could not correct date", str(error))
            return
        self._rescan()

    def _build_subject_crosscheck_widget(self, subject_id: str) -> QWidget:
        """One "Mark/Un-mark crosschecked" control covering every scan type for one subject
        at once.

        Crosschecked status (self._crosschecked) is still recorded per (subject_id,
        scan_type) underneath -- this is a single-subject convenience over toggling every
        scan type in one click (previously one button per scan type here; for a dataset with
        several scan types, like crane's physiology/behaviour/debrief, reviewing a subject is
        one decision, not one per scan type). Bulk multi-subject crosscheck already covers
        every scan type this same way (see `_on_bulk_crosschecked`); this is that same
        semantics for a single subject, without the bulk-action confirmation dialog.
        """
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        scan_types = self.dataset_config.scan_type_names()
        all_crosschecked = all(
            (subject_id, scan_type) in self._crosschecked for scan_type in scan_types
        )
        crosscheck_button = QPushButton(
            "Un-mark crosschecked" if all_crosschecked else "Mark crosschecked"
        )
        crosscheck_button.setToolTip(
            wrap_tooltip(
                "Remove the manual reviewed mark, for every scan type."
                if all_crosschecked
                else "Manually mark this subject as reviewed for every scan type at once, "
                "independent of its automatic ok/missing/duplicate status."
            )
        )
        crosscheck_button.clicked.connect(
            lambda: self._on_toggle_subject_crosschecked(subject_id, not all_crosschecked)
        )
        if not all_crosschecked:
            # Primary action -- same treatment as the group selection's "Mark selected
            # crosschecked" button. Un-marking (the other state) stays plain/secondary,
            # same rule the group version follows.
            crosscheck_button.setMinimumHeight(34)
            crosscheck_button.setStyleSheet(
                _primary_action_stylesheet(FOUND_EVERYWHERE_COLOR, CROSSCHECK_PRIMARY_HOVER_COLOR)
            )
        layout.addWidget(crosscheck_button)
        if all_crosschecked:
            crosschecked_label = QLabel(
                f'<span style="color:#3498db">{CROSSCHECKED_ICON} Crosschecked</span>'
            )
            crosschecked_label.setTextFormat(Qt.TextFormat.RichText)
            layout.addWidget(crosschecked_label)

        return container

    def _refresh_subject_actions_group(self, subject_ids: list[str]) -> None:
        """Repopulate the persistent Subject actions panel in place for the current selection.

        The panel itself (self.subject_actions_group) is built once in _build_ui() and never
        removed from the layout -- only its contents change here, so it doesn't appear,
        disappear, or shift the rest of the window around as the selection changes. Nothing
        selected: left blank. One subject: the actions below apply to it directly. Several:
        the same actions apply across all of them at once. Either way, *which* candidate file
        is correct for a subject with unresolved duplicates stays the recording pane's job
        above -- bulk actions here only ever touch a subject's already-effective candidate,
        never pick one.
        """
        layout = self.subject_actions_group.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

        if not subject_ids:
            self.subject_actions_group.setTitle("Subject Actions")
            return
        if len(subject_ids) == 1:
            self.subject_actions_group.setTitle(
                f"Subject Actions  —  {SUBJECT_FOLDER_PREFIX}{subject_ids[0]}"
            )
        else:
            self.subject_actions_group.setTitle(
                f"Group Actions  —  {len(subject_ids)} subjects selected"
            )

        pending_subject_ids = [s for s in subject_ids if self._pending_selections.get(s)]
        pending_count = sum(len(self._pending_selections[s]) for s in pending_subject_ids)
        commit_label = (
            "Remove non-selected files from BIDS"
            if len(subject_ids) == 1
            else "Remove non-selected files from BIDS for selected"
        )
        if pending_count:
            plural = "s" if pending_count != 1 else ""
            commit_label += f" ({pending_count} pending pick{plural})"
        commit_button = QPushButton(commit_label)
        commit_button.setToolTip(
            wrap_tooltip(
                "Keeps the candidate you picked above. Removes every OTHER candidate from "
                "BIDS -- still safe in the raw folder, which this tool never touches, but "
                "there's no in-app bulk restore for it; treat it as permanent, or re-run "
                "the raw-to-BIDS setup by hand.\n\n"
                "Picking a candidate alone doesn't remove anything yet -- files stay "
                "exactly where they are until you click this.\n\n"
                "Not the same as removing a whole subject -- that's \"Remove from BIDS\" "
                "below."
            )
        )
        commit_button.clicked.connect(lambda: self._on_commit_selected(subject_ids))
        commit_button.setEnabled(bool(pending_subject_ids))
        if pending_count:
            commit_button.setStyleSheet(f"font-weight: bold; color: {PENDING_COLOR};")
        layout.addWidget(commit_button)

        if self._refresh_supported:
            refresh_button = QPushButton("Refresh")
            refresh_button.setToolTip(
                wrap_tooltip(
                    "Re-read the effective candidate's info from disk, ignoring the cached "
                    "copy."
                )
            )
            refresh_button.clicked.connect(lambda: self._on_refresh_subjects(subject_ids))
            layout.addWidget(refresh_button)

        if len(subject_ids) == 1:
            subject_id = subject_ids[0]
            rename_button = QPushButton("Rename subject ID...")
            rename_button.setToolTip(
                wrap_tooltip(
                    "Correct this subject's ID -- renames the sub-<id> folder and every "
                    "file inside it to use the new ID."
                )
            )
            rename_button.clicked.connect(lambda: self._on_rename_subject(subject_id))
            layout.addWidget(rename_button)
        else:
            if self._task_tag_supported:
                task = self.dataset_config.task_tag_task
                bulk_rename_button = QPushButton(f"Tag selected with {task} BIDS tags")
                bulk_rename_button.setToolTip(
                    wrap_tooltip(
                        f"Add real BIDS {self._task_tag_display_marker()!r} tags to every "
                        "selected subject's currently effective recording, skipping any "
                        "that still need a duplicate resolved first."
                    )
                )
                bulk_rename_button.clicked.connect(
                    lambda: self._on_rename_selected_to_task_label(subject_ids)
                )
                layout.addWidget(bulk_rename_button)

            bulk_uncrosscheck_button = QPushButton("Un-mark selected crosschecked")
            bulk_uncrosscheck_button.setToolTip(
                wrap_tooltip(
                    "Remove the manual reviewed mark from every selected subject, for "
                    "every scan type."
                )
            )
            bulk_uncrosscheck_button.clicked.connect(
                lambda: self._on_bulk_crosschecked(subject_ids, False)
            )
            layout.addWidget(bulk_uncrosscheck_button)

        restore_label = (
            "Restore from raw..." if len(subject_ids) == 1 else "Restore selected from raw..."
        )
        restore_button = QPushButton(restore_label)
        restore_button.setToolTip(
            wrap_tooltip(
                "Undoes a committed duplicate pick for just this subject (or each selected "
                "subject), so the next Refresh BIDS re-derives their whole record fresh from "
                "the raw folder -- any other correction already made for them (date fixes, "
                "crosschecked marks) goes with it. Nothing to do here for a subject that was "
                "never deduped, and no help for a subject removed entirely -- there's no "
                "in-app bulk restore for that; re-run the raw-to-BIDS setup by hand."
            )
        )
        restore_button.clicked.connect(lambda: self._on_restore_subjects_from_bids(subject_ids))
        layout.addWidget(restore_button)

        remove_label = (
            "Remove Subject Folder from BIDS..."
            if len(subject_ids) == 1
            else "Remove selected from BIDS..."
        )
        remove_button = QPushButton(remove_label)
        remove_button.setToolTip(
            wrap_tooltip(
                "Deletes the whole subject folder from BIDS -- e.g. a pilot run, a "
                "non-participant, a test recording. Still safe in the raw folder, which this "
                "tool never touches, but there's no in-app bulk restore for it; treat it as "
                "permanent, or re-run the raw-to-BIDS setup by hand. Lets you record why, so "
                "it stays auditable."
            )
        )
        remove_button.clicked.connect(lambda: self._on_remove_subjects_from_bids(subject_ids))
        layout.addWidget(remove_button)

        layout.addStretch(1)

        if len(subject_ids) > 1:
            # The clear primary action for a group selection: bigger, filled, and pinned to
            # the far right of the row (the stretch above pushes it there) -- everything else
            # in this row, un-marking included, stays plain/default-styled so this is the one
            # thing that reads as "the main thing to do here."
            bulk_crosscheck_button = QPushButton("Mark selected crosschecked")
            bulk_crosscheck_button.setToolTip(
                wrap_tooltip(
                    "Manually mark every selected subject as reviewed, for every scan type."
                )
            )
            bulk_crosscheck_button.clicked.connect(
                lambda: self._on_bulk_crosschecked(subject_ids, True)
            )
            bulk_crosscheck_button.setMinimumHeight(34)
            bulk_crosscheck_button.setStyleSheet(
                _primary_action_stylesheet(FOUND_EVERYWHERE_COLOR, CROSSCHECK_PRIMARY_HOVER_COLOR)
            )
            layout.addWidget(bulk_crosscheck_button)
        else:
            # Same placement/treatment as the group version above, for the single-subject
            # case -- see _build_subject_crosscheck_widget.
            layout.addWidget(self._build_subject_crosscheck_widget(subject_ids[0]))

    def _effective_candidates_for(self, subject_ids: list[str]) -> list[tuple[str, str, Path]]:
        """(subject_id, scan_type, file) for every selected subject's effective candidate.

        Skips any subject/scan-type still stuck on an unresolved duplicate -- same rule
        `_refresh_subject_actions_group` documents: bulk actions never pick a candidate.
        """
        if self.scan is None:
            return []
        result = []
        for subject_id in subject_ids:
            for scan_type in self.dataset_config.scan_type_names():
                subject_scan = self.scan.scans[subject_id][scan_type]
                file = self._effective_candidate_file(subject_id, scan_type, subject_scan)
                if file is not None:
                    result.append((subject_id, scan_type, file))
        return result

    def _on_refresh_subjects(self, subject_ids: list[str]) -> None:
        for _subject_id, scan_type, file in self._effective_candidates_for(subject_ids):
            self.extras.refresh(scan_type, file)
        self.extras.flush()
        self._rescan()

    def _on_rename_selected_to_task_label(self, subject_ids: list[str]) -> None:
        if self.bids_folder is None:
            return
        task = self.dataset_config.task_tag_task
        selected = set(subject_ids)
        candidates = [
            (subject_id, scan_type, file)
            for subject_id, scan_type, file in self._rename_all_candidates()
            if subject_id in selected
        ]
        if not candidates:
            return
        confirm = QMessageBox.question(
            self,
            f"Tag selected with {task} BIDS tags",
            f"This will add real BIDS {self._task_tag_display_marker()!r} tags to "
            f"{len(candidates)} file(s) across {len(selected)} selected subject(s). This "
            "cannot be undone from within this tool. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        errors = []
        for subject_id, scan_type, file in candidates:
            try:
                destination = self._record_task_tag_for(subject_id, scan_type, file)
                self._follow_rename_in_pending(subject_id, scan_type, file, destination)
            except (BidsCrosscheckError, OSError) as error:
                errors.append(f"{file.name}: {error}")
        if errors:
            QMessageBox.warning(self, "Some files could not be renamed", "\n".join(errors))
        # reload_pending=True -- see _on_rename_all_selected for why.
        self._rescan(reload_pending=True)

    def _on_bulk_crosschecked(self, subject_ids: list[str], crosschecked: bool) -> None:
        if self.bids_folder is None:
            return
        verb = "mark" if crosschecked else "un-mark"
        confirm = QMessageBox.question(
            self,
            f"{verb.capitalize()} selected crosschecked",
            f"This will {verb} {len(subject_ids)} selected subject(s) as crosschecked, for "
            "every scan type. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        for subject_id in subject_ids:
            for scan_type in self.dataset_config.scan_type_names():
                set_crosschecked(self.bids_folder, subject_id, scan_type, crosschecked)
        self._rescan()

    def _on_remove_subjects_from_bids(self, subject_ids: list[str]) -> None:
        """Deletes the whole subject folder from BIDS for every id in `subject_ids` -- still
        safe in the raw folder, which this tool never touches (see `record_subject_excluded`).

        One reason prompt covers the whole batch, rather than a separate confirm dialog plus
        a second "mark as non-participant" action -- typing (or leaving blank) an optional
        reason here doubles as the confirmation gesture; Cancel aborts the whole batch.
        """
        if self.bids_folder is None or not subject_ids:
            return
        title = "Remove from BIDS" if len(subject_ids) == 1 else "Remove selected from BIDS"
        reason, confirmed = QInputDialog.getText(
            self,
            title,
            "This deletes the whole subject folder from BIDS for: "
            f"{', '.join(f'sub-{s}' for s in subject_ids)}. Still safe in the raw folder, "
            "which this tool never touches, but there's no in-app bulk restore for it -- "
            "re-run the raw-to-BIDS setup by hand if you need it back."
            "\n\nOptional reason (why this shouldn't be in BIDS), or leave blank:",
        )
        if not confirmed:
            return
        errors = []
        for subject_id in subject_ids:
            try:
                record_subject_excluded(self.bids_folder, subject_id, reason or None)
            except (BidsCrosscheckError, OSError) as error:
                errors.append(f"sub-{subject_id}: {error}")
        if errors:
            QMessageBox.warning(self, "Some subjects could not be removed", "\n".join(errors))
        # reload_pending=True -- see _on_rename_all_selected for why (a removed subject's own
        # pending pick no longer matches anything post-delete; this drops it instead of
        # leaving a dangling Path, same fix, same reason).
        self._rescan(reload_pending=True)

    def _on_candidate_picked(
        self, subject_id: str, scan_type: str, file: Path, checked: bool
    ) -> None:
        if not checked:
            return
        self._pending_selections.setdefault(subject_id, {})[scan_type] = file
        self._persist_pending_selections()
        self._update_commit_all_button()
        self._update_rename_all_button()
        self._refresh_subject_row(subject_id)
        self._refresh_selected_detail(subject_id)
        self._refresh_subject_actions_group(self._selected_subject_ids())

    def _on_commit_selected(self, subject_ids: list[str]) -> None:
        """Commit pending picks for the given subject(s), removing non-selected duplicate(s)
        from BIDS (see `record_selected_run`). No confirmation dialog when it's exactly one
        subject -- matches every other single-subject action in this pane; bulk gets one,
        matching every other bulk action."""
        pending_subject_ids = [s for s in subject_ids if self._pending_selections.get(s)]
        if not pending_subject_ids:
            return
        if len(subject_ids) > 1:
            total_picks = sum(len(self._pending_selections[s]) for s in pending_subject_ids)
            confirm = QMessageBox.question(
                self,
                "Remove non-selected files from BIDS for selected",
                f"This will remove the non-selected duplicate file(s) from BIDS for "
                f"{len(pending_subject_ids)} of your selected subject(s) ({total_picks} "
                "pick(s) total). This cannot be undone from within this tool. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        self._commit_pending_selections(pending_subject_ids)

    def _on_commit_all(self) -> None:
        pending_subject_ids = [
            subject_id for subject_id, picks in self._pending_selections.items() if picks
        ]
        if not pending_subject_ids:
            return
        total_picks = sum(len(self._pending_selections[s]) for s in pending_subject_ids)
        confirm = QMessageBox.question(
            self,
            "Remove non selected files from BIDS",
            f"This will remove the non-selected duplicate file(s) from BIDS for "
            f"{len(pending_subject_ids)} subject(s) ({total_picks} pick(s) total). "
            "This cannot be undone from within this tool. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._commit_pending_selections(pending_subject_ids)

    def _commit_pending_selections(self, subject_ids: list[str]) -> None:
        if self.scan is None or self.bids_folder is None:
            return
        for subject_id in subject_ids:
            selections = self._pending_selections.get(subject_id, {})
            for scan_type, selected_file in selections.items():
                candidates = self.scan.scans[subject_id][scan_type].files
                try:
                    record_selected_run(
                        self.bids_folder, subject_id, scan_type, selected_file, candidates
                    )
                except BidsCrosscheckError as error:
                    QMessageBox.warning(self, "Could not record selection", str(error))
                    continue
                self._strip_duplicate_marker_if_needed(subject_id, scan_type, selected_file)
            self._pending_selections[subject_id] = {}
        self._persist_pending_selections()
        self._update_commit_all_button()
        self._rescan()

    def _strip_duplicate_marker_if_needed(
        self, subject_id: str, scan_type: str, file: Path
    ) -> None:
        """Renames `file` if `extras.duplicate_marker_free_name` says it needs one -- see
        that hook's docstring. `file` was just confirmed as the sole survivor for
        `scan_type` by the `record_selected_run` call right before this."""
        corrected_name = self.extras.duplicate_marker_free_name(scan_type, file)
        if corrected_name is None:
            return
        try:
            record_filename_correction(
                self.bids_folder, subject_id, scan_type, file, corrected_name
            )
        except (BidsCrosscheckError, OSError) as error:
            QMessageBox.warning(self, "Could not clean up duplicate marker", str(error))

    def _on_reveal_subject_folder(self, subject_id: str) -> None:
        if self.scan is None:
            return
        folder = self.scan.subject_folder(subject_id)
        if not folder.is_dir():
            QMessageBox.warning(self, "Folder not found", f"{folder} doesn't exist.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_correct_date(self, subject_id: str, scan_type: str, file: Path) -> None:
        if self.bids_folder is None:
            return
        uses_scans_tsv = self.dataset_config.dates_in_scans_tsv
        if uses_scans_tsv:
            original_date = read_scans_tsv_date(self.bids_folder, file) or ""
            prompt = f"Corrected acquisition date for {file.name}:"
        else:
            original_date = file.name.split("_")[0]
            prompt = f"Corrected date prefix for {file.name}:"
        corrected_date, confirmed = QInputDialog.getText(
            self, "Correct date", prompt, text=original_date
        )
        if not confirmed or not corrected_date or corrected_date == original_date:
            return
        try:
            if uses_scans_tsv:
                destination = record_scans_tsv_date_correction(
                    self.bids_folder, subject_id, scan_type, file, corrected_date
                )
            else:
                destination = record_date_correction(
                    self.bids_folder, subject_id, scan_type, file, corrected_date
                )
            self._follow_rename_in_pending(subject_id, scan_type, file, destination)
        except (BidsCrosscheckError, OSError) as error:
            QMessageBox.warning(self, "Could not correct date", str(error))
        # reload_pending=True -- see _on_rename_all_selected for why.
        self._rescan(reload_pending=True)

    def _on_correct_filename(self, subject_id: str, scan_type: str, file: Path) -> None:
        if self.bids_folder is None:
            return
        corrected_name, confirmed = QInputDialog.getText(
            self, "Correct filename", f"Corrected filename for {file.name}:", text=file.name
        )
        if not confirmed or not corrected_name or corrected_name == file.name:
            return
        if Path(corrected_name).suffix != file.suffix:
            QMessageBox.warning(
                self,
                "Could not correct filename",
                f"The corrected filename must keep the same extension ({file.suffix!r}).",
            )
            return
        try:
            destination = record_filename_correction(
                self.bids_folder, subject_id, scan_type, file, corrected_name
            )
            self._follow_rename_in_pending(subject_id, scan_type, file, destination)
        except (BidsCrosscheckError, OSError) as error:
            QMessageBox.warning(self, "Could not correct filename", str(error))
        # reload_pending=True -- see _on_rename_all_selected for why.
        self._rescan(reload_pending=True)

    def _on_task_tag(
        self, subject_id: str, scan_type: str, file: Path, tagged: bool
    ) -> None:
        if self.bids_folder is None:
            return
        try:
            if tagged:
                destination = remove_task_tag(
                    self.bids_folder,
                    subject_id,
                    scan_type,
                    file,
                    self.dataset_config.task_tag_task,
                    self.dataset_config.task_tag_suffix,
                    self.dataset_config.task_tag_acq,
                )
            else:
                destination = self._record_task_tag_for(subject_id, scan_type, file)
            self._follow_rename_in_pending(subject_id, scan_type, file, destination)
        except (BidsCrosscheckError, OSError) as error:
            QMessageBox.warning(self, "Could not rename", str(error))
        # reload_pending=True -- see _on_rename_all_selected for why.
        self._rescan(reload_pending=True)

    def _on_toggle_subject_crosschecked(self, subject_id: str, crosschecked: bool) -> None:
        if self.bids_folder is None:
            return
        for scan_type in self.dataset_config.scan_type_names():
            set_crosschecked(self.bids_folder, subject_id, scan_type, crosschecked)
        self._rescan()

    def _on_rename_subject(self, subject_id: str) -> None:
        if self.bids_folder is None:
            return
        corrected_id, confirmed = QInputDialog.getText(
            self, "Rename subject ID", "Corrected subject ID:", text=subject_id
        )
        if not confirmed or not corrected_id or corrected_id == subject_id:
            return
        try:
            corrected_folder = record_id_correction(self.bids_folder, subject_id, corrected_id)
        except (BidsCrosscheckError, OSError) as error:
            QMessageBox.warning(self, "Could not rename subject", str(error))
            return
        self._follow_id_correction_in_pending(subject_id, corrected_id, corrected_folder)
        # reload_pending=True -- see _on_rename_all_selected for why.
        self._rescan(reload_pending=True)


def run_bids_crosscheck_app(
    dataset_config: DatasetConfig,
    window_title: str,
    extras: CandidateExtras | None = None,
    settings_app_name: str | None = None,
    raw_converter: Callable[[Path, Path, Path | None], list[str]] | None = None,
    override_file_label: str | None = None,
    override_file_filter: str = "All files (*)",
    override_file_autodetect: Callable[[Path], Path | None] | None = None,
    extra_raw_actions: list[tuple[str, str, Callable[[Path, Path, QWidget], None], str]]
    | None = None,
    convert_button_tooltip: str = DEFAULT_CONVERT_BUTTON_TOOLTIP,
    extra_backup_filenames: tuple[str, ...] = (),
) -> None:
    app = QApplication.instance() or QApplication([])
    # Consistent tooltip look regardless of OS/theme default -- black text on white, matching
    # every tooltip in the tool (icon legend, button explanations, describe_tooltip() info).
    # Only affects text color; icon glyphs embedded in tooltip text (e.g. CROSSCHECKED_ICON)
    # keep their own native colors since QToolTip's `color` only applies to monochrome glyphs.
    app.setStyleSheet(
        app.styleSheet() + "QToolTip { color: black; background-color: white; "
        "border: 1px solid black; }"
    )
    window = BidsCrosscheckWindow(
        dataset_config,
        window_title,
        extras,
        settings_app_name,
        raw_converter,
        override_file_label,
        override_file_filter,
        override_file_autodetect,
        extra_raw_actions,
        convert_button_tooltip,
        extra_backup_filenames,
    )
    window.show()
    app.exec()
