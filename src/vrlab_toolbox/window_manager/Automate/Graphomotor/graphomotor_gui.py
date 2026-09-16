from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

# Reliable when started from a .bat file / desktop shortcut
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
os.chdir(CURRENT_DIR)

from pywinauto import Application, Desktop
from automation_layer import setup_opensignals
from signal_checker import OpenSignalsHealthChecker


BASE_DIR = Path.home()
LABRECORDER_EXE = BASE_DIR / "LabRecorder" / "LabRecorder.exe"
OPENSIGNALS_EXE = Path(r"C:\Plux\OpenSignals (r)evolution\OpenSignals.exe")

# DSI EEG apps
DSI_STREAMER_EXE = BASE_DIR / "Desktop" / "Software" / "DSI-Streamer-v.1.08.120" / "DSI-Streamer-v.1.08.120.exe"
DSI_LSL_GUI_SHORTCUT = BASE_DIR / "Desktop" / "dsi2lslgui - Shortcut.lnk"

# DSI Streamer coordinates: connect headset, then open electrode diagnostic quality screen.
DSI_STREAMER_CONNECT_BUTTON = (-1505, 606)
DSI_STREAMER_DIAGNOSTIC_BUTTON = (-1115, 632)

# DSI2LSL coordinates: set COM port, set stream name, then start LSL stream.
DSI2LSL_COM_TEXTBOX = (-1308, 769)
DSI2LSL_STREAM_NAME_TEXTBOX = (-1322, 798)
DSI2LSL_START_BUTTON = (-1161, 996)
DSI2LSL_COM_PORT = "COM7"
DSI2LSL_STREAM_NAME = "EEG"

# Processes that often keep COM7 locked after a previous participant.
COM7_LOCK_TOKENS = [
    "dsi2lsl",
    "DSI2LSL",
    "DSI-Streamer",
    "DSI Streamer",
    "COM7",
]

DSI_PROCESS_NAMES_TO_KILL = [
    "dsi2lslgui.exe",
    "DSI2LSL.exe",
    "DSI-Streamer-v.1.08.120.exe",
]

DSI_COMMANDLINE_TOKENS_TO_KILL = [
    "dsi2lsl",
    "DSI2LSL",
    "DSI-Streamer",
    "DSI Streamer",
    "COM7",
]

# Neon app
NEON_DIR = BASE_DIR / "neon-gui"
NEON_PYTHON = NEON_DIR / ".venv" / "Scripts" / "python.exe"
NEON_SCRIPT = NEON_DIR / "main.py"

# Absolute screen coordinates for Neon on the saved monitor layout.
# These are the coordinates you gave.
NEON_FILENAME_BOX = (-141, 246)
NEON_CONNECT_DEVICE_BUTTON = (-186, 91)
NEON_START_RECORDING_BUTTON = (-144, 274)
NEON_STOP_RECORDING_BUTTON = (-197, 304)

OPENSIGNALS_POSITION_TOLERANCE = 45

MINDLOGGER_RELAY_SCRIPT = BASE_DIR / "Desktop" / "Mindlogger-lsl" / "mindlogger_relay.py"

GRAPHOMOTOR_DIR = BASE_DIR / "graphomotor_CMI_mooi" / "src" / "graphomotor_protocol"
GRAPHOMOTOR_SCRIPT = GRAPHOMOTOR_DIR / "graphomotor_older_mooi.py"

WINDOW_MX_DIR = BASE_DIR / "Automate" / "Graphomotor" / "Code"
AUTO_ARRANGE_SCRIPT = WINDOW_MX_DIR / "auto_arrange_windows.py"
WINDOW_LAYOUT_JSON = WINDOW_MX_DIR / "graphomotor_window_layout.json"

REQUIRED_STREAMS = [
    "MindLogger",
    "OpenSignals",
    "experiment_stream",
    "Neon Companion_Neon Gaze",
    "Neon Companion_Neon Events",
    # DSI/dsi2lsl usually appears in LabRecorder as EEG.
    # If your LabRecorder shows a different name, change "EEG" to that exact stream name.
    "EEG",
]

# Neon is allowed to be bypassed for a participant if the device cannot be recovered.
# All other REQUIRED_STREAMS remain mandatory.
NEON_STREAMS = [
    "Neon Companion_Neon Gaze",
    "Neon Companion_Neon Events",
]

# iPad/MindLogger live-data check:
# Starts only AFTER LabRecorder recording is confirmed.
# Then waits 60 seconds, watches for live samples briefly, and warns if no samples arrive.
IPAD_STREAM_NAME = "MindLogger"
IPAD_CHECK_DELAY_AFTER_LABRECORDER_SEC = 60
# iPad monitoring runs continuously after the 60-second startup delay.
IPAD_SAMPLE_TIMEOUT_SEC = 8
IPAD_DISMISS_SEC = 60

PROCESSES_TO_CLOSE = [
    # Main apps
    "OpenSignals.exe",
    "LabRecorder.exe",
    "DSI-Streamer-v.1.08.120.exe",
    "dsi2lslgui.exe",
    "DSI2LSL.exe",
    # Sometimes DSI2LSL / relays run inside Python or terminal shells.
    "python.exe",
    "pythonw.exe",
    "py.exe",
    # Terminals opened by this automation
    "powershell.exe",
    "pwsh.exe",
    "cmd.exe",
    "WindowsTerminal.exe",
    "wt.exe",
]

SCRIPT_TOKENS_TO_CLOSE = [
    "graphomotor_older_mooi.py",
    "mindlogger_relay.py",
    "auto_arrange_windows.py",
    "dsi2lslgui",
    "DSI2LSL",
    "main.py",  # Neon GUI main.py only when command-line token matches
]

WINDOW_TITLE_PATTERNS_TO_CLOSE = [
    ".*OpenSignals.*",
    ".*Lab Recorder.*",
    ".*LabRecorder.*",
    ".*DSI-Streamer.*",
    ".*DSI Streamer.*",
    ".*DSI2LSL.*",
    ".*dsi2lsl.*",
    ".*Neon.*",
    ".*Pupil.*",
    ".*Graphomotor Protocol.*",
    ".*graphomotor.*",
    ".*Spiral.*",
    ".*Windows PowerShell.*",
    ".*Command Prompt.*",
]

APP_BG = "#101820"
NEXT_BG = "#fff3b0"
DISABLED_BG = "#d0d0d0"
GREEN = "#1f7a3a"
BLUE = "#27548a"
YELLOW_DARK = "#8a6d27"
RED = "#8a2727"
GREY = "#6b7280"


class BigChecklistDialog:
    """Large centered checklist popup where the Continue button is always visible."""

    def __init__(
        self,
        parent: tk.Tk,
        title: str,
        heading: str,
        items: list[tuple[str, str]],
        help_text: str | None = None,
        continue_text: str = "CONTINUE",
    ) -> None:
        self.parent = parent
        self.result = False
        self.vars: dict[str, tk.BooleanVar] = {key: tk.BooleanVar(value=False) for key, _ in items}

        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.configure(bg=APP_BG)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.attributes("-topmost", True)
        self.win.resizable(True, True)

        # Big centered window, but never larger than the screen.
        # This prevents the Continue button from being hidden.
        screen_w = self.win.winfo_screenwidth()
        screen_h = self.win.winfo_screenheight()
        width = min(1180, screen_w - 80)
        height = min(820, screen_h - 90)
        x = max(0, int((screen_w - width) / 2))
        y = max(0, int((screen_h - height) / 2))
        self.win.geometry(f"{width}x{height}+{x}+{y}")
        self.win.minsize(min(980, width), min(620, height))

        # Buttons are packed first at the bottom so they are always visible.
        buttons = tk.Frame(self.win, bg=APP_BG)
        buttons.pack(fill="x", side="bottom", padx=35, pady=(10, 24))

        self.continue_button = tk.Button(
            buttons,
            text=continue_text,
            command=self.on_continue,
            font=("Segoe UI", 19, "bold"),
            bg=DISABLED_BG,
            fg="#333333",
            disabledforeground="#333333",
            state="disabled",
            padx=34,
            pady=8,
        )
        self.continue_button.pack(side="right")

        tk.Button(
            buttons,
            text="CANCEL",
            command=self.on_cancel,
            font=("Segoe UI", 16, "bold"),
            bg=RED,
            fg="white",
            padx=26,
            pady=12,
        ).pack(side="right", padx=(0, 14))

        content = tk.Frame(self.win, bg=APP_BG)
        content.pack(fill="both", expand=True, padx=35, pady=(25, 8))

        tk.Label(
            content,
            text=heading,
            font=("Segoe UI", 24, "bold"),
            bg=APP_BG,
            fg="white",
            wraplength=width - 120,
            justify="left",
        ).pack(anchor="w", pady=(0, 14))

        item_font_size = 18 if len(items) <= 5 else 16

        box = tk.Frame(content, bg=APP_BG)
        box.pack(fill="x")

        for key, label in items:
            cb = tk.Checkbutton(
                box,
                text=label,
                variable=self.vars[key],
                command=self.update_continue_state,
                font=("Segoe UI", item_font_size, "bold"),
                bg=APP_BG,
                fg="white",
                selectcolor="#1f2937",
                activebackground=APP_BG,
                activeforeground="white",
                anchor="w",
                padx=8,
                pady=5,
            )
            cb.pack(fill="x", anchor="w")

        if help_text:
            help_frame = tk.LabelFrame(
                content,
                text=" If something is not working ",
                font=("Segoe UI", 15, "bold"),
                bg=APP_BG,
                fg="#facc15",
                padx=18,
                pady=6,
            )
            help_frame.pack(fill="both", expand=True, pady=(16, 0))

            tk.Label(
                help_frame,
                text=help_text,
                font=("Segoe UI", 14, "bold"),
                bg=APP_BG,
                fg="white",
                wraplength=width - 120,
                justify="left",
                anchor="nw",
            ).pack(anchor="nw", fill="both", expand=True)

        self.win.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.win.lift()
        self.win.focus_force()

    def update_continue_state(self) -> None:
        if all(v.get() for v in self.vars.values()):
            self.continue_button.config(state="normal", bg=GREEN, fg="white")
        else:
            self.continue_button.config(state="disabled", bg=DISABLED_BG, fg="#333333")

    def on_continue(self) -> None:
        self.result = True
        self.win.destroy()

    def on_cancel(self) -> None:
        self.result = False
        self.win.destroy()

    def show(self) -> bool:
        self.parent.wait_window(self.win)
        return self.result


class BigInfoDialog:
    """Large one-button instruction popup."""

    def __init__(
        self,
        parent: tk.Tk,
        title: str,
        heading: str,
        body: str,
        button_text: str = "DONE",
        bg: str = APP_BG,
        fg: str = "white",
    ) -> None:
        self.parent = parent
        self.result = False
        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.configure(bg=bg)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.attributes("-topmost", True)
        self.win.resizable(True, True)

        screen_w = self.win.winfo_screenwidth()
        screen_h = self.win.winfo_screenheight()
        width = min(1250, screen_w - 70)
        height = min(850, screen_h - 80)
        x = max(0, int((screen_w - width) / 2))
        y = max(0, int((screen_h - height) / 2))
        self.win.geometry(f"{width}x{height}+{x}+{y}")

        content = tk.Frame(self.win, bg=bg)
        content.pack(fill="both", expand=True, padx=55, pady=45)

        tk.Label(
            content,
            text=heading,
            font=("Segoe UI", 44, "bold"),
            bg=bg,
            fg=fg,
            justify="center",
            wraplength=width - 140,
        ).pack(pady=(0, 25))

        tk.Label(
            content,
            text=body,
            font=("Segoe UI", 30, "bold"),
            bg=bg,
            fg=fg,
            justify="left",
            wraplength=width - 140,
        ).pack(expand=True, fill="both")

        tk.Button(
            content,
            text=button_text,
            command=self.on_continue,
            font=("Segoe UI", 30, "bold"),
            bg=GREEN,
            fg="white",
            padx=38,
            pady=18,
        ).pack(side="bottom", fill="x", pady=(20, 0))

        self.win.protocol("WM_DELETE_WINDOW", self.on_continue)
        self.win.lift()
        self.win.focus_force()

    def on_continue(self) -> None:
        self.result = True
        self.win.destroy()

    def show(self) -> bool:
        self.parent.wait_window(self.win)
        return self.result


