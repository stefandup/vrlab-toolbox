from __future__ import annotations

import time

from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys


def close_opensignals_error() -> bool:
    closed_any = False

    for w in Desktop(backend="uia").windows():
        try:
            title = w.window_text().strip().lower()

            if "error" in title:
                print(f"[INFO] Closing OpenSignals error popup: {title}")
                w.set_focus()
                time.sleep(0.3)
                send_keys("{ENTER}")
                time.sleep(0.5)
                closed_any = True

        except Exception:
            pass

    return closed_any


def clear_existing_opensignals_errors() -> None:
    for _ in range(3):
        found = close_opensignals_error()
        time.sleep(0.3)
        if not found:
            break


def setup_opensignals() -> None:
    """Configure OpenSignals LSL + continuous mode and press Record."""
    try:
        import pyautogui

        pyautogui.PAUSE = 0.35

        app = Application(backend="uia").connect(title_re=".*OpenSignals.*")
        win = app.window(title_re=".*OpenSignals.*")

        print("[INFO] Connected to OpenSignals")
        try:
            win.restore()
        except Exception:
            pass
        win.set_focus()
        time.sleep(1.5)

        SETTINGS_BTN = (-413, 958)
        INTEGRATION_TAB = (-339, 513)
        LSL_CHECKBOX = (-718, 593)
        CONTINUOUS_CHECKBOX = (-732, 765)
        RECORD_BTN = (-687, 964)

        clear_existing_opensignals_errors()

        print("[WAIT] Letting OpenSignals settle...")
        time.sleep(2)

        print("[INFO] Clicking Change OpenSignals settings...")
        pyautogui.moveTo(*SETTINGS_BTN, duration=0.15)
        pyautogui.click()
        time.sleep(2.0)

        clear_existing_opensignals_errors()

        print("[INFO] Clicking Integration tab...")
        pyautogui.moveTo(*INTEGRATION_TAB, duration=0.15)
        pyautogui.click()
        time.sleep(1.0)

        print("[INFO] Clicking Lab Streaming Layer checkbox...")
        pyautogui.moveTo(*LSL_CHECKBOX, duration=0.15)
        pyautogui.click()
        time.sleep(0.8)

        print("[INFO] Clicking Continuous mode checkbox...")
        pyautogui.moveTo(*CONTINUOUS_CHECKBOX, duration=0.15)
        pyautogui.click()
        time.sleep(0.8)

        print("[INFO] Closing settings...")
        pyautogui.press("enter")
        time.sleep(1.5)

        clear_existing_opensignals_errors()

        print("[INFO] Clicking Record...")
        pyautogui.moveTo(*RECORD_BTN, duration=0.15)
        pyautogui.click()
        time.sleep(2)

        clear_existing_opensignals_errors()

        print("[OK] OpenSignals automated by coordinates")

    except Exception as e:
        print(f"[ERROR] OpenSignals automation failed: {e}")
        raise
