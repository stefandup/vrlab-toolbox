from __future__ import annotations

import os
import subprocess
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from signal_checker import OpenSignalsHealthChecker
from session_controller import SessionLauncher
from automation_layer import setup_opensignals, setup_labrecorder, setup_foh


class FullscreenSessionGUI:
    """
    FOH session launcher with:
        - a large WAIT overlay during automated clicking
        - automatic live OpenSignals EDA/ECG checking
        - a large topmost signal warning window during FOH if signal is lost/flat

    OpenSignals LSL stream expected from lab test:
        stream name: OpenSignals
        channels: 3
        EDA: sample[0]
        ECG: sample[2]
    """

    BG = "#07130d"
    PANEL = "#0f2418"
    TEXT = "#f4f7f4"
    MUTED = "#b8c7bd"
    GREEN = "#1f9d55"
    GREEN_DARK = "#15733d"
    RED = "#b42318"
    RED_DARK = "#7a1b14"
    AMBER = "#f5c542"
    ORANGE = "#d97706"
    ORANGE_DARK = "#92400e"
    WHITE = "#ffffff"
    BLACK = "#000000"
    DISABLED = "#8a8a8a"

    STEPS = [
        "Participant ID",
        "Programs opened",
        "Windows arranged",
        "EDA/ECG ready",
        "OpenSignals started",
        "ECG/EDA spikes checked",
        "LabRecorder started",
        "FOH opened",
        "Recording stopped",
    ]

    KILL_LIST = [
        "OpenSignals.exe",
        "LabRecorder.exe",
        "AxioBiofeedback.exe",
        "DSI-Streamer-v.1.08.120.exe",
        "dsi2lslgui.exe",
        "DSI2LSL.exe",
        "AudioVideoRecorder.exe",
        # Terminal windows opened as part of the session.
        "powershell.exe",
        "pwsh.exe",
        "cmd.exe",
        "WindowsTerminal.exe",
        "wt.exe",
    ]

    COMMANDLINE_TOKENS_TO_CLOSE = [
        "AxioBiofeedback",
        "OpenSignals",
        "LabRecorder",
        "AudioVideoRecorder",
        "DSI-Streamer",
        "dsi2lsl",
        "DSI2LSL",
        "dsi2lslgui",
        "COM7",
        "setup_foh",
        "FOH",
    ]

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("FOH Session")
        self.root.attributes("-fullscreen", True)
        self.root.configure(bg=self.BG)

        self.launcher = SessionLauncher()

        self.participant_id_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Enter participant ID, then press START.")
        self.progress_var = tk.DoubleVar(value=0)
        self.is_running = False
        self.foh_is_running = False

        self.step_labels: list[tk.Label] = []
        self.step_status_labels: list[tk.Label] = []

        self.wait_overlay: tk.Toplevel | None = None
        self.wait_overlay_text_var = tk.StringVar(value="WAIT\nDO NOT TOUCH THE MOUSE")

        self.signal_alert: tk.Toplevel | None = None
        self.signal_alert_text_var = tk.StringVar(value="")
        self._last_signal_bad_time = 0.0

        self.signal_checker = OpenSignalsHealthChecker(
            check_every_sec=1.0,
            window_sec=8.0,
            on_status=self.handle_signal_status,
        )

        self._configure_styles()
        self._build_ui()
        self.reset_steps()
        self.participant_entry.focus_set()

    def _configure_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "FOH.Horizontal.TProgressbar",
            troughcolor="#132d1f",
            background=self.GREEN,
            bordercolor="#132d1f",
            lightcolor=self.GREEN,
            darkcolor=self.GREEN,
            thickness=34,
        )

    def _build_ui(self) -> None:
        outer = tk.Frame(self.root, bg=self.BG)
        outer.pack(fill="both", expand=True, padx=60, pady=40)

        tk.Label(
            outer,
            text="FOH Session",
            font=("Segoe UI", 44, "bold"),
            bg=self.BG,
            fg=self.TEXT,
        ).pack(anchor="w", pady=(0, 20))

        main = tk.Frame(outer, bg=self.BG)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=2)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        left = tk.Frame(main, bg=self.BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 28))

        right = tk.Frame(main, bg=self.BG)
        right.grid(row=0, column=1, sticky="nsew")

        self._build_main_card(left)
        self._build_warning_card(left)
        self._build_steps_card(right)

        bottom = tk.Frame(outer, bg=self.BG)
        bottom.pack(fill="x", pady=(24, 0))

        tk.Button(
            bottom,
            text="Exit Full Screen",
            command=lambda: self.root.attributes("-fullscreen", False),
            font=("Segoe UI", 13, "bold"),
            bg="#33443a",
            fg=self.WHITE,
            relief="flat",
            padx=18,
            pady=10,
        ).pack(side="right")

    def _card(self, parent: tk.Frame) -> tk.Frame:
        return tk.Frame(parent, bg=self.PANEL, highlightbackground="#244a34", highlightthickness=1)

    def _build_main_card(self, parent: tk.Frame) -> None:
        card = self._card(parent)
        card.pack(fill="both", expand=True)

        tk.Label(card, text="Participant ID", font=("Segoe UI", 24, "bold"), bg=self.PANEL, fg=self.TEXT).pack(
            anchor="w", padx=34, pady=(32, 8)
        )

        self.participant_entry = tk.Entry(
            card,
            textvariable=self.participant_id_var,
            font=("Segoe UI", 34, "bold"),
            justify="center",
            bg=self.WHITE,
            fg=self.BLACK,
            insertbackground=self.BLACK,
            relief="flat",
        )
        self.participant_entry.pack(fill="x", padx=34, pady=(0, 24), ipady=14)
        self.participant_entry.bind("<Return>", lambda _event: self.start_pressed())

        instruction_box = tk.LabelFrame(
            card,
            text=" NOW DO THIS ",
            font=("Segoe UI", 22, "bold"),
            bg="#fff3b0",
            fg="#111111",
            padx=26,
            pady=20,
        )
        instruction_box.pack(fill="x", padx=34, pady=(0, 26))

        tk.Label(
            instruction_box,
            textvariable=self.status_var,
            font=("Segoe UI", 28, "bold"),
            bg="#fff3b0",
            fg="#111111",
            justify="left",
            anchor="w",
            wraplength=1000,
        ).pack(fill="x")

        self.progress = ttk.Progressbar(
            card,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
            style="FOH.Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x", padx=34, pady=(0, 34), ipady=8)

        buttons = tk.Frame(card, bg=self.PANEL)
        buttons.pack(fill="x", padx=34, pady=(0, 28))

        self.next_button = tk.Button(
            buttons,
            text="START",
            command=self.start_pressed,
            font=("Segoe UI", 30, "bold"),
            bg=self.GREEN,
            fg=self.WHITE,
            activebackground=self.GREEN_DARK,
            activeforeground=self.WHITE,
            relief="flat",
            padx=30,
            pady=26,
            cursor="hand2",
        )
        self.next_button.pack(fill="x", pady=(0, 18))

        self.exit_button = tk.Button(
            buttons,
            text="STOP / CLOSE EVERYTHING",
            command=self.exit_program_threaded,
            font=("Segoe UI", 20, "bold"),
            bg=self.ORANGE,
            fg=self.WHITE,
            activebackground=self.ORANGE_DARK,
            activeforeground=self.WHITE,
            relief="flat",
            padx=24,
            pady=18,
            cursor="hand2",
        )
        self.exit_button.pack(fill="x")

    def _build_warning_card(self, parent: tk.Frame) -> None:
        card = tk.Frame(parent, bg="#2b1e05", highlightbackground=self.AMBER, highlightthickness=2)
        card.pack(fill="x", pady=(22, 0))

        tk.Label(card, text="DO NOT TOUCH THE MOUSE", font=("Segoe UI", 30, "bold"), bg="#2b1e05", fg=self.AMBER).pack(
            anchor="w", padx=30, pady=(22, 6)
        )

        tk.Label(
            card,
            text="The computer clicks buttons automatically. Only touch the mouse if a permission pop-up asks for Yes.",
            font=("Segoe UI", 17, "bold"),
            bg="#2b1e05",
            fg="#fff4c2",
            justify="left",
            wraplength=1100,
        ).pack(anchor="w", padx=30, pady=(0, 22))

    def _build_steps_card(self, parent: tk.Frame) -> None:
        card = self._card(parent)
        card.pack(fill="both", expand=True)

        tk.Label(card, text="Checklist", font=("Segoe UI", 28, "bold"), bg=self.PANEL, fg=self.TEXT).pack(
            anchor="w", padx=28, pady=(28, 18)
        )

        for step in self.STEPS:
            row = tk.Frame(card, bg=self.PANEL)
            row.pack(fill="x", padx=28, pady=7)

            status = tk.Label(row, text="○", font=("Segoe UI", 22, "bold"), bg=self.PANEL, fg=self.MUTED, width=2)
            status.pack(side="left")

            label = tk.Label(row, text=step, font=("Segoe UI", 17, "bold"), bg=self.PANEL, fg=self.MUTED, anchor="w")
            label.pack(side="left", fill="x", expand=True)

            self.step_status_labels.append(status)
            self.step_labels.append(label)

        tk.Frame(card, bg=self.PANEL).pack(fill="both", expand=True)

        tk.Label(
            card,
            text="Enter the participant ID and press START once. After that, only STOP / CLOSE EVERYTHING remains.",
            font=("Segoe UI", 15, "bold"),
            bg=self.PANEL,
            fg=self.MUTED,
            wraplength=520,
            justify="left",
        ).pack(anchor="w", padx=28, pady=(0, 28))

    # ------------------------------------------------------------------
    # Big WAIT overlay and signal warning windows
    # ------------------------------------------------------------------

    def _get_monitor_geometry(self, prefer_secondary: bool = False) -> tuple[int, int, int, int]:
        """Return x, y, width, height. Uses screeninfo if available; otherwise primary screen."""
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
        win.focus_force()

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
                fg=self.AMBER,
                justify="center",
                wraplength=1400,
            ).pack(expand=True)

            tk.Label(
                holder,
                text="THE COMPUTER IS BUSY. DO NOT TOUCH THE MOUSE OR KEYBOARD.",
                font=("Segoe UI", 30, "bold"),
                bg="#050505",
                fg=self.WHITE,
                justify="center",
                wraplength=1400,
            ).pack(pady=(0, 40))

        self.root.after(0, _show)

    def hide_wait_overlay(self) -> None:
        def _hide() -> None:
            if self.wait_overlay is not None and self.wait_overlay.winfo_exists():
                self.wait_overlay.withdraw()

        self.root.after(0, _hide)

    def show_signal_alert(self, message: str) -> None:
        def _show() -> None:
            self.signal_alert_text_var.set(
                "Participant may continue.\n\n"
                "1. Press OK on any error.\n"
                "2. Press red RECORD if visible.\n"
                 "3. Wait 10 seconds.\n"
                 "4. If signal returns, continue.\n"
                 "5. If signal does not return, check EDA/ECG device is ON."
                 )

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
                    fg=self.WHITE,
                ).pack(pady=(20, 20))

                tk.Label(
                    holder,
                    textvariable=self.signal_alert_text_var,
                    font=("Segoe UI", 36, "bold"),
                    bg="#7a0000",
                    fg=self.WHITE,
                    justify="center",
                    wraplength=1400,
                ).pack(expand=True)

                tk.Label(
                    holder,
                    text="Fix EDA/ECG now. The recording may continue, but this participant may have bad physiological data.",
                    font=("Segoe UI", 26, "bold"),
                    bg="#7a0000",
                    fg="#ffe5e5",
                    justify="center",
                    wraplength=1400,
                ).pack(pady=(20, 20))

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
        if not self.is_running:
            return

        signal_good = bool(status.stream_ok and status.eda_ok and status.ecg_ok)

        if signal_good:
            # Wait a moment before hiding so the alert does not flicker.
            if time.time() - self._last_signal_bad_time > 3:
                self.hide_signal_alert()
            return

        self._last_signal_bad_time = time.time()

        message = (
            "CHECK EDA / ECG NOW\n\n"
            f"{status.stream_message}\n"
            f"{status.eda_message}\n"
            f"{status.ecg_message}"
        )

        if self.foh_is_running:
            self.show_signal_alert(message)
        else:
            self.root.after(0, lambda: self.status_var.set(message.replace("\n", "  ")))

    # ------------------------------------------------------------------
    # Normal GUI helpers
    # ------------------------------------------------------------------

    def set_instruction(self, text: str) -> None:
        self.status_var.set(text)
        self.root.update_idletasks()

    def log(self, message: str) -> None:
        self.status_var.set(message)
        self.root.update_idletasks()

    def set_progress(self, value: float, status: str, active_step: int | None = None) -> None:
        self.progress_var.set(value)
        self.status_var.set(status)
        if active_step is not None:
            for i in range(len(self.STEPS)):
                if i < active_step:
                    self.update_step(i, "done")
                elif i == active_step:
                    self.update_step(i, "active")
                else:
                    self.update_step(i, "pending")
        self.root.update_idletasks()

    def update_step(self, index: int, state: str) -> None:
        if not 0 <= index < len(self.step_labels):
            return

        config = {
            "pending": ("○", self.MUTED),
            "active": ("●", self.AMBER),
            "done": ("✓", self.GREEN),
            "error": ("!", self.RED),
        }
        symbol, colour = config.get(state, config["pending"])

        self.step_status_labels[index].configure(text=symbol, fg=colour)
        self.step_labels[index].configure(fg=colour if state in {"active", "error"} else self.MUTED)
        self.root.update_idletasks()

    def reset_steps(self) -> None:
        for i in range(len(self.STEPS)):
            self.update_step(i, "pending")

    def mark_done_until(self, index: int) -> None:
        for i in range(index + 1):
            self.update_step(i, "done")

    def get_participant_id(self) -> str:
        pid = self.participant_id_var.get().strip()
        if not pid:
            raise ValueError("Please enter the participant ID first.")
        return pid

    def set_buttons_running(self, running: bool) -> None:
        self.is_running = running
        self.participant_entry.configure(state="disabled" if running else "normal")
        self.exit_button.configure(state="normal")

    def start_pressed(self) -> None:
        if self.is_running:
            return

        try:
            self.get_participant_id()
        except ValueError as exc:
            messagebox.showerror("Participant ID", str(exc))
            return

        # START is available once only. After it is pressed, the only remaining
        # researcher action is STOP / CLOSE EVERYTHING.
        self.next_button.pack_forget()
        self.participant_entry.configure(state="disabled")
        threading.Thread(target=self.run_full_session, daemon=True).start()

    def exit_program_threaded(self) -> None:
        threading.Thread(target=self.exit_program, daemon=True).start()

    def ask_yes_no(self, title: str, message: str) -> bool:
        self.hide_wait_overlay()
        result = {"val": False}
        done = threading.Event()

        def _show() -> None:
            self.bring_gui_front()
            result["val"] = messagebox.askyesno(title, message)
            done.set()

        self.root.after(0, _show)
        done.wait()
        return result["val"]

    def show_error(self, title: str, message: str) -> None:
        self.hide_wait_overlay()
        done = threading.Event()

        def _show() -> None:
            self.bring_gui_front()
            messagebox.showerror(title, message)
            done.set()

        self.root.after(0, _show)
        done.wait()

    def show_info(self, title: str, message: str) -> None:
        self.hide_wait_overlay()
        done = threading.Event()

        def _show() -> None:
            self.bring_gui_front()
            messagebox.showinfo(title, message)
            done.set()

        self.root.after(0, _show)
        done.wait()

    def bring_gui_front(self) -> None:
        self.root.deiconify()
        self.root.attributes("-fullscreen", True)
        self.root.lift()
        self.root.focus_force()
        self.root.update_idletasks()

    def kill_processes_by_commandline_token(self, token: str) -> None:
        """Close processes whose Windows command line contains the supplied token."""
        safe_token = token.replace("'", "''")
        command = (
            "Get-CimInstance Win32_Process | "
            f"Where-Object {{ $_.CommandLine -like '*{safe_token}*' }} | "
            "ForEach-Object { "
            "try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} "
            "}"
        )
        try:
            subprocess.call(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        except Exception:
            pass


    def close_dsi2lsl_forcefully(self) -> None:
        """Force-close DSI2LSL, including GUI, Python-hosted, and COM7-linked processes."""
        # Exact executable names used by different DSI2LSL builds.
        for process_name in (
            "dsi2lslgui.exe",
            "DSI2LSL.exe",
            "DSI-Streamer-v.1.08.120.exe",
        ):
            try:
                subprocess.call(
                    ["taskkill", "/f", "/t", "/im", process_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                )
            except Exception:
                pass

        # Catch shortcut-launched or Python-hosted versions whose executable name differs.
        command = (
            "$currentPid = $PID; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { "
            "$_.ProcessId -ne $currentPid -and "
            "($_.CommandLine -match 'dsi2lsl|DSI2LSL|dsi2lslgui|DSI-Streamer|COM7') "
            "} | ForEach-Object { "
            "try { taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null } catch {} "
            "}"
        )
        try:
            subprocess.call(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        except Exception:
            pass

        time.sleep(0.8)

    def kill_session_apps(self) -> None:
        """Force-close session applications and any remaining terminal process trees."""
        # DSI2LSL can remain open under several different executable names.
        self.close_dsi2lsl_forcefully()

        # Then close script-hosted/session processes that may not use a predictable exe name.
        for token in self.COMMANDLINE_TOKENS_TO_CLOSE:
            self.kill_processes_by_commandline_token(token)

        # Then force-close known applications and their complete child process trees.
        # Terminals are deliberately last so they cannot interrupt earlier cleanup commands.
        terminal_names = {"powershell.exe", "pwsh.exe", "cmd.exe", "WindowsTerminal.exe", "wt.exe"}
        ordered_names = [name for name in self.KILL_LIST if name not in terminal_names]
        ordered_names.extend(name for name in self.KILL_LIST if name in terminal_names)

        for process_name in ordered_names:
            try:
                subprocess.call(
                    ["taskkill", "/f", "/t", "/im", process_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                )
            except Exception:
                pass

        # Repeat once because closing one parent can expose a delayed child process/window.
        time.sleep(0.8)
        for process_name in ordered_names:
            try:
                subprocess.call(
                    ["taskkill", "/f", "/t", "/im", process_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                )
            except Exception:
                pass

    def stop_labrecorder(self) -> None:
        try:
            from pywinauto import Application

            self.show_wait_overlay("WAIT\nSTOPPING RECORDING")
            self.set_progress(96, "Stopping LabRecorder...", active_step=8)

            app = Application(backend="uia").connect(title="Lab Recorder", timeout=4)
            win = app.window(title="Lab Recorder")
            win.set_focus()
            time.sleep(1)

            stop_button = win.child_window(
                title="Stop",
                auto_id="MainWindow.centralwidget.groupBox_recording.stopButton",
                control_type="Button",
            )

            if stop_button.exists(timeout=2):
                stop_button.click_input()
                time.sleep(2)

        except Exception as e:
            self.log(f"Could not stop LabRecorder automatically: {e}")

    def close_session_apps_safely(self) -> None:
        """Restore the saved layout, stop LabRecorder safely, then close everything else."""
        self.foh_is_running = False
        self.show_wait_overlay("WAIT\nPREPARING TO STOP RECORDING")

        # Re-apply the saved window layout before clicking LabRecorder Stop.
        # This protects the coordinate/button layout if a user moved or resized a window.
        try:
            self.set_progress(94, "Restoring the saved window layout...", active_step=8)
            self.launcher.apply_window_layout()
            time.sleep(2)
        except Exception as exc:
            # Continue to the safe LabRecorder stop even if arranging the windows fails.
            self.log(f"Could not restore window layout before closing: {exc}")

        # LabRecorder must be stopped and given time to finalize the recording
        # before any other application or terminal is closed.
        self.stop_labrecorder()
        time.sleep(4)

        # Only after LabRecorder has finalized do we stop monitoring and close apps.
        self.signal_checker.stop()
        self.hide_signal_alert()
        self.kill_session_apps()
        self.hide_wait_overlay()

    def confirm_device_ready(self) -> bool:
        self.bring_gui_front()
        return self.ask_yes_no(
            "Quick check",
            "Before we start:\n\n"
            "• EDA/ECG device is ON\n"
            "• Participant is ready\n"
            "• Do not touch the mouse\n\n"
            "Ready?",
        )

    def confirm_ecg_eda_spikes_before_labrecorder(self, max_attempts: int = 3) -> bool:
        for attempt in range(1, max_attempts + 1):
            self.bring_gui_front()
            self.set_progress(60, "Check ECG/EDA in OpenSignals.", active_step=5)

            signals_ok = self.ask_yes_no(
                "Check OpenSignals",
                "Look at OpenSignals now.\n\n"
                "Do ECG and EDA show live spikes/waves?\n\n"
                "YES = both are moving\n"
                "NO = flat, missing, frozen, or error",
            )

            if signals_ok:
                self.update_step(5, "done")
                return True

            if attempt < max_attempts:
                self.show_info(
                    "Fix signal",
                    "Try this:\n\n"
                    "1. Switch EDA/ECG OFF.\n"
                    "2. Switch it ON again.\n"
                    "3. Press OK on any error.\n"
                    "4. Press the red record button if needed.\n"
                    "5. Wait for spikes/waves.",
                )
                self.set_progress(58, "Fix ECG/EDA, then the check will appear again.", active_step=5)
                time.sleep(5)
            else:
                return self.ask_yes_no(
                    "Continue?",
                    "ECG/EDA was still not confirmed.\n\n"
                    "Recommended: NO, then restart setup.\n\n"
                    "Continue anyway?",
                )

        return False

    def setup_labrecorder_with_retry(
       self,
       participant_id: str,
       max_attempts: int = 3,
      ) -> bool:
      self.show_wait_overlay("WAIT\nSTARTING LABRECORDER")
      self.set_progress(
        70,
        "Starting LabRecorder. Do not touch the mouse.",
        active_step=6,
      )

      try:
        setup_labrecorder(participant_id)

      except Exception as e:
        # Terminal only — do not interrupt the participant/user.
        print(f"[WARN] LabRecorder automation reported: {e}")

      time.sleep(3)

      self.hide_wait_overlay()
      self.update_step(6, "done")

      return True

    def bring_foh_to_front(self) -> None:
        try:
            from pywinauto import Application

            app = Application(backend="uia").connect(title_re=".*AxioBiofeedback.*", timeout=5)
            win = app.window(title_re=".*AxioBiofeedback.*")
            win.set_focus()
            win.maximize()
            time.sleep(1)

        except Exception:
            pass

    def wait_until_foh_closes(self) -> None:
        self.set_progress(92, "FOH/VR is running. Waiting for it to close.", active_step=7)

        while True:
            try:
                from pywinauto import Application

                Application(backend="uia").connect(title_re=".*AxioBiofeedback.*", timeout=2)
                time.sleep(2)

            except Exception:
                break

    def close_launcher_terminal(self) -> None:
        """Close the terminal that launched this GUI, but only when it is a terminal process."""
        parent_pid = os.getppid()

        try:
            command = (
                f"$p = Get-CimInstance Win32_Process -Filter \"ProcessId={parent_pid}\"; "
                "if ($p -and $p.Name -match '^(cmd|powershell|pwsh|WindowsTerminal|wt)\\.exe$') { "
                f"Stop-Process -Id {parent_pid} -Force -ErrorAction SilentlyContinue "
                "}"
            )
            subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-WindowStyle",
                    "Hidden",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass

    def finish_session_and_close_gui(self) -> None:
        """Close the launcher terminal and GUI silently after cleanup."""
        self.foh_is_running = False
        self.hide_signal_alert()
        self.hide_wait_overlay()
        self.close_launcher_terminal()
        self.root.after(0, self.root.destroy)

    def run_full_session(self) -> None:
        try:
            self.set_buttons_running(True)
            self.reset_steps()
            self.hide_signal_alert()

            pid = self.get_participant_id()
            self.update_step(0, "done")

            self.show_wait_overlay("WAIT\nOPENING PROGRAMS")
            self.set_progress(5, "Opening programs. Do not touch the mouse.", active_step=1)
            self.launcher.launch_core_apps()

            self.set_progress(15, "Wait. If VIVE asks permission, click Yes. Otherwise do not touch the mouse.", active_step=1)
            time.sleep(20)
            self.update_step(1, "done")

            self.show_wait_overlay("WAIT\nARRANGING WINDOWS")
            self.set_progress(30, "Arranging windows. Do not touch the mouse.", active_step=2)
            self.launcher.apply_window_layout()
            time.sleep(3)
            self.update_step(2, "done")
            self.hide_wait_overlay()

            self.set_progress(38, "Quick device check.", active_step=3)
            if not self.confirm_device_ready():
                self.update_step(3, "error")
                self.set_progress(0, "Cancelled. Press STOP / CLOSE EVERYTHING.")
                self.is_running = False
                return
            self.update_step(3, "done")

            self.show_wait_overlay("WAIT\nSTARTING OPENSIGNALS")
            self.set_progress(48, "Starting OpenSignals. Do not touch the mouse.", active_step=4)
            setup_opensignals()
            time.sleep(2)
            self.hide_wait_overlay()

            self.set_progress(52, "Automatically checking EDA/ECG signal.", active_step=4)
            self.signal_checker.start()
            if not self.signal_checker.wait_for_good_signal(timeout_sec=30):
                self.signal_checker.stop()
                self.update_step(4, "error")
                self.show_error(
                    "EDA/ECG problem",
                    "EDA/ECG signal was not detected properly.\n\n"
                    "Switch the device OFF and ON, check OpenSignals, then try again.",
                )
                self.is_running = False
                return

            self.update_step(4, "done")

            signals_ok = self.confirm_ecg_eda_spikes_before_labrecorder()
            if not signals_ok:
                self.signal_checker.stop()
                self.update_step(5, "error")
                self.set_progress(0, "Cancelled. ECG/EDA signal was not confirmed.")
                self.is_running = False
                return

            labrecorder_ok = self.setup_labrecorder_with_retry(pid)
            if not labrecorder_ok:
                self.signal_checker.stop()
                self.set_progress(0, "Cancelled. LabRecorder could not start.")
                self.is_running = False
                return

            self.show_wait_overlay(
                "WAIT\nSETTING UP FOH\n\n"
                "PARTICIPANT ID IS ENTERED AUTOMATICALLY\n"
                "DO NOT TYPE OR CLICK ANYTHING"
            )
            self.set_progress(
                82,
                "Entering participant ID and preparing FOH automatically.",
                active_step=7,
            )

            # IMPORTANT: remove the topmost WAIT/GUI before setup_foh() clicks.
            # Otherwise FOH opens behind this GUI and cannot receive the automated input.
            time.sleep(1)
            self.hide_wait_overlay()

            def _move_gui_out_of_way() -> None:
                try:
                    self.root.attributes("-topmost", False)
                except Exception:
                    pass
                self.root.withdraw()

            self.root.after(0, _move_gui_out_of_way)
            time.sleep(1.0)

            # setup_foh() now launches/focuses FOH and enters the participant ID
            # while this GUI is completely out of the way.
            setup_foh(pid)
            time.sleep(2)

            self.update_step(7, "done")
            self.bring_foh_to_front()

            self.set_progress(90, "FOH is ready. Complete the FOH/VR task.", active_step=7)

            self.foh_is_running = True

            self.wait_until_foh_closes()
            self.close_session_apps_safely()
            self.finish_session_and_close_gui()

        except Exception as e:
            self.foh_is_running = False
            self.signal_checker.stop()
            self.hide_signal_alert()
            self.hide_wait_overlay()
            self.bring_gui_front()
            for i in range(len(self.STEPS)):
                if self.step_status_labels[i].cget("text") == "●":
                    self.update_step(i, "error")
            self.progress_var.set(0)
            self.is_running = False
            self.show_error("Session Error", str(e))
            self.set_instruction("An error occurred. Press STOP / CLOSE EVERYTHING.")

    def exit_program(self) -> None:
        confirm = self.ask_yes_no("Stop / Close Everything", "Stop recording and close all FOH session apps?")
        if not confirm:
            return

        try:
            self.bring_gui_front()
            self.show_wait_overlay("WAIT\nSTOPPING AND CLOSING EVERYTHING")
            self.set_progress(10, "Stopping and closing everything...", active_step=8)
            self.close_session_apps_safely()
            time.sleep(1)
        finally:
            self.close_launcher_terminal()
            self.root.after(0, self.root.destroy)


def main() -> None:
    root = tk.Tk()
    FullscreenSessionGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
