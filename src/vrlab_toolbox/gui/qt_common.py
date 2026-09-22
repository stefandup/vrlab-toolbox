"""Small PySide6 helpers shared across this project's GUI tools -- currently the BIDS
crosscheck windows (`bids_crosscheck_common.py`) and the process-results viewer
(`process_results_common.py`). Kept to the handful of pieces both actually use today, not
a speculative shared base class.
"""

import sys
import textwrap
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLabel, QMainWindow

SETTINGS_ORGANIZATION = "MooiToolbox"

# Qt's plain-text QToolTip never wraps on its own -- a long tooltip string renders as one
# unbroken line stretching off-screen unless it already contains manual line breaks. Kept
# narrow enough to read as a compact box rather than a nearly-full-width banner.
TOOLTIP_WRAP_WIDTH = 68

# Small, muted caption style for a panel's "Path: <parent>" line, paired with a large bold
# name label below it -- see `style_name_label`/`set_path_display`.
SECONDARY_TEXT_COLOR = "#9aa0a6"
NAME_LABEL_FONT_POINT_INCREASE = 9

# Shared disabled-state colors for `primary_action_stylesheet` -- one look for "this
# button's action isn't available right now" across every tool, not a per-tool choice.
PRIMARY_BUTTON_DISABLED_BG = "#555555"
PRIMARY_BUTTON_DISABLED_FG = "#999999"

# "Home base" accent -- the quiet colored-border + bolder-name-label treatment a tool
# uses to mark whichever one or two panels a user's attention should stay anchored to
# for the rest of the session (crosscheck's BIDS Folder/Summary, the process-results
# viewer's Output Folder/Summary Output). Shared so "this panel matters" reads the same
# way across every tool, not a fresh color choice each time.
HOME_BASE_ACCENT_COLOR = "#5b9bd5"
HOME_BASE_ACCENT_HOVER_COLOR = "#4a86b5"
HOME_BASE_NAME_EXTRA_POINT_INCREASE = 2


def default_browse_dir(preferred: Path | None = None) -> str:
    """Starting directory for a folder-picker dialog -- `preferred` (e.g. the already-
    selected folder for that same picker) if it still exists, else the user's home folder.
    Avoids Qt's own fallback (the process's current working directory), which for a
    packaged app is the install/AppData folder -- exactly where a student would otherwise
    risk creating a "BIDS folder" or "raw folder" by mistake instead of somewhere sensible
    under their own home folder.
    """
    if preferred is not None and preferred.is_dir():
        return str(preferred)
    return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.HomeLocation)


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


def style_secondary_label(label: QLabel) -> None:
    """Small, muted caption style for a panel's "Path: <parent>" line -- kept quiet since
    the bold name label below it (see `style_name_label`) is what a user needs to read at a
    glance, not the full path."""
    label.setStyleSheet(f"color: {SECONDARY_TEXT_COLOR};")


def style_name_label(label: QLabel) -> None:
    """Large, bold style for a panel's selected folder/file *name* -- the thing a user most
    needs to read clearly at a glance, unlike the small "Path:" caption above it."""
    font = label.font()
    font.setPointSize(font.pointSize() + NAME_LABEL_FONT_POINT_INCREASE)
    font.setBold(True)
    label.setFont(font)
    label.setWordWrap(True)


def set_path_display(path_label: QLabel, name_label: QLabel, path) -> None:
    """Splits `path` into a small "Path: <parent>" caption and a large bold name -- the
    shared display shape for a tool's folder/file picker panels."""
    path_label.setText(f"Path: {path.parent}\\")
    name_label.setText(path.name or str(path))


def primary_action_stylesheet(base_color: str, hover_color: str) -> str:
    """Stylesheet for an "explicit primary action" button -- bold, padded, filled with
    `base_color` -- used for whichever single button in a row is the main thing to click
    (e.g. crosscheck's "Refresh BIDS", the process-results viewer's "Process BIDS
    Folder"), so it reads as a real call to action rather than sitting flush with plain
    Browse/Reveal-style buttons.
    """
    return (
        f"QPushButton {{ font-weight: bold; font-size: 13px; padding: 6px 20px; "
        f"background-color: {base_color}; color: white; border-radius: 4px; border: none; }}"
        f"QPushButton:hover {{ background-color: {hover_color}; }}"
        f"QPushButton:disabled {{ background-color: {PRIMARY_BUTTON_DISABLED_BG}; "
        f"color: {PRIMARY_BUTTON_DISABLED_FG}; }}"
    )


def accent_group_box_stylesheet(color: str) -> str:
    """Stylesheet for a QGroupBox's "home base" accent border -- a colored 2px border
    plus the title-padding tweak that border needs to look right -- see
    `HOME_BASE_ACCENT_COLOR`.
    """
    return (
        f"QGroupBox {{ border: 2px solid {color}; border-radius: 4px; margin-top: 8px; }}"
        "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
    )


def resolve_asset_path(relative_path: Path) -> Path:
    """Resolves a repo-root-relative asset path (e.g. `Path("assets") / "crane_icon.png"`)
    against wherever it actually lives: bundled next to the frozen exe (see
    specs/toolbox.spec's per-tool `extra_datas`) when packaged, or the real repo root in
    dev mode. Same dual-path logic `toolbox_launcher.py` uses for its own logo, shared here
    so every tool's window icon resolves the same way instead of each reimplementing it.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / relative_path
    # src/vrlab_toolbox/gui/qt_common.py -> repo root is three parents up.
    return Path(__file__).resolve().parents[3] / relative_path


def set_window_icon(window: QMainWindow, relative_icon_path: Path | None) -> None:
    """Sets `window`'s title-bar/taskbar icon from a repo-root-relative asset path, if given
    and the file actually exists there -- silently does nothing otherwise (e.g. a dev
    checkout missing an optional asset), same "degrade quietly" behavior as
    `toolbox_launcher.py`'s own logo loading.
    """
    if relative_icon_path is None:
        return
    icon_path = resolve_asset_path(relative_icon_path)
    if icon_path.is_file():
        window.setWindowIcon(QIcon(str(icon_path)))
