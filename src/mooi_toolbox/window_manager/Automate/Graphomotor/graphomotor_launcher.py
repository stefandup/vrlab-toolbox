from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog
import tkinter as tk


REQUIRED_PACKAGES = [
    ("pywinauto", "pywinauto"),
    ("win32gui", "pywin32"),
    ("win32con", "pywin32"),
    ("pyautogui", "pyautogui"),
]


def package_installed(import_name: str) -> bool:
    return importlib.util.find_spec(import_name) is not None


def install_package(package_name: str) -> None:
    subprocess.check_call([
        sys.executable,
        "-m",
        "pip",
        "install",
        package_name,
    ])


def check_and_install_packages() -> None:
    missing = [
        (import_name, pip_name)
        for import_name, pip_name in REQUIRED_PACKAGES
        if not package_installed(import_name)
    ]

    if not missing:
        return

    root = tk.Tk()
    root.withdraw()

    names = "\n".join(pip_name for _, pip_name in missing)

    ok = messagebox.askyesno(
        "Missing packages",
        "Some required packages are missing:\n\n"
        f"{names}\n\n"
        "Press YES to install them now."
    )

    if not ok:
        raise SystemExit("Missing packages. Program cannot start.")

    for _, pip_name in missing:
        install_package(pip_name)

    messagebox.showinfo(
        "Packages installed",
        "Packages installed successfully.\n\n"
        "The program will now continue."
    )

    root.destroy()


check_and_install_packages()

from pywinauto import Desktop
from automation_layer import setup_opensignals


BASE_DIR = Path(r"C:\Users\MoBI-Midtown")

LABRECORDER_EXE = BASE_DIR / "LabRecorder" / "LabRecorder.exe"

OPENSIGNALS_EXE = Path(
    r"C:\Plux\OpenSignals (r)evolution\OpenSignals.exe"
)

NEON_GUI_DIR = BASE_DIR / "neon-gui"

GRAPHOMOTOR_DIR = Path(
    r"C:\Users\MoBI-Midtown\graphomotor_CMI_mooi\src\graphomotor_protocol"
)

GRAPHOMOTOR_SCRIPT = (
    GRAPHOMOTOR_DIR / "graphomotor_older_mooi.py"
)

WINDOW_MX_DIR = Path(
    r"C:\Users\MoBI-Midtown\Automate\Graphomotor\Code"
)

AUTO_ARRANGE_SCRIPT = (
    WINDOW_MX_DIR / "auto_arrange_windows.py"
)

WINDOW_LAYOUT_JSON = (
    WINDOW_MX_DIR / "graphomotor_window_layout.json"
)

# Neon Scene Camera Recorder coordinates.
# These are the coordinates you gave:
# Filename textbox: -141, 246
# Connect device button: -186, 91
# Start recording button: -144, 274
NEON_CONNECT_DEVICE_BTN = (-186, 91)
NEON_FILENAME_TEXTBOX = (-141, 246)
NEON_START_RECORDING_BTN = (-144, 274)


def get_participant_id() -> str:
    root = tk.Tk()
    root.withdraw()

    participant_id = simpledialog.askstring(
        "Participant ID",
        "Enter participant ID:"
    )

    root.destroy()

    if not participant_id:
        raise SystemExit("No participant ID entered. Stopping launcher.")

    safe_id = (
        participant_id.strip()
        .upper()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
    )

    return safe_id


