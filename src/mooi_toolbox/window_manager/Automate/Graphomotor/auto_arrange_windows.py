from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import win32con
import win32gui


def get_all_windows():
    windows = []

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)

            if title.strip():
                windows.append((hwnd, title))

    win32gui.EnumWindows(callback, None)
    return windows


def find_window(title_search: str):
    windows = get_all_windows()

    for hwnd, title in windows:
        if title_search.lower() in title.lower():
            print(f"[FOUND] {title}")
            return hwnd

    print(f"[WARN] Could not find window: {title_search}")
    return None


def bring_to_front(hwnd):
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.5)
    except Exception as e:
        print(f"[WARN] Could not bring window to front: {e}")


def save_layout(config_path: Path):
    payload = {
        "version": 1,
        "windows": [],
        "titles": [
            "Lab Recorder",
            "OpenSignals (r)evolution",
            "Graphomotor Protocol",
            "Neon",
        ],
    }

    for title in payload["titles"]:
        hwnd = find_window(title)

        if hwnd is None:
            continue

        rect = win32gui.GetWindowRect(hwnd)

        payload["windows"].append(
            {
                "title": title,
                "left": rect[0],
                "top": rect[1],
                "width": rect[2] - rect[0],
                "height": rect[3] - rect[1],
            }
        )

    config_path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )

    print(f"[OK] Layout saved to: {config_path}")


def apply_layout(config_path: Path):
    if not config_path.exists():
        raise FileNotFoundError(config_path)

    payload = json.loads(
        config_path.read_text(encoding="utf-8")
    )

    for item in payload["windows"]:
        title = item["title"]

        hwnd = find_window(title)

        if hwnd is None:
            continue

        bring_to_front(hwnd)

        win32gui.MoveWindow(
            hwnd,
            item["left"],
            item["top"],
            item["width"],
            item["height"],
            True,
        )

        print(f"[OK] Moved: {title}")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "mode",
        choices=["save", "apply"],
    )

    parser.add_argument(
        "--config",
        type=str,
        default="graphomotor_window_layout.json",
    )

    args = parser.parse_args()

    config_path = Path(args.config)

    if args.mode == "save":
        save_layout(config_path)

    elif args.mode == "apply":
        apply_layout(config_path)


if __name__ == "__main__":
    main()