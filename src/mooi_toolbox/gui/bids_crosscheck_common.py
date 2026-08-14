"""Shared master-detail PySide6 window for the BIDS crosscheck tools.

Dataset-specific entry points (`crane_bids_crosscheck_gui.py`,
`foh_bids_crosscheck_gui.py`) supply a `DatasetConfig` and an optional
`CandidateExtras` and call `run_bids_crosscheck_app`. See
docs/bids_crosscheck_plan.md for the design.
"""

import logging
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
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
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from rich.progress import Progress

from mooi_toolbox.processing.bids_crosscheck import (
    BidsCrosscheckError,
    BidsFolderScan,
    DatasetConfig,
    SubjectScan,
    completeness_summary,
    crosschecked_scan_types,
    load_pending_selections,
    record_date_correction,
    record_id_correction,
    ensure_bidsignore,
    record_selected_run,
    record_subject_junked,
    record_task_correction,
    remove_task_correction,
    restore_all_from_junk,
    revert_all_decisions,
    save_pending_selections,
    scan_bids_folder,
    set_crosschecked,
)

logger = logging.getLogger(__name__)

STATUS_ICON = {"ok": "●", "missing": "○", "duplicate": "⚠"}
CROSSCHECKED_ICON = "☑"
PENDING_ICON = "⏳"
NEEDS_TAG_ICON = "🏷"
WARNING_ICON = "❗"
PLEASE_SELECT_COLOR = "#f39c12"
PENDING_COLOR = "#9b59b6"
UNCROSSCHECKED_COLOR = "#e74c3c"
SUBJECT_ID_ROLE = Qt.ItemDataRole.UserRole
SETTINGS_ORGANIZATION = "MooiToolbox"
LAST_BIDS_FOLDER_SETTINGS_KEY = "last_bids_folder"
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

    def task_correction_available(self, scan_type: str) -> bool:
        return False

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
        (crosscheck.json, crosscheck_pending.json, crosscheck_junk/) -- e.g. an info cache
        filename. Crane's no-op default needs none."""
        return ()


