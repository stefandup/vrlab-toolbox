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
    QGroupBox,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mooi_toolbox import __version__

GUI_TOOLS = (
    ("FOH BIDS Crosscheck", "vrlab_foh_bids_crosscheck.exe"),
    ("Crane BIDS Crosscheck", "vrlab_crane_bids_crosscheck.exe"),
)

CLI_TOOLS = (
    "vrlab_check_xdf",
    "vrlab_crane_convert_to_bids",
    "vrlab_crane_generate_sample_data",
    "vrlab_crane_process",
    "vrlab_foh_assess_data",
    "vrlab_foh_batch_process",
    "vrlab_foh_import_to_bids",
    "vrlab_plot_target_data",
)

# Bundled beside the exe when frozen (see specs/toolbox.spec's toolbox_launcher `datas`
# entry) -- at the repo root in dev mode.
ICON_ASSET_RELATIVE_PATH = Path("assets") / "vrlab_icon.ico"
# Big enough to read as a real logo, not a favicon -- but capped so it doesn't push the
# window taller than the button list actually needs.
ICON_DISPLAY_HEIGHT = 72
# Keeps the window slim regardless of how long the CLI tools list gets -- that list wraps
# inside its own box (see CLI_TOOLS_GROUP below) instead of forcing the window wide.
WINDOW_WIDTH = 320


def _toolbox_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _icon_path() -> Path:
    if getattr(sys, "frozen", False):
        return _toolbox_dir() / ICON_ASSET_RELATIVE_PATH
    # src/mooi_toolbox/gui/toolbox_launcher.py -> repo root is three parents up.
    return Path(__file__).resolve().parents[3] / ICON_ASSET_RELATIVE_PATH


class ToolboxLauncher(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"VR Lab Toolbox (v{__version__})")

        icon_path = _icon_path()
        pixmap = QPixmap(str(icon_path)) if icon_path.is_file() else None
        if pixmap and not pixmap.isNull():
            self.setWindowIcon(QIcon(str(icon_path)))

        layout = QVBoxLayout()
        layout.setSpacing(8)

        if pixmap and not pixmap.isNull():
            icon_label = QLabel()
            icon_label.setPixmap(
                pixmap.scaledToHeight(
                    ICON_DISPLAY_HEIGHT, Qt.TransformationMode.SmoothTransformation
                )
            )
            icon_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(icon_label)

        layout.addWidget(QLabel("<b>GUI tools</b>"))
        for label, exe_name in GUI_TOOLS:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, exe_name=exe_name: self._launch(exe_name))
            layout.addWidget(button)

        # A bordered box that sizes itself to its wrapped content, rather than a bare label
        # whose long comma-separated text would otherwise force the whole window wide.
        cli_group = QGroupBox("CLI tools (run from a terminal)")
        cli_layout = QVBoxLayout(cli_group)
        cli_label = QLabel(", ".join(CLI_TOOLS))
        cli_label.setWordWrap(True)
        cli_layout.addWidget(cli_label)
        layout.addWidget(cli_group)

        container = QWidget()
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
    window = ToolboxLauncher()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
