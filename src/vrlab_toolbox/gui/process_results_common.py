"""Shared master-detail PySide6 window for the process-results viewer tools.

Dataset-specific entry points (`crane_process_results_gui.py`,
`longwalk_process_results_gui.py`) supply a `ProcessResultsConfig` and call
`run_process_results_app`.

Read-only over its *output* folder by design: this window never re-implements a
pipeline's logic, and its "Process BIDS Folder" button never subprocesses the
`vrlab_*_process` exe either -- `ProcessResultsConfig.process_bids_folder` is a plain
callable the dataset-specific entry point wires straight to that CLI's own extracted
`run_batch` function (see `vrlab_crane_process.py`/`vrlab_longwalk_process.py`), the same
function object the CLI itself calls. Everything else here -- plots, stats, subject
roster -- only ever reads whatever that run already wrote to the output folder (the batch
CSV, the per-subject QC PNGs, the per-subject and batch log files -- see that CLI's own
docstring). That keeps it decoupled from the pipeline's internals: it depends only on the
output *filenames* that CLI already commits to, not on which figures or columns a given
pipeline happens to produce today, so a change to the pipeline's own logic doesn't require
a matching change here.
"""

import html
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from vrlab_toolbox import __version__
from vrlab_toolbox.gui.qt_common import (
    HOME_BASE_ACCENT_COLOR,
    HOME_BASE_NAME_EXTRA_POINT_INCREASE,
    SETTINGS_ORGANIZATION,
    accent_group_box_stylesheet,
    default_browse_dir,
    primary_action_stylesheet,
    set_path_display,
    style_name_label,
    style_secondary_label,
    wrap_tooltip,
)
from vrlab_toolbox.processing.bids import (
    is_bids_like_folder,
    is_effectively_empty_folder,
    paths_conflict,
)
from vrlab_toolbox.processing.biopac import get_subject_id_from_mat
from vrlab_toolbox.processing.processing_status import ProcessingStatus

logger = logging.getLogger(__name__)

LAST_BIDS_FOLDER_SETTINGS_KEY = "last_bids_folder"
LAST_OUTPUT_FOLDER_SETTINGS_KEY = "last_output_folder"

# "Process BIDS Folder" gets its own quiet accent, distinct from crosscheck's BIDS-folder
# blue and its own green/grey action colors -- a different tool doing a different kind of
# action shouldn't borrow a color that already means something else elsewhere.
PROCESS_ACCENT_COLOR = "#16a085"
PROCESS_ACCENT_HOVER_COLOR = "#128f76"

# Shared status-color palette -- named once, reused by the Status column's icons, the
# autodetected Log column's icons, and the Activity Log's per-line coloring, so "red"
# always means the same severity everywhere in this window.
_OK_COLOR = "#2ecc71"
_CORRECTED_COLOR = "#3498db"
_WARNING_COLOR = "#f39c12"
_ERROR_COLOR = "#e74c3c"
_UNKNOWN_COLOR = "#9aa0a6"

# Ranks worst-to-best in ProcessingStatus's own declaration order -- reused here (rather
# than guessed at) so a subject's badge always agrees with what `Processing_Status` itself
# means, without importing processing_status.py's private `_STATUS_RANK`.
_STATUS_RANK = list(ProcessingStatus)
# Public (not underscore-prefixed): a dataset-specific `build_group_dashboard` (see
# `ProcessResultsConfig`) reuses this and `worst_status` below to render its own
# processing-status banner from the same icon/color/ranking this window's subject
# table already uses, rather than a second copy of the same mapping.
STATUS_ICON = {
    ProcessingStatus.OK: ("✓", _OK_COLOR),  # check
    ProcessingStatus.CORRECTED: ("◐", _CORRECTED_COLOR),  # half circle
    ProcessingStatus.PARTIAL: ("◐", _WARNING_COLOR),  # half circle
    ProcessingStatus.ERROR: ("✗", _ERROR_COLOR),  # cross
    ProcessingStatus.NOT_RUN: ("?", _UNKNOWN_COLOR),
}
# A subject known only from a log file (no row in the batch CSV at all -- e.g. it failed
# before any output data was produced, see vrlab_crane_process.py's "if
# participant_data_out.empty: continue") gets this instead of a ProcessingStatus, since
# there's no Processing_Status text to parse for it.
_NO_CSV_ROW_ICON = ("✗", _ERROR_COLOR)
# A subject discovered from the BIDS folder itself (see `_discover_bids_subject_ids`)
# that has never even been attempted -- no CSV row *and* no log file. Deliberately a
# neutral "nothing here yet" (matching bids_crosscheck_common.py's own "missing" icon),
# not the alarming red `_NO_CSV_ROW_ICON` -- nothing has gone wrong, it just hasn't run.
_NOT_YET_RUN_ICON = ("○", _UNKNOWN_COLOR)

# The log levels mobi_logging.LOG_FORMAT ("{asctime} - {name} - {levelname} - {message}")
# can name, and the color each renders as in the Activity Log -- the usual dim-debug,
# default-info, amber-warning, red-error/critical logging convention. `None` means "leave
# at the widget's default color."
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_LOG_LEVEL_TEXT_COLORS = {
    "DEBUG": _UNKNOWN_COLOR,
    "INFO": None,
    "WARNING": _WARNING_COLOR,
    "ERROR": _ERROR_COLOR,
    "CRITICAL": _ERROR_COLOR,
}

# _ZoomablePlotView's zoom step/bounds -- re-scaled from the original QPixmap each time
# rather than compounding on an already-scaled one, so repeated zooming never degrades.
_ZOOM_STEP = 1.25
_MIN_SCALE = 0.1
_MAX_SCALE = 8.0

# `(index, total, subject_id)`, called once per subject during "Process BIDS Folder" --
# see `ProcessResultsConfig.process_bids_folder` and `ProcessResultsWindow._on_process_progress`.
ProgressCallback = Callable[[int, int, str], None]


