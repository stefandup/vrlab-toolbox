"""Shared master-detail PySide6 window for the BIDS crosscheck tools.

Dataset-specific entry points (`crane_bids_crosscheck_gui.py`,
`foh_bids_crosscheck_gui.py`) supply a `DatasetConfig` and an optional
`CandidateExtras` and call `run_bids_crosscheck_app`. See
docs/bids_crosscheck_plan.md for the design.
"""

import logging
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
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
    record_selected_run,
    record_task_correction,
    remove_task_correction,
    save_pending_selections,
    scan_bids_folder,
    set_crosschecked,
)

logger = logging.getLogger(__name__)

STATUS_ICON = {"ok": "●", "missing": "○", "duplicate": "⚠"}
CROSSCHECKED_ICON = "☑"
PENDING_ICON = "⏳"
NEEDS_TAG_ICON = "🏷"
PLEASE_SELECT_COLOR = "#f39c12"
PENDING_COLOR = "#9b59b6"
SUBJECT_ID_ROLE = Qt.ItemDataRole.UserRole
SETTINGS_ORGANIZATION = "MooiToolbox"
LAST_BIDS_FOLDER_SETTINGS_KEY = "last_bids_folder"
STATUS_ICON_TOOLTIP = (
    f"{STATUS_ICON['ok']} complete -- exactly one file found\n"
    f"{STATUS_ICON['missing']} missing -- no file found\n"
    f"{STATUS_ICON['duplicate']} duplicate -- more than one candidate, pick one\n"
    f"{CROSSCHECKED_ICON} crosschecked -- manually marked as reviewed\n"
    f"{PENDING_ICON} picked but not committed yet\n"
    f"{NEEDS_TAG_ICON} the currently selected file hasn't been tagged yet"
)


