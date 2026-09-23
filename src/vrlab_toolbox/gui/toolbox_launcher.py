"""Standalone PySide6 launcher: FSL-style button list for the toolbox's GUI tools.

Ships as vrlab_toolbox_launcher.exe next to the other toolbox exes (see
toolbox_installer.iss). CLI tools aren't listed as buttons -- they run from a
terminal once the install folder is on PATH -- but are listed below the
buttons as a reminder of what's available.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vrlab_toolbox import __version__

# Grouped and labelled for display -- crosscheck first since it's the step that has to
# happen before processing, so the button order matches the order a subject's data
# actually moves through the two tools. Each entry's third element is its dataset icon
# file under assets/ (see ICON_ASSET_RELATIVE_PATH below), or None for a tool with no
# dataset-specific icon (REDCap Pull isn't tied to one dataset).
GUI_TOOL_GROUPS = (
    (
        "Crosscheck",
        (
            ("FOH BIDS Crosscheck", "vrlab_foh_bids_crosscheck.exe", "FOH_icon.png"),
            ("Crane BIDS Crosscheck", "vrlab_crane_bids_crosscheck.exe", "crane_icon.png"),
            (
                "Longwalk BIDS Crosscheck",
                "vrlab_longwalk_bids_crosscheck.exe",
                "longwalk_icon.png",
            ),
            (
                "LongwalkV3 BIDS Crosscheck",
                "vrlab_longwalk3_bids_crosscheck.exe",
                "longwalkv3_icon.png",
            ),
        ),
    ),
    (
        "Processing",
        (
            ("Crane Process Results", "vrlab_crane_process_GUI.exe", "crane_icon.png"),
            ("FOH Process Results", "vrlab_foh_process_GUI.exe", "FOH_icon.png"),
            (
                "Longwalk Process Results",
                "vrlab_longwalk_process_GUI.exe",
                "longwalk_icon.png",
            ),
        ),
    ),
    (
        "Data",
        [
            ("REDCap Pull", "vrlab_redcap_pull.exe", None),
        ],
    ),
)

CLI_TOOLS = (
    "vrlab_check_xdf",
    "vrlab_crane_convert_to_bids",
    "vrlab_crane_generate_sample_data",
    "vrlab_crane_process",
    "vrlab_foh_assess_data",
    "vrlab_foh_process",
    "vrlab_foh_import_to_bids",
    "vrlab_longwalk_convert_to_bids",
    "vrlab_longwalk_process",
    "vrlab_plot_target_data",
)

# Bundled beside the exe when frozen (see specs/toolbox.spec's toolbox_launcher `datas`
# entry) -- at the repo root in dev mode.
ICON_ASSET_RELATIVE_PATH = Path("assets") / "vrlab_icon.ico"
# Big enough to read as a real logo, not a favicon -- but capped so it doesn't push the
# window taller than the button list actually needs.
ICON_DISPLAY_HEIGHT = 72
# The .ico ships multiple embedded resolutions (16..256px). We render from this one and
# scale down to ICON_DISPLAY_HEIGHT, instead of loading the file's default (smallest, 16px)
# resolution and scaling that up -- which is what was making the logo look out of focus.
ICON_SOURCE_SIZE = 256
# Height shared by both the icon box and the text box in a tool row -- the icon box is a
# square of this size, so it always fills the row's full height (not a small icon floating
# inside a taller row).
ROW_HEIGHT = 56
# The glyph itself, filling most of ROW_HEIGHT so it reads clearly rather than looking like
# an empty box with a faint mark in the middle.
ICON_GLYPH_SIZE = ROW_HEIGHT + 20
# Gap between the icon box and the text box -- they're two separate bordered elements, not
# one nested inside the other.
ROW_GAP = 10
# Gap from the row's icon box (left) and text box (right) to the window's edges -- rows are
# inset, not flush against the window border.
ROW_SIDE_MARGIN = 16
TEXT_BOX_PADDING_LEFT = 16
BUTTON_FONT_POINT_SIZE = 12
# Keeps the window slim regardless of how long the CLI tools list gets -- that list wraps
# inside its own box (see CLI_TOOLS_GROUP below) instead of forcing the window wide.
WINDOW_WIDTH = 380

# Dark theme colors, matched to the toolbox's target look-and-feel.
COLOR_WINDOW_BG = "#1b1c1f"
COLOR_TEXT = "#e8e8ea"
COLOR_HEADER_TEXT = "#c7c8cc"
COLOR_BUTTON_BG = "#2a2b2f"
COLOR_BUTTON_BORDER = "#3a3b40"
COLOR_BUTTON_HOVER_BG = "#35363b"
COLOR_BUTTON_PRESSED_BG = "#202124"
COLOR_GROUPBOX_BORDER = "#3a3b40"

STYLESHEET = f"""
QMainWindow {{
    background-color: {COLOR_WINDOW_BG};
    color: {COLOR_TEXT};
}}
QWidget#container {{
    background-color: {COLOR_WINDOW_BG};
}}
QLabel {{
    color: {COLOR_TEXT};
}}
QLabel#groupHeader {{
    color: {COLOR_HEADER_TEXT};
    font-weight: bold;
    padding-top: 4px;
}}
QPushButton#toolRow {{
    background: transparent;
    border: none;
    padding: 0;
    outline: none;
}}
QLabel#iconBox, QLabel#textBox {{
    background-color: {COLOR_BUTTON_BG};
    border: 1px solid {COLOR_BUTTON_BORDER};
    border-radius: 10px;
}}
QLabel#textBox {{
    padding-left: {TEXT_BOX_PADDING_LEFT}px;
}}
QPushButton#toolRow:hover QLabel#iconBox,
QPushButton#toolRow:hover QLabel#textBox {{
    background-color: {COLOR_BUTTON_HOVER_BG};
}}
QPushButton#toolRow:pressed QLabel#iconBox,
QPushButton#toolRow:pressed QLabel#textBox {{
    background-color: {COLOR_BUTTON_PRESSED_BG};
}}
QFrame#cliBox {{
    border: 1px solid {COLOR_GROUPBOX_BORDER};
    border-radius: 8px;
    margin-top: 6px;
}}
"""


def _toolbox_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _asset_path(relative_path: Path) -> Path:
    if getattr(sys, "frozen", False):
        return _toolbox_dir() / relative_path
    # src/vrlab_toolbox/gui/toolbox_launcher.py -> repo root is three parents up.
    return Path(__file__).resolve().parents[3] / relative_path


def _icon_path() -> Path:
    return _asset_path(ICON_ASSET_RELATIVE_PATH)


def _build_tool_row(label: str, icon_source: QPixmap) -> QPushButton:
    """A clickable row: a bordered icon box and a bordered text box, side by side with a
    gap -- two separate elements, not one nested inside the other. The row itself is a
    borderless/transparent QPushButton so the whole row (including the gap) is clickable,
    while QLabel#iconBox/#textBox (styled via STYLESHEET) supply the visible card chrome.
    """
    row_button = QPushButton()
    row_button.setObjectName("toolRow")
    row_button.setFixedHeight(ROW_HEIGHT)

    row = QHBoxLayout(row_button)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(ROW_GAP)

    icon_label = QLabel()
    icon_label.setObjectName("iconBox")
    icon_label.setFixedSize(ROW_HEIGHT, ROW_HEIGHT)
    icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    if not icon_source.isNull():
        glyph = icon_source.scaled(
            ICON_GLYPH_SIZE,
            ICON_GLYPH_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        icon_label.setPixmap(glyph)
    icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    row.addWidget(icon_label)

    text_label = QLabel(label)
    text_label.setObjectName("textBox")
    font = text_label.font()
    font.setPointSize(BUTTON_FONT_POINT_SIZE)
    text_label.setFont(font)
    text_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
    text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    row.addWidget(text_label, 1)

    return row_button


class ToolboxLauncher(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"VR Lab Toolbox (v{__version__})")
        self.setStyleSheet(STYLESHEET)

        icon_path = _icon_path()
        # Render from the .ico's largest embedded resolution (see ICON_SOURCE_SIZE) --
        # QPixmap(path) alone loads the file's default (smallest) resolution and scaling
        # that up is what made the logo look out of focus.
        logo_pixmap = (
            QIcon(str(icon_path)).pixmap(ICON_SOURCE_SIZE, ICON_SOURCE_SIZE)
            if icon_path.is_file()
            else QPixmap()
        )
        if not logo_pixmap.isNull():
            self.setWindowIcon(QIcon(str(icon_path)))

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(ROW_SIDE_MARGIN, 12, ROW_SIDE_MARGIN, 12)

        if not logo_pixmap.isNull():
            icon_label = QLabel()
            icon_label.setPixmap(
                logo_pixmap.scaledToHeight(
                    ICON_DISPLAY_HEIGHT, Qt.TransformationMode.SmoothTransformation
                )
            )
            icon_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(icon_label)

        for group_label, tools in GUI_TOOL_GROUPS:
            header = QLabel(group_label)
            header.setObjectName("groupHeader")
            layout.addWidget(header)
            for label, exe_name, icon_filename in tools:
                icon_source = QPixmap()
                if icon_filename is not None:
                    button_icon_path = _asset_path(Path("assets") / icon_filename)
                    if button_icon_path.is_file():
                        icon_source = QPixmap(str(button_icon_path))
                row_button = _build_tool_row(label, icon_source)
                row_button.clicked.connect(
                    lambda _checked=False, exe_name=exe_name: self._launch(exe_name)
                )
                layout.addWidget(row_button)

        # A bordered box that sizes itself to its wrapped content, rather than a bare label
        # whose long comma-separated text would otherwise force the whole window wide. Built
        # from a plain QFrame + QLabel rather than QGroupBox -- QGroupBox::title ignores the
        # QSS color on Windows, leaving it stuck at the native accent color.
        cli_box = QFrame()
        cli_box.setObjectName("cliBox")
        cli_layout = QVBoxLayout(cli_box)
        cli_header = QLabel("CLI tools (run from a terminal)")
        cli_header.setObjectName("groupHeader")
        cli_layout.addWidget(cli_header)
        cli_label = QLabel(", ".join(CLI_TOOLS))
        cli_label.setWordWrap(True)
        cli_layout.addWidget(cli_label)
        layout.addWidget(cli_box)

        container = QWidget()
        container.setObjectName("container")
        container.setLayout(layout)
        self.setCentralWidget(container)
        self.setFixedWidth(WINDOW_WIDTH)

    def _launch(self, exe_name: str) -> None:
        exe_path = _toolbox_dir() / exe_name
        try:
            subprocess.Popen([str(exe_path)])
        except OSError as exc:
            QMessageBox.critical(self, "VR Lab Toolbox", f"Could not start {exe_name}:\n{exc}")


def main() -> None:
    app = QApplication(sys.argv)
    # Windows' native "windowsvista" style ignores QSS colors for some elements (e.g.
    # QGroupBox title text keeps its native accent color) -- Fusion respects the
    # stylesheet fully, so the dark theme renders consistently.
    app.setStyle("Fusion")
    window = ToolboxLauncher()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