@dataclass(frozen=True)
class ProcessResultsConfig:
    """Everything the shared window needs to know about one dataset's `vrlab_*_process`
    output folder. `csv_glob` matches both the plain batch filename and the
    `{subject_id}`-prefixed one the CLI writes for a single-subject `--subject_id` run
    (see vrlab_crane_process.py/vrlab_longwalk_process.py) -- the newest match on disk
    wins, see `_find_batch_csv`.

    `process_bids_folder`, if given, adds a "Process BIDS Folder" button -- called as
    `process_bids_folder(bids_folder, output_folder, progress_callback, skip_existing)`,
    expected to do its own writing into `output_folder` and return human-readable lines
    describing what it did, for display in the Activity Log; a raised exception is
    caught and shown as an error there instead. `progress_callback` is this window's own
    `ProgressCallback` -- forward it straight through to whatever batch function is doing
    the work (e.g. `vrlab_crane_process.run_batch`'s own `progress_callback` parameter)
    so its progress bar moves; that batch function's own `rich.Progress` terminal bar has
    nowhere to draw once this is running inside a windowed (console-less) GUI process,
    which is exactly why this callback exists. `skip_existing` mirrors this window's
    "Skip already-processed subjects" checkbox -- forward it to that same batch
    function's own `skip_existing` parameter. This window never imports a pipeline
    itself -- it only ever calls whatever callable it's handed (see the module
    docstring).

    `bids_physio_glob`, if given, lets the Summary panel and subject table also show a
    subject that has a physiology recording in the BIDS folder but hasn't been processed
    yet ("not yet processed", see `_discover_bids_subject_ids`) -- the same glob pattern
    that batch function itself uses to find subjects (e.g.
    `vrlab_crane_process.PHYSIO_GLOB_PATTERN`), reused rather than duplicated so the two
    can't quietly drift apart. `None` skips that discovery entirely.

    `build_group_dashboard`, if given, replaces the Summary Stats tab's generic
    one-measure-at-a-time bar chart (and its "Measure:" dropdown, which this window
    hides for the whole tab in that case) with a dataset-specific fixed layout --
    called as `build_group_dashboard(figure, batch_df, subject_ids)` on every
    selection change (`subject_ids` is the current selection, or the full roster when
    nothing's selected), with `figure` already cleared and ready to lay out via
    `figure.add_gridspec(...)`. `None` keeps today's plain behaviour (the whole figure
    driven by the "Measure:" dropdown alone).
    """

    dataset_name: str
    window_title: str
    csv_glob: str
    process_bids_folder: Callable[[Path, Path, ProgressCallback | None, bool], list[str]] | None = (
        None
    )
    bids_physio_glob: str | None = None
    build_group_dashboard: Callable[[Figure, pd.DataFrame, list[str]], None] | None = None


def _find_batch_csv(output_folder: Path, csv_glob: str) -> Path | None:
    matches = list(output_folder.glob(csv_glob))
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def _load_batch_dataframe(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype={"Subject_ID": str})
    return df.drop(columns=[c for c in df.columns if c.startswith("Unnamed")], errors="ignore")


def worst_status(status_text: str) -> ProcessingStatus:
    """The worst-off `ProcessingStatus` named in a `Processing_Status` cell (e.g.
    "RawBioData=ok LongWalkRawBehaviourData=error") -- same "worst wins" idea as
    `PipelineStatus.merge`, just reading the already-flattened text back out instead of
    merging two live statuses.
    """
    found = []
    for token in status_text.split():
        _, _, value = token.partition("=")
        try:
            found.append(ProcessingStatus(value))
        except ValueError:
            continue
    if not found:
        return ProcessingStatus.NOT_RUN
    return max(found, key=_STATUS_RANK.index)


def _discover_subject_ids(
    output_folder: Path | None, csv_subject_ids: set[str], bids_subject_ids: set[str] = frozenset()
) -> list[str]:
    """Every subject worth listing: the batch CSV's own roster, any subject with a log
    file that isn't in the CSV at all (a subject that failed before producing any output
    row, see vrlab_crane_process.py, still gets a row here, since its log is exactly what
    a human would need to open to see why), and `bids_subject_ids` (from
    `_discover_bids_subject_ids`) -- a subject with a BIDS-folder recording but nothing
    processed yet still gets a row too, reported as "not yet processed" by
    `ProcessResultsWindow._subject_status_icon`.
    """
    log_subject_ids: set[str] = set()
    if output_folder is not None:
        logs_dir = output_folder / "logs"
        if logs_dir.is_dir():
            # Per-subject logs are named "<subject_id>.log" (see pipeline.py's
            # participant_log_handler); the batch-level log is named after the CLI
            # script itself, always "vrlab_..." -- excluded so it never appears as a
            # fake subject.
            log_subject_ids = {
                p.stem for p in logs_dir.glob("*.log") if not p.stem.startswith("vrlab_")
            }
    return sorted(csv_subject_ids | log_subject_ids | bids_subject_ids, key=str.casefold)


def _discover_bids_subject_ids(bids_folder: Path, physio_glob: str) -> set[str]:
    """Every subject with a physiology recording under `bids_folder`, found by the same
    glob + filename-parsing a batch function's own subject-discovery loop uses (see
    `ProcessResultsConfig.bids_physio_glob`) -- so a subject that's been crosschecked but
    never processed still shows up (see `_discover_subject_ids`), without this window
    reimplementing that discovery logic itself. `get_subject_id_from_mat` only ever
    parses the filename string, so there's nothing here that can fail per-file.
    """
    return {get_subject_id_from_mat(mat_path) for mat_path in bids_folder.rglob(physio_glob)}


def _discover_plot_paths(output_folder: Path, subject_id: str) -> dict[str, Path]:
    """`{figure title: png path}` for one subject, discovered by globbing rather than
    naming specific figures -- `save_plot` names each file
    "<subject_id>_Subject <subject_id> - <figure title>.png" (see plot_utils.py), so
    whatever figures a pipeline run happens to produce this time just show up as that many
    tabs, with no change needed here if a pipeline adds, renames, or drops one.
    """
    prefix = f"{subject_id}_Subject {subject_id} - "
    plots = {}
    for png_path in sorted(output_folder.glob(f"{prefix}*.png")):
        title = png_path.stem[len(prefix) :]
        plots[title] = png_path
    return plots


