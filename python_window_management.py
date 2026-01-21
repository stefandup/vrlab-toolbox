import ctypes
from ctypes import wintypes
from typing import Callable
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Win32 API bindings (user32.dll)
# ---------------------------------------------------------------------------

# Load Windows' user32.dll (window management APIs). `use_last_error=True` allows
# retrieving extended error info via ctypes.get_last_error() if a call fails.
user32 = ctypes.WinDLL("user32", use_last_error=True)

# ---- define callback type explicitly ----
# EnumWindows expects a callback with signature:
#   BOOL callback(HWND hwnd, LPARAM lParam)
# Windows will call this function once per top-level window.
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

# Bind EnumWindows from user32. We also set arg/return types for safer calls.
EnumWindows = user32.EnumWindows  # Windows user32 function
EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
EnumWindows.restype = wintypes.BOOL

# Bind other user32 functions used during enumeration:
# - GetWindowTextLengthW/GetWindowTextW: read the window title (Unicode "W" versions)
# - IsWindowVisible: skip invisible windows
# - GetWindowThreadProcessId: get the owning process ID for a window
GetWindowTextLengthW = user32.GetWindowTextLengthW
GetWindowTextW = user32.GetWindowTextW
IsWindowVisible = user32.IsWindowVisible
GetWindowThreadProcessId = user32.GetWindowThreadProcessId

# Window resizing APIs
class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]

GetWindowRect = user32.GetWindowRect
GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
GetWindowRect.restype = wintypes.BOOL

MoveWindow = user32.MoveWindow
MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL]
MoveWindow.restype = wintypes.BOOL

# ShowWindow can change a window's state (minimize/maximize/restore/etc.)
ShowWindow = user32.ShowWindow
ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
ShowWindow.restype = wintypes.BOOL

# SetForegroundWindow brings a window to the front (may be needed before minimizing)
SetForegroundWindow = user32.SetForegroundWindow
SetForegroundWindow.argtypes = [wintypes.HWND]
SetForegroundWindow.restype = wintypes.BOOL

# GetSystemMetrics gets screen dimensions and other system metrics
GetSystemMetrics = user32.GetSystemMetrics
GetSystemMetrics.argtypes = [ctypes.c_int]
GetSystemMetrics.restype = ctypes.c_int

SW_MINIMIZE = 6
SW_RESTORE = 9
SM_CXSCREEN = 0  # Screen width in pixels
SM_CYSCREEN = 1  # Screen height in pixels

# ---------------------------------------------------------------------------
# Window management helpers
# ---------------------------------------------------------------------------

def get_window_title(hwnd: wintypes.HWND) -> str:
    """Return the window title text (empty string if no title)."""
    length = GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""

    # +1 for the null terminator.
    buffer = ctypes.create_unicode_buffer(length + 1)
    GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def is_window_visible(hwnd: wintypes.HWND) -> bool:
    """True if the window is visible."""
    return bool(IsWindowVisible(hwnd))


def get_window_pid(hwnd: wintypes.HWND) -> int:
    """Return the owning process ID for a window."""
    pid = wintypes.DWORD()
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)

def bring_window_to_front(hwnd: wintypes.HWND):
    ShowWindow(hwnd, SW_RESTORE)
    SetForegroundWindow(hwnd)
    

def minimize_window(hwnd: wintypes.HWND) -> bool:
    """
    Minimize a window by its handle. Returns True if successful.
    Restores the window first if needed, then minimizes it.
    """
    # Try to bring window to foreground first (helps with some windows)
    SetForegroundWindow(hwnd)
    # First, try to restore if it's minimized/maximized (SW_RESTORE = 9)
    ShowWindow(hwnd, SW_RESTORE)
    # Then minimize it
    result = ShowWindow(hwnd, SW_MINIMIZE)
    if not result:
        # Debug: check if window handle is valid
        error = ctypes.get_last_error()
        print(f"ShowWindow failed, error code: {error}, HWND: {hwnd}")
    return bool(result)

def resize_window(hwnd: wintypes.HWND, width: int, height: int) -> bool:
    """Resize a window by its handle while preserving its current top-left position."""
    rect = RECT()
    if not GetWindowRect(hwnd, ctypes.byref(rect)):
        error = ctypes.get_last_error()
        print(f"GetWindowRect failed, error code: {error}, HWND: {hwnd}")
        return False

    result = MoveWindow(hwnd, rect.left, rect.top, width, height, True)
    if not result:
        error = ctypes.get_last_error()
        print(f"MoveWindow failed, error code: {error}, HWND: {hwnd}")
    return bool(result)


def get_screen_size() -> tuple[int, int]:
    """Return screen width and height in pixels as (width, height)."""
    width = GetSystemMetrics(SM_CXSCREEN)
    height = GetSystemMetrics(SM_CYSCREEN)
    return (width, height)


def move_window(hwnd: wintypes.HWND, x: int, y: int) -> bool:
    """Move a window by its handle to position (x, y) while preserving its current size."""
    rect = RECT()
    if not GetWindowRect(hwnd, ctypes.byref(rect)):
        error = ctypes.get_last_error()
        print(f"GetWindowRect failed, error code: {error}, HWND: {hwnd}")
        return False

    # Calculate current width and height
    width = rect.right - rect.left
    height = rect.bottom - rect.top

    result = MoveWindow(hwnd, x, y, width, height, True)
    if not result:
        error = ctypes.get_last_error()
        print(f"MoveWindow failed, error code: {error}, HWND: {hwnd}")
    return bool(result)

