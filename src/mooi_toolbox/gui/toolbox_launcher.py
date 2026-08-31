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

from PySide6.QtWidgets import (
    QApplication,
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


def _toolbox_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


class ToolboxLauncher(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Mooi Toolbox (v{__version__})")

        layout = QVBoxLayout()
        layout.addWidget(QLabel("<b>GUI tools</b>"))
        for label, exe_name in GUI_TOOLS:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, exe_name=exe_name: self._launch(exe_name))
            layout.addWidget(button)

        layout.addWidget(QLabel("<br><b>CLI tools</b> (run from a terminal):"))
        layout.addWidget(QLabel(", ".join(CLI_TOOLS)))

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def _launch(self, exe_name: str) -> None:
        exe_path = _toolbox_dir() / exe_name
        try:
            subprocess.Popen([str(exe_path)])
        except OSError as exc:
            QMessageBox.critical(self, "Mooi Toolbox", f"Could not start {exe_name}:\n{exc}")


def main() -> None:
    app = QApplication(sys.argv)
    window = ToolboxLauncher()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