def _log_line_level(line: str) -> str | None:
    """The level named in one mobi_logging-formatted line ("<asctime> - <name> -
    <levelname> - <message>", see mobi_logging.LOG_FORMAT), or None if `line` doesn't
    match that shape (e.g. a continuation line from a multi-line traceback/schema-error
    dump) -- those are left unstyled/unflagged rather than guessed at.
    """
    parts = line.split(" - ", 3)
    if len(parts) == 4 and parts[2] in _LOG_LEVELS:
        return parts[2]
    return None


def _colorize_log_html(text: str) -> str:
    """Renders `text` as HTML, color-coding each recognized log-record line by level --
    see `_LOG_LEVEL_TEXT_COLORS`. `white-space: pre-wrap` preserves a multi-line
    traceback/schema-error dump's own indentation.
    """
    rendered_lines = []
    for line in text.splitlines():
        escaped = html.escape(line)
        level = _log_line_level(line)
        color = _LOG_LEVEL_TEXT_COLORS.get(level) if level else None
        if color:
            weight = "font-weight:bold;" if level == "CRITICAL" else ""
            rendered_lines.append(f'<span style="color:{color};{weight}">{escaped}</span>')
        else:
            rendered_lines.append(escaped)
    body = "\n".join(rendered_lines)
    return f'<div style="white-space:pre-wrap;">{body}</div>'


def _detect_log_issue(output_folder: Path, subject_id: str) -> tuple[str, str] | None:
    """Scans `<output_folder>/logs/<subject_id>.log` for WARNING/ERROR/CRITICAL lines --
    an autodetected signal separate from the pipeline's own Processing_Status column (a
    warning logged mid-run doesn't always show up there). Error outranks warning if the
    log has both; each keeps its own severity color here too -- the same
    amber/red split `_colorize_log_html` already uses for a WARNING vs an ERROR
    *line* -- so a warning-only log doesn't read as urgently as a real error. None if
    there's no log file, or nothing to flag.
    """
    log_path = output_folder / "logs" / f"{subject_id}.log"
    if not log_path.is_file():
        return None
    text = log_path.read_text(encoding="utf-8", errors="replace")
    has_error = False
    has_warning = False
    for line in text.splitlines():
        level = _log_line_level(line)
        if level in ("ERROR", "CRITICAL"):
            has_error = True
        elif level == "WARNING":
            has_warning = True
    if has_error:
        return ("✗", _ERROR_COLOR)
    if has_warning:
        return ("❗", _WARNING_COLOR)
    return None


def draw_bars(axes: Axes, values: pd.Series, rotation: int) -> None:
    """One bar per `values` entry, each annotated with its own value -- shared between
    this window's own individual/group bar charts and a dataset's `build_group_dashboard`
    (see `ProcessResultsConfig`), so both render bars the same way.
    """
    bars = axes.bar(values.index.astype(str), values.to_numpy())
    for bar, value in zip(bars, values.to_numpy(), strict=True):
        if pd.notna(value):
            axes.annotate(
                f"{value:.3g}",
                (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                ha="center",
                va="bottom",
                fontsize=7,
            )
    axes.tick_params(axis="x", labelrotation=rotation)
    ha = "right" if rotation else "center"
    for label in axes.get_xticklabels():
        label.set_ha(ha)


class _TabBarWheelFilter(QObject):
    """Installed on a QTabBar so the mouse wheel scrolls through its tabs -- lets you
    scroll through a subject's QC plots instead of only clicking each tab by name.
    """

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta().y()
            if delta:
                step = -1 if delta > 0 else 1
                new_index = watched.currentIndex() + step
                if 0 <= new_index < watched.count():
                    watched.setCurrentIndex(new_index)
            return True
        return False


def figure_to_pixmap(figure: Figure, dpi: int) -> QPixmap:
    """Renders a matplotlib `Figure` to a `QPixmap` -- lets the Summary Stats tab show
    a dataset dashboard (or the plain generic chart) through the same
    `_ZoomablePlotView` the per-subject QC plots use, instead of a separately-behaving
    live canvas, so both kinds of plot share one Zoom In/Out/Fit to Window model. Never
    touches disk: `FigureCanvasAgg` (the same rasterizer `FigureCanvasQTAgg` wraps)
    draws straight into an in-memory RGBA buffer.
    """
    figure.set_dpi(dpi)
    canvas = FigureCanvasAgg(figure)
    canvas.draw()
    width, height = canvas.get_width_height()
    image = QImage(canvas.buffer_rgba(), width, height, QImage.Format.Format_RGBA8888)
    # .copy() detaches from `canvas`'s buffer, which is only alive as long as `canvas`
    # (and, transitively, `figure`) stay referenced -- both are otherwise local to
    # whichever caller built the figure and are free to go out of scope right after.
    return QPixmap.fromImage(image.copy())


class _ZoomablePlotView(QWidget):
    """One plot (a per-subject QC PNG, or a rendered Summary Stats figure -- see
    `figure_to_pixmap`) with Zoom In/Out/Fit to Window controls above a scrollable
    image.
    """

    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self._pixmap = pixmap
        self._scale = 1.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        zoom_in_button = QPushButton("Zoom In")
        zoom_in_button.clicked.connect(self._zoom_in)
        toolbar.addWidget(zoom_in_button)
        zoom_out_button = QPushButton("Zoom Out")
        zoom_out_button.clicked.connect(self._zoom_out)
        toolbar.addWidget(zoom_out_button)
        fit_button = QPushButton("Fit to Window")
        fit_button.clicked.connect(self._fit_to_window)
        toolbar.addWidget(fit_button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._image_label = QLabel()
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._image_label)
        layout.addWidget(self._scroll, 1)

        self._apply_scale()
        # The viewport has no real size yet at construction time, before this widget's
        # first layout pass -- fits once the event loop actually gets there.
        QTimer.singleShot(0, self._fit_to_window)

    def showEvent(self, event) -> None:
        """A background tab's viewport has no real size until it's actually shown, so the
        constructor's single fit-on-load can land before that -- refitting here as each
        plot tab becomes current keeps it fitted without needing the button.
        """
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_to_window)

    def resizeEvent(self, event) -> None:
        """Keeps the plot fitted as the window/splitter is resized, same reasoning as
        `showEvent` above.
        """
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_to_window)

    def _apply_scale(self) -> None:
        width = max(1, round(self._pixmap.width() * self._scale))
        height = max(1, round(self._pixmap.height() * self._scale))
        scaled = self._pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)
        self._image_label.resize(scaled.size())

    def _zoom_in(self) -> None:
        self._scale = min(self._scale * _ZOOM_STEP, _MAX_SCALE)
        self._apply_scale()

    def _zoom_out(self) -> None:
        self._scale = max(self._scale / _ZOOM_STEP, _MIN_SCALE)
        self._apply_scale()

    def _fit_to_window(self) -> None:
        if self._pixmap.isNull():
            return
        viewport = self._scroll.viewport().size()
        has_size = self._pixmap.width() and self._pixmap.height()
        has_size = has_size and viewport.width() and viewport.height()
        if has_size:
            self._scale = min(
                viewport.width() / self._pixmap.width(),
                viewport.height() / self._pixmap.height(),
            )
        self._apply_scale()