class BidsCrosscheckWindow(QMainWindow):
    def __init__(
        self,
        dataset_config: DatasetConfig,
        window_title: str,
        extras: CandidateExtras | None = None,
        settings_app_name: str | None = None,
    ):
        super().__init__()
        self.dataset_config = dataset_config
        self.extras = extras or CandidateExtras()
        self.bids_folder: Path | None = None
        self.scan: BidsFolderScan | None = None
        self._crosschecked: set[tuple[str, str]] = set()
        self._pending_selections: dict[str, dict[str, Path]] = {}
        self.detail_extra_layout: QVBoxLayout | None = None
        self._settings = QSettings(
            SETTINGS_ORGANIZATION,
            settings_app_name or f"BidsCrosscheck-{dataset_config.dataset_name}",
        )

        self.setWindowTitle(window_title)
        self.resize(1100, 650)
        self._build_ui()
        self._restore_last_bids_folder()

    def _restore_last_bids_folder(self) -> None:
        stored = self._settings.value(LAST_BIDS_FOLDER_SETTINGS_KEY, "")
        if stored and Path(stored).is_dir():
            self.load_bids_folder(Path(stored))

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("BIDS folder:"))
        self.folder_label = QLabel("No BIDS folder selected")
        top_bar.addWidget(self.folder_label, 1)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.setToolTip("Pick the top-level BIDS folder to scan for subjects.")
        self.browse_button.clicked.connect(self._on_browse)
        top_bar.addWidget(self.browse_button)
        root_layout.addLayout(top_bar)

        summary_bar = QHBoxLayout()
        self.summary_label = QLabel("")
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        summary_bar.addWidget(self.summary_label, 1)
        self.commit_all_button = QPushButton()
        self.commit_all_button.setToolTip(
            "For every subject with a duplicate you've picked, move the non-selected "
            "file(s) to the junk folder. This can't be undone from within the tool."
        )
        self.commit_all_button.clicked.connect(self._on_commit_all)
        summary_bar.addWidget(self.commit_all_button)
        self._task_correction_supported = any(
            self.extras.task_correction_available(scan_type)
            for scan_type in self.dataset_config.scan_type_names()
        )
        self._refresh_supported = any(
            self.extras.refreshable(scan_type)
            for scan_type in self.dataset_config.scan_type_names()
        )
        self.rename_all_button = QPushButton()
        self.rename_all_button.setToolTip(
            f"Add the {self.dataset_config.task_correction_label!r} tag to every subject's "
            "currently selected recording, skipping any already renamed. "
            "This can't be undone from within the tool."
        )
        self.rename_all_button.clicked.connect(self._on_rename_all_selected)
        self.rename_all_button.setVisible(self._task_correction_supported)
        summary_bar.addWidget(self.rename_all_button)

        self.restore_junk_button = QPushButton("Restore all from junk...")
        self.restore_junk_button.setToolTip(
            "Move everything currently in crosscheck_junk/ back to where it came from. "
            "Bulk only in this version -- there's no way to restore just one subject or "
            "file; it's everything in the junk folder, or nothing."
        )
        self.restore_junk_button.clicked.connect(self._on_restore_all_from_junk)
        summary_bar.addWidget(self.restore_junk_button)

        self.revert_all_button = QPushButton("Revert all changes...")
        self.revert_all_button.setToolTip(
            "Reverse every recorded rename (date/ID/tag corrections) and clear all recorded "
            "decisions, including crosschecked marks. Bulk only in this version -- there's "
            "no way to revert just one decision; it's everything recorded, or nothing. Only "
            "reverts the LATEST recorded decision per subject/scan-type -- a file corrected "
            "more than once can't be reverted past its first correction. Junked files are "
            "untouched -- use \"Restore all from junk\" for those."
        )
        self.revert_all_button.clicked.connect(self._on_revert_all_decisions)
        summary_bar.addWidget(self.revert_all_button)

        root_layout.addLayout(summary_bar)
        self._update_commit_all_button()
        self._update_rename_all_button()

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
        self.subject_table = QTableWidget(0, 2)
        self.subject_table.setHorizontalHeaderLabels(["Subject", "Info"])
        self.subject_table.verticalHeader().setVisible(False)
        self.subject_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.subject_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.subject_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.subject_table.horizontalHeader().setStretchLastSection(True)
        self.subject_table.setColumnWidth(0, 140)
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
        self.subject_actions_group = QGroupBox("Subject actions")
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
        self._settings.setValue(LAST_BIDS_FOLDER_SETTINGS_KEY, str(bids_folder))
        ensure_bidsignore(bids_folder, self.extras.bidsignore_patterns())
        self.extras.on_bids_folder_changed(bids_folder)
        self._rescan(reload_pending=True)

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

    def _refresh_summary(self) -> None:
        if self.scan is None:
            return
        summary = completeness_summary(self.scan, self.dataset_config)
        total = len(self.scan.scans)
        parts = [f"{total} subjects"] + [
            f"{scan_type}: {ok}/{total}" for scan_type, (ok, _total) in summary.items()
        ]
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
        id_item.setToolTip(STATUS_ICON_TOOLTIP)
        self.subject_table.setItem(row, 0, id_item)

        info_widget = self._build_subject_info_widget(subject_id)
        self.subject_table.setCellWidget(row, 1, info_widget)
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
            if self._needs_task_correction(subject_id, scan_type):
                icon += NEEDS_TAG_ICON
            if self._has_candidate_warning(subject_id, scan_type):
                icon += WARNING_ICON
            icons.append(icon)
        return " ".join(icons)

    def _has_candidate_warning(self, subject_id: str, scan_type: str) -> bool:
        """True if the file currently in effect for this scan type has a flagged issue.

        Mirrors `_needs_task_correction`: checks the effective candidate only, so a duplicate
        with no pick made yet doesn't get judged before there's anything to judge.
        """
        if self.scan is None:
            return False
        subject_scan = self.scan.scans[subject_id][scan_type]
        file = self._effective_candidate_file(subject_id, scan_type, subject_scan)
        if file is None:
            return False
        return self.extras.has_warning(scan_type, file)

    def _needs_task_correction(self, subject_id: str, scan_type: str) -> bool:
        """True if a file counts as "the one" for this scan type but hasn't been tagged yet.

        Deliberately independent of crosschecked/duplicate status: a subject can be marked
        reviewed, or have only a single "ok" candidate, and still have nobody having confirmed
        it's actually the tagged recording -- this is what makes that omission visible instead
        of silently passing as complete.
        """
        if self.scan is None or not self.extras.task_correction_available(scan_type):
            return False
        subject_scan = self.scan.scans[subject_id][scan_type]
        file = self._effective_candidate_file(subject_id, scan_type, subject_scan)
        if file is None:
            return False
        label = self.dataset_config.task_correction_label
        return f"_{label}" not in file.stem

    def _subject_has_issues(self, subject_id: str) -> bool:
        if self.scan.has_issues(subject_id):
            return True
        return any(
            self._needs_task_correction(subject_id, scan_type)
            or self._has_candidate_warning(subject_id, scan_type)
            for scan_type in self.dataset_config.scan_type_names()
        )

    def _build_subject_info_widget(self, subject_id: str) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(4, 2, 4, 2)

        pending_for_subject = self._pending_selections.get(subject_id, {})

        for scan_type in self.dataset_config.scan_type_names():
            subject_scan = self.scan.scans[subject_id][scan_type]

            extra_html = None
            extra_tooltip = None
            if subject_scan.status == "ok":
                extra_html = self.extras.describe(scan_type, subject_scan.files[0])
                extra_tooltip = self.extras.describe_tooltip(scan_type, subject_scan.files[0])
            elif subject_scan.status == "duplicate":
                pending_file = pending_for_subject.get(scan_type)
                if pending_file is not None:
                    # Radio-picked but not yet committed via "Move non-selected to junk" --
                    # preview the pick's info now. The PENDING_ICON next to the status icon
                    # (see _status_icons) is what signals "not yet saved"; no need to repeat
                    # that in text here too.
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
                    extra_label.setToolTip(extra_tooltip)
                row_layout.addWidget(extra_label)

        row_layout.addStretch(1)
        return row

    def _refresh_subject_row(self, subject_id: str) -> None:
        for row in range(self.subject_table.rowCount()):
            item = self.subject_table.item(row, 0)
            if item is not None and item.data(SUBJECT_ID_ROLE) == subject_id:
                item.setText(f"sub-{subject_id}   {self._status_icons(subject_id)}")
                info_widget = self._build_subject_info_widget(subject_id)
                self.subject_table.setCellWidget(row, 1, info_widget)
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
                f"Commit all pending selections ({total_pending} pick{plural})"
            )
            self.commit_all_button.setStyleSheet(f"font-weight: bold; color: {PENDING_COLOR};")
        else:
            self.commit_all_button.setText("Commit all pending selections")
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

    def _pending_task_correction_file(self, subject_id: str, scan_type: str) -> Path | None:
        if self.scan is None or not self.extras.task_correction_available(scan_type):
            return None
        subject_scan = self.scan.scans[subject_id][scan_type]
        file = self._effective_candidate_file(subject_id, scan_type, subject_scan)
        if file is None:
            return None
        label = self.dataset_config.task_correction_label
        if f"_{label}" in file.stem:
            return None
        return file

    def _rename_all_candidates(self) -> list[tuple[str, str, Path]]:
        if self.scan is None:
            return []
        candidates = []
        for subject_id in self.scan.subject_ids():
            for scan_type in self.dataset_config.scan_type_names():
                file = self._pending_task_correction_file(subject_id, scan_type)
                if file is not None:
                    candidates.append((subject_id, scan_type, file))
        return candidates

    def _update_rename_all_button(self) -> None:
        if not self._task_correction_supported:
            return
        label = self.dataset_config.task_correction_label
        pending = len(self._rename_all_candidates())
        if pending:
            plural = "s" if pending != 1 else ""
            self.rename_all_button.setText(
                f"Rename all selected to {label} ({pending} file{plural})"
            )
            self.rename_all_button.setStyleSheet(f"font-weight: bold; color: {PENDING_COLOR};")
        else:
            self.rename_all_button.setText(f"Rename all selected to {label}")
            self.rename_all_button.setStyleSheet("")
        self.rename_all_button.setEnabled(bool(pending))

    def _on_rename_all_selected(self) -> None:
        if self.bids_folder is None:
            return
        candidates = self._rename_all_candidates()
        if not candidates:
            return
        label = self.dataset_config.task_correction_label
        subject_count = len({subject_id for subject_id, _scan_type, _file in candidates})
        confirm = QMessageBox.question(
            self,
            f"Rename all selected to {label}",
            f"This will rename {len(candidates)} file(s) across {subject_count} subject(s) "
            f"to add the {label!r} tag. This cannot be undone from within this tool. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        errors = []
        for subject_id, scan_type, file in candidates:
            try:
                record_task_correction(self.bids_folder, subject_id, scan_type, file, label)
            except (BidsCrosscheckError, OSError) as error:
                errors.append(f"{file.name}: {error}")
        if errors:
            QMessageBox.warning(self, "Some files could not be renamed", "\n".join(errors))
        # reload_pending=True: a renamed file that was someone's pending duplicate-pick would
        # otherwise leave a dangling Path in self._pending_selections -- see
        # _on_rename_selected_to_task_label for the crash that caused when this was missed.
        self._rescan(reload_pending=True)

    def _on_restore_all_from_junk(self) -> None:
        if self.bids_folder is None:
            return
        confirm = QMessageBox.question(
            self,
            "Restore all from junk",
            "This will move everything currently in crosscheck_junk/ back to where it "
            "came from. There's no selective restore in this version -- it's everything "
            "in the junk folder, or nothing. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        restored, errors = restore_all_from_junk(self.bids_folder)
        if errors:
            QMessageBox.warning(self, "Some items could not be restored", "\n".join(errors))
        elif not restored:
            QMessageBox.information(self, "Nothing to restore", "The junk folder is empty.")
        self._rescan(reload_pending=True)

    def _on_revert_all_decisions(self) -> None:
        if self.bids_folder is None:
            return
        confirm = QMessageBox.question(
            self,
            "Revert all changes",
            "This will reverse every recorded rename (date/ID/tag corrections) and clear "
            "every recorded decision, including crosschecked marks. There's no selective "
            "revert in this version -- it's everything recorded, or nothing. Only the "
            "LATEST recorded decision per subject/scan-type can be reverted -- a file "
            "corrected more than once can't be reverted past its first correction. Junked "
            "files are untouched -- use \"Restore all from junk\" first if you want those "
            "back too. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        reverted, errors = revert_all_decisions(self.bids_folder)
        if errors:
            QMessageBox.warning(self, "Some decisions could not be reverted", "\n".join(errors))
        self._rescan(reload_pending=True)

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
        else:
            row_layout.addWidget(QLabel(f"✓ {file.name}"))

        extra_text = self.extras.describe(scan_type, file)
        if extra_text:
            extra_label = QLabel(extra_text)
            extra_label.setTextFormat(Qt.TextFormat.RichText)
            extra_tooltip = self.extras.describe_tooltip(scan_type, file)
            if extra_tooltip:
                extra_label.setToolTip(extra_tooltip)
            row_layout.addWidget(extra_label)

        reveal_button = QPushButton("Reveal subject folder")
        reveal_button.setToolTip(
            "Open this subject's folder in the system file browser, so you can look at the "
            "raw files yourself."
        )
        reveal_button.clicked.connect(lambda: self._on_reveal_subject_folder(subject_id))
        row_layout.addWidget(reveal_button)

        date_button = QPushButton("Correct date...")
        date_button.setToolTip(
            "Rewrite this file's leading date prefix (the part before the first '_') "
            "if it doesn't match when the recording actually happened."
        )
        date_button.clicked.connect(lambda: self._on_correct_date(subject_id, scan_type, file))
        row_layout.addWidget(date_button)

        if self.extras.task_correction_available(scan_type):
            label = self.dataset_config.task_correction_label
            tagged = f"_{label}" in file.stem
            task_button = QPushButton(f"Un-mark as {label}" if tagged else f"Rename to {label}")
            task_button.setToolTip(
                f"Remove the {label!r} tag from this file's name -- use this if it was "
                "tagged by mistake."
                if tagged
                else f"Add the {label!r} tag to this file's name."
            )
            task_button.clicked.connect(
                lambda: self._on_task_correction(subject_id, scan_type, file, tagged)
            )
            row_layout.addWidget(task_button)

        row_layout.addStretch(1)
        return row

    def _build_crosscheck_widget(self, subject_id: str, scan_type: str) -> QWidget:
        """One "Mark/Un-mark crosschecked" control for a whole subject/scan-type.

        Crosschecked status (self._crosschecked) is keyed by (subject_id, scan_type), not by
        file -- it means "someone has reviewed whichever recording currently counts as the
        one for this scan type", not a property of any single candidate. Built exactly once
        per scan type in the "Subject actions" pane (see `_build_subject_actions_group`), not
        once per candidate row.
        """
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        label_suffix = (
            "" if len(self.dataset_config.scan_type_names()) == 1 else f" ({scan_type})"
        )
        crosschecked = (subject_id, scan_type) in self._crosschecked
        crosscheck_button = QPushButton(
            f"Un-mark crosschecked{label_suffix}"
            if crosschecked
            else f"Mark crosschecked{label_suffix}"
        )
        crosscheck_button.setToolTip(
            "Remove the manual reviewed mark."
            if crosschecked
            else "Manually mark this subject/scan type as reviewed, independent of its "
            "automatic ok/missing/duplicate status."
        )
        crosscheck_button.clicked.connect(
            lambda: self._on_toggle_crosschecked(subject_id, scan_type)
        )
        layout.addWidget(crosscheck_button)
        if crosschecked:
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
        selected: left blank. One subject: the actions below apply to it directly, plus the
        two junk variants (plain, or tagged with a reason). Several: the same actions apply
        across all of them at once. Either way, *which* candidate file is correct for a
        subject with unresolved duplicates stays the recording pane's job above -- bulk
        actions here only ever touch a subject's already-effective candidate, never pick one.
        """
        layout = self.subject_actions_group.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

        if not subject_ids:
            self.subject_actions_group.setTitle("Subject actions")
            return
        if len(subject_ids) == 1:
            self.subject_actions_group.setTitle("Subject actions")
        else:
            self.subject_actions_group.setTitle(
                f"Subject actions -- {len(subject_ids)} subjects selected"
            )

        pending_subject_ids = [s for s in subject_ids if self._pending_selections.get(s)]
        pending_count = sum(len(self._pending_selections[s]) for s in pending_subject_ids)
        commit_label = "Move non-selected to junk" if len(subject_ids) == 1 else "Commit selected"
        if pending_count:
            plural = "s" if pending_count != 1 else ""
            commit_label += f" ({pending_count} pending pick{plural})"
        commit_button = QPushButton(commit_label)
        commit_button.setToolTip(
            "For each scan type where you've picked a candidate with the radio button in "
            "the recording panel above, move the non-selected duplicate file(s) to the "
            "junk folder and record the pick as a permanent decision. This can't be undone "
            "from within the tool."
        )
        commit_button.clicked.connect(lambda: self._on_commit_selected(subject_ids))
        commit_button.setEnabled(bool(pending_subject_ids))
        if pending_count:
            commit_button.setStyleSheet(f"font-weight: bold; color: {PENDING_COLOR};")
        layout.addWidget(commit_button)

        if self._refresh_supported:
            refresh_button = QPushButton("Refresh")
            refresh_button.setToolTip(
                "Re-read the effective candidate's info from disk, ignoring the cached copy."
            )
            refresh_button.clicked.connect(lambda: self._on_refresh_subjects(subject_ids))
            layout.addWidget(refresh_button)

        if len(subject_ids) == 1:
            subject_id = subject_ids[0]
            rename_button = QPushButton("Rename subject ID...")
            rename_button.setToolTip(
                "Correct this subject's ID -- renames the sub-<id> folder and every file "
                "inside it to use the new ID."
            )
            rename_button.clicked.connect(lambda: self._on_rename_subject(subject_id))
            layout.addWidget(rename_button)

            for scan_type in self.dataset_config.scan_type_names():
                layout.addWidget(self._build_crosscheck_widget(subject_id, scan_type))
        else:
            if self._task_correction_supported:
                label = self.dataset_config.task_correction_label
                bulk_rename_button = QPushButton(f"Rename selected to {label}")
                bulk_rename_button.setToolTip(
                    f"Add the {label!r} tag to every selected subject's currently effective "
                    "recording, skipping any that still need a duplicate resolved first."
                )
                bulk_rename_button.clicked.connect(
                    lambda: self._on_rename_selected_to_task_label(subject_ids)
                )
                layout.addWidget(bulk_rename_button)

            bulk_crosscheck_button = QPushButton("Mark selected crosschecked")
            bulk_crosscheck_button.setToolTip(
                "Manually mark every selected subject as reviewed, for every scan type."
            )
            bulk_crosscheck_button.clicked.connect(
                lambda: self._on_bulk_crosschecked(subject_ids, True)
            )
            layout.addWidget(bulk_crosscheck_button)

            bulk_uncrosscheck_button = QPushButton("Un-mark selected crosschecked")
            bulk_uncrosscheck_button.setToolTip(
                "Remove the manual reviewed mark from every selected subject, for every "
                "scan type."
            )
            bulk_uncrosscheck_button.clicked.connect(
                lambda: self._on_bulk_crosschecked(subject_ids, False)
            )
            layout.addWidget(bulk_uncrosscheck_button)

        junk_label = "Send to junk..." if len(subject_ids) == 1 else "Send selected to junk..."
        junk_button = QPushButton(junk_label)
        junk_button.setToolTip(
            "Move the whole subject folder to crosscheck_junk/, removing it from this view. "
            "Nothing is ever deleted -- see the junk folder to recover it."
        )
        junk_button.clicked.connect(lambda: self._on_junk_subjects(subject_ids, None))
        layout.addWidget(junk_button)

        if len(subject_ids) == 1:
            label = self.dataset_config.task_correction_label
            non_participant_button = QPushButton(
                f"Mark as non-participant / non-{label} and junk..."
            )
            non_participant_button.setToolTip(
                "Same as 'Send to junk', but records why -- e.g. this wasn't a real "
                "participant or isn't real study data -- so the junk folder stays auditable."
            )
            non_participant_button.clicked.connect(
                lambda: self._on_junk_subjects(subject_ids, "non_participant")
            )
            layout.addWidget(non_participant_button)

        layout.addStretch(1)

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
        label = self.dataset_config.task_correction_label
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
            f"Rename selected to {label}",
            f"This will rename {len(candidates)} file(s) across {len(selected)} selected "
            f"subject(s) to add the {label!r} tag. This cannot be undone from within this "
            "tool. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        errors = []
        for subject_id, scan_type, file in candidates:
            try:
                record_task_correction(self.bids_folder, subject_id, scan_type, file, label)
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

    def _on_junk_subjects(self, subject_ids: list[str], reason: str | None) -> None:
        if self.bids_folder is None or not subject_ids:
            return
        title = "Send to junk" if reason is None else "Mark as non-participant and junk"
        confirm = QMessageBox.question(
            self,
            title,
            "This will move the whole subject folder to crosscheck_junk/ for: "
            f"{', '.join(f'sub-{s}' for s in subject_ids)}. Nothing is deleted, but this "
            "removes the subject from this view, and can't be undone from within this tool. "
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        errors = []
        for subject_id in subject_ids:
            try:
                record_subject_junked(self.bids_folder, subject_id, reason)
            except (BidsCrosscheckError, OSError) as error:
                errors.append(f"sub-{subject_id}: {error}")
        if errors:
            QMessageBox.warning(self, "Some subjects could not be junked", "\n".join(errors))
        # reload_pending=True -- see _on_rename_all_selected for why (a junked subject's own
        # pending pick no longer matches anything post-move; this drops it instead of leaving
        # a dangling Path, same fix, same reason).
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
        """Commit pending picks for the given subject(s). No confirmation dialog when it's
        exactly one subject -- matches every other single-subject action in this pane; bulk
        gets one, matching every other bulk action."""
        pending_subject_ids = [s for s in subject_ids if self._pending_selections.get(s)]
        if not pending_subject_ids:
            return
        if len(subject_ids) > 1:
            total_picks = sum(len(self._pending_selections[s]) for s in pending_subject_ids)
            confirm = QMessageBox.question(
                self,
                "Commit selected",
                f"This will move the non-selected duplicate file(s) to the junk folder for "
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
            "Commit all pending selections",
            f"This will move the non-selected duplicate file(s) to the junk folder for "
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
            self._pending_selections[subject_id] = {}
        self._persist_pending_selections()
        self._update_commit_all_button()
        self._rescan()

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
        original_date = file.name.split("_")[0]
        corrected_date, confirmed = QInputDialog.getText(
            self, "Correct date", f"Corrected date prefix for {file.name}:", text=original_date
        )
        if not confirmed or not corrected_date or corrected_date == original_date:
            return
        try:
            record_date_correction(self.bids_folder, subject_id, scan_type, file, corrected_date)
        except (BidsCrosscheckError, OSError) as error:
            QMessageBox.warning(self, "Could not correct date", str(error))
        # reload_pending=True -- see _on_rename_all_selected for why.
        self._rescan(reload_pending=True)

    def _on_task_correction(
        self, subject_id: str, scan_type: str, file: Path, tagged: bool
    ) -> None:
        if self.bids_folder is None:
            return
        label = self.dataset_config.task_correction_label
        try:
            if tagged:
                remove_task_correction(self.bids_folder, subject_id, scan_type, file, label)
            else:
                record_task_correction(self.bids_folder, subject_id, scan_type, file, label)
        except (BidsCrosscheckError, OSError) as error:
            QMessageBox.warning(self, "Could not rename", str(error))
        # reload_pending=True -- see _on_rename_all_selected for why.
        self._rescan(reload_pending=True)

    def _on_toggle_crosschecked(self, subject_id: str, scan_type: str) -> None:
        if self.bids_folder is None:
            return
        currently_crosschecked = (subject_id, scan_type) in self._crosschecked
        set_crosschecked(self.bids_folder, subject_id, scan_type, not currently_crosschecked)
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
            record_id_correction(self.bids_folder, subject_id, corrected_id)
        except (BidsCrosscheckError, OSError) as error:
            QMessageBox.warning(self, "Could not rename subject", str(error))
            return
        # reload_pending=True -- see _on_rename_all_selected for why.
        self._rescan(reload_pending=True)


def run_bids_crosscheck_app(
    dataset_config: DatasetConfig,
    window_title: str,
    extras: CandidateExtras | None = None,
    settings_app_name: str | None = None,
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
    window = BidsCrosscheckWindow(dataset_config, window_title, extras, settings_app_name)
    window.show()
    app.exec()
