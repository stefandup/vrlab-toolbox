import json
import threading
from datetime import datetime
from io import StringIO
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import keyring
import pandas as pd
import requests


APP_NAME = "MobiLab REDCap"
KEYRING_SERVICE = "MobiLab_REDCap"
KEYRING_USERNAME = "api_token"

CONFIG_DIR = Path.home() / ".mobilab_redcap"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "redcap_url": "https://redcap.sun.ac.za/api/",
    "report_id": 14932,
    "output_folder": str(Path.home() / "Desktop" / "redcap_output"),
}


def load_config():
    config = DEFAULT_CONFIG.copy()

    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("r", encoding="utf-8") as f:
                config.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass

    return config


def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    # Restrict permissions on macOS/Linux where supported.
    try:
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass


def get_api_token():
    return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)


def save_api_token(token):
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, token)


def delete_api_token():
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass


def download_redcap_report(redcap_url, api_token, report_id, output_folder):
    payload = {
        "token": api_token,
        "content": "report",
        "report_id": str(report_id),
        "format": "csv",
        "rawOrLabel": "raw",
        "rawOrLabelHeaders": "raw",
        "exportCheckboxLabel": "false",
        "returnFormat": "json",
    }

    response = requests.post(redcap_url, data=payload, timeout=90)

    if not response.ok:
        raise RuntimeError(
            f"REDCap returned HTTP {response.status_code}:\n"
            f"{response.text[:500]}"
        )

    content_type = response.headers.get("Content-Type", "").lower()

    # REDCap may return an error message instead of CSV.
    if "json" in content_type:
        try:
            body = response.json()
        except ValueError:
            body = None

        if isinstance(body, dict) and body.get("error"):
            raise RuntimeError(f"REDCap API error:\n{body['error']}")

    try:
        df = pd.read_csv(StringIO(response.text))
    except Exception as exc:
        raise RuntimeError(
            "The REDCap response could not be read as CSV.\n\n"
            f"Response preview:\n{response.text[:500]}"
        ) from exc

    output_folder = Path(output_folder).expanduser()
    date_folder = output_folder / datetime.now().strftime("%Y-%m-%d")
    date_folder.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_file = date_folder / f"redcap_export_{timestamp}.csv"

    df.to_csv(output_file, index=False)

    return output_file, len(df), len(df.columns)


class RedcapApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(APP_NAME)
        self.geometry("680x360")
        self.minsize(650, 340)

        self.config_data = load_config()

        self.output_var = tk.StringVar(
            value=self.config_data.get("output_folder", DEFAULT_CONFIG["output_folder"])
        )
        self.status_var = tk.StringVar(value="Ready.")
        self.token_status_var = tk.StringVar()

        self._build_gui()
        self._refresh_token_status()

        # On first launch, immediately ask for settings/token.
        if not get_api_token():
            self.after(250, self.open_settings)

    def _build_gui(self):
        container = ttk.Frame(self, padding=24)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="MobiLab REDCap Data Pull",
            font=("TkDefaultFont", 18, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            container,
            text=(
                "Download the configured REDCap report and save it locally. "
                "Your API token is stored securely in the operating system credential store."
            ),
            wraplength=610,
        ).pack(anchor="w", pady=(8, 22))

        folder_frame = ttk.LabelFrame(container, text="Save location", padding=12)
        folder_frame.pack(fill="x")

        folder_entry = ttk.Entry(folder_frame, textvariable=self.output_var)
        folder_entry.pack(side="left", fill="x", expand=True)

        ttk.Button(
            folder_frame,
            text="Browse…",
            command=self.choose_output_folder,
        ).pack(side="left", padx=(8, 0))

        action_frame = ttk.Frame(container)
        action_frame.pack(fill="x", pady=(20, 0))

        self.download_button = ttk.Button(
            action_frame,
            text="Pull REDCap Data",
            command=self.start_download,
        )
        self.download_button.pack(side="left")

        ttk.Button(
            action_frame,
            text="Settings",
            command=self.open_settings,
        ).pack(side="left", padx=(10, 0))

        self.progress = ttk.Progressbar(
            container,
            mode="indeterminate",
        )
        self.progress.pack(fill="x", pady=(20, 8))

        ttk.Label(
            container,
            textvariable=self.status_var,
            wraplength=610,
        ).pack(anchor="w")

        ttk.Label(
            container,
            textvariable=self.token_status_var,
        ).pack(anchor="w", pady=(12, 0))

    def choose_output_folder(self):
        selected = filedialog.askdirectory(
            title="Choose where REDCap exports should be saved"
        )
        if selected:
            self.output_var.set(selected)
            self.config_data["output_folder"] = selected
            save_config(self.config_data)

    def _refresh_token_status(self):
        if get_api_token():
            self.token_status_var.set("API token: securely stored")
        else:
            self.token_status_var.set("API token: not configured")

    def open_settings(self):
        window = tk.Toplevel(self)
        window.title("REDCap Settings")
        window.geometry("600x340")
        window.transient(self)
        window.grab_set()

        frame = ttk.Frame(window, padding=20)
        frame.pack(fill="both", expand=True)

        url_var = tk.StringVar(
            value=self.config_data.get("redcap_url", DEFAULT_CONFIG["redcap_url"])
        )
        report_var = tk.StringVar(
            value=str(self.config_data.get("report_id", DEFAULT_CONFIG["report_id"]))
        )
        token_var = tk.StringVar()

        ttk.Label(frame, text="REDCap API URL").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        ttk.Entry(frame, textvariable=url_var, width=58).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(0, 14)
        )

        ttk.Label(frame, text="Report ID").grid(
            row=2, column=0, sticky="w", pady=(0, 6)
        )
        ttk.Entry(frame, textvariable=report_var, width=20).grid(
            row=3, column=0, sticky="w", pady=(0, 14)
        )

        ttk.Label(frame, text="API token").grid(
            row=4, column=0, sticky="w", pady=(0, 6)
        )
        ttk.Entry(
            frame,
            textvariable=token_var,
            show="•",
            width=58,
        ).grid(row=5, column=0, columnspan=2, sticky="ew")

        if get_api_token():
            ttk.Label(
                frame,
                text="A token is already stored. Leave this blank to keep it unchanged.",
            ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(5, 14))
        else:
            ttk.Label(
                frame,
                text="Enter the project API token. It will not be written to the config file.",
            ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(5, 14))

        def save_settings():
            try:
                report_id = int(report_var.get().strip())
            except ValueError:
                messagebox.showerror(
                    "Invalid Report ID",
                    "Report ID must be a number.",
                    parent=window,
                )
                return

            redcap_url = url_var.get().strip()
            if not redcap_url:
                messagebox.showerror(
                    "Missing URL",
                    "Please enter the REDCap API URL.",
                    parent=window,
                )
                return

            self.config_data["redcap_url"] = redcap_url
            self.config_data["report_id"] = report_id
            self.config_data["output_folder"] = self.output_var.get().strip()
            save_config(self.config_data)

            new_token = token_var.get().strip()
            if new_token:
                save_api_token(new_token)

            self._refresh_token_status()
            window.destroy()

        def forget_token():
            delete_api_token()
            self._refresh_token_status()
            token_var.set("")
            messagebox.showinfo(
                "Token removed",
                "The stored REDCap API token has been removed.",
                parent=window,
            )

        buttons = ttk.Frame(frame)
        buttons.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        ttk.Button(
            buttons,
            text="Save",
            command=save_settings,
        ).pack(side="left")

        ttk.Button(
            buttons,
            text="Forget stored token",
            command=forget_token,
        ).pack(side="left", padx=(10, 0))

        ttk.Button(
            buttons,
            text="Cancel",
            command=window.destroy,
        ).pack(side="right")

        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

    def start_download(self):
        api_token = get_api_token()

        if not api_token:
            messagebox.showwarning(
                "API token required",
                "No REDCap API token is configured. Open Settings and save the token first.",
            )
            self.open_settings()
            return

        output_folder = self.output_var.get().strip()
        if not output_folder:
            messagebox.showwarning(
                "Output folder required",
                "Please choose an output folder.",
            )
            return

        self.config_data["output_folder"] = output_folder
        save_config(self.config_data)

        self.download_button.config(state="disabled")
        self.progress.start(12)
        self.status_var.set("Connecting to REDCap and downloading report…")

        worker = threading.Thread(
            target=self._download_worker,
            args=(api_token, output_folder),
            daemon=True,
        )
        worker.start()

    def _download_worker(self, api_token, output_folder):
        try:
            output_file, rows, columns = download_redcap_report(
                redcap_url=self.config_data["redcap_url"],
                api_token=api_token,
                report_id=self.config_data["report_id"],
                output_folder=output_folder,
            )
        except Exception as exc:
            self.after(0, lambda: self._download_failed(str(exc)))
            return

        self.after(
            0,
            lambda: self._download_finished(output_file, rows, columns),
        )

    def _download_finished(self, output_file, rows, columns):
        self.progress.stop()
        self.download_button.config(state="normal")
        self.status_var.set(
            f"Done — downloaded {rows:,} rows and {columns:,} columns.\n"
            f"Saved to: {output_file}"
        )

        messagebox.showinfo(
            "Download complete",
            f"REDCap data downloaded successfully.\n\n"
            f"Rows: {rows:,}\n"
            f"Columns: {columns:,}\n\n"
            f"Saved to:\n{output_file}",
        )

    def _download_failed(self, error_message):
        self.progress.stop()
        self.download_button.config(state="normal")
        self.status_var.set("Download failed.")

        messagebox.showerror(
            "REDCap download failed",
            error_message,
        )


if __name__ == "__main__":
    app = RedcapApp()
    app.mainloop()