class ProcessResultsWindow(QMainWindow):
    def __init__(self, config: ProcessResultsConfig, settings_app_name: str):
        super().__init__()
        self.config = config
        self.bids_folder: Path | None = None
        self.output_folder: Path | None = None
        self.batch_df: pd.DataFrame | None = None
        self.subject_ids: list[str] = []
        self._last_csv_path: Path | None = None
        self._settings = QSettings(SETTINGS_ORGANIZATION, settings_app_name)

        self.setWindowTitle(f"{config.window_title} (v{__version__})")
        self.resize(1250, 750)
        self._build_ui()
        self._restore_last_bids_folder()
        self._restore_last_output_folder()

    def _restore_last_bids_folder(self) -> None:
        stored = self._settings.value(LAST_BIDS_FOLDER_SETTINGS_KEY, "")
        if stored and Path(stored).is_dir():
            self.load_bids_folder(Path(stored))

    def _restore_last_output_folder(self) -> None:
        stored = self._settings.value(LAST_OUTPUT_FOLDER_SETTINGS_KEY, "")
        if stored and Path(stored).is_dir():
            self.load_output_folder(Path(stored))

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        top_row = QHBoxLayout()
        folders_grid = QGridLayout()
        folders_grid.setSpacing(8)
        folders_grid.addWidget(self._build_bids_folder_group(), 0, 0)
        folders_grid.addWidget(self._build_output_folder_group(), 0, 1)
        folders_grid.addWidget(self._build_summary_group(), 0, 2)
        top_row.addLayout(folders_grid, 1)

        # Same placement/style as the crosscheck tools' Activity Log -- see
        # bids_crosscheck_common.py. Doubles as this window's per-subject log viewer
        # (replaced wholesale on each subject selection) and its "Process BIDS Folder"
        # run-status feed (appended, timestamped) -- selecting a different subject
        # replaces whatever a prior run message left showing, same as it would replace a
        # previous subject's log.
        activity_log_group = QGroupBox("Activity Log")
        activity_log_layout = QVBoxLayout(activity_log_group)
        self.activity_log_text = QTextEdit()
        self.activity_log_text.setReadOnly(True)
        self.activity_log_text.setFont(QFont("Courier New"))
        self.activity_log_text.setPlaceholderText(
            'Select a subject to view its log, or click "Process BIDS Folder" to run processing.'
        )
        activity_log_layout.addWidget(self.activity_log_text)
        top_row.addWidget(activity_log_group, 1)

        root_layout.addLayout(top_row)

        # Hidden until "Process BIDS Folder" runs -- see `_on_process_progress`. Kept
        # responsive during a long batch the same way bids_crosscheck_common.py's own
        # subject-row progress bar does: `QApplication.processEvents()` once per
        # subject, so the window keeps repainting/accepting input instead of Windows
        # flagging it "Not Responding" for the whole run.
        self.process_progress_bar = QProgressBar()
        self.process_progress_bar.setVisible(False)
        root_layout.addWidget(self.process_progress_bar)

        splitter = QSplitter()
        root_layout.addWidget(splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(
            QLabel("Select one subject for its plots/log; select several for group stats.")
        )
        self.subject_table = QTableWidget(0, 3)
        self.subject_table.setHorizontalHeaderLabels(["Subject", "Status", "Log"])
        self.subject_table.verticalHeader().setVisible(False)
        self.subject_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.subject_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.subject_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.subject_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.subject_table.setColumnWidth(1, 55)
        self.subject_table.setColumnWidth(2, 45)
        self.subject_table.horizontalHeaderItem(1).setToolTip(
            wrap_tooltip(
                "Reported by the pipeline's own Processing_Status column, or, for a "
                "subject with no CSV row yet: ✗ if it has a log (attempted, no output), "
                "○ if it doesn't (found in the BIDS folder, never attempted)."
            )
        )
        self.subject_table.horizontalHeaderItem(2).setToolTip(
            "Autodetected: this subject's log contains a WARNING (❗) or ERROR (✗) line."
        )
        self.subject_table.itemSelectionChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.subject_table, 1)
        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.detail_tabs = QTabWidget()
        # Kept alive on self -- an event filter installed on a local variable would be
        # garbage-collected (and silently stop firing) as soon as _build_ui returns.
        self._tab_wheel_filter = _TabBarWheelFilter()
        self.detail_tabs.tabBar().installEventFilter(self._tab_wheel_filter)
        right_layout.addWidget(self.detail_tabs)
        splitter.addWidget(right_panel)
        splitter.setSizes([380, 870])

        self.stats_measure_combo = QComboBox()
        self.stats_measure_combo.currentIndexChanged.connect(self._refresh_stats_tab)
        has_dashboard = self.config.build_group_dashboard is not None
        # A dataset dashboard packs many small subplots into one figure -- rendered at
        # a generous size/DPI (see `_refresh_stats_tab`) and shown through the same
        # Zoom In/Out/Fit to Window view the per-subject QC plots use (`figure_to_pixmap`
        # + `_ZoomablePlotView`), rather than a live matplotlib canvas, so both kinds of
        # plot default to fitting the tab and share one zoom model.
        self._stats_figsize = (10, 15) if has_dashboard else (6, 4)
        self._stats_dpi = 150 if has_dashboard else 100
        self._stats_plot_view: _ZoomablePlotView | None = None
        stats_widget = QWidget()
        stats_layout = QVBoxLayout(stats_widget)
        self.stats_measure_row_widget = QWidget()
        stats_measure_row = QHBoxLayout(self.stats_measure_row_widget)
        stats_measure_row.setContentsMargins(0, 0, 0, 0)
        stats_measure_row.addWidget(QLabel("Measure:"))
        stats_measure_row.addWidget(self.stats_measure_combo, 1)
        # A dataset dashboard is a fixed, comprehensive layout with nowhere sensible to
        # put a free-choice "pick any column" fallback -- so it never shows this row at
        # all, rather than a control that's easy to miss doing something far down a
        # long scrollable figure.
        self.stats_measure_row_widget.setVisible(not has_dashboard)
        stats_layout.addWidget(self.stats_measure_row_widget)
        self.stats_plot_container = QVBoxLayout()
        self.stats_plot_container.setContentsMargins(0, 0, 0, 0)
        stats_layout.addLayout(self.stats_plot_container, 1)
        self.detail_tabs.addTab(stats_widget, "Summary Stats")

    def _build_bids_folder_group(self) -> QGroupBox:
        group = QGroupBox("BIDS Folder")
        layout = QVBoxLayout(group)
        self.bids_folder_path_label = QLabel("")
        style_secondary_label(self.bids_folder_path_label)
        layout.addWidget(self.bids_folder_path_label)
        self.bids_folder_name_label = QLabel("No BIDS folder selected")
        style_name_label(self.bids_folder_name_label)
        layout.addWidget(self.bids_folder_name_label)

        button_row = QHBoxLayout()
        browse_button = QPushButton("Browse...")
        browse_button.setToolTip("Pick the BIDS folder to process -- must already be crosschecked.")
        browse_button.clicked.connect(self._on_browse_bids_folder)
        button_row.addWidget(browse_button)
        self.bids_reveal_button = QPushButton("Reveal")
        self.bids_reveal_button.setEnabled(False)
        self.bids_reveal_button.clicked.connect(self._on_reveal_bids_folder)
        button_row.addWidget(self.bids_reveal_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.skip_existing_checkbox = QCheckBox("Skip already-processed subjects")
        self.skip_existing_checkbox.setChecked(True)
        self.skip_existing_checkbox.setToolTip(
            wrap_tooltip(
                "Reuses a subject's existing row instead of reprocessing it, for any "
                "subject already recorded in processed_subjects.json (written into the "
                "output folder the first time it's processed). Uncheck to force a full "
                "re-run of everyone found -- e.g. after a pipeline or crosscheck change "
                "that should apply retroactively."
            )
        )
        self.skip_existing_checkbox.setVisible(self.config.process_bids_folder is not None)
        layout.addWidget(self.skip_existing_checkbox)

        self.process_button = QPushButton("Process BIDS Folder")
        self.process_button.setToolTip(
            wrap_tooltip(
                f"Runs vrlab_{self.config.dataset_name}_process on the BIDS folder above, "
                "writing QC plots, logs, and the group CSV/SAV into the output folder to "
                "the right -- the same batch step the vrlab_*_process CLI runs, just "
                'triggered from here. With "Skip already-processed subjects" checked, '
                "this is how newly crosschecked/unprocessed scans get picked up without "
                "redoing everyone else."
            )
        )
        self.process_button.setStyleSheet(
            primary_action_stylesheet(PROCESS_ACCENT_COLOR, PROCESS_ACCENT_HOVER_COLOR)
        )
        self.process_button.setEnabled(False)
        self.process_button.setVisible(self.config.process_bids_folder is not None)
        self.process_button.clicked.connect(self._on_process_bids_folder)
        layout.addWidget(self.process_button)
        return group

    def _build_output_folder_group(self) -> QGroupBox:
        # "Home base" accent -- once a BIDS folder's been picked (a one-off action),
        # this is the panel a user's attention should stay anchored to for the rest of
        # the session: it's what "Browse..."/"Refresh" and the subject list below are
        # actually about. Same treatment as crosscheck's own BIDS Folder panel.
        group = QGroupBox("Output Folder")
        group.setStyleSheet(accent_group_box_stylesheet(HOME_BASE_ACCENT_COLOR))
        layout = QVBoxLayout(group)
        self.folder_path_label = QLabel("")
        style_secondary_label(self.folder_path_label)
        layout.addWidget(self.folder_path_label)
        self.folder_name_label = QLabel("No output folder selected")
        style_name_label(self.folder_name_label)
        name_font = self.folder_name_label.font()
        name_font.setPointSize(name_font.pointSize() + HOME_BASE_NAME_EXTRA_POINT_INCREASE)
        self.folder_name_label.setFont(name_font)
        layout.addWidget(self.folder_name_label)

        button_row = QHBoxLayout()
        browse_button = QPushButton("Browse...")
        browse_button.setToolTip(
            f"Pick the output folder a vrlab_{self.config.dataset_name}_process run wrote to."
        )
        browse_button.clicked.connect(self._on_browse_output_folder)
        button_row.addWidget(browse_button)
        self.reveal_button = QPushButton("Reveal")
        self.reveal_button.setEnabled(False)
        self.reveal_button.clicked.connect(self._on_reveal_output_folder)
        button_row.addWidget(self.reveal_button)
        refresh_button = QPushButton("Refresh")
        refresh_button.setToolTip("Re-scan the output folder for new/changed results.")
        refresh_button.clicked.connect(self._on_refresh)
        button_row.addWidget(refresh_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return group

    def _build_summary_group(self) -> QGroupBox:
        # Same "home base" accent as the Output Folder panel beside it -- see that
        # panel's own comment.
        group = QGroupBox("Summary Output")
        group.setStyleSheet(accent_group_box_stylesheet(HOME_BASE_ACCENT_COLOR))
        layout = QVBoxLayout(group)
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        layout.addStretch(1)
        return group

    def _on_browse_bids_folder(self) -> None:
        start_dir = default_browse_dir(self.bids_folder)
        folder = QFileDialog.getExistingDirectory(self, "Select BIDS folder", start_dir)
        if not folder:
            return
        candidate = Path(folder)
        if self.output_folder is not None and paths_conflict(candidate, self.output_folder):
            QMessageBox.warning(
                self,
                "Same as output folder",
                "The BIDS folder can't be the same as (or contain, or be contained by) "
                "the output folder above -- pick a different folder to process.",
            )
            return
        self.load_bids_folder(candidate)

    def _on_reveal_bids_folder(self) -> None:
        if self.bids_folder is not None and self.bids_folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.bids_folder)))

    def load_bids_folder(self, bids_folder: Path) -> None:
        self.bids_folder = bids_folder
        set_path_display(self.bids_folder_path_label, self.bids_folder_name_label, bids_folder)
        self.bids_reveal_button.setEnabled(True)
        self._settings.setValue(LAST_BIDS_FOLDER_SETTINGS_KEY, str(bids_folder))
        self._update_process_button_enabled()
        self._refresh_roster()
        self._warn_if_not_bids_folder(bids_folder)

    def _warn_if_not_bids_folder(self, bids_folder: Path) -> None:
        """Advisory only -- never blocks the pick, just flags a likely mistake (e.g. an
        empty folder, or one that was never crosschecked into BIDS) before "Process BIDS
        Folder" is run against it.
        """
        if is_effectively_empty_folder(bids_folder):
            QMessageBox.warning(
                self,
                "Empty BIDS folder",
                "This BIDS folder is empty. If you haven't run the crosscheck tool for "
                "this dataset yet, do that first -- it's what populates a BIDS folder "
                "from your raw data.",
            )
        elif not is_bids_like_folder(bids_folder):
            QMessageBox.warning(
                self,
                "Doesn't look like a BIDS folder",
                "This folder doesn't look like a BIDS folder (no sub-* subject folders "
                "found). Make sure you're pointing this at a converted BIDS folder -- "
                "run the crosscheck tool first if you haven't yet.",
            )

    def _update_process_button_enabled(self) -> None:
        self.process_button.setEnabled(
            self.config.process_bids_folder is not None
            and self.bids_folder is not None
            and self.output_folder is not None
        )

    def _on_process_bids_folder(self) -> None:
        if (
            self.config.process_bids_folder is None
            or self.bids_folder is None
            or self.output_folder is None
        ):
            return
        self.process_button.setEnabled(False)
        self.process_progress_bar.setRange(0, 0)  # indeterminate until the first callback
        self.process_progress_bar.setFormat("Starting...")
        self.process_progress_bar.setVisible(True)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            lines = self.config.process_bids_folder(
                self.bids_folder,
                self.output_folder,
                self._on_process_progress,
                self.skip_existing_checkbox.isChecked(),
            )
            error = None
        except Exception as error_raised:  # noqa: BLE001 -- arbitrary pipeline call, shown not swallowed
            logger.exception("Processing failed")
            lines = []
            error = str(error_raised)
        finally:
            QApplication.restoreOverrideCursor()
            self.process_progress_bar.setVisible(False)
            self._update_process_button_enabled()

        if error:
            self._log_activity(f"Process BIDS Folder failed:\n{error}", is_error=True)
        else:
            # Reload first, log after: `load_output_folder` rebuilds the subject table,
            # which (via `_refresh_detail_tabs`) can blank the Activity Log if no subject
            # ends up focused -- logging the result afterward means it's always the last
            # thing written, never wiped by that reload.
            self.load_output_folder(self.output_folder)
            message = "\n".join(lines) if lines else "Finished with nothing to report."
            self._log_activity(f"Process BIDS Folder:\n{message}")

    def _on_process_progress(self, index: int, total: int, subject_id: str) -> None:
        """`ProgressCallback` passed into `process_bids_folder` -- called once per
        subject from inside that (potentially long-running) call, still on this
        window's own thread. `processEvents()` is what actually keeps the window
        responsive: without it, nothing between here and the call returning ever lets
        Qt repaint or handle input, and Windows flags the window "Not Responding".
        """
        self.process_progress_bar.setRange(0, total)
        self.process_progress_bar.setValue(index)
        self.process_progress_bar.setFormat(f"Processing {subject_id} (%v/%m)")
        QApplication.processEvents()

    def _log_activity(self, message: str, *, is_error: bool = False) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = "⚠ " if is_error else ""
        escaped = html.escape(f"[{timestamp}] {prefix}{message}").replace("\n", "<br>")
        if is_error:
            escaped = f'<span style="color:{_ERROR_COLOR};">{escaped}</span>'
        if self.activity_log_text.toPlainText():
            self.activity_log_text.append("")
        self.activity_log_text.append(escaped)

    def _on_browse_output_folder(self) -> None:
        start_dir = default_browse_dir(self.output_folder)
        folder = QFileDialog.getExistingDirectory(self, "Select output folder", start_dir)
        if not folder:
            return
        candidate = Path(folder)
        if self.bids_folder is not None and paths_conflict(candidate, self.bids_folder):
            QMessageBox.warning(
                self,
                "Same as BIDS folder",
                "The output folder can't be the same as (or contain, or be contained by) "
                "the BIDS folder above -- processing output shouldn't be written into "
                "your BIDS data. Pick a different folder.",
            )
            return
        self.load_output_folder(candidate)

    def _on_refresh(self) -> None:
        if self.output_folder is not None:
            self.load_output_folder(self.output_folder)

    def _on_reveal_output_folder(self) -> None:
        if self.output_folder is not None and self.output_folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output_folder)))

    def load_output_folder(self, output_folder: Path) -> None:
        self.output_folder = output_folder
        set_path_display(self.folder_path_label, self.folder_name_label, output_folder)
        self.reveal_button.setEnabled(True)
        self._settings.setValue(LAST_OUTPUT_FOLDER_SETTINGS_KEY, str(output_folder))
        self._update_process_button_enabled()

        self._last_csv_path = _find_batch_csv(output_folder, self.config.csv_glob)
        self.batch_df = (
            _load_batch_dataframe(self._last_csv_path) if self._last_csv_path is not None else None
        )
        self._refresh_measure_combo()
        self._refresh_roster()

    def _refresh_roster(self) -> None:
        """Recomputes `self.subject_ids` from every source this window knows about --
        the batch CSV, the output folder's logs, and (if a BIDS folder is set) its own
        physiology recordings -- then refreshes everything downstream of that roster.
        Called after either folder changes, so picking a BIDS folder before an output
        folder (or vice versa) both converge on the same combined list.
        """
        csv_subject_ids = set(self.batch_df["Subject_ID"]) if self.batch_df is not None else set()
        bids_subject_ids = (
            _discover_bids_subject_ids(self.bids_folder, self.config.bids_physio_glob)
            if self.bids_folder is not None and self.config.bids_physio_glob is not None
            else set()
        )
        self.subject_ids = _discover_subject_ids(
            self.output_folder, csv_subject_ids, bids_subject_ids
        )
        self._refresh_summary_label()
        self._refresh_subject_table()

    def _refresh_summary_label(self) -> None:
        n_subjects = len(self.subject_ids)
        if self._last_csv_path is None:
            found_text = f"No {self.config.csv_glob} found here -- showing logs only, if any."
        else:
            n_rows = len(self.batch_df) if self.batch_df is not None else 0
            found_text = f"{n_rows} in {self._last_csv_path.name}"
        lines = [f"{n_subjects} subject{'s' if n_subjects != 1 else ''} found ({found_text})"]

        # "No output yet" rather than "not yet processed" -- covers both a subject
        # that's never been attempted (found only via bids_physio_glob) and one that
        # was attempted but failed before producing a row (found only via its log),
        # since both cases mean the same thing here: nothing to show for this subject
        # in the batch CSV yet.
        no_output_yet = self._no_output_yet_subject_ids()
        if no_output_yet:
            names = ", ".join(sorted(no_output_yet, key=str.casefold))
            lines.append(f"{len(no_output_yet)} with no output yet: {names}")
        self.summary_label.setText("\n".join(lines))

    def _no_output_yet_subject_ids(self) -> set[str]:
        csv_subject_ids = set(self.batch_df["Subject_ID"]) if self.batch_df is not None else set()
        return set(self.subject_ids) - csv_subject_ids

    def _refresh_measure_combo(self) -> None:
        self.stats_measure_combo.blockSignals(True)
        self.stats_measure_combo.clear()
        if self.batch_df is not None:
            numeric_columns = self.batch_df.select_dtypes(include="number").columns.tolist()
            self.stats_measure_combo.addItems(numeric_columns)
        self.stats_measure_combo.blockSignals(False)

    def _subject_status_icon(self, subject_id: str) -> tuple[str, str]:
        if self.batch_df is not None and subject_id in set(self.batch_df["Subject_ID"]):
            row = self.batch_df.loc[self.batch_df["Subject_ID"] == subject_id].iloc[0]
            status = worst_status(str(row.get("Processing_Status", "")))
            return STATUS_ICON[status]
        if self._has_log(subject_id):
            return _NO_CSV_ROW_ICON
        return _NOT_YET_RUN_ICON

    def _has_log(self, subject_id: str) -> bool:
        if self.output_folder is None:
            return False
        return (self.output_folder / "logs" / f"{subject_id}.log").is_file()

    def _refresh_subject_table(self) -> None:
        previously_selected = set(self._selected_subject_ids())
        self.subject_table.setRowCount(0)
        for subject_id in self.subject_ids:
            row = self.subject_table.rowCount()
            self.subject_table.insertRow(row)
            id_item = QTableWidgetItem(subject_id)
            self.subject_table.setItem(row, 0, id_item)
            icon, color = self._subject_status_icon(subject_id)
            status_item = QTableWidgetItem(icon)
            status_item.setForeground(QColor(color))
            self.subject_table.setItem(row, 1, status_item)

            log_issue = (
                _detect_log_issue(self.output_folder, subject_id)
                if self.output_folder is not None
                else None
            )
            log_item = QTableWidgetItem(log_issue[0] if log_issue else "")
            if log_issue:
                log_item.setForeground(QColor(log_issue[1]))
            self.subject_table.setItem(row, 2, log_item)
        self._restore_subject_selection(previously_selected)
        self._refresh_detail_tabs()
        self._refresh_stats_tab()

    def _restore_subject_selection(self, subject_ids: set[str]) -> None:
        """Re-selects whichever of `subject_ids` still exist after a table rebuild (a
        Refresh, or a "Process BIDS Folder" reload) -- so a rebuild doesn't silently drop
        whatever subject/plot/log was on screen a moment ago. Sets the current cell
        first, then extends the selection, so `_refresh_detail_tabs`'s `currentRow()`
        lookup finds a real row again instead of staying unfocused after the rebuild.
        """
        matching_rows = []
        for row in range(self.subject_table.rowCount()):
            item = self.subject_table.item(row, 0)
            if item is not None and item.text() in subject_ids:
                matching_rows.append(row)
        if not matching_rows:
            return
        self.subject_table.setCurrentCell(matching_rows[0], 0)
        for row in matching_rows:
            self.subject_table.item(row, 0).setSelected(True)
            self.subject_table.item(row, 1).setSelected(True)

    def _selected_subject_ids(self) -> list[str]:
        rows = sorted({index.row() for index in self.subject_table.selectedIndexes()})
        return [self.subject_table.item(row, 0).text() for row in rows]

    def _on_selection_changed(self) -> None:
        self._refresh_detail_tabs()
        self._refresh_stats_tab()

    def _refresh_detail_tabs(self) -> None:
        """Plots (and the Activity Log's subject-log view) are inherently per-subject --
        driven by whichever row is currently *focused* (Qt's `currentRow`), even while
        several rows are multi-selected for the stats tab below. Keeps a sensible
        single-subject view visible no matter how many rows are selected, instead of
        forcing an exact-one-selection rule.
        """
        current_row = self.subject_table.currentRow()
        subject_id = self.subject_table.item(current_row, 0).text() if current_row >= 0 else None

        # Remembers which tab was open by its *label* (e.g. "EDA QC") rather than its
        # index, so switching to a subject whose plots come back in the same order (or
        # a different order/count) still reopens on the same plot instead of resetting
        # to the first tab every time.
        previous_tab_label = self.detail_tabs.tabText(self.detail_tabs.currentIndex())

        while self.detail_tabs.count() > 1:
            self.detail_tabs.removeTab(0)

        if subject_id is None:
            self.activity_log_text.setPlainText("")
            return

        if self.output_folder is not None:
            for title, png_path in _discover_plot_paths(self.output_folder, subject_id).items():
                tab_label = title.replace("_", " ")
                self.detail_tabs.insertTab(
                    self.detail_tabs.count() - 1, self._build_plot_tab(png_path), tab_label
                )

        self._restore_detail_tab_selection(previous_tab_label)
        self._show_subject_log(subject_id)

    def _restore_detail_tab_selection(self, tab_label: str) -> None:
        """Re-selects whichever tab has `tab_label`, if the newly rebuilt tab set still
        has one -- e.g. this subject also has an "EDA QC" plot. Otherwise leaves
        whatever Qt already settled on after the rebuild (typically the first tab).
        """
        for index in range(self.detail_tabs.count()):
            if self.detail_tabs.tabText(index) == tab_label:
                self.detail_tabs.setCurrentIndex(index)
                return

    def _show_subject_log(self, subject_id: str) -> None:
        if self.output_folder is None:
            self.activity_log_text.setPlainText("")
            return
        log_path = self.output_folder / "logs" / f"{subject_id}.log"
        if log_path.is_file():
            text = log_path.read_text(encoding="utf-8", errors="replace")
            self.activity_log_text.setHtml(_colorize_log_html(text))
            cursor = self.activity_log_text.textCursor()
            self.activity_log_text.moveCursor(cursor.MoveOperation.End)
        else:
            self.activity_log_text.setPlainText(f"No log found for {subject_id}.")

    def _build_plot_tab(self, png_path: Path) -> QWidget:
        return _ZoomablePlotView(QPixmap(str(png_path)))

    def _refresh_stats_tab(self) -> None:
        selected = self._selected_subject_ids()
        individual = len(selected) == 1
        has_dashboard = self.config.build_group_dashboard is not None
        self.stats_measure_row_widget.setVisible(not individual and not has_dashboard)

        # "constrained" layout (rather than a manual `tight_layout()` call) for a
        # dataset dashboard -- its many small subplots and full-width panels (rotated
        # tick labels included) need their spacing/margins recomputed on every draw,
        # which is exactly what constrained layout does and a single `tight_layout()`
        # call does not always get right for a layout this dense.
        figure = Figure(
            figsize=self._stats_figsize,
            dpi=self._stats_dpi,
            layout="constrained" if has_dashboard else None,
        )
        if self.batch_df is None:
            figure.add_subplot(111).set_axis_off()
        elif self.config.build_group_dashboard is not None:
            self.config.build_group_dashboard(figure, self.batch_df, selected or self.subject_ids)
        else:
            axes = figure.add_subplot(111)
            if individual:
                self._plot_individual_stats(axes, selected[0])
            else:
                self._plot_group_stats(axes, selected or self.subject_ids)
            figure.tight_layout()

        self._show_stats_pixmap(figure_to_pixmap(figure, self._stats_dpi))

    def _show_stats_pixmap(self, pixmap: QPixmap) -> None:
        if self._stats_plot_view is not None:
            self.stats_plot_container.removeWidget(self._stats_plot_view)
            self._stats_plot_view.deleteLater()
        self._stats_plot_view = _ZoomablePlotView(pixmap)
        self.stats_plot_container.addWidget(self._stats_plot_view)

    def _plot_individual_stats(self, axes, subject_id: str) -> None:
        """Individual mode: every numeric measure as one bar each, for the one selected
        subject -- no measure picker needed since there's only one subject's row to show.
        """
        numeric_columns = self.batch_df.select_dtypes(include="number").columns.tolist()
        matching_rows = self.batch_df.loc[self.batch_df["Subject_ID"] == subject_id]
        if matching_rows.empty or not numeric_columns:
            axes.set_axis_off()
            return
        values = pd.to_numeric(matching_rows.iloc[0][numeric_columns], errors="coerce")
        draw_bars(axes, values, rotation=90)
        axes.set_title(f"Subject {subject_id}")

    def _plot_group_stats(self, axes, subject_ids: list[str]) -> None:
        """Group mode (0, or 2+, subjects selected): the measure picker's chosen column,
        one bar per subject, with a mean line once there's more than one bar.
        """
        measure = self.stats_measure_combo.currentText()
        if not measure or not subject_ids:
            axes.set_axis_off()
            return
        subset = self.batch_df[self.batch_df["Subject_ID"].isin(subject_ids)]
        subset = subset.set_index("Subject_ID").reindex(subject_ids)
        values = pd.to_numeric(subset[measure], errors="coerce")
        draw_bars(axes, values, rotation=45)
        if len(subject_ids) > 1 and values.notna().any():
            axes.axhline(values.mean(), linestyle="--", color="gray", linewidth=1)
        axes.set_ylabel(measure)
        axes.set_title(measure)


def run_process_results_app(config: ProcessResultsConfig, settings_app_name: str) -> None:
    app = QApplication.instance() or QApplication([])
    window = ProcessResultsWindow(config, settings_app_name)
    window.show()
    app.exec()
