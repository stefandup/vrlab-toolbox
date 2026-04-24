from __future__ import annotations

import time

from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys


def connect_exact_window(title: str, backend: str = "uia", timeout: int = 20):
    end_time = time.time() + timeout
    last_error = None

    while time.time() < end_time:
        try:
            print(f"[CONNECT] Trying exact title '{title}' with backend='{backend}'")
            app = Application(backend=backend).connect(title=title)
            win = app.window(title=title)
            print(f"[OK] Connected to window: {win.window_text()}")
            return win
        except Exception as e:
            last_error = e
            time.sleep(1)

    raise RuntimeError(
        f"Could not connect to exact window '{title}'. Last error: {last_error}"
    )


def opensignals_error_present() -> bool:
    for w in Desktop(backend="uia").windows():
        try:
            title = w.window_text().strip().lower()
            if "error" in title:
                return True
        except Exception:
            pass
    return False


def wait_for_opensignals_result(timeout: int = 8, poll_interval: float = 0.5) -> bool:
    """
    Wait a few seconds after pressing Record.
    Returns True if an error popup appears, otherwise False.
    """
    end_time = time.time() + timeout

    while time.time() < end_time:
        if opensignals_error_present():
            return True
        time.sleep(poll_interval)

    return False


def close_opensignals_error() -> bool:
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys
    import time

    closed_any = False

    for w in Desktop(backend="uia").windows():
        try:
            title = w.window_text().strip().lower()

            if "error" in title:
                print(f"[INFO] Closing OpenSignals error popup: {title}")
                w.set_focus()
                time.sleep(0.5)
                send_keys("{ENTER}")
                time.sleep(1)
                closed_any = True
        except Exception:
            pass

    return closed_any


def clear_existing_opensignals_errors():
    import time

    for _ in range(3):
        found = close_opensignals_error()
        time.sleep(0.8)
        if not found:
            break

def clear_existing_opensignals_errors():
    for _ in range(3):
        found = close_opensignals_error()
        time.sleep(0.8)
        if not found:
            break

def setup_opensignals():
    try:
        import time
        import pyautogui
        from pywinauto import Application

        pyautogui.PAUSE = 0.8

        app = Application(backend="uia").connect(title="OpenSignals (r)evolution")
        win = app.window(title="OpenSignals (r)evolution")

        print("[INFO] Connected to OpenSignals")
        win.set_focus()
        time.sleep(2)

        SETTINGS_BTN = (-664, 929)
        INTEGRATION_TAB = (-592, 361)
        LSL_CHECKBOX = (-968, 442)
        CONTINUOUS_CHECKBOX = (-983, 613)
        RECORD_BTN = (-937, 929)

        print("[WAIT] Letting OpenSignals settle...")
        time.sleep(4)

        print("[INFO] Clicking Change OpenSignals settings...")
        pyautogui.moveTo(*SETTINGS_BTN, duration=0.4)
        pyautogui.click()
        time.sleep(2.5)

        print("[INFO] Clicking Integration tab...")
        pyautogui.moveTo(*INTEGRATION_TAB, duration=0.4)
        pyautogui.click()
        time.sleep(2)

        print("[INFO] Clicking Lab Streaming Layer checkbox...")
        pyautogui.moveTo(*LSL_CHECKBOX, duration=0.4)
        pyautogui.click()
        time.sleep(1.2)

        print("[INFO] Clicking Continuous mode checkbox...")
        pyautogui.moveTo(*CONTINUOUS_CHECKBOX, duration=0.4)
        pyautogui.click()
        time.sleep(1.2)

        print("[INFO] Closing settings...")
        pyautogui.press("enter")
        time.sleep(3)

        print("[WAIT] Waiting before pressing Record...")
        time.sleep(8)

        print("[INFO] Clicking Record...")
        pyautogui.moveTo(*RECORD_BTN, duration=0.4)
        pyautogui.click()

        print("[WAIT] Waiting after pressing Record before continuing...")
        time.sleep(8)

        print("[OK] OpenSignals automated by coordinates")

    except Exception as e:
        print(f"[ERROR] OpenSignals automation failed: {e}")
        raise

def setup_labrecorder(participant_id: str):
    try:
        app = Application(backend="uia").connect(title="Lab Recorder")
        win = app.window(title="Lab Recorder")

        print("[INFO] Connected to Lab Recorder")
        win.set_focus()
        time.sleep(1)

        print("[INFO] Setting participant ID...")
        participant_edit = win.child_window(
            auto_id="MainWindow.centralwidget.scrollArea.qt_scrollarea_viewport.scrollAreaWidgetContents.lineEdit_participant",
            control_type="Edit",
        )
        participant_edit.set_edit_text(participant_id)

        time.sleep(1)

        print("[INFO] Clicking Update...")
        win.child_window(
            title="Update",
            auto_id="MainWindow.centralwidget.groupBox_streams.refreshButton",
            control_type="Button",
        ).click_input()

        time.sleep(3)

        print("[INFO] Clicking Select All...")
        win.child_window(
            title="Select All",
            auto_id="MainWindow.centralwidget.groupBox_streams.selectAllButton",
            control_type="Button",
        ).click_input()

        time.sleep(1)

        print("[INFO] Clicking Start...")
        win.child_window(
            title="Start",
            auto_id="MainWindow.centralwidget.groupBox_recording.startButton",
            control_type="Button",
        ).click_input()

        print("[OK] LabRecorder fully automated")

    except Exception as e:
        print(f"[ERROR] LabRecorder automation failed: {e}")
        raise


def setup_foh(participant_id: str):
    try:
        import pyautogui

        pyautogui.PAUSE = 0.6

        app = Application(backend="uia").connect(
            title="AxioBiofeedback (64-bit Development PCD3D_SM5) "
        )
        win = app.window(title="AxioBiofeedback (64-bit Development PCD3D_SM5) ")

        print("[INFO] Connected to FOH")
        win.set_focus()
        time.sleep(1)

        PARTICIPANT_FIELD = (727, 302)
        TRAINING_BTN = (864, 546)
        BACK_BTN = (875, 973)
        START_VR_BTN = (876, 666)

        print("[INFO] Clicking FOH participant field...")
        pyautogui.moveTo(*PARTICIPANT_FIELD, duration=0.3)
        pyautogui.click()
        time.sleep(0.5)

        print("[INFO] Clearing old participant ID...")
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.press("backspace")
        time.sleep(0.2)

        print(f"[INFO] Typing participant ID: {participant_id}")
        pyautogui.write(participant_id, interval=0.05)
        time.sleep(0.5)

        print("[INFO] Clicking Training...")
        pyautogui.moveTo(*TRAINING_BTN, duration=0.3)
        pyautogui.click()

        print("[INFO] Waiting on training screen...")
        time.sleep(5)

        print("[INFO] Clicking Back...")
        pyautogui.moveTo(*BACK_BTN, duration=0.3)
        pyautogui.click()
        time.sleep(1)

        print("[INFO] Clicking Start VR...")
        pyautogui.moveTo(*START_VR_BTN, duration=0.3)
        pyautogui.click()
        time.sleep(1)

        print("[OK] FOH fully automated")

    except Exception as e:
        print(f"[ERROR] FOH automation failed: {e}")
        raise