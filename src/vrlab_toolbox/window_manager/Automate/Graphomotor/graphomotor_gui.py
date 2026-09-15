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


BASE_DIR = Path(r"C:\Users\MoBI-Midtown")

LABRECORDER_EXE = BASE_DIR / "LabRecorder" / "LabRecorder.exe"
OPENSIGNALS_EXE = Path(r"C:\Plux\OpenSignals (r)evolution\OpenSignals.exe")

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

GRAPHOMOTOR_DIR = Path(r"C:\Users\MoBI-Midtown\graphomotor_CMI_mooi\src\graphomotor_protocol")
GRAPHOMOTOR_SCRIPT = GRAPHOMOTOR_DIR / "graphomotor_older_mooi.py"

WINDOW_MX_DIR = Path(r"C:\Users\MoBI-Midtown\Automate\Graphomotor\Code")
AUTO_ARRANGE_SCRIPT = WINDOW_MX_DIR / "auto_arrange_windows.py"
WINDOW_LAYOUT_JSON = WINDOW_MX_DIR / "graphomotor_window_layout.json"

REQUIRED_STREAMS = [
    "MindLogger",
    "OpenSignals",
    "experiment_stream",
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
IPAD_DISMISS_SEC = 30

PROCESSES_TO_CLOSE = [
    "OpenSignals.exe",
    "LabRecorder.exe",
    "powershell.exe",
]

SCRIPT_TOKENS_TO_CLOSE = [
    "graphomotor_older_mooi.py",
    "mindlogger_relay.py",
    "auto_arrange_windows.py",
    "main.py",  # Neon GUI main.py only when command-line token matches
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
            pady=14,
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
                pady=10,
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

class GraphomotorGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Graphomotor Session Setup")
        self.root.attributes("-fullscreen", True)
        self.root.configure(bg=APP_BG)

        self.participant_id_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Ready.")
        self.progress_var = tk.DoubleVar(value=0)
        self.warning_var = tk.StringVar(value="⚠ Use NEXT only. Do not touch the mouse unless the GUI says so. ⚠")
        self.next_instruction_var = tk.StringVar(value="Enter participant ID, then press NEXT.")
        self.next_button_text_var = tk.StringVar(value="NEXT")
        self.current_phase = "start_setup"
        self.busy = False

        self.processes: list[subprocess.Popen] = []
        self.graphomotor_started = False
        self.cleanup_started = False
        self.neon_started_by_gui = False
        self.eda_checked_once = False
        self.recording_is_running = False

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

        self.signal_checker = OpenSignalsHealthChecker(
            check_every_sec=1.0,
            window_sec=8.0,
            on_status=self.handle_signal_status,
        )

        self.steps: dict[str, tk.StringVar] = {}
        self.reset_step_texts()

        self.next_button: tk.Button | None = None
        self.stop_button: tk.Button | None = None
        self.advanced_visible = False
        self.advanced_frame: tk.Frame | None = None

        self.build_ui()
        self.set_initial_button_states()

    def reset_step_texts(self) -> None:
        self.steps = {
            "participant": tk.StringVar(value="☐ Participant ID"),
            "apps": tk.StringVar(value="☐ Open apps"),
            "device": tk.StringVar(value="☐ EDA/ECG ready"),
            "neon": tk.StringVar(value="☐ Neon recording"),
            "opensignals": tk.StringVar(value="☐ OpenSignals recording"),
            "labrecorder": tk.StringVar(value="☐ LabRecorder ready"),
            "ipad": tk.StringVar(value="☐ iPad submitted"),
            "streams": tk.StringVar(value="☐ Streams checked"),
            "task": tk.StringVar(value="☐ Task started"),
            "cleanup": tk.StringVar(value="☐ Session closed safely"),
        }

    def build_ui(self) -> None:
        outer = tk.Frame(self.root, bg=APP_BG)
        outer.pack(fill="both", expand=True, padx=65, pady=38)

        tk.Label(
            outer,
            text="Graphomotor Session",
            font=("Segoe UI", 42, "bold"),
            bg=APP_BG,
            fg="white",
        ).pack(anchor="w")

        tk.Label(
            outer,
            text="Use only the big NEXT button. The computer will tell you exactly when to touch the mouse.",
            font=("Segoe UI", 20, "bold"),
            bg=APP_BG,
            fg="white",
            wraplength=1500,
            justify="left",
        ).pack(anchor="w", pady=(8, 20))

        next_box = tk.LabelFrame(
            outer,
            text=" WHAT TO DO NOW ",
            font=("Segoe UI", 23, "bold"),
            bg=NEXT_BG,
            fg="#111111",
            padx=28,
            pady=22,
        )
        next_box.pack(fill="x", pady=(0, 22))

        tk.Label(
            next_box,
            textvariable=self.next_instruction_var,
            font=("Segoe UI", 28, "bold"),
            bg=NEXT_BG,
            fg="#111111",
            wraplength=1500,
            justify="left",
            anchor="w",
        ).pack(fill="x")

        main_box = tk.LabelFrame(
            outer,
            text=" Start here ",
            font=("Segoe UI", 21, "bold"),
            bg=APP_BG,
            fg="white",
            padx=28,
            pady=22,
        )
        main_box.pack(fill="x", pady=(0, 22))

        tk.Label(main_box, text="Participant ID", font=("Segoe UI", 23, "bold"), bg=APP_BG, fg="white").grid(row=0, column=0, padx=(0, 18), sticky="w")
        tk.Entry(main_box, textvariable=self.participant_id_var, font=("Segoe UI", 30, "bold"), width=18, justify="center").grid(row=0, column=1, padx=(0, 28), ipady=10)
        self.participant_id_var.trace_add("write", lambda *_: self.update_next_button_state())

        self.next_button = tk.Button(
            main_box,
            textvariable=self.next_button_text_var,
            command=self.thread_next_action,
            font=("Segoe UI", 32, "bold"),
            bg=GREEN,
            fg="white",
            padx=55,
            pady=18,
        )
        self.next_button.grid(row=0, column=2, padx=8, sticky="we")

        self.stop_button = tk.Button(
            main_box,
            text="STOP / CLOSE EVERYTHING",
            command=self.thread_exit_program,
            font=("Segoe UI", 17, "bold"),
            bg=RED,
            fg="white",
            padx=24,
            pady=18,
        )
        self.stop_button.grid(row=0, column=3, padx=(22, 0), sticky="we")

        tk.Label(
            outer,
            textvariable=self.warning_var,
            font=("Segoe UI", 42, "bold"),
            bg=APP_BG,
            fg="#b00000",
            pady=10,
        ).pack(fill="x")

        status_box = tk.LabelFrame(outer, text=" Status ", font=("Segoe UI", 19, "bold"), bg=APP_BG, fg="white", padx=28, pady=18)
        status_box.pack(fill="x", pady=(0, 18))
        tk.Label(status_box, textvariable=self.status_var, font=("Segoe UI", 24, "bold"), bg=APP_BG, fg="white", anchor="w", wraplength=1500, justify="left").pack(fill="x", pady=(0, 12))
        ttk.Progressbar(status_box, variable=self.progress_var, maximum=100, mode="determinate").pack(fill="x")

        checklist_box = tk.LabelFrame(outer, text=" Progress ", font=("Segoe UI", 19, "bold"), bg=APP_BG, fg="white", padx=28, pady=16)
        checklist_box.pack(fill="x", pady=(0, 14))
        for step_var in self.steps.values():
            tk.Label(checklist_box, textvariable=step_var, font=("Segoe UI", 15, "bold"), bg=APP_BG, fg="white", anchor="w").pack(fill="x", pady=1)

        small_help = tk.Frame(outer, bg=APP_BG)
        small_help.pack(fill="x", pady=(0, 10))
        tk.Label(
            small_help,
            text="iPad reminder: password 654321 → pencil → Submit → Spiral Task Identifier → same participant ID → Next.",
            font=("Segoe UI", 16, "bold"),
            bg=APP_BG,
            fg="white",
            wraplength=1500,
            justify="left",
        ).pack(side="left", anchor="w")

        bottom = tk.Frame(outer, bg=APP_BG)
        bottom.pack(fill="both", expand=True)
        tk.Button(bottom, text="Advanced / Show details", command=self.toggle_advanced, font=("Segoe UI", 13, "bold"), bg=GREY, fg="white", padx=16, pady=8).pack(side="left", anchor="s")
        tk.Button(bottom, text="Exit Full Screen", command=lambda: self.root.attributes("-fullscreen", False), font=("Segoe UI", 13, "bold"), bg="#444444", fg="white", padx=16, pady=8).pack(side="right", anchor="s")

        self.advanced_frame = tk.Frame(outer, bg=APP_BG)
        self.log_text = tk.Text(self.advanced_frame, height=7, wrap="word", font=("Consolas", 12), bg="white", fg="black")
        self.log_text.pack(fill="both", expand=True, pady=(8, 0))

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
        self.set_phase("start_setup", "NEXT")
        self.update_next_button_state()

    def set_phase(self, phase: str, button_text: str = "NEXT") -> None:
        self.current_phase = phase
        self.next_button_text_var.set(button_text)
        self.update_next_button_state()

    def update_next_button_state(self) -> None:
        if self.next_button is None:
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

    def show_mouse_warning(self) -> None:
        self.warning_var.set("⚠ STOP. DO NOT TOUCH THE MOUSE. ⚠")
        self.show_wait_overlay("WAIT\nDO NOT TOUCH THE MOUSE")

    def hide_mouse_warning(self) -> None:
        self.hide_wait_overlay()
        self.warning_var.set("⚠ Use NEXT only. Do not touch the mouse unless the GUI says so. ⚠")
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

    def show_wait_overlay(self, message: str = "WAIT\nDO NOT TOUCH THE MOUSE") -> None:
        def _show() -> None:
            self.wait_overlay_text_var.set(message)

            if self.wait_overlay is not None and self.wait_overlay.winfo_exists():
                self.wait_overlay.deiconify()
                self._set_topmost_fullscreen(self.wait_overlay, prefer_secondary=False)
                return

            win = tk.Toplevel(self.root)
            win.configure(bg="#050505")
            self.wait_overlay = win
            self._set_topmost_fullscreen(win, prefer_secondary=False)

            holder = tk.Frame(win, bg="#050505")
            holder.pack(fill="both", expand=True, padx=70, pady=70)

            tk.Label(
                holder,
                textvariable=self.wait_overlay_text_var,
                font=("Segoe UI", 76, "bold"),
                bg="#050505",
                fg="#f5c542",
                justify="center",
                wraplength=1400,
            ).pack(expand=True)

            tk.Label(
                holder,
                text="THE COMPUTER IS BUSY. DO NOT TOUCH THE MOUSE OR KEYBOARD.",
                font=("Segoe UI", 30, "bold"),
                bg="#050505",
                fg="white",
                justify="center",
                wraplength=1400,
            ).pack(pady=(0, 40))

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
            "Press DISMISS FOR 30 seconds.\n\n"
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
                text="DISMISS FOR 30 seconds",
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
        self.log("iPad warning dismissed for 1 minute.")

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
            'cd /d "C:\\Users\\MoBI-Midtown\\Automate\\Graphomotor\\Code"\n'
            'py graphomotor_gui.py\n'
            'pause\n\n'
            "The cd /d line is important. It makes the GUI start from the correct folder.",
        )

    # Checklist prompts at the right time
    def ask_initial_checks(self) -> bool:
        return BigChecklistDialog(
            self.root,
            "Before opening apps",
            "Tick these, then continue:",
            [
                ("participant", "Participant ready"),
                ("eda", "EDA/ECG ON"),
                ("mouse", "I will not touch the mouse"),
            ],
            help_text="If signal is flat: switch device OFF, wait, switch ON again.",
            continue_text="NEXT",
        ).show()

    def ask_neon_checks(self) -> bool:
        return BigChecklistDialog(
            self.root,
            "Before Neon automation",
            "Tick these, then continue:",
            [
                ("glasses", "Glasses on participant"),
                ("phone", "Phone ON and awake"),
                ("mouse", "I will not touch the mouse"),
            ],
            help_text="The GUI will type the name, connect Neon, and start recording.",
            continue_text="NEXT",
        ).show()

    def ask_ipad_checks(self, pid: str) -> bool:
        return BigChecklistDialog(
            self.root,
            "iPad / MindLogger step",
            "Do this on the iPad:",
            [
                ("pencil", "Pencil"),
                ("select", "Spiral Task Identifier"),
                ("pid", f"Same ID: {pid}"),
                ("submit2", "Pressed Next"),
            ],
            help_text="Password: 654321. Then return here and press NEXT.",
            continue_text="NEXT",
        ).show()

    # Process launching
    def start_file(self, path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        self.log(f"Opening: {path}")
        proc = subprocess.Popen(["cmd", "/c", "start", "", str(path)], shell=False)
        self.processes.append(proc)

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
        pyautogui.write(recording_name, interval=0.02)
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
        missing = [s for s in REQUIRED_STREAMS if s.lower() not in text]
        if missing:
            self.log(f"Missing streams: {', '.join(missing)}")
            return False, missing
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
        safe_token = token.replace("'", "''")
        ps_command = (
            "Get-CimInstance Win32_Process | "
            f"Where-Object {{ $_.CommandLine -like '*{safe_token}*' }} | "
            "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }"
        )
        try:
            subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)
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

    # Threads
    def thread_next_action(self) -> None:
        if self.busy:
            return
        phase = self.current_phase
        if phase == "start_setup":
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
            if not self.ask_initial_checks():
                self.set_next_instruction("Finish the checks, then press NEXT again.")
                return
            self.eda_checked_once = True

            self.set_step("participant", "done", f"Participant ID: {pid}")
            self.set_step("device", "done", "EDA/ECG checked")
            self.set_next_instruction("Opening apps. Do not touch the mouse.")

            self.set_step("apps", "busy", "Opening apps")
            self.show_wait_overlay("WAIT\nOPENING PROGRAMS")
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

            self.hide_wait_overlay()
            self.set_next_instruction("Check Neon. Then press START NEON RECORDING in the popup.")
            if not self.ask_neon_checks():
                self.set_step("neon", "warn", "Neon not confirmed")
                self.set_next_instruction("Fix Neon, then press NEXT again.")
                return

            self.automate_neon_start(pid)
            self.root.deiconify()
            self.root.attributes("-fullscreen", True)
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()

            self.ensure_opensignals_ready()
            self.set_progress(62, "Starting OpenSignals recording...")
            self.set_next_instruction("OpenSignals and LabRecorder are being controlled. DO NOT TOUCH THE MOUSE.")
            self.warning_var.set("⚠ STOP. DO NOT TOUCH THE MOUSE. ⚠")
            self.show_wait_overlay("WAIT\nSTARTING OPENSIGNALS")
            time.sleep(1)
            setup_opensignals()

            self.show_wait_overlay("WAIT\nCHECKING EDA/ECG SIGNAL")
            self.set_progress(66, "Automatically checking EDA/ECG signal...")
            self.signal_checker.start()
            if not self.signal_checker.wait_for_good_signal(timeout_sec=30):
                self.signal_checker.stop()
                self.set_step("opensignals", "error", "EDA/ECG signal problem")
                messagebox.showerror(
                    "EDA/ECG problem",
                    "EDA/ECG signal was not detected properly.\n\n"
                    "Switch the device OFF and ON, press OK on any OpenSignals error, "
                    "then press the red record button if visible.",
                )
                self.hide_wait_overlay()
                self.warning_var.set("⚠ Use NEXT only. Do not touch the mouse unless the GUI says so. ⚠")
                self.set_next_instruction("Fix EDA/ECG, then press NEXT again.")
                return

            self.show_wait_overlay("WAIT\nPREPARING LABRECORDER")
            self.root.deiconify()
            self.root.attributes("-fullscreen", True)
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()
            self.set_step("opensignals", "done", "OpenSignals started")

            self.set_step("labrecorder", "busy", "Preparing LabRecorder")
            self.set_next_instruction("Preparing LabRecorder. Do not touch the mouse.")
            self.setup_labrecorder_refresh(pid)
            self.set_step("labrecorder", "done", "LabRecorder ready")
            self.hide_wait_overlay()
            self.warning_var.set("⚠ Use NEXT only. Do not touch the mouse unless the GUI says so. ⚠")

            self.set_step("ipad", "busy", "Do the iPad step")
            self.set_progress(85, "Now do the iPad step.")
            self.set_next_instruction("Do iPad: 654321 → pencil → Submit → Spiral Task Identifier → same ID → Next. Then press NEXT here.")
            self.set_phase("check_streams", "NEXT")

        except Exception as e:
            self.hide_mouse_warning()
            self.hide_signal_alert()
            self.signal_checker.stop()
            self.set_progress(0, f"Setup error: {e}")
            self.set_next_instruction("Fix the error, then press NEXT again.")
            messagebox.showerror("Setup Error", str(e))
        finally:
            self.set_busy(False)

    def check_streams_user_action(self) -> None:
        self.set_busy(True)
        try:
            self.set_step("streams", "busy", "Checking streams")
            self.set_next_instruction("Checking streams. Do not touch the mouse.")
            self.show_wait_overlay("WAIT\nCHECKING LABRECORDER STREAMS")
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
                self.set_step("streams", "warn", f"Missing: {', '.join(missing)}")
                self.set_progress(75, "Still missing streams.")
                self.set_next_instruction("Fix iPad/devices, then press NEXT again.")
                messagebox.showwarning("Missing Streams", "Still missing:\n\n" + "\n".join(missing) + "\n\nFix this, then press NEXT again.")
                self.set_phase("check_streams", "NEXT")
                return
            self.set_step("streams", "done", "All streams found")
            self.set_step("ipad", "done", "iPad submitted")
            self.set_step("task", "busy", "Ready to start task")
            self.set_progress(95, "Ready to start task.")
            self.set_next_instruction("Ready. Press NEXT to start LabRecorder and show Graphomotor.")
            self.set_phase("start_task", "NEXT: START TASK")
            messagebox.showinfo("Ready", "All streams are visible.\n\nPress NEXT to start the task.")
        except Exception as e:
            self.hide_wait_overlay()
            self.set_progress(0, f"Stream check error: {e}")
            self.set_next_instruction("Fix the stream error, then press NEXT again.")
            self.set_phase("check_streams", "NEXT")
            messagebox.showerror("Stream Check Error", str(e))
        finally:
            self.set_busy(False)

    def start_task(self) -> None:
        self.set_busy(True)
        try:
            self.set_next_instruction("Starting LabRecorder. Do not touch the mouse.")
            ok, missing = self.check_required_streams()
            if not ok:
                self.set_step("task", "warn", "Cannot start yet. Streams missing.")
                self.set_next_instruction("Streams are missing. Fix them, then press NEXT again.")
                self.set_phase("check_streams", "NEXT")
                messagebox.showwarning("Cannot Start Task", "Missing streams:\n\n" + "\n".join(missing))
                return
            self.show_wait_overlay("WAIT\nSTARTING LABRECORDER")
            win = self.connect_labrecorder()
            self.log("Selecting all LabRecorder streams...")
            win.child_window(title="Select All", auto_id="MainWindow.centralwidget.groupBox_streams.selectAllButton", control_type="Button").click_input()
            time.sleep(0.8)
            self.log("Starting LabRecorder recording...")
            win.child_window(title="Start", auto_id="MainWindow.centralwidget.groupBox_recording.startButton", control_type="Button").click_input()
            if not self.verify_labrecorder_started():
                self.set_step("task", "error", "LabRecorder not confirmed")
                self.set_next_instruction("Check LabRecorder manually, then press NEXT again.")
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
            self.set_next_instruction("Fix the task start error, then press NEXT again.")
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
        self.set_next_instruction("Done. Press NEXT for the next participant.")
        self.set_phase("new_participant", "NEXT PARTICIPANT")
        self.set_busy(False)
        messagebox.showinfo("Session Complete", "Done. Recordings were stopped safely.")

    def close_all_apps(self) -> None:
        self.recording_is_running = False
        self.signal_checker.stop()
        self.stop_ipad_monitor()
        self.hide_signal_alert()
        self.show_wait_overlay("WAIT\nSTOPPING RECORDINGS")
        self.log("Stopping Neon before LabRecorder...")
        self.stop_neon_recording()
        time.sleep(0.8)
        self.log("Stopping LabRecorder recording...")
        self.stop_labrecorder()
        time.sleep(1)
        self.log("Closing Graphomotor, LabRecorder, OpenSignals, Neon, and relay windows...")
        self.close_graphomotor_windows()
        for proc in self.processes:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
        time.sleep(0.8)
        for token in SCRIPT_TOKENS_TO_CLOSE:
            self.kill_processes_by_commandline_token(token)
        for process_name in PROCESSES_TO_CLOSE:
            try:
                subprocess.call(f"taskkill /f /im {process_name}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        self.close_graphomotor_windows()
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
            self.warning_var.set("⚠ Use NEXT only. Do not touch the mouse unless the GUI says so. ⚠")
            self.graphomotor_started = False
            self.cleanup_started = False
            self.neon_started_by_gui = False
            self.eda_checked_once = False
            self.recording_is_running = False
            self.ipad_monitor_started = False
            self.ipad_monitor_stop.clear()
            self.ipad_alert_snoozed_until = 0.0
            self.hide_signal_alert()
            self.hide_ipad_alert()
            self.hide_wait_overlay()
            self.processes = []
            self.reset_step_texts()
            self.log_text.delete("1.0", "end")
            self.set_next_instruction("Enter the new participant ID, then press NEXT.")
            self.set_initial_button_states()
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
        try:
            self.root.deiconify()
            self.root.attributes("-fullscreen", True)
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.focus_force()
            confirm = messagebox.askyesno(
                "Exit Program",
                "This will stop Neon first, stop LabRecorder, then close Graphomotor, OpenSignals, PowerShell relay windows, and this GUI.\n\nExit and close everything now?",
            )
            if not confirm:
                return
            self.set_next_instruction("Exiting: stopping recordings and closing all apps...")
            self.set_progress(0, "Exit selected. Closing all apps...")
            self.close_all_apps()
            time.sleep(1)
            self.root.after(0, self.root.destroy)
        except Exception as e:
            try:
                self.set_progress(0, f"Exit error: {e}")
                messagebox.showerror("Exit Error", str(e))
            except Exception:
                pass


def main() -> None:
    root = tk.Tk()
    GraphomotorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