def get_window_rect(hwnd: wintypes.HWND) -> tuple[int, int, int, int] | None:
    """Return (left, top, width, height) for a window handle, or None on failure."""
    rect = RECT()
    if not GetWindowRect(hwnd, ctypes.byref(rect)):
        error = ctypes.get_last_error()
        print(f"GetWindowRect failed, error code: {error}, HWND: {hwnd}")
        return None

    left = int(rect.left)
    top = int(rect.top)
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    return (left, top, width, height)

def place_window(hwnd: wintypes.HWND, left: int, top: int, width: int, height: int) -> bool:
    """Move + resize a window by handle in one call."""
    result = MoveWindow(hwnd, left, top, width, height, True)
    if not result:
        error = ctypes.get_last_error()
        print(f"MoveWindow failed, error code: {error}, HWND: {hwnd}")
    return bool(result)


def layout_row(
    hwnds: list[wintypes.HWND],
    *,
    margin: int = 20,
    gap: int = 10,
    height_ratio: float = 0.5,
) -> None:
    """
    Lay out windows in a single row across the screen using screen-relative sizing.
    - margin: space from the screen edge (px)
    - gap: space between windows (px)
    - height_ratio: window height as a fraction of screen height (0..1)
    """
    if not hwnds:
        return

    screen_w, screen_h = get_screen_size()
    usable_w = max(0, screen_w - 2 * margin)
    usable_h = max(0, screen_h - 2 * margin)

    n = len(hwnds)
    total_gap = gap * (n - 1)
    win_w = max(50, (usable_w - total_gap) // n)
    win_h = max(50, int(usable_h * height_ratio))

    x = margin
    y = margin
    for hwnd in hwnds:
        
        place_window(hwnd, x, y, win_w, win_h)
        x += win_w + gap

def save_layout(hwnds: list[wintypes.HWND], config_path: str | Path = "window_layout.json") -> None:
    """
    Save current positions/sizes for the given window handles to a JSON file.
    Layout is stored by list index, so load with the same handle list ordering.
    """
    path = Path(config_path)
    windows: list[dict[str, int]] = []
    for hwnd in hwnds:
        rect = get_window_rect(hwnd)
        if rect is None:
            continue
        left, top, width, height = rect
        windows.append(
            {
                "hwnd": int(hwnd),  # informational only
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }
        )

    payload = {"version": 1, "windows": windows}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_layout(hwnds: list[wintypes.HWND], config_path: str | Path = "window_layout.json") -> None:
    """
    Load a JSON layout file and apply it to the given window handles by list index.
    """
    path = Path(config_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    windows = payload.get("windows", [])

    for i, hwnd in enumerate(hwnds):
        if i >= len(windows):
            break
        w = windows[i]
        place_window(hwnd, int(w["left"]), int(w["top"]), int(w["width"]), int(w["height"]))


def minimize_windows_by_pid(pid: int) -> int:
    """
    Minimize all visible top-level windows owned by `pid`.
    Returns the number of windows minimized.
    """
    minimized = 0

    def handle_window(hwnd: wintypes.HWND) -> bool:
        nonlocal minimized
        if not is_window_visible(hwnd):
            return True

        if get_window_pid(hwnd) == pid:
            ShowWindow(hwnd, SW_MINIMIZE)
            minimized += 1

        return True

    enumerate_windows(handle_window)
    return minimized


def enumerate_windows(on_window: Callable[[wintypes.HWND], bool]) -> None:
    """
    Call `on_window(hwnd)` for each top-level window.
    `on_window` should return True to continue enumeration, False to stop early.
    """
    @WNDENUMPROC
    def _callback(hwnd, lParam):
        return bool(on_window(hwnd))

    # Start enumeration. The second argument is an arbitrary LPARAM value (unused here).
    EnumWindows(_callback, 0)


# ---------------------------------------------------------------------------
# Debug: list all visible windows
# ---------------------------------------------------------------------------

def list_all_windows() -> None:
    """Print all visible windows with their PID and title (useful for debugging)."""
    def handle_window(hwnd: wintypes.HWND) -> bool:
        if not is_window_visible(hwnd):
            return True

        title = get_window_title(hwnd)
        if not title:
            return True

        pid = get_window_pid(hwnd)
        print(f"PID={pid:6} | TITLE='{title}'")
        return True

    enumerate_windows(handle_window)


# ---------------------------------------------------------------------------
# Example: find windows by exact title match
# ---------------------------------------------------------------------------

def find_windows_by_title(search_text: str) -> list[wintypes.HWND]:
    """
    Return a list of visible window handles (HWND) whose title exactly matches search_text
    (case-insensitive).
    """
    search_lower = search_text.lower()
    matches: list[wintypes.HWND] = []

    def handle_window(hwnd: wintypes.HWND) -> bool:
        if not is_window_visible(hwnd):
            return True

        title = get_window_title(hwnd)
        if not title:
            return True

        # Case-insensitive exact match against the window title.
        if search_lower in title.lower():
            pid = get_window_pid(hwnd)
            print(f"PID={pid} | TITLE='{title}'")
            matches.append(hwnd)

        return True  # continue enumeration

    enumerate_windows(handle_window)
    return matches


def main() -> None:

    window_search_titles = [
        "Example Python Window 1",
        "Example Python Window 2",
        "Example Python Window 3",
        "python.exe"
    ]
    
    print(f"Screensize is: {get_screen_size()[0]} by {get_screen_size()[1]}")
    
    window_handles = []

    for window_search_title in window_search_titles:
        
        window_handle = find_windows_by_title(window_search_title)
        
        if window_handle:
            print(f"Window handle is: {window_handle}")
            if window_search_title == "python.exe":
                # Minimize the first matching window
                if window_handle:
                    minimize_window(window_handle[0])
            else:
                window_handles.append(window_handle[0])

    #list_all_windows()
    for window_handle in window_handles:
        bring_window_to_front(window_handle)

    layout_row(window_handles)

if __name__ == "__main__":
    main()
