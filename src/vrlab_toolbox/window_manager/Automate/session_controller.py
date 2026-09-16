from __future__ import annotations

import subprocess
import time
from pathlib import Path

from automation_layer import setup_opensignals, setup_labrecorder


BASE_DIR = Path.home()

LABRECORDER_EXE = BASE_DIR / "LabRecorder" / "LabRecorder.exe"
DSI_STREAMER_EXE = BASE_DIR / "Desktop" / "Software" / "DSI-Streamer-v.1.08.120" / "DSI-Streamer-v.1.08.120.exe"
DSI_LSL_GUI_SHORTCUT = BASE_DIR / "Desktop" / "dsi2lslgui - Shortcut.lnk"
NEON_GUI_DIR = BASE_DIR / "neon-gui"
MINDLOGGER_RELAY_SCRIPT = BASE_DIR / "Desktop" / "Mindlogger-lsl" / "mindlogger_relay.py"
AUDIO_VIDEO_RECORDER_EXE = BASE_DIR / "Desktop" / "mobi_video_audio_stream" / "dist" / "AudioVideoRecorder.exe"
BIOSIGNALS_API_DIR = BASE_DIR / "MoBI-Physio-API"
FOH_EXE = Path(r"C:\Program Files (x86)\FOH\AxioBiofeedback.exe")
OPENSIGNALS_EXE = Path(r"C:\Plux\OpenSignals (r)evolution\OpenSignals.exe")

WINDOW_MX_DIR = BASE_DIR / "window_mx"
AUTO_ARRANGE_SCRIPT = WINDOW_MX_DIR / "auto_arrange_windows.py"
WINDOW_LAYOUT_JSON = WINDOW_MX_DIR / "window_layout.json"


class SessionLauncher:
    def __init__(self) -> None:
        self.processes: list[subprocess.Popen] = []

    def start_file(self, path: Path) -> subprocess.Popen:
        print(f"[START] {path}")
        proc = subprocess.Popen(
            ["cmd", "/c", "start", "", str(path)],
            shell=False
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
            shell=False
        )
        self.processes.append(proc)
        return proc

    def launch_core_apps(self) -> None:
        self.start_file(LABRECORDER_EXE)
        self.start_file(DSI_STREAMER_EXE)
        self.start_file(DSI_LSL_GUI_SHORTCUT)

        self.start_powershell_command(
            f"cd '{NEON_GUI_DIR}'; uv run main.py"
        )

        self.start_powershell_command(
            f"uv run '{MINDLOGGER_RELAY_SCRIPT}'"
        )

        self.start_file(AUDIO_VIDEO_RECORDER_EXE)

        self.start_powershell_command(
            f"cd '{BIOSIGNALS_API_DIR}'; uv run --python 3.10 mobi-physio-api --help"
        )

        self.start_file(FOH_EXE)
        self.start_file(OPENSIGNALS_EXE)

    def wait_for_apps(self, seconds: int = 10) -> None:
        print(f"[WAIT] Waiting {seconds} seconds for apps to open...")
        time.sleep(seconds)

    def apply_window_layout(self) -> None:
        command = (
            f"python '{AUTO_ARRANGE_SCRIPT}' apply --config '{WINDOW_LAYOUT_JSON}'"
        )
        self.start_powershell_command(command)

    def run(self) -> None:
        print("[INFO] Launching session apps...")
        self.launch_core_apps()

        print("[INFO] Click VIVE permission manually if it appears.")
        self.wait_for_apps(10)

        print("[INFO] Applying window layout...")
        self.apply_window_layout()

        time.sleep(3)

        participant_id = "TEST001"
        print(f"[INFO] Using participant ID: {participant_id}")

        print("[INFO] Setting up OpenSignals...")
        setup_opensignals()

        time.sleep(2)

        print("[INFO] Setting up LabRecorder...")
        setup_labrecorder(participant_id)

        print("[DONE] Session setup complete.")


if __name__ == "__main__":
    launcher = SessionLauncher()
    launcher.run()