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
# Example: find windows by (partial) title
# ---------------------------------------------------------------------------

def find_windows_by_title(search_text: str) -> list[wintypes.HWND]:
    """
    Return a list of visible window handles (HWND) whose title contains search_text
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

        # Case-insensitive substring match against the window title.
        if search_lower in title.lower():
            pid = get_window_pid(hwnd)
            print(f"PID={pid} | TITLE='{title}'")
            matches.append(hwnd)

        return True  # continue enumeration

    enumerate_windows(handle_window)
    return matches


def main() -> None:
    window_handle = find_windows_by_title("Example Python Window")
    if window_handle:
        print(f"Window handle is: {window_handle}")


if __name__ == "__main__":
    main()
