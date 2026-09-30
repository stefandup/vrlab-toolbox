from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vrlab_toolbox.gui.qt_common import wrap_tooltip
from vrlab_toolbox.processing.redcap import (
    DEFAULT_REDCAP_URL,
    get_token,
    load_config,
    save_config,
    save_token,
)

# Step-by-step versions of both live in the docs ("Setting up REDCap the first time" in
# docs/longwalkv3-crosscheck.md) -- these are the short, in-place reminders.
REPORT_ID_TOOLTIP = (
    "The number of a saved report in your REDCap project -- the pull downloads exactly what "
    "that report contains.\n\n"
    "To make one: in REDCap open Data Exports, Reports, and Stats, click Create New Report, "
    "add the participant id field (study_id for LongwalkV3, record_id for Crane) plus the "
    "debrief fields, and save. Then copy the number in its Report ID "
    "column (e.g. 15195). The built-in reports A and B have no Report ID, so they can't be "
    "used."
)
API_TOKEN_TOOLTIP = (
    "A personal code that lets this tool read your REDCap project as you -- treat it like "
    "a password. It's saved in your operating system's credential store, never in a file.\n\n"
    "To get one: your REDCap user needs API Export rights on the project (User Rights). "
    "Then click API in the project's left menu and request a token; an administrator may "
    "have to approve it. Copy it from that same API page. A token only works for the "
    "project it was issued for."
)
REDCAP_URL_TOOLTIP = (
    "Your institution's REDCap API address -- usually the REDCap web address ending in "
    "/api/. The default is Stellenbosch University's."
)


class RedcapSetupDialog(QDialog):
    """Shared REDCap settings dialog used by the BIDS crosscheck GUIs."""

    def __init__(
        self,
        study_id: str,
        crosscheck_id: str,
        config_file: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.study_id = study_id
        self.crosscheck_id = crosscheck_id
        self.config_file = config_file

        self.setWindowTitle("REDCap Settings")
        self.setMinimumWidth(620)
        self.resize(620, 430)

        existing_config = load_config(config_file) or {}

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 22, 24, 22)
        main_layout.setSpacing(16)

        # Heading
        title = QLabel("REDCap Settings")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        main_layout.addWidget(title)

        description = QLabel(
            "Configure the REDCap report used by this crosscheck. "
            "Your API token is stored securely in the operating system "
            "credential store and is not written to the configuration file."
        )
        description.setWordWrap(True)
        main_layout.addWidget(description)

        # Study information
        study_group = QGroupBox("Study")
        study_layout = QGridLayout(study_group)
        study_layout.setContentsMargins(14, 14, 14, 14)
        study_layout.setHorizontalSpacing(18)
        study_layout.setVerticalSpacing(8)

        study_layout.addWidget(QLabel("Study ID:"), 0, 0)
        study_value = QLabel(self.study_id)
        study_value.setStyleSheet("font-weight: bold;")
        study_layout.addWidget(study_value, 0, 1)

        study_layout.addWidget(QLabel("Task:"), 1, 0)
        task_value = QLabel(self.crosscheck_id.capitalize())
        task_value.setStyleSheet("font-weight: bold;")
        study_layout.addWidget(task_value, 1, 1)

        study_layout.setColumnStretch(1, 1)
        main_layout.addWidget(study_group)

        # REDCap connection settings
        connection_group = QGroupBox("REDCap connection")
        connection_layout = QGridLayout(connection_group)
        connection_layout.setContentsMargins(14, 16, 14, 16)
        connection_layout.setHorizontalSpacing(12)
        connection_layout.setVerticalSpacing(10)

        url_label = QLabel("REDCap API URL")
        url_label.setToolTip(wrap_tooltip(REDCAP_URL_TOOLTIP))
        connection_layout.addWidget(url_label, 0, 0, 1, 2)

        self.url_edit = QLineEdit(
            existing_config.get(
                "redcap_url",
                DEFAULT_REDCAP_URL,
            )
        )
        self.url_edit.setMinimumWidth(430)
        self.url_edit.setToolTip(wrap_tooltip(REDCAP_URL_TOOLTIP))
        connection_layout.addWidget(self.url_edit, 1, 0, 1, 2)

        report_id_label = QLabel("Report ID  ⓘ")
        report_id_label.setToolTip(wrap_tooltip(REPORT_ID_TOOLTIP))
        connection_layout.addWidget(report_id_label, 2, 0, 1, 2)

        self.report_id_edit = QLineEdit(str(existing_config.get("report_id", "")))
        self.report_id_edit.setMaximumWidth(180)
        self.report_id_edit.setPlaceholderText("e.g. 15195")
        self.report_id_edit.setToolTip(wrap_tooltip(REPORT_ID_TOOLTIP))
        connection_layout.addWidget(self.report_id_edit, 3, 0, 1, 2)

        token_label = QLabel("API token  ⓘ")
        token_label.setToolTip(wrap_tooltip(API_TOKEN_TOOLTIP))
        connection_layout.addWidget(token_label, 4, 0, 1, 2)

        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setToolTip(wrap_tooltip(API_TOKEN_TOOLTIP))
        connection_layout.addWidget(self.token_edit, 5, 0, 1, 2)

        if self._token_exists():
            token_text = (
                "API token: securely stored. Leave this field blank to keep the existing token."
            )
        else:
            token_text = "API token: not configured. Enter the project API token before saving."

        self.token_status = QLabel(token_text)
        self.token_status.setWordWrap(True)
        self.token_status.setStyleSheet("color: #555555;")
        connection_layout.addWidget(self.token_status, 6, 0, 1, 2)

        connection_layout.setColumnStretch(1, 1)
        main_layout.addWidget(connection_group)

        # Buttons
        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        self.save_button = QPushButton("Save Settings")
        self.save_button.setMinimumWidth(120)
        self.save_button.clicked.connect(self._on_save)
        button_row.addWidget(self.save_button)

        button_row.addStretch(1)

        cancel_button = QPushButton("Cancel")
        cancel_button.setMinimumWidth(90)
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)

        main_layout.addLayout(button_row)

    def _token_exists(self) -> bool:
        try:
            get_token(
                self.study_id,
                self.crosscheck_id,
            )
        except RuntimeError:
            return False

        return True

    def _on_save(self) -> None:
        redcap_url = self.url_edit.text().strip()
        report_id_text = self.report_id_edit.text().strip()
        token = self.token_edit.text().strip()

        if not redcap_url:
            QMessageBox.warning(
                self,
                "Missing REDCap URL",
                "Enter the REDCap API URL.",
            )
            return

        try:
            report_id = int(report_id_text)
        except ValueError:
            QMessageBox.warning(
                self,
                "Invalid Report ID",
                "Report ID must be a number.",
            )
            return

        if report_id <= 0:
            QMessageBox.warning(
                self,
                "Invalid Report ID",
                "Report ID must be greater than zero.",
            )
            return

        if not token and not self._token_exists():
            QMessageBox.warning(
                self,
                "API Token Required",
                "Enter the REDCap API token for this project.",
            )
            return

        save_config(
            config_file=self.config_file,
            redcap_url=redcap_url,
            report_id=report_id,
        )

        if token:
            save_token(
                study_id=self.study_id,
                crosscheck_id=self.crosscheck_id,
                token=token,
            )

        self.accept()