def make_recording_name(participant_id: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{participant_id}_{timestamp}"


def wait_for_window(title_contains: str, timeout: int = 30):
    print(f"[WAIT] Waiting for window containing: {title_contains}")

    end_time = time.time() + timeout

    while time.time() < end_time:
        try:
            win = Desktop(backend="uia").window(
                title_re=f".*{title_contains}.*"
            )

            if win.exists(timeout=1):
                print(f"[FOUND] Window: {title_contains}")
                return win

        except Exception:
            pass

        time.sleep(1)

    print(f"[WARN] Could not find window: {title_contains}")
    return None


def setup_neon_recording(recording_name: str) -> None:
    """
    Set Neon Scene Camera Recorder filename and press Start Recording.

    Order:
    1. Focus Neon window
    2. Press Connect Device
    3. Clear filename textbox
    4. Insert participantID_timestamp
    5. Press Start Recording
    """

    import pyautogui

    print("[INFO] Setting up Neon Scene Camera Recorder...")
    print(f"[INFO] Neon recording name: {recording_name}")

    win = wait_for_window("Neon Scene Camera Recorder", timeout=45)

    if win is None:
        print("[ERROR] Neon Scene Camera Recorder window not found.")
        messagebox.showwarning(
            "Neon not found",
            "Could not find the Neon Scene Camera Recorder window.\n\n"
            "Please start Neon manually and then start recording manually."
        )
        return

    try:
        win.set_focus()
        time.sleep(1)
    except Exception:
        pass

    pyautogui.PAUSE = 0.35

    print("[INFO] Clicking Neon Connect Device...")
    pyautogui.moveTo(*NEON_CONNECT_DEVICE_BTN, duration=0.15)
    pyautogui.click()
    time.sleep(2)

    print("[INFO] Clearing and entering Neon filename...")
    pyautogui.moveTo(*NEON_FILENAME_TEXTBOX, duration=0.15)
    pyautogui.click()
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.2)
    pyautogui.press("backspace")
    time.sleep(0.2)
    pyautogui.write(recording_name, interval=0.03)
    time.sleep(0.8)

    print("[INFO] Clicking Neon Start Recording...")
    pyautogui.moveTo(*NEON_START_RECORDING_BTN, duration=0.15)
    pyautogui.click()
    time.sleep(2)

    print("[OK] Neon recording start attempted.")


def setup_labrecorder_filename_and_start(recording_name: str) -> None:
    """
    Sets the LabRecorder filename to participantID_timestamp and presses Start.

    If LabRecorder controls differ on this computer, it will ask the operator
    to enter the filename manually and then it will still try to press Start.
    """

    print("[INFO] Setting LabRecorder filename...")
    print(f"[INFO] Recording name: {recording_name}")

    win = wait_for_window("Lab Recorder", timeout=30)

    if win is None:
        print("[ERROR] LabRecorder window not found. Cannot start LabRecorder.")
        return

    try:
        win.set_focus()
        time.sleep(0.5)
    except Exception:
        pass

    filename_set = False

    try:
        edits = win.descendants(control_type="Edit")
        print(f"[INFO] Found {len(edits)} editable fields in LabRecorder.")

        for edit in reversed(edits):
            try:
                edit.set_focus()
                edit.set_edit_text(recording_name)
                filename_set = True
                print("[OK] LabRecorder filename entered.")
                break
            except Exception:
                continue

    except Exception as e:
        print(f"[WARN] Could not set filename through Edit controls: {e}")

    if not filename_set:
        print("[WARN] Could not automatically find filename field.")
        try:
            print("[INFO] LabRecorder controls:")
            win.print_control_identifiers()
        except Exception as e:
            print(f"[WARN] Could not print controls: {e}")

        messagebox.showwarning(
            "LabRecorder filename",
            "Could not automatically enter the LabRecorder filename.\n\n"
            f"Please enter this manually:\n\n{recording_name}\n\n"
            "Then press OK here and the script will try to press Start."
        )

    print("[INFO] Starting LabRecorder recording...")

    started = False

    try:
        buttons = win.descendants(control_type="Button")

        for button in buttons:
            try:
                text = button.window_text().strip().lower()

                if "start" in text:
                    button.click_input()
                    started = True
                    print(f"[OK] Clicked LabRecorder button: {button.window_text()}")
                    break

            except Exception:
                continue

    except Exception as e:
        print(f"[WARN] Could not search LabRecorder buttons: {e}")

    if not started:
        print("[WARN] Could not automatically press LabRecorder Start.")
        messagebox.showwarning(
            "LabRecorder Start",
            "Could not automatically press Start in LabRecorder.\n\n"
            "Please press Start manually now."
        )


