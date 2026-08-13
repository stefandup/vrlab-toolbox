"""Shared master-detail PySide6 window for the BIDS crosscheck tools.

Dataset-specific entry points (`crane_bids_crosscheck_gui.py`,
`foh_bids_crosscheck_gui.py`) supply a `DatasetConfig` and an optional
`CandidateExtras` and call `run_bids_crosscheck_app`. See
docs/bids_crosscheck_plan.md for the design.
"""

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mooi_toolbox.processing.bids_crosscheck import (
    BidsCrosscheckError,
    BidsFolderScan,
    DatasetConfig,
    SubjectScan,
    completeness_summary,
    record_date_correction,
    record_id_correction,
    record_selected_run,
    record_task_correction,
    scan_bids_folder,
)

logger = logging.getLogger(__name__)

STATUS_ICON = {"ok": "●", "missing": "○", "duplicate": "⚠"}
SUBJECT_ID_ROLE = Qt.ItemDataRole.UserRole


class CandidateExtras:
    """Hook for dataset-specific per-candidate UI. Crane uses the no-op default."""

    def describe(self, scan_type: str, file: Path) -> str | None:
        return None

    def task_correction_available(self, scan_type: str) -> bool:
        return False


class BidsCrosscheckWindow(QMainWindow):
    def __init__(
        self,
        dataset_config: DatasetConfig,
        window_title: str,
        extras: CandidateExtras | None = None,
    ):
        super().__init__()
        self.dataset_config = dataset_config
        self.extras = extras or CandidateExtras()
        self.bids_folder: Path | None = None
        self.scan: BidsFolderScan | None = None
        self._pending_selections: dict[str, dict[str, Path]] = {}
        self._commit_button: QPushButton | None = None

        self.setWindowTitle(window_title)
        self.resize(1100, 650)
        self._build_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("BIDS folder:"))
        self.folder_label = QLabel("No BIDS folder selected")
        top_bar.addWidget(self.folder_label, 1)
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._on_browse)
        top_bar.addWidget(browse_button)
        root_layout.addLayout(top_bar)

        self.summary_label = QLabel("")
        root_layout.addWidget(self.summary_label)

        splitter = QSplitter()
        root_layout.addWidget(splitter, 1)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        self.issues_only_checkbox = QCheckBox("Issues only")
        self.issues_only_checkbox.stateChanged.connect(self._refresh_subject_list)
        left_layout.addWidget(self.issues_only_checkbox)
        self.subject_list = QListWidget()
        self.subject_list.currentItemChanged.connect(self._on_subject_selected)
        left_layout.addWidget(self.subject_list, 1)
        splitter.addWidget(left_panel)

        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_container = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_container)
        self.detail_layout.addStretch(1)
        self.detail_scroll.setWidget(self.detail_container)
        splitter.addWidget(self.detail_scroll)

        splitter.setSizes([300, 800])

    def _on_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select BIDS folder")
        if folder:
            self.load_bids_folder(Path(folder))

    def load_bids_folder(self, bids_folder: Path) -> None:
        self.bids_folder = bids_folder
        self.folder_label.setText(str(bids_folder))
        self._pending_selections.clear()
        self._rescan()

    def _rescan(self) -> None:
        if self.bids_folder is None:
            return
        self.scan = scan_bids_folder(self.bids_folder, self.dataset_config)
        self._refresh_summary()
        self._refresh_subject_list()

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
        self.subject_list.blockSignals(True)
        self.subject_list.clear()
        issues_only = self.issues_only_checkbox.isChecked()
        for subject_id in self.scan.subject_ids():
            if issues_only and not self.scan.has_issues(subject_id):
                continue
            dots = " ".join(
                STATUS_ICON[self.scan.scans[subject_id][scan_type].status]
                for scan_type in self.dataset_config.scan_type_names()
            )
            item = QListWidgetItem(f"sub-{subject_id}   {dots}")
            item.setData(SUBJECT_ID_ROLE, subject_id)
            self.subject_list.addItem(item)
        self.subject_list.blockSignals(False)

        restored = False
        for row in range(self.subject_list.count()):
            if self.subject_list.item(row).data(SUBJECT_ID_ROLE) == previously_selected:
                self.subject_list.setCurrentRow(row)
                restored = True
                break
        if not restored:
            if self.subject_list.count():
                self.subject_list.setCurrentRow(0)
            else:
                self._render_detail(None)

    def _current_subject_id(self) -> str | None:
        item = self.subject_list.currentItem()
        return item.data(SUBJECT_ID_ROLE) if item else None

    def _on_subject_selected(self, current: QListWidgetItem, _previous: QListWidgetItem) -> None:
        self._render_detail(current.data(SUBJECT_ID_ROLE) if current else None)

    def _clear_detail_layout(self) -> None:
        while self.detail_layout.count() > 1:
            item = self.detail_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _render_detail(self, subject_id: str | None) -> None:
        self._clear_detail_layout()
        self._commit_button = None
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
        rename_button.clicked.connect(lambda: self._on_rename_subject(subject_id))
        footer.addWidget(rename_button)

        self._commit_button = QPushButton("Move non-selected to junk")
        self._commit_button.clicked.connect(lambda: self._on_commit_selections(subject_id))
        self._commit_button.setEnabled(bool(self._pending_selections.get(subject_id)))
        footer.addWidget(self._commit_button)
        footer.addStretch(1)

        footer_widget = QWidget()
        footer_widget.setLayout(footer)
        self.detail_layout.insertWidget(self.detail_layout.count() - 1, footer_widget)

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
            row_layout.addWidget(QLabel(extra_text))

        date_button = QPushButton("Correct date...")
        date_button.clicked.connect(lambda: self._on_correct_date(subject_id, scan_type, file))
        row_layout.addWidget(date_button)

        if self.extras.task_correction_available(scan_type):
            label = self.dataset_config.task_correction_label
            task_button = QPushButton(f"Rename to {label}")
            task_button.setEnabled(f"_{label}" not in file.stem)
            task_button.clicked.connect(
                lambda: self._on_task_correction(subject_id, scan_type, file)
            )
            row_layout.addWidget(task_button)

        row_layout.addStretch(1)
        return row

    def _on_candidate_picked(
        self, subject_id: str, scan_type: str, file: Path, checked: bool
    ) -> None:
        if not checked:
            return
        self._pending_selections.setdefault(subject_id, {})[scan_type] = file
        if self._commit_button is not None:
            self._commit_button.setEnabled(True)

    def _on_commit_selections(self, subject_id: str) -> None:
        selections = self._pending_selections.get(subject_id, {})
        if not selections or self.scan is None or self.bids_folder is None:
            return
        for scan_type, selected_file in selections.items():
            candidates = self.scan.scans[subject_id][scan_type].files
            try:
                record_selected_run(
                    self.bids_folder, subject_id, scan_type, selected_file, candidates
                )
            except BidsCrosscheckError as error:
                QMessageBox.warning(self, "Could not record selection", str(error))
        self._pending_selections[subject_id] = {}
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

    def _on_task_correction(self, subject_id: str, scan_type: str, file: Path) -> None:
        if self.bids_folder is None:
            return
        try:
            record_task_correction(
                self.bids_folder,
                subject_id,
                scan_type,
                file,
                self.dataset_config.task_correction_label,
            )
        except (BidsCrosscheckError, OSError) as error:
            QMessageBox.warning(self, "Could not rename", str(error))
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
    dataset_config: DatasetConfig, window_title: str, extras: CandidateExtras | None = None
) -> None:
    app = QApplication.instance() or QApplication([])
    window = BidsCrosscheckWindow(dataset_config, window_title, extras)
    window.show()
    app.exec()
