from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
import subprocess

from session_controller import SessionLauncher
from automation_layer import setup_opensignals, setup_labrecorder, setup_foh


class FullscreenSessionGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("MoBI Mooi Session")
        self.root.attributes("-fullscreen", True)
        self.root.configure(bg="#f4f4f4")

        self.launcher = SessionLauncher()
        self.participant_id_var = tk.StringVar(value="TEST001")
        self.status_var = tk.StringVar(value="Ready")
        self.progress_var = tk.DoubleVar(value=0)

        self._build_ui()

    def _build_ui(self) -> None:
        outer = tk.Frame(self.root, bg="#f4f4f4")
        outer.pack(fill="both", expand=True, padx=40, pady=30)

        top_bar = tk.Frame(outer, bg="#f4f4f4")
        top_bar.pack(fill="x", pady=(0, 20))

        tk.Label(
            top_bar,
            text="MoBI Mooi Session",
            font=("Segoe UI", 28, "bold"),
            bg="#f4f4f4",
        ).pack(anchor="w")

        tk.Label(
            top_bar,
            text="Guided session startup",
            font=("Segoe UI", 12),
            bg="#f4f4f4",
        ).pack(anchor="w", pady=(4, 0))

        middle = tk.Frame(outer, bg="#f4f4f4")
        middle.pack(fill="both", expand=True)

        participant_box = ttk.LabelFrame(middle, text="Participant", padding=20)
        participant_box.pack(fill="x", pady=(0, 20))

        ttk.Label(participant_box, text="Participant ID:").grid(
            row=0, column=0, sticky="w", padx=(0, 12), pady=8
        )
        ttk.Entry(
            participant_box,
            textvariable=self.participant_id_var,
            width=28,
        ).grid(row=0, column=1, sticky="w", pady=8)

        ttk.Button(
            participant_box,
            text="Run Full Session",
            command=self.run_full_session_threaded,
        ).grid(row=0, column=2, padx=(20, 0), pady=8, sticky="ew")

        ttk.Button(
            participant_box,
            text="End & Restart Cleanly",
            command=self.restart_threaded,
        ).grid(row=0, column=3, padx=(12, 0), pady=8, sticky="ew")

        participant_box.columnconfigure(2, weight=1)
        participant_box.columnconfigure(3, weight=1)

        processing_box = ttk.LabelFrame(middle, text="Processing", padding=24)
        processing_box.pack(fill="x", pady=(0, 20))

        self.large_status_label = tk.Label(
            processing_box,
            textvariable=self.status_var,
            font=("Segoe UI", 22, "bold"),
            bg=self.root.cget("bg"),
            anchor="w",
            justify="left",
        )
        self.large_status_label.pack(fill="x", pady=(0, 18))

        self.progress = ttk.Progressbar(
            processing_box,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
            length=900,
        )
        self.progress.pack(fill="x", pady=(0, 18))

        self.big_notice = tk.Label(
            processing_box,
            text="Please do not move the mouse while setup is running.",
            font=("Segoe UI", 20, "bold"),
            fg="#9a1f1f",
            bg=self.root.cget("bg"),
        )
        self.big_notice.pack(fill="x", pady=(0, 8))

        self.sub_notice = tk.Label(
            processing_box,
            text="The software is positioning windows and clicking buttons automatically.",
            font=("Segoe UI", 13),
            bg=self.root.cget("bg"),
            justify="left",
            anchor="w",
        )
        self.sub_notice.pack(fill="x")

        log_box = ttk.LabelFrame(middle, text="Session Log", padding=16)
        log_box.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            log_box,
            height=12,
            wrap="word",
            font=("Consolas", 11),
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")

        bottom = tk.Frame(outer, bg="#f4f4f4")
        bottom.pack(fill="x", pady=(16, 0))

        ttk.Button(
            bottom,
            text="Exit Full Screen",
            command=self.exit_fullscreen,
        ).pack(side="right")

        self.log("Ready.")

    def exit_fullscreen(self) -> None:
        self.root.attributes("-fullscreen", False)

    def log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.status_var.set(message)
        self.root.update_idletasks()

    def set_progress(self, value: float, status: str) -> None:
        self.progress_var.set(value)
        self.status_var.set(status)
        self.root.update_idletasks()
        self.log(status)

    def get_participant_id(self) -> str:
        pid = self.participant_id_var.get().strip()
        if not pid:
            raise ValueError("Participant ID is empty")
        return pid

    def run_full_session_threaded(self) -> None:
        threading.Thread(target=self.run_full_session, daemon=True).start()

    def restart_threaded(self) -> None:
        threading.Thread(target=self.restart_all, daemon=True).start()

    def ask_yes_no(self, title: str, message: str) -> bool:
        result = {"val": False}
        done = threading.Event()

        def _show() -> None:
            result["val"] = messagebox.askyesno(title, message)
            done.set()

        self.root.after(0, _show)
        done.wait()
        return result["val"]

    def show_error(self, title: str, message: str) -> None:
        done = threading.Event()

        def _show() -> None:
            messagebox.showerror(title, message)
            done.set()

        self.root.after(0, _show)
        done.wait()




    def bring_foh_to_front(self):
     try:
        from pywinauto import Application
        import time

        app = Application(backend="uia").connect(title_re=".*AxioBiofeedback.*")
        win = app.window(title_re=".*AxioBiofeedback.*")

        print("[INFO] Bringing FOH to front...")
        win.set_focus()
        win.maximize()

        time.sleep(1)

     except Exception as e:
        print(f"[WARN] Could not bring FOH to front: {e}")





    def run_full_session(self) -> None:
        try:
            pid = self.get_participant_id()

            self.set_progress(5, "Launching apps...")
            self.launcher.launch_core_apps()

            self.set_progress(15, "If VIVE permission appears, click Yes manually...")
            time.sleep(10)

            self.set_progress(28, "Applying window layout...")
            self.launcher.apply_window_layout()
            time.sleep(3)

            device_ready = self.ask_yes_no(
                "EDA/ECG Device",
                "Is the EDA/ECG device on and ready?",
            )
            if not device_ready:
                self.set_progress(0, "Session cancelled before recording.")
                return

            self.set_progress(45, "Starting OpenSignals recording...")
            setup_opensignals()
            self.set_progress(55, "Waiting for OpenSignals recording to settle...")
            time.sleep(2)

            self.set_progress(65, "Starting LabRecorder...")
            setup_labrecorder(pid)
            time.sleep(2)

            self.set_progress(82, "Starting FOH...")
            setup_foh(pid)
            time.sleep(1)

            self.set_progress(100, "Session ready. Launching VR...")
            self.bring_foh_to_front()
            self.root.withdraw()


        except Exception as e:
            self.log(f"Error: {e}")
            self.progress_var.set(0)
            self.show_error("Session Error", str(e))

    def restart_all(self) -> None:
        try:
            confirm = self.ask_yes_no(
                "Restart Session",
                "This will close the main apps and start again cleanly. Continue?",
            )
            if not confirm:
                return

            self.set_progress(10, "Closing apps...")

            kill_list = [
                "OpenSignals.exe",
                "LabRecorder.exe",
                "AxioBiofeedback.exe",
                "DSI-Streamer-v.1.08.120.exe",
                "AudioVideoRecorder.exe",
            ]

            for proc in kill_list:
                subprocess.call(f"taskkill /f /im {proc}", shell=True)

            time.sleep(3)

            self.set_progress(20, "Apps closed. Restarting clean session...")
            self.run_full_session()

        except Exception as e:
            self.log(f"Restart failed: {e}")
            self.progress_var.set(0)
            self.show_error("Restart Error", str(e))


def main() -> None:
    root = tk.Tk()
    style = ttk.Style()
    try:
        style.theme_use("vista")
    except tk.TclError:
        pass

    app = FullscreenSessionGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()