class GraphomotorSessionLauncher:
    def __init__(self) -> None:
        self.processes: list[subprocess.Popen] = []

    def start_file(self, path: Path) -> subprocess.Popen:
        print(f"[START] {path}")

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        proc = subprocess.Popen(
            ["cmd", "/c", "start", "", str(path)],
            shell=False,
        )

        self.processes.append(proc)
        return proc

    def start_powershell_command(self, command: str) -> subprocess.Popen:
        print(f"[START] PowerShell command: {command}")

        proc = subprocess.Popen(
            [
                "powershell",
                "-NoExit",
                "-Command",
                command,
            ],
            shell=False,
        )

        self.processes.append(proc)
        return proc

    def launch_neon(self) -> None:
        """
        Launch Neon the same way as the older working launcher:
        cd into C:\\Users\\MoBI-Midtown\\neon-gui, then run uv run main.py.
        """
        print("[INFO] Opening Neon Scene Camera Recorder...")

        self.start_powershell_command(
            f"cd '{NEON_GUI_DIR}'; uv run main.py"
        )

        print("[WAIT] Waiting for Neon Scene Camera Recorder to open...")

        neon_found = False

        for _ in range(45):
            try:
                win = Desktop(backend="uia").window(
                    title_re=".*Neon Scene Camera Recorder.*"
                )

                if win.exists(timeout=1):
                    print("[FOUND] Neon Scene Camera Recorder")
                    neon_found = True
                    break

            except Exception:
                pass

            time.sleep(1)

        if not neon_found:
            print("[WARN] Neon did not appear within 45 seconds.")
            print("[WARN] Continuing anyway. Check the Neon PowerShell window for errors.")

    def launch_apps(self) -> None:
        print("[INFO] Opening LabRecorder...")
        self.start_file(LABRECORDER_EXE)

        time.sleep(1)

        print("[INFO] Opening OpenSignals...")
        self.start_file(OPENSIGNALS_EXE)

        time.sleep(1)

        self.launch_neon()

        time.sleep(2)

        print("[INFO] Opening Graphomotor...")
        self.start_powershell_command(
            f"cd '{GRAPHOMOTOR_DIR}'; "
            f"python '{GRAPHOMOTOR_SCRIPT}'"
        )

    def wait_for_apps(self, seconds: int = 8) -> None:
        print(f"[WAIT] Waiting {seconds} seconds for apps to settle...")
        time.sleep(seconds)

    def apply_window_layout(self) -> None:
        if not AUTO_ARRANGE_SCRIPT.exists():
            print(
                f"[WARN] auto_arrange_windows.py not found: "
                f"{AUTO_ARRANGE_SCRIPT}"
            )
            return

        if not WINDOW_LAYOUT_JSON.exists():
            print(
                f"[WARN] Layout JSON not found: "
                f"{WINDOW_LAYOUT_JSON}"
            )
            return

        command = (
            f"python '{AUTO_ARRANGE_SCRIPT}' "
            f"apply --config '{WINDOW_LAYOUT_JSON}'"
        )

        print("[INFO] Applying saved window layout...")
        self.start_powershell_command(command)

    def run(self) -> None:
        print("=" * 60)
        print("[INFO] Starting Graphomotor automation...")
        print("=" * 60)

        participant_id = get_participant_id()
        recording_name = make_recording_name(participant_id)

        print(f"[INFO] Participant ID: {participant_id}")
        print(f"[INFO] Recording filename: {recording_name}")

        self.launch_apps()

        self.wait_for_apps(8)

        self.apply_window_layout()

        print("[WAIT] Waiting before recording automation...")
        time.sleep(2)

        print("[INFO] Running OpenSignals setup first...")
        setup_opensignals()
        print("[OK] OpenSignals recording should now be started.")

        time.sleep(1)

        print("[INFO] Now setting Neon filename and starting Neon recording...")
        setup_neon_recording(recording_name)

        time.sleep(1)

        print("[INFO] Now setting LabRecorder filename and starting LabRecorder...")
        setup_labrecorder_filename_and_start(recording_name)

        print("=" * 60)
        print("[DONE] Graphomotor session ready.")
        print("[DONE] OpenSignals recording started first.")
        print("[DONE] Neon filename/start attempted second.")
        print("[DONE] LabRecorder filename/start attempted third.")
        print("[DONE] Graphomotor protocol running.")
        print("=" * 60)


if __name__ == "__main__":
    launcher = GraphomotorSessionLauncher()
    launcher.run()