class CandidateExtras:
    """Hook for dataset-specific per-candidate UI. Crane uses the no-op default."""

    def describe(self, scan_type: str, file: Path) -> str | None:
        return None

    def detail(self, scan_type: str, file: Path) -> str | None:
        """Extended info for the currently selected candidate of `scan_type`, if any."""
        return None

    def task_correction_available(self, scan_type: str) -> bool:
        return False


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
        self._commit_button: QPushButton | None = None
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
        self.rename_all_button = QPushButton()
        self.rename_all_button.setToolTip(
            f"Add the {self.dataset_config.task_correction_label!r} tag to every subject's "
            "currently selected recording, skipping any already renamed. "
            "This can't be undone from within the tool."
        )
        self.rename_all_button.clicked.connect(self._on_rename_all_selected)
        self.rename_all_button.setVisible(self._task_correction_supported)
        summary_bar.addWidget(self.rename_all_button)
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
        self.subject_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.subject_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.subject_table.horizontalHeader().setStretchLastSection(True)
        self.subject_table.setColumnWidth(0, 140)
        self.subject_table.itemSelectionChanged.connect(self._on_subject_selected)
        left_layout.addWidget(self.subject_table, 1)
        splitter.addWidget(left_panel)

        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_container = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_container)
        self.detail_layout.addStretch(1)
        self.detail_scroll.setWidget(self.detail_container)
        splitter.addWidget(self.detail_scroll)

        splitter.setSizes([500, 700])

    def _on_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select BIDS folder")
        if folder:
            self.load_bids_folder(Path(folder))

    def load_bids_folder(self, bids_folder: Path) -> None:
        self.bids_folder = bids_folder
        self.folder_label.setText(str(bids_folder))
        self._settings.setValue(LAST_BIDS_FOLDER_SETTINGS_KEY, str(bids_folder))
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
        self.summary_label.setText(" | ".join(parts))

    def _refresh_subject_list(self) -> None:
        if self.scan is None:
            return
        previously_selected = self._current_subject_id()
        issues_only = self.issues_only_checkbox.isChecked()
        subject_ids = [
            subject_id
            for subject_id in self.scan.subject_ids()
            if not issues_only or self._subject_has_issues(subject_id)
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
            icons.append(icon)
        return " ".join(icons)

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
            elif subject_scan.status == "duplicate":
                pending_file = pending_for_subject.get(scan_type)
                if pending_file is not None:
                    # Radio-picked but not yet committed via "Move non-selected to junk" --
                    # preview the pick's info now. The PENDING_ICON next to the status icon
                    # (see _status_icons) is what signals "not yet saved"; no need to repeat
                    # that in text here too.
                    extra_html = self.extras.describe(scan_type, pending_file)
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

    def _restore_subject_selection(self, previously_selected: str | None) -> None:
        restored = False
        for row in range(self.subject_table.rowCount()):
            item = self.subject_table.item(row, 0)
            if item is not None and item.data(SUBJECT_ID_ROLE) == previously_selected:
                self.subject_table.setCurrentCell(row, 0)
                restored = True
                break
        if not restored:
            if self.subject_table.rowCount():
                self.subject_table.setCurrentCell(0, 0)
            else:
                self._render_detail(None)

    def _current_subject_id(self) -> str | None:
        row = self.subject_table.currentRow()
        if row < 0:
            return None
        item = self.subject_table.item(row, 0)
        return item.data(SUBJECT_ID_ROLE) if item is not None else None

    def _on_subject_selected(self) -> None:
        self._render_detail(self._current_subject_id())

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

    def _render_detail(self, subject_id: str | None) -> None:
        self._clear_detail_layout()
        self._commit_button = None
        self.detail_extra_layout = None
        if subject_id is None or self.scan is None:
            return

        self._pending_selections.setdefault(subject_id, {})
        for scan_type in self.dataset_config.scan_type_names():
            subject_scan = self.scan.scans[subject_id][scan_type]
            self.detail_layout.insertWidget(
                self.detail_layout.count() - 1,
                self._build_scan_type_group(subject_id, subject_scan),
            )

        footer = QHBoxLayout()
        rename_button = QPushButton("Rename subject ID...")
        rename_button.setToolTip(
            "Correct this subject's ID -- renames the sub-<id> folder and every file "
            "inside it to use the new ID."
        )
        rename_button.clicked.connect(lambda: self._on_rename_subject(subject_id))
        footer.addWidget(rename_button)

        self._commit_button = QPushButton()
        self._commit_button.setToolTip(
            "For each scan type above where you've picked a candidate with the radio "
            "button, move the non-selected duplicate file(s) to the junk folder and "
            "record the pick as a permanent decision. This can't be undone from within "
            "the tool."
        )
        self._commit_button.clicked.connect(lambda: self._on_commit_selections(subject_id))
        self._update_commit_button(subject_id)
        footer.addWidget(self._commit_button)
        footer.addStretch(1)

        footer_widget = QWidget()
        footer_widget.setLayout(footer)
        self.detail_layout.insertWidget(self.detail_layout.count() - 1, footer_widget)

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

    def _update_commit_button(self, subject_id: str) -> None:
        if self._commit_button is None:
            return
        pending_count = len(self._pending_selections.get(subject_id, {}))
        if pending_count:
            plural = "s" if pending_count != 1 else ""
            self._commit_button.setText(
                f"Move non-selected to junk ({pending_count} pending pick{plural})"
            )
            self._commit_button.setStyleSheet(f"font-weight: bold; color: {PENDING_COLOR};")
        else:
            self._commit_button.setText("Move non-selected to junk")
            self._commit_button.setStyleSheet("")
        self._commit_button.setEnabled(bool(pending_count))

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
        self._rescan()

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
            row_layout.addWidget(extra_label)

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

        crosschecked = (subject_id, scan_type) in self._crosschecked
        crosscheck_button = QPushButton(
            "Un-mark crosschecked" if crosschecked else "Mark crosschecked"
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
        row_layout.addWidget(crosscheck_button)
        if crosschecked:
            crosschecked_label = QLabel(
                f'<span style="color:#3498db">{CROSSCHECKED_ICON} Crosschecked</span>'
            )
            crosschecked_label.setTextFormat(Qt.TextFormat.RichText)
            row_layout.addWidget(crosschecked_label)

        row_layout.addStretch(1)
        return row

    def _on_candidate_picked(
        self, subject_id: str, scan_type: str, file: Path, checked: bool
    ) -> None:
        if not checked:
            return
        self._pending_selections.setdefault(subject_id, {})[scan_type] = file
        self._persist_pending_selections()
        self._update_commit_button(subject_id)
        self._update_commit_all_button()
        self._update_rename_all_button()
        self._refresh_subject_row(subject_id)
        self._refresh_selected_detail(subject_id)

    def _on_commit_selections(self, subject_id: str) -> None:
        if not self._pending_selections.get(subject_id):
            return
        self._commit_pending_selections([subject_id])

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
        self._rescan()

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
        self._rescan()

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
        self._rescan()


def run_bids_crosscheck_app(
    dataset_config: DatasetConfig,
    window_title: str,
    extras: CandidateExtras | None = None,
    settings_app_name: str | None = None,
) -> None:
    app = QApplication.instance() or QApplication([])
    window = BidsCrosscheckWindow(dataset_config, window_title, extras, settings_app_name)
    window.show()
    app.exec()
