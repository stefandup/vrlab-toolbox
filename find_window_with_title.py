import ctypes
from ctypes import wintypes
from typing import Callable

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
    for window_search_title in window_search_titles:
        
        window_handle = find_windows_by_title(window_search_title)
        
        if window_handle:
            print(f"Window handle is: {window_handle}")
            if window_search_title == "python.exe":
                # Minimize the first matching window
                if window_handle:
                    minimize_window(window_handle[0])
            else:
                resize_window(window_handle[0],width=800,height=600)

    #list_all_windows()


if __name__ == "__main__":
    main()