class BigChoiceDialog:
    """Large popup with one or two clear action buttons."""

    def __init__(
        self,
        parent: tk.Tk,
        title: str,
        heading: str,
        body: str,
        primary_text: str,
        secondary_text: str | None = None,
        bg: str = APP_BG,
        fg: str = "white",
    ) -> None:
        self.parent = parent
        self.result: str | None = None
        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.configure(bg=bg)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.attributes("-topmost", True)
        self.win.resizable(True, True)

        screen_w = self.win.winfo_screenwidth()
        screen_h = self.win.winfo_screenheight()
        width = min(1250, screen_w - 70)
        height = min(850, screen_h - 80)
        x = max(0, int((screen_w - width) / 2))
        y = max(0, int((screen_h - height) / 2))
        self.win.geometry(f"{width}x{height}+{x}+{y}")

        content = tk.Frame(self.win, bg=bg)
        content.pack(fill="both", expand=True, padx=55, pady=45)

        tk.Label(
            content,
            text=heading,
            font=("Segoe UI", 44, "bold"),
            bg=bg,
            fg=fg,
            justify="center",
            wraplength=width - 140,
        ).pack(pady=(0, 25))

        tk.Label(
            content,
            text=body,
            font=("Segoe UI", 28, "bold"),
            bg=bg,
            fg=fg,
            justify="left",
            wraplength=width - 140,
        ).pack(expand=True, fill="both")

        buttons = tk.Frame(content, bg=bg)
        buttons.pack(fill="x", pady=(24, 0))

        if secondary_text:
            tk.Button(
                buttons,
                text=secondary_text,
                command=lambda: self.choose("secondary"),
                font=("Segoe UI", 24, "bold"),
                bg=GREY,
                fg="white",
                padx=28,
                pady=16,
            ).pack(side="left", expand=True, fill="x", padx=(0, 12))

        tk.Button(
            buttons,
            text=primary_text,
            command=lambda: self.choose("primary"),
            font=("Segoe UI", 24, "bold"),
            bg=GREEN,
            fg="white",
            padx=28,
            pady=16,
        ).pack(side="left", expand=True, fill="x", padx=(12 if secondary_text else 0, 0))

        self.win.protocol("WM_DELETE_WINDOW", lambda: self.choose("secondary" if secondary_text else "primary"))
        self.win.lift()
        self.win.focus_force()

    def choose(self, value: str) -> None:
        self.result = value
        self.win.destroy()

    def show(self) -> str:
        self.parent.wait_window(self.win)
        return self.result or "primary"

class GraphomotorGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Graphomotor Session Setup")
        self.root.attributes("-fullscreen", True)
        self.root.configure(bg=APP_BG)

        self.participant_id_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Ready.")
        self.progress_var = tk.DoubleVar(value=0)
        self.warning_var = tk.StringVar(value="Follow the instruction in the yellow box.")
        self.next_instruction_var = tk.StringVar(value="Enter participant ID, then press START SETUP.")
        self.next_button_text_var = tk.StringVar(value="NEXT")
        self.current_phase = "start_setup"
        self.busy = False

        self.processes: list[subprocess.Popen] = []
        self.graphomotor_started = False
        self.cleanup_started = False
        self.neon_started_by_gui = False
        self.eda_checked_once = False
        self.recording_is_running = False

        # Per-participant data-quality decisions.
        # These are reset before the next participant.
        self.session_warnings: list[str] = []
        self.eda_bypassed = False
        self.neon_bypassed = False

        self.wait_overlay: tk.Toplevel | None = None
        self.wait_overlay_text_var = tk.StringVar(value="WAIT\nDO NOT TOUCH THE MOUSE")

        self.signal_alert: tk.Toplevel | None = None
        self.signal_alert_text_var = tk.StringVar(value="")
        self._last_signal_bad_time = 0.0

        self.ipad_alert: tk.Toplevel | None = None
        self.ipad_alert_text_var = tk.StringVar(value="")
        self.ipad_monitor_stop = threading.Event()
        self.ipad_monitor_started = False
        self.ipad_alert_snoozed_until = 0.0

        # Persistent preparation checklist. This stays visible while the software opens.
        self.prep_window: tk.Toplevel | None = None
        self.prep_ready_event = threading.Event()
        self.prep_vars: dict[str, tk.BooleanVar] = {}
        self.prep_ready_button: tk.Button | None = None
        self.prep_status_var = tk.StringVar(value="Tick all items before the EEG connection starts.")
        self.prep_keepalive_job: str | None = None
        self.prep_confirmed = False

        self.signal_checker = OpenSignalsHealthChecker(
            check_every_sec=1.0,
            window_sec=8.0,
            on_status=self.handle_signal_status,
        )

        self.steps: dict[str, tk.StringVar] = {}
        self.reset_step_texts()

        self.next_button: tk.Button | None = None
        self.stop_button: tk.Button | None = None
        self.start_button_hidden = False
        self.advanced_visible = False
        self.advanced_frame: tk.Frame | None = None

        self.build_ui()
        self.set_initial_button_states()

    def reset_step_texts(self) -> None:
        self.steps = {
            "participant": tk.StringVar(value="☐ Participant ID"),
            "apps": tk.StringVar(value="☐ Open apps"),
            "device": tk.StringVar(value="☐ EDA/ECG ready"),
            "dsi": tk.StringVar(value="☐ DSI EEG ready"),
            "neon": tk.StringVar(value="☐ Neon recording"),
            "opensignals": tk.StringVar(value="☐ OpenSignals recording"),
            "labrecorder": tk.StringVar(value="☐ LabRecorder ready"),
            "ipad": tk.StringVar(value="☐ iPad submitted"),
            "streams": tk.StringVar(value="☐ Streams checked"),
            "task": tk.StringVar(value="☐ Task started"),
            "cleanup": tk.StringVar(value="☐ Session closed safely"),
        }

    def build_ui(self) -> None:
        """Very simple researcher-facing screen.

        The user only sees: participant ID, START, and STOP/CLOSE EVERYTHING.
        All technical setup details go to the hidden advanced log only.
        """
        outer = tk.Frame(self.root, bg=APP_BG)
        outer.pack(fill="both", expand=True, padx=80, pady=55)

        tk.Label(
            outer,
            text="Graphomotor Session",
            font=("Segoe UI", 40, "bold"),
            bg=APP_BG,
            fg="white",
        ).pack(anchor="center", pady=(10, 35))

        card = tk.Frame(outer, bg="#182430")
        card.pack(anchor="center", fill="x", padx=120, pady=(10, 30))

        tk.Label(
            card,
            text="Participant ID",
            font=("Segoe UI", 32, "bold"),
            bg="#182430",
            fg="white",
        ).pack(anchor="center", pady=(35, 10))

        tk.Entry(
            card,
            textvariable=self.participant_id_var,
            font=("Segoe UI", 44, "bold"),
            width=18,
            justify="center",
        ).pack(anchor="center", ipady=12, pady=(0, 35))
        self.participant_id_var.trace_add("write", lambda *_: self.update_next_button_state())

        buttons = tk.Frame(card, bg="#182430")
        buttons.pack(fill="x", padx=55, pady=(0, 45))

        self.next_button = tk.Button(
            buttons,
            text="START",
            command=self.thread_next_action,
            font=("Segoe UI", 38, "bold"),
            bg=GREEN,
            fg="white",
            padx=60,
            pady=22,
        )
        self.next_button.pack(side="left", expand=True, fill="x", padx=(0, 16))

        self.stop_button = tk.Button(
            buttons,
            text="STOP / CLOSE EVERYTHING",
            command=self.thread_exit_program,
            font=("Segoe UI", 26, "bold"),
            bg=RED,
            fg="white",
            padx=35,
            pady=22,
        )
        self.stop_button.pack(side="left", expand=True, fill="x", padx=(16, 0))

        tk.Label(
            outer,
            text="After START, follow only the big screens. Do not press anything during WAIT.",
            font=("Segoe UI", 24, "bold"),
            bg=APP_BG,
            fg="white",
            justify="center",
            wraplength=1300,
        ).pack(anchor="center", pady=(15, 0))

        # Hidden variables/widgets kept so existing logging code does not break.
        self.next_instruction_var.set("Enter participant ID, then press START.")
        self.warning_var.set("")
        self.status_var.set("Ready.")

        self.advanced_frame = tk.Frame(outer, bg=APP_BG)
        self.log_text = tk.Text(self.advanced_frame, height=7, wrap="word", font=("Consolas", 12), bg="white", fg="black")
        self.log_text.pack(fill="both", expand=True, pady=(8, 0))

        bottom = tk.Frame(outer, bg=APP_BG)
        bottom.pack(fill="x", side="bottom", pady=(20, 0))
        tk.Button(
            bottom,
            text="Advanced / Show details",
            command=self.toggle_advanced,
            font=("Segoe UI", 12, "bold"),
            bg=GREY,
            fg="white",
            padx=14,
            pady=8,
        ).pack(side="left")
        tk.Button(
            bottom,
            text="Exit Full Screen",
            command=lambda: self.root.attributes("-fullscreen", False),
            font=("Segoe UI", 12, "bold"),
            bg="#444444",
            fg="white",
            padx=14,
            pady=8,
        ).pack(side="right")

    def toggle_advanced(self) -> None:
        if self.advanced_frame is None:
            return
        if self.advanced_visible:
            self.advanced_frame.pack_forget()
            self.advanced_visible = False
        else:
            self.advanced_frame.pack(fill="both", expand=True, pady=(8, 0))
            self.advanced_visible = True

    def set_initial_button_states(self) -> None:
        self.set_phase("start_setup", "START")
        self.update_next_button_state()

    def set_phase(self, phase: str, button_text: str = "NEXT") -> None:
        self.current_phase = phase
        self.next_button_text_var.set(button_text)
        self.update_next_button_state()

    def update_next_button_state(self) -> None:
        if self.next_button is None or self.start_button_hidden:
            return
        if self.busy or self.current_phase == "task_running":
            self.disable_button(self.next_button)
            return
        needs_pid = self.current_phase in {"start_setup", "check_streams", "start_task"}
        if needs_pid and not self.participant_id_var.get().strip():
            self.disable_button(self.next_button)
        else:
            self.enable_button(self.next_button)

    def disable_button(self, button: tk.Button | None) -> None:
        if button is not None:
            button.config(state="disabled", bg=DISABLED_BG, fg="#333333")

    def enable_button(self, button: tk.Button | None) -> None:
        if button is not None:
            original_bg = getattr(button, "original_bg", None)
            if original_bg is None:
                original_bg = button.cget("bg")
                button.original_bg = original_bg
            button.config(state="normal", bg=original_bg, fg="white")

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.update_next_button_state()

    def set_next_instruction(self, message: str) -> None:
        self.next_instruction_var.set(message)
        self.root.update_idletasks()

    def set_step(self, key: str, state: str, text: str) -> None:
        symbol = {"todo": "☐", "busy": "⏳", "done": "✅", "warn": "⚠", "error": "❌"}.get(state, "☐")
        self.steps[key].set(f"{symbol} {text}")
        self.root.update_idletasks()

    def log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.status_var.set(message)
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.root.update_idletasks()

    def set_progress(self, value: float, message: str) -> None:
        self.progress_var.set(value)
        self.log(message)

    def add_session_warning(self, message: str) -> None:
        """Remember a participant-specific data warning for the end-of-session summary."""
        if message not in self.session_warnings:
            self.session_warnings.append(message)
        self.log(f"SESSION WARNING: {message}")

    def get_required_streams_for_session(self) -> list[str]:
        """Return required LabRecorder streams, excluding Neon only when explicitly bypassed."""
        if self.neon_bypassed:
            return [stream for stream in REQUIRED_STREAMS if stream not in NEON_STREAMS]
        return list(REQUIRED_STREAMS)

    def build_session_summary(self) -> str:
        """Build the message shown after recordings have been stopped safely."""
        lines = ["Done. Recordings were stopped safely."]

        if self.session_warnings:
            lines.extend(["", "DATA WARNINGS FOR THIS PARTICIPANT:"])
            for warning in self.session_warnings:
                lines.append(f"• {warning}")
            lines.extend(["", "Please note these issues in the participant log."])
        else:
            lines.extend(["", "No EDA or Neon bypasses were recorded during setup."])

        return "\n".join(lines)

    def show_mouse_warning(self) -> None:
        self.warning_var.set("⚠ STOP. DO NOT TOUCH THE MOUSE. ⚠")
        self.show_wait_overlay("WAIT\nDO NOT TOUCH THE MOUSE")

    def hide_mouse_warning(self) -> None:
        self.hide_wait_overlay()
        self.warning_var.set("")
        self.root.update_idletasks()

    # Big WAIT overlay and signal warning screens
    def _get_monitor_geometry(self, prefer_secondary: bool = False) -> tuple[int, int, int, int]:
        try:
            from screeninfo import get_monitors

            monitors = get_monitors()
            if monitors:
                monitors = sorted(monitors, key=lambda m: (m.x, m.y))
                selected = monitors[-1] if prefer_secondary and len(monitors) > 1 else monitors[0]
                return int(selected.x), int(selected.y), int(selected.width), int(selected.height)
        except Exception:
            pass

        self.root.update_idletasks()
        return 0, 0, int(self.root.winfo_screenwidth()), int(self.root.winfo_screenheight())

    def _set_topmost_fullscreen(self, win: tk.Toplevel, prefer_secondary: bool = False) -> None:
        x, y, w, h = self._get_monitor_geometry(prefer_secondary=prefer_secondary)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.lift()
        try:
            win.focus_force()
        except Exception:
            pass

    def show_wait_overlay(self, message: str = "WAIT") -> None:
        """Plain full-screen WAIT screen.

        Most of the time the user only sees WAIT. During the eyes-closed phase,
        normal WAIT calls keep the eyes-closed instruction visible instead of
        replacing it or restarting anything.
        """
        def _show() -> None:
            display_message = message
            if getattr(self, "eyes_closed_message_visible", False) and message.strip() == "WAIT":
                display_message = "WAIT\n\nPARTICIPANT KEEPS EYES CLOSED\nUNTIL SETUP IS DONE"

            self.wait_overlay_text_var.set(display_message)

            if self.wait_overlay is not None and self.wait_overlay.winfo_exists():
                self.wait_overlay.deiconify()
                self._set_topmost_fullscreen(self.wait_overlay, prefer_secondary=False)
                return

            win = tk.Toplevel(self.root)
            win.configure(bg="#050505")
            self.wait_overlay = win
            self._set_topmost_fullscreen(win, prefer_secondary=False)

            holder = tk.Frame(win, bg="#050505")
            holder.pack(fill="both", expand=True, padx=55, pady=45)

            tk.Label(
                holder,
                textvariable=self.wait_overlay_text_var,
                font=("Segoe UI", 64, "bold"),
                bg="#050505",
                fg="#f5c542",
                justify="center",
                wraplength=1250,
            ).pack(expand=True)

            tk.Label(
                holder,
                text="DO NOT PRESS ANYTHING",
                font=("Segoe UI", 28, "bold"),
                bg="#050505",
                fg="white",
                justify="center",
                wraplength=1250,
            ).pack(pady=(0, 26))

        self.root.after(0, _show)
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            pass

    def hide_wait_overlay(self) -> None:
        def _hide() -> None:
            if self.wait_overlay is not None and self.wait_overlay.winfo_exists():
                self.wait_overlay.withdraw()

        self.root.after(0, _hide)

    def show_eyes_closed_timer(self) -> None:
        """Stable eyes-closed screen. No countdown, so it cannot restart or confuse users."""
        self.eyes_closed_message_visible = True
        self.show_wait_overlay("WAIT\n\nPARTICIPANT KEEPS EYES CLOSED\nUNTIL SETUP IS DONE")

    def update_eyes_closed_timer(self) -> None:
        # Kept only so older calls do not break. The timer was removed on purpose.
        return

    def hide_eyes_closed_timer(self) -> None:
        self.eyes_closed_message_visible = False
        self.show_wait_overlay("WAIT")


    def show_device_prep_checklist(self) -> None:
        """Simple required checklist before DSI connects."""
        self.prep_ready_event.clear()
        self.prep_confirmed = False
        self.prep_status_var.set("Tick each box. Then press the green button once.")

        def _show() -> None:
            if self.prep_window is not None and self.prep_window.winfo_exists():
                self.prep_window.deiconify()
                self.prep_window.attributes("-topmost", True)
                self.prep_window.lift()
                self.start_prep_keepalive()
                return

            win = tk.Toplevel(self.root)
            self.prep_window = win
            win.title("Participant ready")
            win.configure(bg="white")
            win.attributes("-topmost", True)
            win.resizable(True, True)

            screen_w = win.winfo_screenwidth()
            screen_h = win.winfo_screenheight()
            width = min(1350, screen_w - 70)
            height = min(880, screen_h - 70)
            x = max(0, int((screen_w - width) / 2))
            y = max(0, int((screen_h - height) / 2))
            win.geometry(f"{width}x{height}+{x}+{y}")
            win.minsize(min(980, width), min(680, height))

            outer = tk.Frame(win, bg="white")
            outer.pack(fill="both", expand=True, padx=52, pady=34)

            tk.Label(
                outer,
                text="CHECK PARTICIPANT",
                font=("Segoe UI", 32, "bold"),
                bg="white",
                fg="#111111",
                justify="center",
            ).pack(fill="x", pady=(0, 8))

            tk.Label(
                outer,
                text="Read each line out loud. Tick only after you checked it.",
                font=("Segoe UI", 22, "bold"),
                bg="white",
                fg="#7a0000",
                justify="center",
                wraplength=width - 120,
            ).pack(fill="x", pady=(0, 20))

            self.prep_vars = {
                "eda": tk.BooleanVar(value=False),
                "eeg_on_head": tk.BooleanVar(value=False),
                "eeg_power": tk.BooleanVar(value=False),
                "glasses": tk.BooleanVar(value=False),
                "phone": tk.BooleanVar(value=False),
            }

            items = [
                ("1", "eda", "White EDA/ECG box is ON", False),
                ("2", "eeg_on_head", "EEG headset is ON participant", False),
                ("3", "eeg_power", "PRESS EEG POWER BUTTON TWICE", True),
                ("4", "glasses", "Neon glasses are ON participant", False),
                ("5", "phone", "Neon phone is ON and awake", False),
            ]

            list_frame = tk.Frame(outer, bg="white")
            list_frame.pack(fill="both", expand=True, pady=(5, 8))

            for number, key, label, is_red in items:
                row = tk.Frame(list_frame, bg="white", highlightthickness=2, highlightbackground="#e5e7eb")
                row.pack(fill="x", pady=6)

                tk.Label(
                    row,
                    text=number,
                    font=("Segoe UI", 34, "bold"),
                    bg="#111111",
                    fg="white",
                    width=3,
                    pady=8,
                ).pack(side="left", padx=(0, 18))

                cb = tk.Checkbutton(
                    row,
                    text=label,
                    variable=self.prep_vars[key],
                    command=self.update_prep_ready_state,
                    font=("Segoe UI", 28, "bold"),
                    bg="white",
                    fg=("#b00000" if is_red else "#111111"),
                    selectcolor="#e5e7eb",
                    activebackground="white",
                    activeforeground=("#b00000" if is_red else "#111111"),
                    anchor="w",
                    justify="left",
                    wraplength=width - 260,
                    padx=12,
                    pady=6,
                )
                cb.pack(side="left", fill="x", expand=True)

            tk.Label(
                outer,
                textvariable=self.prep_status_var,
                font=("Segoe UI", 19, "bold"),
                bg="white",
                fg="#7a0000",
                justify="center",
                wraplength=width - 110,
            ).pack(fill="x", pady=(8, 10))

            self.prep_ready_button = tk.Button(
                outer,
                text="ALL CHECKED - START EEG CONNECTION",
                command=self.confirm_prep_ready,
                font=("Segoe UI", 26, "bold"),
                bg=DISABLED_BG,
                fg="#333333",
                disabledforeground="#333333",
                state="disabled",
                padx=26,
                pady=16,
            )
            self.prep_ready_button.pack(fill="x", pady=(4, 0))

            win.protocol("WM_DELETE_WINDOW", lambda: None)
            win.lift()
            try:
                win.focus_force()
            except Exception:
                pass
            self.start_prep_keepalive()

        self.root.after(0, _show)
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            pass

    def start_prep_keepalive(self) -> None:
        """Keep the prep checklist visible; prevents the disappear/reappear problem."""
        if self.prep_keepalive_job is not None:
            return

        def _keep_alive() -> None:
            self.prep_keepalive_job = None
            try:
                if self.prep_window is not None and self.prep_window.winfo_exists() and not self.prep_ready_event.is_set():
                    self.prep_window.deiconify()
                    self.prep_window.attributes("-topmost", True)
                    self.prep_window.lift()
                    # Do not steal focus constantly if user is clicking checkboxes, but keep it above apps.
                    self.prep_keepalive_job = self.root.after(300, _keep_alive)
            except Exception:
                self.prep_keepalive_job = self.root.after(300, _keep_alive)

        self.prep_keepalive_job = self.root.after(300, _keep_alive)

    def stop_prep_keepalive(self) -> None:
        if self.prep_keepalive_job is not None:
            try:
                self.root.after_cancel(self.prep_keepalive_job)
            except Exception:
                pass
            self.prep_keepalive_job = None

    def update_prep_ready_state(self) -> None:
        if not self.prep_vars or self.prep_ready_button is None:
            return
        if all(var.get() for var in self.prep_vars.values()):
            self.prep_ready_button.config(state="normal", bg=GREEN, fg="white")
            self.prep_status_var.set("Ready. Press the green button ONCE only.")
        else:
            self.prep_ready_button.config(state="disabled", bg=DISABLED_BG, fg="#333333")
            self.prep_status_var.set("Tick every item. EEG will not connect until this is confirmed.")

    def confirm_prep_ready(self) -> None:
        # Immediately change the screen so the user knows they clicked successfully.
        self.prep_ready_event.set()
        self.prep_confirmed = True
        self.prep_status_var.set("Confirmed. Do not press again.")
        self.stop_prep_keepalive()
        if self.prep_ready_button is not None:
            self.prep_ready_button.config(text="CONFIRMED - WAIT", state="disabled", bg=GREEN, fg="white")
        self.show_wait_overlay("WAIT")

    def wait_for_prep_ready_before_dsi_connect(self) -> None:
        """Block the worker thread until the researcher confirms the prep checklist."""
        self.set_next_instruction("Confirm the GET THESE READY checklist before EEG connects.")
        self.log("Waiting for device preparation checklist before clicking DSI Connect...")
        while not self.prep_ready_event.is_set():
            try:
                if self.prep_window is not None and self.prep_window.winfo_exists():
                    self.root.after(0, lambda: (self.prep_window.deiconify(), self.prep_window.attributes("-topmost", True), self.prep_window.lift()))
            except Exception:
                pass
            time.sleep(0.25)

    def close_prep_checklist(self) -> None:
        self.stop_prep_keepalive()
        def _close() -> None:
            if self.prep_window is not None and self.prep_window.winfo_exists():
                self.prep_window.destroy()
            self.prep_window = None
        self.root.after(0, _close)

    def show_signal_alert(self) -> None:
        message = (
            "Participant may continue.\n\n"
            "1. Press OK on any error.\n"
            "2. Press red RECORD if visible.\n"
            "3. Wait 10 seconds.\n"
            "4. If signal returns, continue.\n"
            "5. If signal does not return, check EDA/ECG device is ON."
        )

        def _show() -> None:
            self.signal_alert_text_var.set(message)

            if self.signal_alert is not None and self.signal_alert.winfo_exists():
                self.signal_alert.deiconify()
                self._set_topmost_fullscreen(self.signal_alert, prefer_secondary=True)
            else:
                win = tk.Toplevel(self.root)
                win.configure(bg="#7a0000")
                self.signal_alert = win
                self._set_topmost_fullscreen(win, prefer_secondary=True)

                holder = tk.Frame(win, bg="#7a0000")
                holder.pack(fill="both", expand=True, padx=60, pady=60)

                tk.Label(
                    holder,
                    text="SIGNAL PROBLEM",
                    font=("Segoe UI", 66, "bold"),
                    bg="#7a0000",
                    fg="white",
                ).pack(pady=(20, 20))

                tk.Label(
                    holder,
                    textvariable=self.signal_alert_text_var,
                    font=("Segoe UI", 34, "bold"),
                    bg="#7a0000",
                    fg="white",
                    justify="center",
                    wraplength=1400,
                ).pack(expand=True)

            try:
                self.root.bell()
            except Exception:
                pass

        self.root.after(0, _show)

    def hide_signal_alert(self) -> None:
        def _hide() -> None:
            if self.signal_alert is not None and self.signal_alert.winfo_exists():
                self.signal_alert.withdraw()

        self.root.after(0, _hide)

    def handle_signal_status(self, status: Any) -> None:
        if not self.recording_is_running:
            return

        # If poor EDA was explicitly accepted during setup, do not keep warning
        # about EDA during the task. The OpenSignals stream and ECG still matter.
        if self.eda_bypassed:
            signal_good = bool(status.stream_ok and status.ecg_ok)
        else:
            signal_good = bool(status.stream_ok and status.eda_ok and status.ecg_ok)

        if signal_good:
            if time.time() - self._last_signal_bad_time > 3:
                self.hide_signal_alert()
            return

        self._last_signal_bad_time = time.time()
        self.show_signal_alert()

    # ------------------------------------------------------------------
    # iPad / MindLogger live-data checker
    # ------------------------------------------------------------------

    def show_ipad_alert(self, detail: str = "No live iPad drawing data detected.") -> None:
        """Full-screen warning shown only after task recording has started."""
        if time.time() < self.ipad_alert_snoozed_until:
            return

        message = (
            "IPAD DRAWING DATA NOT SEEN\n\n"
            "IF THE PARTICIPANT HAS NOT STARTED DRAWING YET:\n"
            "Press DISMISS FOR 1 minute.\n\n"
            "IF THE PARTICIPANT HAS STARTED DRAWING:\n"
            "1. Press Save and Exit on the iPad.\n"
            "2. Press the pencil button on the iPad home screen.\n"
            "3. Press Spiral Task again.\n"
            "4. Press Resume.\n\n"
            "Also make sure the iPad is connected."
        )

        def _show() -> None:
            self.ipad_alert_text_var.set(message)

            if self.ipad_alert is not None and self.ipad_alert.winfo_exists():
                self.ipad_alert.deiconify()
                self._set_topmost_fullscreen(self.ipad_alert, prefer_secondary=True)
                return

            win = tk.Toplevel(self.root)
            win.configure(bg="#7a0000")
            self.ipad_alert = win
            self._set_topmost_fullscreen(win, prefer_secondary=True)

            holder = tk.Frame(win, bg="#7a0000")
            holder.pack(fill="both", expand=True, padx=60, pady=50)

            tk.Label(
                holder,
                text="IPAD DRAWING DATA NOT SEEN",
                font=("Segoe UI", 52, "bold"),
                bg="#7a0000",
                fg="white",
                justify="center",
                wraplength=1450,
            ).pack(pady=(10, 18))

            tk.Label(
                holder,
                textvariable=self.ipad_alert_text_var,
                font=("Segoe UI", 27, "bold"),
                bg="#7a0000",
                fg="white",
                justify="center",
                wraplength=1450,
            ).pack(expand=True)

            buttons = tk.Frame(holder, bg="#7a0000")
            buttons.pack(fill="x", pady=(22, 10))

            tk.Button(
                buttons,
                text="DISMISS FOR 1 minute",
                command=self.dismiss_ipad_alert_for_1_minute,
                font=("Segoe UI", 24, "bold"),
                bg="#1f7a3a",
                fg="white",
                padx=24,
                pady=16,
            ).pack(side="left", expand=True, fill="x")

            try:
                self.root.bell()
            except Exception:
                pass

        self.root.after(0, _show)

    def hide_ipad_alert(self) -> None:
        def _hide() -> None:
            if self.ipad_alert is not None and self.ipad_alert.winfo_exists():
                self.ipad_alert.withdraw()

        self.root.after(0, _hide)

    def dismiss_ipad_alert_for_1_minute(self) -> None:
        self.ipad_alert_snoozed_until = time.time() + IPAD_DISMISS_SEC
        self.hide_ipad_alert()
        self.log(f"iPad warning dismissed for {IPAD_DISMISS_SEC} seconds.")

    def start_ipad_monitor_after_labrecorder(self) -> None:
        """Start iPad live-data tracking only after LabRecorder has actually started."""
        if self.ipad_monitor_started:
            return
        self.ipad_monitor_started = True
        self.ipad_monitor_stop.clear()
        threading.Thread(target=self._ipad_monitor_worker, daemon=True).start()

    def _ipad_monitor_worker(self) -> None:
        """
        Wait 60 seconds after LabRecorder Start was confirmed, then continuously monitor
        MindLogger/iPad live_event data until the task/session is stopped.

        The DISMISS button only hides the warning for 1 minute. Monitoring continues in
        the background and the warning will return after that if data is still missing.
        """
        self.log("iPad live-data checker will start 60 seconds after LabRecorder started.")

        if self.ipad_monitor_stop.wait(IPAD_CHECK_DELAY_AFTER_LABRECORDER_SEC):
            return

        self.log("Checking iPad/MindLogger live data continuously during the task...")
        last_sample_time = 0.0
        inlet = None

        while not self.ipad_monitor_stop.is_set():
            try:
                if inlet is None:
                    from pylsl import StreamInlet, resolve_byprop

                    streams = resolve_byprop("name", IPAD_STREAM_NAME, timeout=2.0)
                    if not streams:
                        self.show_ipad_alert("No MindLogger stream was found in LabRecorder/LSL.")
                        time.sleep(2)
                        continue

                    inlet = StreamInlet(streams[0], max_buflen=10)
                    last_sample_time = 0.0

                sample, _timestamp = inlet.pull_sample(timeout=1.0)

                if sample:
                    sample_text = " ".join(str(x) for x in sample)
                    # The relay pushes live_event drawing points containing x, y, line_number, time.
                    # This accepts both parsed numeric samples and raw JSON/text samples.
                    looks_like_live_event = (
                        "live_event" in sample_text
                        or "line_number" in sample_text
                        or len([x for x in sample if str(x).strip()]) >= 4
                    )

                    if looks_like_live_event:
                        last_sample_time = time.time()
                        self.hide_ipad_alert()
                else:
                    if last_sample_time == 0:
                        self.show_ipad_alert("MindLogger stream exists, but no live drawing samples arrived yet.")
                    elif time.time() - last_sample_time > IPAD_SAMPLE_TIMEOUT_SEC:
                        self.show_ipad_alert(
                            f"MindLogger live data stopped for more than {IPAD_SAMPLE_TIMEOUT_SEC} seconds."
                        )

            except Exception as exc:
                # If the stream/inlet breaks, reset and try to reconnect.
                inlet = None
                self.show_ipad_alert(f"Could not read MindLogger live data: {exc}")
                time.sleep(2)

        self.hide_ipad_alert()
        self.log("iPad/MindLogger live-data monitoring stopped.")

    def stop_ipad_monitor(self) -> None:
        self.ipad_monitor_stop.set()
        self.hide_ipad_alert()

    def get_participant_id(self) -> str:
        pid = self.participant_id_var.get().strip()
        if not pid:
            raise ValueError("Participant ID is empty.")
        return pid

    def build_recording_name(self, participant_id: str) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_pid = "".join(ch for ch in participant_id if ch.isalnum() or ch in "-_")
        return f"{safe_pid}_{stamp}"

    # Help popups
    def show_eda_help(self) -> None:
        messagebox.showinfo(
            "Help: EDA/ECG",
            "Check:\n\n"
            "1. Device ON.\n"
            "2. Participant nearby.\n"
            "3. Signals moving.\n\n"
            "If flat: switch OFF, wait, switch ON again.",
        )

    def show_neon_help(self) -> None:
        messagebox.showinfo(
            "Help: Neon",
            "Check:\n\n"
            "1. Glasses on participant.\n"
            "2. Phone ON and awake.\n"
            "3. Do not touch the mouse.",
        )

    def show_ipad_help(self) -> None:
        messagebox.showinfo(
            "Help: iPad",
            "Password: 654321\n\n"
            "pencil → Submit → Spiral Task Identifier → same ID → Next.\n\n"
            "Then come back here and press NEXT.",
        )

    def show_shortcut_help(self) -> None:
        messagebox.showinfo(
            "Help: BAT file",
            "Use this .bat file:\n\n"
            '@echo off\n'
            'cd /d "%USERPROFILE%\\Automate\\Graphomotor\\Code"\n'
            'py graphomotor_gui.py\n'
            'pause\n\n'
            "The cd /d line is important. It makes the GUI start from the correct folder.",
        )

    # Checklist prompts at the right time
    def ask_initial_checks(self) -> bool:
        # No startup checklist anymore. The GET THESE READY screen is shown while apps open.
        return True

    def ask_neon_checks(self) -> bool:
        # Neon readiness is included in the GET THESE READY screen.
        return True

    def ask_ipad_checks(self, pid: str) -> bool:
        """Full-screen iPad instruction with one obvious OK button."""
        self.hide_eyes_closed_timer()
        self.hide_wait_overlay()
        self.root.deiconify()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.focus_force()

        result = {"ok": False}
        win = tk.Toplevel(self.root)
        win.title("iPad setup")
        win.configure(bg="white")
        win.transient(self.root)
        win.grab_set()
        win.attributes("-topmost", True)
        win.resizable(True, True)

        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        width = min(1240, screen_w - 70)
        height = min(820, screen_h - 70)
        x = max(0, int((screen_w - width) / 2))
        y = max(0, int((screen_h - height) / 2))
        win.geometry(f"{width}x{height}+{x}+{y}")

        # Button is packed first at the bottom so it can never disappear.
        bottom = tk.Frame(win, bg="white")
        bottom.pack(fill="x", side="bottom", padx=45, pady=(8, 22))

        def done() -> None:
            result["ok"] = True
            try:
                win.destroy()
            except Exception:
                pass
            self.show_wait_overlay("WAIT")

        tk.Button(
            bottom,
            text="OK - iPAD IS READY",
            command=done,
            font=("Segoe UI", 28, "bold"),
            bg=GREEN,
            fg="white",
            padx=34,
            pady=8,
        ).pack(fill="x")

        outer = tk.Frame(win, bg="white")
        outer.pack(fill="both", expand=True, padx=45, pady=(22, 6))

        tk.Label(
            outer,
            text="iPAD SETUP",
            font=("Segoe UI", 40, "bold"),
            bg="white",
            fg="#111111",
            justify="center",
         ).pack(fill="x", pady=(0, 4))

        tk.Label(
            outer,
            text="CODE: 654321",
            font=("Segoe UI", 32, "bold"),
            bg="white",
            fg="#111111",
            justify="center",
         ).pack(fill="x", pady=(0, 8))

        steps = tk.Frame(outer, bg="white")
        steps.pack(fill="both", expand=True)

        def add_step(number: str, text_value: str, red: bool = False) -> None:
            bg = "#b00000" if red else "white"
            fg = "white" if red else "#111111"
            border = "#b00000" if red else "#e5e7eb"
            row = tk.Frame(steps, bg=bg, highlightthickness=4 if red else 2, highlightbackground=border)
            row.pack(fill="x", pady=4)
            tk.Label(
                row,
                text=number,
                font=("Segoe UI", 26, "bold"),
                bg="#111111",
                fg="white",
                width=3,
                pady=6,
            ).pack(side="left", padx=(0, 18))
            tk.Label(
                row,
                text=text_value,
                font=("Segoe UI", 27 if red else 24, "bold"),
                bg=bg,
                fg=fg,
                justify="left",
                wraplength=width - 270,
                padx=12,
                pady=8,
            ).pack(side="left", fill="x", expand=True)

        add_step("1", "Unlock iPad with code 654321")
        add_step("2", "PRESS THE PENCIL BUTTON", red=True)
        add_step("3", "Select Spiral Task Identifier")
        add_step("4", f"Use participant ID: {pid}")
        add_step("5", "Press Next / Submit on the iPad")
        add_step("6", "Press the green OK button below")

        win.protocol("WM_DELETE_WINDOW", lambda: None)
        win.lift()
        try:
            win.focus_force()
        except Exception:
            pass
        self.root.wait_window(win)
        return result["ok"]

    def start_file(self, path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        self.log(f"Opening: {path}")
        proc = subprocess.Popen(["cmd", "/c", "start", "", str(path)], shell=False)
        self.processes.append(proc)

    def start_optional_file(self, path: Path, app_name: str) -> bool:
        """
        Open an app if the path exists.

        This is used for DSI because the exact shortcut/exe path can differ
        between computers. If the file is missing, the GUI continues and shows
        a warning instead of crashing.
        """
        if not path.exists():
            self.log(f"{app_name} not found at: {path}")
            return False

        self.log(f"Opening {app_name}: {path}")
        proc = subprocess.Popen(["cmd", "/c", "start", "", str(path)], shell=False)
        self.processes.append(proc)
        return True

    def focus_window_by_title(self, title_re: str, app_name: str, timeout_seconds: int = 20) -> bool:
        """Bring a window to the front using pywinauto, without mouse coordinates."""
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            try:
                app = Application(backend="uia").connect(title_re=title_re, timeout=2)
                win = app.window(title_re=title_re)
                if win.exists(timeout=2):
                    try:
                        win.restore()
                    except Exception:
                        pass
                    try:
                        win.set_focus()
                    except Exception:
                        pass
                    self.log(f"{app_name} brought to front.")
                    time.sleep(1.0)
                    return True
            except Exception:
                time.sleep(1)
        self.log(f"Could not bring {app_name} to front within {timeout_seconds} seconds.")
        return False

    def kill_process_by_name(self, process_name: str) -> None:
        """Force-kill by image name and by process name stem. Safe if the process is absent."""
        try:
            subprocess.call(
                f'taskkill /f /t /im "{process_name}"',
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

        # PowerShell fallback catches cases where image names differ slightly.
        stem = process_name[:-4] if process_name.lower().endswith(".exe") else process_name
        safe_stem = stem.replace("'", "''")
        ps_command = (
            "Get-CimInstance Win32_Process | "
            f"Where-Object {{ $_.Name -like '*{safe_stem}*' -or $_.ProcessName -like '*{safe_stem}*' }} | "
            "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }"
        )
        try:
            subprocess.call(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        except Exception:
            pass

    def release_dsi_com_port(self) -> None:
        """Release stale DSI/COM7 holders before starting a new EEG stream."""
        self.log(f"Hard-cleaning old DSI/COM port holders for {DSI2LSL_COM_PORT}...")

        # Close known DSI windows first. This is graceful and gives apps a chance to release COM7.
        for pattern in [
            ".*DSI2LSL.*",
            ".*dsi2lsl.*",
            ".*DSI-Streamer.*",
            ".*DSI Streamer.*",
        ]:
            try:
                app = Application(backend="uia").connect(title_re=pattern, timeout=1)
                for win in app.windows():
                    try:
                        win.close()
                    except Exception:
                        pass
            except Exception:
                pass

        time.sleep(0.8)

        # Kill DSI-specific command lines. This catches hidden Python/terminal dsi2lsl processes
        # without killing Neon, Graphomotor, or the MindLogger relay.
        for token in DSI_COMMANDLINE_TOKENS_TO_KILL:
            self.kill_processes_by_commandline_token(token)

        # Exact image-name fallback.
        for process_name in DSI_PROCESS_NAMES_TO_KILL:
            self.kill_process_by_name(process_name)

        # Extra PowerShell cleanup: catch Python processes where the command line contains dsi/com7.
        ps_command = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { "
            "$_.CommandLine -match 'dsi2lsl|DSI2LSL|DSI-Streamer|COM7' "
            "} | ForEach-Object { "
            "try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} "
            "}"
        )
        try:
            subprocess.call(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        except Exception:
            pass

        time.sleep(2.0)
        self.log(f"Finished DSI cleanup attempt for {DSI2LSL_COM_PORT}.")

    def wait_for_com_port_to_be_free(self, com_port: str = DSI2LSL_COM_PORT, timeout_sec: float = 10.0) -> bool:
        """Try opening the serial port briefly. If pyserial is unavailable, use Windows mode command."""
        start = time.time()
        last_error = "unknown"

        while time.time() - start < timeout_sec:
            # Best check when pyserial is installed.
            try:
                import serial
                ser = serial.Serial(com_port, baudrate=115200, timeout=0.2)
                ser.close()
                self.log(f"{com_port} is free.")
                return True
            except Exception as exc:
                last_error = str(exc)

            # Fallback check using Windows MODE. This is not perfect, but it often reports busy ports.
            try:
                completed = subprocess.run(
                    ["cmd", "/c", f"mode {com_port}"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    shell=False,
                    timeout=3,
                )
                output = (completed.stdout + completed.stderr).lower()
                if completed.returncode == 0 and "not available" not in output and "access is denied" not in output:
                    self.log(f"{com_port} responded to Windows MODE check.")
                    return True
                if output.strip():
                    last_error = output.strip().replace("\n", " | ")
            except Exception as exc:
                last_error = str(exc)

            self.log(f"{com_port} still looks busy/not ready: {last_error}")
            time.sleep(1)

        self.log(f"{com_port} is still not free after cleanup: {last_error}")
        return False

    def require_com7_free_or_manual_fix(self) -> None:
        """Hard cleanup + clear manual fallback if COM7 is still locked."""
        for attempt in range(1, 4):
            self.set_next_instruction(f"Cleaning old EEG COM7 connection, attempt {attempt}/3. Do not press anything.")
            self.show_wait_overlay(f"WAIT\nCLEARING OLD EEG COM7\nATTEMPT {attempt}/3")
            time.sleep(0.4)
            self.release_dsi_com_port()
            if self.wait_for_com_port_to_be_free(DSI2LSL_COM_PORT, timeout_sec=6):
                return

        self.hide_wait_overlay()
        self.root.deiconify()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.focus_force()

        choice = BigChoiceDialog(
            self.root,
            "COM7 locked",
            "EEG COM7 IS STILL BUSY",
            (
                "The old EEG connection is still holding COM7.\n\n"
                "Do this now:\n\n"
                "1. Unplug the EEG USB/COM7 cable or dongle from the computer.\n\n"
                "2. Wait 5 seconds.\n\n"
                "3. Plug it back in.\n\n"
                "4. Make sure DSI Streamer and DSI2LSL are closed.\n\n"
                "Then press RETRY COM7 CLEANUP."
            ),
            primary_text="RETRY COM7 CLEANUP",
            secondary_text="CANCEL SETUP",
            bg="#7a0000",
            fg="white",
        ).show()

        if choice != "primary":
            raise RuntimeError("COM7 was still busy and setup was cancelled.")

        self.show_wait_overlay("WAIT")
        self.release_dsi_com_port()
        if not self.wait_for_com_port_to_be_free(DSI2LSL_COM_PORT, timeout_sec=12):
            self.hide_wait_overlay()
            raise RuntimeError("COM7 is still busy after manual unplug/replug. Restart the lab PC or check Device Manager.")

    def setup_dsi_eeg(self) -> None:
        """
        DSI workflow for Graphomotor EEG:
        1. Open DSI Streamer while the prep checklist stays visible.
        2. Wait until the researcher confirms that EDA/ECG, EEG headset, Neon glasses,
           and Neon phone are ready.
        3. Only then click DSI Connect and open Diagnostic.
        4. Researcher confirms EEG quality is green/yellow.
        5. Close DSI Streamer and start DSI2LSL as EEG.
        """
        import pyautogui

        pyautogui.PAUSE = 0.35
        self.set_step("dsi", "busy", "Releasing old COM7/DSI connections")
        self.set_next_instruction("Please wait.")
        self.require_com7_free_or_manual_fix()

        self.set_step("dsi", "busy", "Opening DSI Streamer")
        self.set_next_instruction("Please wait.")

        if not self.start_optional_file(DSI_STREAMER_EXE, "DSI Streamer"):
            raise FileNotFoundError(f"DSI Streamer not found: {DSI_STREAMER_EXE}")

        time.sleep(5)
        try:
            self.apply_saved_window_layout()
        except Exception as exc:
            self.log(f"Window layout warning before DSI Streamer clicks: {exc}")

        self.focus_window_by_title(".*DSI-Streamer.*", "DSI Streamer", timeout_seconds=20)
        time.sleep(1)

        # Critical safety/user-flow point: do not click Connect until the researcher confirms the checklist.
        self.wait_for_prep_ready_before_dsi_connect()
        self.show_wait_overlay("WAIT")
        time.sleep(0.4)
        self.close_prep_checklist()

        self.set_next_instruction("Please wait.")

        self.log("Clicking DSI Streamer Connect...")
        pyautogui.moveTo(*DSI_STREAMER_CONNECT_BUTTON, duration=0.25)
        pyautogui.click()
        time.sleep(5)

        self.log("Clicking DSI Streamer Diagnostic...")
        pyautogui.moveTo(*DSI_STREAMER_DIAGNOSTIC_BUTTON, duration=0.25)
        pyautogui.click()
        time.sleep(2)

        self.hide_wait_overlay()
        self.root.deiconify()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.focus_force()

        choice = BigChoiceDialog(
            self.root,
            "EEG quality check",
            "EEG QUALITY CHECK",
            (
                "Look at the DSI quality screen.\n\n"
                "Only answer this:\n\n"
                "Is the EEG headset good enough to record?\n\n"
                "YES = continue.\n"
                "NO = stop and fix the headset before restarting."
            ),
            primary_text="YES - CONTINUE",
            secondary_text="NO - STOP",
            bg=APP_BG,
            fg="white",
        ).show()

        if choice != "primary":
            self.show_wait_overlay("WAIT")
            self.set_step("dsi", "warn", "EEG quality not confirmed")
            self.set_next_instruction("EEG quality was not confirmed. Closing setup safely.")
            self.close_all_apps()
            raise RuntimeError("EEG quality was not confirmed. Setup was stopped safely. Fix the headset, then start again.")

        # Show WAIT immediately after the quality confirmation closes so the user does not
        # think they must press another button during the pause.
        self.set_next_instruction("Please wait.")
        self.show_wait_overlay("WAIT")
        time.sleep(0.2)

        self.log("Closing DSI Streamer before DSI2LSL starts...")
        self.kill_process_by_name("DSI-Streamer-v.1.08.120.exe")
        time.sleep(3)

        self.require_com7_free_or_manual_fix()

        if not self.start_optional_file(DSI_LSL_GUI_SHORTCUT, "DSI2LSL"):
            raise FileNotFoundError(f"DSI2LSL shortcut not found: {DSI_LSL_GUI_SHORTCUT}")

        time.sleep(4)
        try:
            self.apply_saved_window_layout()
        except Exception as exc:
            self.log(f"Window layout warning before DSI2LSL clicks: {exc}")

        self.focus_window_by_title(".*DSI2LSL.*", "DSI2LSL", timeout_seconds=20)
        time.sleep(1)

        self.log(f"Setting DSI2LSL COM port to {DSI2LSL_COM_PORT}...")
        pyautogui.moveTo(*DSI2LSL_COM_TEXTBOX, duration=0.25)
        pyautogui.click()
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        self.paste_text_exact(DSI2LSL_COM_PORT)
        time.sleep(0.5)

        self.log(f"Setting DSI2LSL stream name to {DSI2LSL_STREAM_NAME}...")
        pyautogui.moveTo(*DSI2LSL_STREAM_NAME_TEXTBOX, duration=0.25)
        pyautogui.click()
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        self.paste_text_exact(DSI2LSL_STREAM_NAME)
        time.sleep(0.5)

        self.log("Clicking DSI2LSL Start...")
        pyautogui.moveTo(*DSI2LSL_START_BUTTON, duration=0.25)
        pyautogui.click()
        time.sleep(3)

        self.set_step("dsi", "done", "DSI2LSL started as EEG on COM7")
        # Keep one simple full-screen message: WAIT plus the eyes-closed timer.
        self.show_eyes_closed_timer()
        self.warning_var.set("")
        self.log("DSI EEG setup completed. Eyes-closed timer started for participant.")

    def start_powershell_command(self, command: str) -> subprocess.Popen:
        self.log(f"Running: {command}")
        proc = subprocess.Popen(["powershell", "-NoExit", "-Command", command], shell=False)
        self.processes.append(proc)
        return proc

    def start_neon(self) -> None:
        if not NEON_PYTHON.exists():
            raise FileNotFoundError(f"Neon Python not found: {NEON_PYTHON}")
        if not NEON_SCRIPT.exists():
            raise FileNotFoundError(f"Neon script not found: {NEON_SCRIPT}")

        self.log("Launching Neon GUI...")
        proc = subprocess.Popen([str(NEON_PYTHON), str(NEON_SCRIPT)], cwd=str(NEON_DIR), shell=False)
        self.processes.append(proc)
        self.neon_started_by_gui = True

    def ensure_window_open(self, title_re: str, app_name: str, timeout_seconds: int = 25) -> bool:
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            try:
                app = Application(backend="uia").connect(title_re=title_re, timeout=2)
                win = app.window(title_re=title_re)
                if win.exists(timeout=2):
                    self.log(f"{app_name} window found.")
                    return True
            except Exception:
                time.sleep(1)
        self.log(f"{app_name} window not found within {timeout_seconds} seconds.")
        return False

    def focus_neon_window(self, timeout_seconds: int = 45) -> bool:
        """Bring Neon forward before coordinate clicks. Returns True if a Neon-like window was found."""
        patterns = ["neon", "pupil"]
        start = time.time()
        while time.time() - start < timeout_seconds:
            try:
                windows = Desktop(backend="uia").windows()
                for w in windows:
                    try:
                        title = w.window_text().strip()
                        if any(p in title.lower() for p in patterns):
                            self.log(f"Focusing Neon window: {title}")
                            try:
                                w.restore()
                            except Exception:
                                pass
                            try:
                                w.set_focus()
                            except Exception:
                                pass
                            time.sleep(1.5)
                            return True
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(1)
        self.log("Could not find a Neon window by title. Will still use saved absolute coordinates.")
        return False

    def apply_saved_window_layout(self) -> None:
        if not AUTO_ARRANGE_SCRIPT.exists():
            raise FileNotFoundError(f"Window layout script not found: {AUTO_ARRANGE_SCRIPT}")
        if not WINDOW_LAYOUT_JSON.exists():
            raise FileNotFoundError(f"Window layout JSON not found: {WINDOW_LAYOUT_JSON}")
        self.log("Applying saved window layout...")
        completed = subprocess.run(
            ["python", str(AUTO_ARRANGE_SCRIPT), "apply", "--config", str(WINDOW_LAYOUT_JSON)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
        if completed.stdout.strip():
            self.log(completed.stdout.strip())
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Window layout apply failed.")
        time.sleep(1.2)

    def paste_text_exact(self, text: str) -> None:
     import pyautogui
     import pyperclip
     import time

     pyperclip.copy(text)
     time.sleep(0.1)
     pyautogui.hotkey("ctrl", "v")
     time.sleep(0.1)  


    def automate_neon_start(self, participant_id: str) -> str:
        """Type recording name, connect device, start recording."""
        import pyautogui

        recording_name = self.build_recording_name(participant_id)
        self.set_step("neon", "busy", f"4. Starting Neon recording: {recording_name}")
        self.set_next_instruction("Next: Neon is being controlled automatically. DO NOT MOVE THE MOUSE.")
        self.show_mouse_warning()

        # Give Neon time to fully render, apply layout, focus it, then click.
        self.log("Waiting for Neon to load before clicking...")
        time.sleep(5)
        try:
            self.apply_saved_window_layout()
        except Exception as exc:
            self.log(f"Saved layout could not be applied before Neon clicks: {exc}")
        self.focus_neon_window(timeout_seconds=20)
        time.sleep(2)

        pyautogui.PAUSE = 0.45

        self.log("Clicking Neon filename box and entering recording name...")
        pyautogui.moveTo(*NEON_FILENAME_BOX, duration=0.25)
        pyautogui.click()
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        self.paste_text_exact(recording_name)
        time.sleep(0.8)

        self.log("Clicking Neon Connect Device...")
        pyautogui.moveTo(*NEON_CONNECT_DEVICE_BUTTON, duration=0.25)
        pyautogui.click()
        time.sleep(3.0)

        self.log("Clicking Neon Start Recording...")
        pyautogui.moveTo(*NEON_START_RECORDING_BUTTON, duration=0.25)
        pyautogui.click()
        time.sleep(2.0)

        self.hide_mouse_warning()
        self.set_step("neon", "done", f"4. Neon recording started: {recording_name}")
        self.log("Neon filename/connect/start automation completed.")
        return recording_name

    def stop_neon_recording(self) -> None:
        """Stop Neon before stopping LabRecorder."""
        try:
            import pyautogui

            self.log("Stopping Neon recording first...")
            self.set_next_instruction("Next: Stopping Neon first. DO NOT MOVE THE MOUSE.")
            self.show_mouse_warning()
            try:
                self.apply_saved_window_layout()
            except Exception as exc:
                self.log(f"Saved layout could not be applied before Neon stop: {exc}")
            self.focus_neon_window(timeout_seconds=10)
            time.sleep(1.2)
            pyautogui.moveTo(*NEON_STOP_RECORDING_BUTTON, duration=0.25)
            pyautogui.click()
            time.sleep(2)
            self.hide_mouse_warning()
            self.log("Neon Stop Recording clicked.")
        except Exception as e:
            self.hide_mouse_warning()
            self.log(f"Could not stop Neon automatically: {e}")

    # OpenSignals and LabRecorder helpers
    def connect_opensignals_window(self, timeout_seconds: int = 30):
        start_time = time.time()
        last_error: Exception | None = None
        while time.time() - start_time < timeout_seconds:
            try:
                app = Application(backend="uia").connect(title_re=".*OpenSignals.*", timeout=2)
                win = app.window(title_re=".*OpenSignals.*")
                if win.exists(timeout=2):
                    try:
                        win.restore()
                    except Exception:
                        pass
                    try:
                        win.set_focus()
                    except Exception:
                        pass
                    return win
            except Exception as exc:
                last_error = exc
                time.sleep(1)
        raise RuntimeError(f"OpenSignals window was not found. Last error: {last_error}")

    def get_window_rect_tuple(self, win) -> tuple[int, int, int, int]:
        rect = win.rectangle()
        return int(rect.left), int(rect.top), int(rect.width()), int(rect.height())

    def load_opensignals_rect_from_layout(self) -> tuple[int, int, int, int] | None:
        if not WINDOW_LAYOUT_JSON.exists():
            self.log(f"Window layout JSON not found: {WINDOW_LAYOUT_JSON}")
            return None
        try:
            data = json.loads(WINDOW_LAYOUT_JSON.read_text(encoding="utf-8"))
        except Exception as exc:
            self.log(f"Could not read layout JSON: {exc}")
            return None

        def mentions_opensignals(d: dict) -> bool:
            return any(isinstance(v, str) and "opensignals" in v.lower() for v in d.values())

        def extract_rect(d: dict) -> tuple[int, int, int, int] | None:
            if all(k in d for k in ("x", "y", "width", "height")):
                return int(d["x"]), int(d["y"]), int(d["width"]), int(d["height"])
            if all(k in d for k in ("left", "top", "width", "height")):
                return int(d["left"]), int(d["top"]), int(d["width"]), int(d["height"])
            if all(k in d for k in ("left", "top", "right", "bottom")):
                left, top, right, bottom = int(d["left"]), int(d["top"]), int(d["right"]), int(d["bottom"])
                return left, top, right - left, bottom - top
            for key in ("rect", "rectangle", "geometry", "position", "window_rect"):
                if isinstance(d.get(key), dict):
                    r = extract_rect(d[key])
                    if r is not None:
                        return r
            return None

        def walk(obj) -> tuple[int, int, int, int] | None:
            if isinstance(obj, dict):
                if mentions_opensignals(obj):
                    r = extract_rect(obj)
                    if r is not None:
                        return r
                for v in obj.values():
                    r = walk(v)
                    if r is not None:
                        return r
            elif isinstance(obj, list):
                for item in obj:
                    r = walk(item)
                    if r is not None:
                        return r
            return None

        return walk(data)

    def opensignals_matches_saved_layout(self, expected_rect: tuple[int, int, int, int] | None) -> bool:
        win = self.connect_opensignals_window(timeout_seconds=10)
        actual_rect = self.get_window_rect_tuple(win)
        self.log(f"Current OpenSignals position: x={actual_rect[0]}, y={actual_rect[1]}, width={actual_rect[2]}, height={actual_rect[3]}")
        if expected_rect is None:
            self.log("No exact OpenSignals coordinates parsed. Continuing because OpenSignals is visible.")
            return True
        return all(abs(a - e) <= OPENSIGNALS_POSITION_TOLERANCE for a, e in zip(actual_rect, expected_rect))

    def ensure_opensignals_ready(self) -> None:
        self.set_step("opensignals", "busy", "5. Checking OpenSignals and applying saved layout...")
        self.set_progress(56, "Checking OpenSignals window automatically...")
        found = self.ensure_window_open(title_re=".*OpenSignals.*", app_name="OpenSignals", timeout_seconds=30)
        if not found:
            self.log("OpenSignals was not visible. Trying to launch it again.")
            self.start_file(OPENSIGNALS_EXE)
            found = self.ensure_window_open(title_re=".*OpenSignals.*", app_name="OpenSignals", timeout_seconds=35)
        if not found:
            raise RuntimeError("OpenSignals could not be opened automatically.")

        expected_rect = self.load_opensignals_rect_from_layout()
        layout_ok = False
        for attempt in range(1, 4):
            self.set_progress(56 + attempt, f"Applying saved window layout attempt {attempt}/3...")
            self.apply_saved_window_layout()
            self.root.deiconify()
            self.root.attributes("-fullscreen", True)
            self.root.attributes("-topmost", True)
            self.root.lift()
            if self.opensignals_matches_saved_layout(expected_rect):
                layout_ok = True
                break
            time.sleep(0.8)
        if not layout_ok:
            raise RuntimeError("OpenSignals is open, but it does not match the saved window layout after 3 attempts.")

    def confirm_ecg_eda_spikes_before_labrecorder(self, context: str = "refresh") -> bool:
        next_action = "SELECT ALL and START LabRecorder" if context == "select_all" else "press UPDATE in LabRecorder"
        self.root.deiconify()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.focus_force()
        return BigChecklistDialog(
            self.root,
            "Check OpenSignals ECG/EDA",
            f"Before I {next_action}, check OpenSignals:",
            [
                ("ecg", "ECG spikes/waves are moving"),
                ("eda", "EDA signal is moving / visible"),
                ("not_flat", "The signal is not flat or missing"),
            ],
            help_text="If not moving: switch the EDA/ECG device OFF, wait a few seconds, switch it ON again, press OK on any OpenSignals error, then wait for moving spikes/waves.",
            continue_text="YES, SIGNALS ARE MOVING",
        ).show()

    def connect_labrecorder(self):
        app = Application(backend="uia").connect(title="Lab Recorder")
        win = app.window(title="Lab Recorder")
        win.set_focus()
        time.sleep(0.5)
        return win

    def setup_labrecorder_refresh(self, participant_id: str) -> None:
        win = self.connect_labrecorder()
        participant_edit = win.child_window(auto_id="MainWindow.centralwidget.scrollArea.qt_scrollarea_viewport.scrollAreaWidgetContents.lineEdit_participant", control_type="Edit")
        participant_edit.set_edit_text(participant_id)
        time.sleep(0.5)
        win.child_window(title="Update", auto_id="MainWindow.centralwidget.groupBox_streams.refreshButton", control_type="Button").click_input()
        time.sleep(2)

    def get_labrecorder_text(self) -> str:
        win = self.connect_labrecorder()
        texts = []
        for item in win.descendants():
            try:
                txt = item.window_text()
                if txt:
                    texts.append(txt)
            except Exception:
                pass
        return "\n".join(texts)

    def verify_labrecorder_started(self) -> bool:
        time.sleep(1.5)
        text = self.get_labrecorder_text().lower()
        if "stop" in text:
            self.log("LabRecorder recording confirmed.")
            return True
        self.log("Could not confirm LabRecorder recording started.")
        return False

    def check_required_streams(self) -> tuple[bool, list[str]]:
        text = self.get_labrecorder_text().lower()
        required_streams = self.get_required_streams_for_session()
        missing = [s for s in required_streams if s.lower() not in text]
        if missing:
            self.log(f"Missing streams: {', '.join(missing)}")
            return False, missing
        if self.neon_bypassed:
            self.log("All required non-Neon streams found. Neon was explicitly bypassed.")
        else:
            self.log("All required streams found.")
        return True, []

    def stop_labrecorder(self) -> None:
        try:
            self.log("Trying to stop LabRecorder recording safely...")
            app = Application(backend="uia").connect(title="Lab Recorder", timeout=3)
            win = app.window(title="Lab Recorder")
            win.set_focus()
            time.sleep(0.8)
            stop_button = win.child_window(title="Stop", auto_id="MainWindow.centralwidget.groupBox_recording.stopButton", control_type="Button")
            if stop_button.exists(timeout=2):
                stop_button.click_input()
                time.sleep(2)
                self.log("LabRecorder Stop button clicked. Recording should be finalized.")
            else:
                self.log("LabRecorder Stop button was not available. It may already be stopped.")
        except Exception as e:
            self.log(f"Could not stop LabRecorder automatically: {e}")

    def kill_processes_by_commandline_token(self, token: str) -> None:
        """Force-kill processes whose command line contains a token, e.g. dsi2lsl or relay scripts."""
        safe_token = token.replace("'", "''")
        ps_command = (
            "Get-CimInstance Win32_Process | "
            f"Where-Object {{ $_.CommandLine -like '*{safe_token}*' }} | "
            "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }"
        )
        try:
            subprocess.call(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        except Exception:
            pass

    def close_graphomotor_windows(self) -> None:
        for pattern in [".*Graphomotor Protocol.*", ".*graphomotor.*", ".*Spiral.*"]:
            try:
                app = Application(backend="uia").connect(title_re=pattern, timeout=2)
                for win in app.windows():
                    try:
                        win.close()
                    except Exception:
                        pass
            except Exception:
                pass

    def close_windows_by_title_patterns(self) -> None:
        """Try graceful window closes before force-killing process names."""
        try:
            windows = Desktop(backend="uia").windows()
        except Exception:
            windows = []

        import re as _re
        for pattern in WINDOW_TITLE_PATTERNS_TO_CLOSE:
            rx = _re.compile(pattern, _re.IGNORECASE)
            for win in windows:
                try:
                    title = win.window_text().strip()
                    if title and rx.match(title):
                        try:
                            win.close()
                            time.sleep(0.15)
                        except Exception:
                            pass
                except Exception:
                    pass

        # Fallback through pywinauto application connections.
        for pattern in WINDOW_TITLE_PATTERNS_TO_CLOSE:
            try:
                app = Application(backend="uia").connect(title_re=pattern, timeout=1)
                for win in app.windows():
                    try:
                        win.close()
                        time.sleep(0.15)
                    except Exception:
                        pass
            except Exception:
                pass


    def hide_start_button_after_first_click(self) -> None:
        if self.next_button is not None:
            try:
                self.next_button.grid_remove()
            except Exception:
                pass

    def show_start_button_for_new_participant(self) -> None:
        if self.next_button is not None:
            try:
                self.next_button.grid()
            except Exception:
                pass

    def hide_start_button_after_press(self) -> None:
        """Remove START from the screen immediately after the researcher presses it."""
        def _hide() -> None:
            try:
                if self.next_button is not None and self.next_button.winfo_ismapped():
                    self.next_button.pack_forget()
                    self.start_button_hidden = True
            except Exception:
                pass
        self.root.after(0, _hide)

    def show_start_button_for_new_participant(self) -> None:
        """Show START again only after a full reset for a new participant."""
        def _show() -> None:
            try:
                if self.next_button is not None and not self.next_button.winfo_ismapped():
                    self.next_button.pack(side="left", expand=True, fill="x", padx=(0, 16))
                    self.start_button_hidden = False
            except Exception:
                pass
        self.root.after(0, _show)

    def thread_next_action(self) -> None:
        if self.busy:
            return
        phase = self.current_phase
        if phase == "start_setup":
            self.hide_start_button_after_press()
            self.show_wait_overlay("WAIT")
            threading.Thread(target=self.start_setup, daemon=True).start()
        elif phase == "check_streams":
            threading.Thread(target=self.check_streams_user_action, daemon=True).start()
        elif phase == "start_task":
            threading.Thread(target=self.start_task, daemon=True).start()
        elif phase == "new_participant":
            threading.Thread(target=self.restart_for_next_participant, daemon=True).start()

    def thread_exit_program(self) -> None:
        threading.Thread(target=self.exit_program, daemon=True).start()

    # Main flow
    def start_setup(self) -> None:
        self.set_busy(True)
        try:
            pid = self.get_participant_id()
            self.root.after(0, self.hide_start_button_after_first_click)
            self.eda_checked_once = True

            self.set_step("participant", "done", f"Participant ID: {pid}")
            self.set_step("device", "busy", "Device preparation checklist open")
            self.set_next_instruction("Tick the GET THESE READY checklist while the software opens.")
            self.show_device_prep_checklist()

            self.set_step("apps", "busy", "Opening apps")

            self.set_progress(10, "Opening LabRecorder...")
            self.start_file(LABRECORDER_EXE)
            time.sleep(0.5)

            self.set_progress(18, "Opening OpenSignals...")
            self.start_file(OPENSIGNALS_EXE)
            time.sleep(0.5)

            self.set_progress(26, "Opening Neon...")
            self.start_neon()
            time.sleep(1.0)

            self.set_progress(34, "Opening iPad relay...")
            self.start_powershell_command(f"cd '{MINDLOGGER_RELAY_SCRIPT.parent}'; uv run '{MINDLOGGER_RELAY_SCRIPT}'")
            time.sleep(1)

            self.set_progress(42, "Opening Graphomotor...")
            self.start_powershell_command(f"cd '{GRAPHOMOTOR_DIR}'; python '{GRAPHOMOTOR_SCRIPT}'")
            time.sleep(2)

            self.set_step("apps", "done", "Apps opened")
            self.set_progress(50, "Arranging windows...")
            try:
                self.apply_saved_window_layout()
            except Exception as exc:
                self.log(f"Window layout warning: {exc}")

            self.root.deiconify()
            self.root.attributes("-fullscreen", True)
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()

            self.set_progress(54, "Preparing DSI Streamer. Waiting for checklist before EEG connects...")
            self.setup_dsi_eeg()
            self.set_step("device", "done", "Devices confirmed")
            time.sleep(0.5)

            self.root.deiconify()
            self.root.attributes("-fullscreen", True)
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()

            self.set_next_instruction("Starting Neon recording automatically.")
            self.automate_neon_start(pid)
            self.root.deiconify()
            self.root.attributes("-fullscreen", True)
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()

            self.ensure_opensignals_ready()
            self.set_progress(62, "Starting OpenSignals recording...")
            self.set_next_instruction("Starting OpenSignals recording automatically.")
            self.warning_var.set("Recording setup is running. Please wait.")
            self.show_wait_overlay("WAIT")
            time.sleep(1)
            setup_opensignals()

            self.show_wait_overlay("WAIT")
            self.set_progress(66, "Checking EDA/ECG signal...")
            self.hide_wait_overlay()

            # Keep checking until the researcher confirms the signal is good,
            # or explicitly chooses to continue with poor EDA only.
            while True:
                choice = BigChoiceDialog(
                    self.root,
                    "EDA / ECG Check",
                    "ARE ECG AND EDA SPIKES VISIBLE?",
                    (
                        "Look at OpenSignals.\n\n"
                        "If both ECG and EDA are moving, continue.\n\n"
                        "If EDA is flat or weak, choose SIGNAL PROBLEM."
                    ),
                    primary_text="YES - CONTINUE",
                    secondary_text="SIGNAL PROBLEM",
                    bg=APP_BG,
                    fg="white",
                ).show()

                if choice == "primary":
                    break

                retry_choice = BigChoiceDialog(
                    self.root,
                    "EDA signal problem",
                    "EDA SIGNAL IS FLAT / POOR",
                    (
                        "Cold hands or poor electrode contact can make EDA very flat.\n\n"
                        "1. Warm the participant's hands if they are cold.\n\n"
                        "2. Check that the EDA electrodes have good contact.\n\n"
                        "3. If needed, switch the white EDA/ECG device OFF, wait 5 seconds, "
                        "switch it ON again, and clear any OpenSignals error.\n\n"
                        "4. Wait for the signal to settle, then RETRY.\n\n"
                        "ONLY choose CONTINUE WITH POOR EDA if ECG is still moving and "
                        "the problem is EDA only."
                    ),
                    primary_text="RETRY EDA / ECG CHECK",
                    secondary_text="CONTINUE WITH POOR EDA",
                    bg="#7a0000",
                    fg="white",
                ).show()

                if retry_choice == "primary":
                    self.log("Researcher chose to retry the EDA/ECG visual check.")
                    continue

                self.eda_bypassed = True
                self.add_session_warning(
                    "EDA: continued with a poor/flat signal after the setup check."
                )
                self.set_step("device", "warn", "EDA poor/flat - continued by researcher")
                self.log("Continuing with poor EDA. ECG must still be moving.")
                break

            self.show_wait_overlay("WAIT")
            self.root.deiconify()
            self.root.attributes("-fullscreen", True)
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()
            self.set_step("opensignals", "done", "OpenSignals started")

            self.set_step("labrecorder", "busy", "Preparing LabRecorder")
            self.set_next_instruction("Preparing LabRecorder.")
            self.setup_labrecorder_refresh(pid)
            self.set_step("labrecorder", "done", "LabRecorder ready")
            self.hide_wait_overlay()
            self.warning_var.set("")

            self.set_step("ipad", "busy", "Do the iPad step")
            self.set_progress(85, "Now do the iPad step.")
            self.set_next_instruction("Complete the iPad setup in the popup.")
            if not self.ask_ipad_checks(pid):
                self.set_next_instruction("Complete the iPad setup before continuing.")
                return

            self.show_wait_overlay("WAIT")
            self.set_phase("check_streams", "CHECK STREAMS")
            self.root.after(100, self.thread_next_action)

        except Exception as e:
            self.hide_mouse_warning()
            self.hide_signal_alert()
            self.close_prep_checklist()
            self.signal_checker.stop()
            self.set_progress(0, f"Setup error: {e}")
            self.set_next_instruction("Fix the error. Then close and restart the setup when ready.")
            messagebox.showerror("Setup Error", str(e))
        finally:
            self.set_busy(False)

    def check_streams_user_action(self) -> None:
        self.set_busy(True)
        start_now = False
        try:
            self.set_step("streams", "busy", "Checking streams")
            self.set_next_instruction("Checking streams in LabRecorder.")
            self.show_wait_overlay("WAIT")
            pid = self.get_participant_id()
            self.setup_labrecorder_refresh(pid)
            ok, missing = self.check_required_streams()
            self.hide_wait_overlay()
            self.root.deiconify()
            self.root.attributes("-fullscreen", True)
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()

            if not ok:
                neon_missing = [stream for stream in missing if stream in NEON_STREAMS]
                other_missing = [stream for stream in missing if stream not in NEON_STREAMS]

                # Neon is optional only after the researcher explicitly chooses to bypass it.
                if neon_missing:
                    self.set_step("streams", "warn", f"Missing Neon: {', '.join(neon_missing)}")
                    self.set_progress(75, "Neon stream missing.")
                    self.set_next_instruction("Fix Neon and retry, or explicitly continue without Neon.")

                    neon_text = "\n".join(f"• {stream}" for stream in neon_missing)
                    extra_text = ""
                    if other_missing:
                        extra_text = (
                            "\n\nOther required streams are also missing and still MUST be fixed:\n\n"
                            + "\n".join(f"• {stream}" for stream in other_missing)
                        )

                    choice = BigChoiceDialog(
                        self.root,
                        "Neon missing",
                        "NEON STREAM NOT FOUND",
                        (
                            "Missing Neon stream(s):\n\n"
                            + neon_text
                            + "\n\nCheck that the Neon glasses and phone are on and connected. "
                              "If needed, reconnect/start Neon, then retry."
                            + extra_text
                            + "\n\nIf Neon cannot be recovered, you may continue without eye tracking."
                        ),
                        primary_text="RETRY / CHECK STREAMS AGAIN",
                        secondary_text="CONTINUE WITHOUT NEON",
                        bg="#7a0000",
                        fg="white",
                    ).show()

                    if choice == "primary":
                        self.set_phase("check_streams", "CHECK STREAMS")
                        self.root.after(100, self.thread_next_action)
                        return

                    self.neon_bypassed = True
                    self.add_session_warning(
                        "Neon: continued without eye tracking because Neon stream(s) were not detected."
                    )
                    self.set_step("neon", "warn", "Neon unavailable - continued without eye tracking")
                    self.log("Researcher explicitly chose to continue without Neon.")

                    # If another required stream is also missing, re-check now that
                    # Neon has been removed from the required list.
                    if other_missing:
                        self.set_phase("check_streams", "CHECK STREAMS")
                        self.root.after(100, self.thread_next_action)
                        return

                    ok = True
                    missing = []

                if not ok:
                    self.set_step("streams", "warn", f"Missing: {', '.join(missing)}")
                    self.set_progress(75, "Still missing streams.")
                    self.set_next_instruction("Fix the missing stream, then press CHECK STREAMS AGAIN in the popup.")
                    missing_text = "\n".join(f"• {s}" for s in missing)
                    choice = BigChoiceDialog(
                        self.root,
                        "Streams missing",
                        "STREAMS MISSING",
                        "Missing:\n\n" + missing_text + "\n\nFix the device/app, then check again.",
                        primary_text="CHECK STREAMS AGAIN",
                        secondary_text="CANCEL",
                        bg="#7a0000",
                        fg="white",
                    ).show()
                    self.set_phase("check_streams", "CHECK STREAMS")
                    if choice == "primary":
                        self.root.after(100, self.thread_next_action)
                    return

            if self.neon_bypassed:
                self.set_step("streams", "warn", "Required streams found; Neon bypassed")
            else:
                self.set_step("streams", "done", "All streams found")
            self.set_step("ipad", "done", "iPad submitted")
            self.set_step("task", "busy", "Ready to start task")
            self.set_progress(95, "Ready to start task.")
            self.set_next_instruction("All streams found. Press START TASK in the popup.")

            active_streams = self.get_required_streams_for_session()
            stream_text = "\n".join(f"✓ {s}" for s in active_streams)
            if self.neon_bypassed:
                stream_text += "\n⚠ Neon eye tracking: BYPASSED for this participant"
                ready_heading = "REQUIRED STREAMS READY"
            else:
                ready_heading = "ALL STREAMS FOUND"

            if self.eda_bypassed:
                stream_text += "\n⚠ EDA quality: poor/flat signal accepted for this participant"

            choice = BigChoiceDialog(
                self.root,
                "Ready",
                ready_heading,
                stream_text + "\n\nPress START TASK to start LabRecorder and show Graphomotor.",
                primary_text="START TASK NOW",
                secondary_text="CHECK AGAIN",
                bg=APP_BG,
                fg="white",
            ).show()
            if choice == "primary":
                start_now = True
            else:
                self.set_phase("check_streams", "CHECK STREAMS")
                self.root.after(100, self.thread_next_action)
                return

        except Exception as e:
            self.hide_wait_overlay()
            self.set_progress(0, f"Stream check error: {e}")
            self.set_next_instruction("Fix the stream error, then press CHECK STREAMS.")
            self.set_phase("check_streams", "CHECK STREAMS")
            messagebox.showerror("Stream Check Error", str(e))
        finally:
            self.set_busy(False)
            if start_now:
                self.set_phase("start_task", "START TASK")
                self.root.after(100, self.thread_next_action)

    def start_task(self) -> None:
        self.set_busy(True)
        try:
            self.set_next_instruction("Starting LabRecorder.")
            ok, missing = self.check_required_streams()
            if not ok:
                self.set_step("task", "warn", "Cannot start yet. Streams missing.")
                self.set_next_instruction("Streams are missing. Fix them, then check streams again.")
                self.set_phase("check_streams", "CHECK STREAMS")
                messagebox.showwarning("Cannot Start Task", "Missing streams:\n\n" + "\n".join(missing))
                return
            self.show_wait_overlay("WAIT")
            win = self.connect_labrecorder()
            self.log("Selecting all LabRecorder streams...")
            win.child_window(title="Select All", auto_id="MainWindow.centralwidget.groupBox_streams.selectAllButton", control_type="Button").click_input()
            time.sleep(0.8)
            self.log("Starting LabRecorder recording...")
            win.child_window(title="Start", auto_id="MainWindow.centralwidget.groupBox_recording.startButton", control_type="Button").click_input()
            if not self.verify_labrecorder_started():
                self.set_step("task", "error", "LabRecorder not confirmed")
                self.set_next_instruction("Check LabRecorder manually, then try START TASK again.")
                self.set_phase("start_task", "NEXT: START TASK")
                messagebox.showerror("LabRecorder Not Confirmed", "Start was clicked, but recording was not confirmed. Check LabRecorder manually.")
                return
            self.hide_wait_overlay()
            self.recording_is_running = True
            self.graphomotor_started = True
            self.start_ipad_monitor_after_labrecorder()
            self.set_step("task", "done", "Task started")
            self.set_step("cleanup", "busy", "Waiting for task to finish")
            self.set_progress(100, "LabRecorder recording confirmed. Showing Graphomotor.")
            self.set_next_instruction("Graphomotor is running. Finish the task. The GUI will close recordings safely.")
            self.set_phase("task_running", "TASK RUNNING")
            self.root.attributes("-topmost", False)
            self.root.iconify()
            app = Application(backend="uia").connect(title_re=".*Graphomotor Protocol.*")
            graph_win = app.window(title_re=".*Graphomotor Protocol.*")
            graph_win.set_focus()
            self.start_cleanup_watcher()
        except Exception as e:
            self.hide_wait_overlay()
            self.set_progress(0, f"Start task error: {e}")
            self.set_next_instruction("Fix the task start error, then try START TASK again.")
            self.set_phase("start_task", "NEXT: START TASK")
            messagebox.showerror("Start Task Error", str(e))
        finally:
            self.set_busy(False)

    def start_cleanup_watcher(self) -> None:
        if self.cleanup_started:
            return
        self.cleanup_started = True
        threading.Thread(target=self.wait_for_graphomotor_and_cleanup, daemon=True).start()

    def wait_for_graphomotor_and_cleanup(self) -> None:
        self.log("Waiting for Graphomotor window to close...")
        while True:
            try:
                Application(backend="uia").connect(title_re=".*Graphomotor Protocol.*", timeout=2)
                time.sleep(2)
            except Exception:
                break
        self.root.deiconify()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.focus_force()
        self.set_progress(100, "Graphomotor finished. Stopping recordings...")
        self.set_step("cleanup", "busy", "Closing safely")
        self.close_all_apps()
        self.set_step("cleanup", "done", "Closed safely")

        # Capture warnings before resetting participant state.
        session_summary = self.build_session_summary()

        self.participant_id_var.set("")
        self.graphomotor_started = False
        self.cleanup_started = False
        self.neon_started_by_gui = False
        self.eda_checked_once = False
        self.recording_is_running = False
        self.ipad_monitor_started = False
        self.ipad_monitor_stop.clear()
        self.ipad_alert_snoozed_until = 0.0
        self.prep_ready_event.clear()
        self.hide_signal_alert()
        self.hide_ipad_alert()
        self.hide_wait_overlay()
        self.processes = []

        # Reset participant-specific bypasses only after the summary has been built.
        self.session_warnings = []
        self.eda_bypassed = False
        self.neon_bypassed = False
        self.reset_step_texts()
        self.status_var.set("Ready for next participant.")
        self.progress_var.set(0)
        self.warning_var.set("")
        self.set_next_instruction("Done. Enter the next participant ID and press START.")
        self.show_start_button_for_new_participant()
        self.set_phase("start_setup", "START")
        self.show_start_button_for_new_participant()
        self.set_busy(False)
        messagebox.showinfo("Session Complete", session_summary)

    def close_all_apps(self) -> None:
        """Stop recordings, close GUI-launched apps, and force-kill stubborn leftovers."""
        self.recording_is_running = False
        try:
            self.signal_checker.stop()
        except Exception:
            pass
        try:
            self.stop_ipad_monitor()
        except Exception:
            pass
        self.hide_signal_alert()
        self.close_prep_checklist()
        self.show_wait_overlay("WAIT")

        # 1) Stop recordings in the safe order.
        if self.neon_bypassed:
            self.log("Neon was bypassed for this participant; skipping Neon Stop Recording click.")
        else:
            self.log("Stopping Neon before LabRecorder...")
            try:
                self.stop_neon_recording()
            except Exception as exc:
                self.log(f"Neon stop warning: {exc}")
            time.sleep(0.8)

        self.log("Stopping LabRecorder recording...")
        try:
            self.stop_labrecorder()
        except Exception as exc:
            self.log(f"LabRecorder stop warning: {exc}")
        time.sleep(1)

        # 2) Close visible windows by title first.
        self.log("Closing OpenSignals, LabRecorder, DSI2LSL, DSI Streamer, Neon, Graphomotor, and terminal windows...")
        try:
            self.close_graphomotor_windows()
        except Exception:
            pass
        self.close_windows_by_title_patterns()
        time.sleep(0.8)

        # 3) Terminate handles started by this GUI.
        self.log("Terminating processes started by this GUI...")
        for proc in list(self.processes):
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
        time.sleep(0.8)

        # 4) Kill exact scripts/apps by command line token. This catches shortcuts and Python-hosted apps.
        self.log("Killing leftover script processes by command line...")
        for token in SCRIPT_TOKENS_TO_CLOSE:
            self.kill_processes_by_commandline_token(token)

        # Extra targeted command-line kills for apps that may not have their own exe name.
        for token in [
            str(DSI_LSL_GUI_SHORTCUT),
            str(MINDLOGGER_RELAY_SCRIPT),
            str(GRAPHOMOTOR_SCRIPT),
            str(NEON_SCRIPT),
            "OpenSignals",
            "LabRecorder",
            "DSI-Streamer",
            "DSI2LSL",
            "dsi2lsl",
            "COM7",
        ]:
            self.kill_processes_by_commandline_token(token)

        # 5) Kill by process image name, including terminals.
        self.log("Force-killing app and terminal process names...")
        for process_name in PROCESSES_TO_CLOSE:
            self.kill_process_by_name(process_name)

        # 6) Final visible-window pass.
        try:
            self.close_graphomotor_windows()
        except Exception:
            pass
        self.close_windows_by_title_patterns()
        self.processes = []
        self.hide_wait_overlay()

    def restart_for_next_participant(self) -> None:
        try:
            self.set_next_instruction("Restarting: closing leftover apps and resetting the checklist...")
            self.set_progress(0, "Restarting for next participant...")
            self.close_all_apps()
            time.sleep(1)
            self.participant_id_var.set("")
            self.status_var.set("Ready for next participant.")
            self.progress_var.set(0)
            self.warning_var.set("")
            self.graphomotor_started = False
            self.cleanup_started = False
            self.neon_started_by_gui = False
            self.eda_checked_once = False
            self.recording_is_running = False
            self.ipad_monitor_started = False
            self.ipad_monitor_stop.clear()
            self.ipad_alert_snoozed_until = 0.0
            self.prep_ready_event.clear()
            self.hide_signal_alert()
            self.hide_ipad_alert()
            self.hide_wait_overlay()
            self.processes = []
            self.session_warnings = []
            self.eda_bypassed = False
            self.neon_bypassed = False
            self.reset_step_texts()
            self.log_text.delete("1.0", "end")
            self.set_next_instruction("Enter the new participant ID, then press START.")
            self.show_start_button_for_new_participant()
            self.set_initial_button_states()
            self.show_start_button_for_new_participant()
            self.root.deiconify()
            self.root.attributes("-fullscreen", True)
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()
            self.log("Ready for next participant.")
        except Exception as e:
            self.set_progress(0, f"Restart error: {e}")
            messagebox.showerror("Restart Error", str(e))

    def exit_program(self) -> None:
        destroy_gui = False
        try:
            self.root.deiconify()
            self.root.attributes("-fullscreen", True)
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()
            confirm = messagebox.askyesno(
                "Close Everything",
                "This will stop Neon recording, stop LabRecorder, close Graphomotor, OpenSignals, DSI/dsi2lsl, PowerShell relay windows, Neon, and this GUI.\n\nClose everything now?",
            )
            if not confirm:
                return
            destroy_gui = True
            self.set_next_instruction("Closing everything...")
            self.set_progress(0, "Close Everything selected. Closing all apps...")
            try:
                self.close_all_apps()
            except Exception as close_error:
                self.log(f"Close warning: {close_error}")
            time.sleep(1)
        except Exception as e:
            try:
                self.set_progress(0, f"Exit error: {e}")
                messagebox.showerror("Exit Error", str(e))
            except Exception:
                pass
        finally:
            if destroy_gui:
                try:
                    self.root.after(0, self.root.destroy)
                except Exception:
                    pass


def main() -> None:
    root = tk.Tk()
    GraphomotorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
