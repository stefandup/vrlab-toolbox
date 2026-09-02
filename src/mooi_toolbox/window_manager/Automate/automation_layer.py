from __future__ import annotations

import time
import pyperclip

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
        time.sleep(12)

        print("[INFO] Clicking Record...")
        pyautogui.moveTo(*RECORD_BTN, duration=0.4)
        pyautogui.click()

        print("[WAIT] Waiting after pressing Record before continuing...")
        time.sleep(12)

        print("[OK] OpenSignals automated by coordinates")
        return True

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

        # ---------------------------------------------------------
        # Participant ID
        # ---------------------------------------------------------
        print("[INFO] Setting participant ID...")
        participant_edit = win.child_window(
            auto_id=(
                "MainWindow.centralwidget.scrollArea.qt_scrollarea_viewport."
                "scrollAreaWidgetContents.lineEdit_participant"
            ),
            control_type="Edit",
        )
        participant_edit.set_edit_text(participant_id)

        time.sleep(1)

        # ---------------------------------------------------------
        # ORIGINAL WORKING FLOW
        # ---------------------------------------------------------
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

        # ---------------------------------------------------------
        # EXTRA FIELDS
        # These must NEVER stop Lab Recorder from starting.
        # ---------------------------------------------------------

        try:
            print("[INFO] Setting session to S001...")
            session_edit = win.child_window(
                auto_id=(
                    "MainWindow.centralwidget.scrollArea.qt_scrollarea_viewport."
                    "scrollAreaWidgetContents.lineEdit_session"
                ),
                control_type="Edit",
            )
            session_edit.set_edit_text("S001")
        except Exception as e:
            print(f"[WARN] Could not set session: {e}")

        try:
            print("[INFO] Setting task to foh...")
            task_combo = win.child_window(
                auto_id=(
                    "MainWindow.centralwidget.scrollArea.qt_scrollarea_viewport."
                    "scrollAreaWidgetContents.input_blocktask"
                ),
                control_type="ComboBox",
            )

            task_edit = task_combo.child_window(control_type="Edit")
            task_edit.set_edit_text("foh")
        except Exception as e:
            print(f"[WARN] Could not set task: {e}")

        try:
            print("[INFO] Setting modality to beh...")
            modality_combo = win.child_window(
                auto_id=(
                    "MainWindow.centralwidget.scrollArea.qt_scrollarea_viewport."
                    "scrollAreaWidgetContents.input_modality"
                ),
                control_type="ComboBox",
            )

            modality_edit = modality_combo.child_window(control_type="Edit")
            modality_edit.set_edit_text("beh")
        except Exception as e:
            print(f"[WARN] Could not set modality: {e}")

        try:
            print("[INFO] Setting FOH filename template...")
            template_edit = win.child_window(
                auto_id=(
                    "MainWindow.centralwidget.scrollArea.qt_scrollarea_viewport."
                    "scrollAreaWidgetContents.lineEdit_template"
                ),
                control_type="Edit",
            )

            template_edit.set_edit_text(
                r"sub-%p\ses-%s\%m\sub-%p_ses-%s_task-%b_run-%r_foh.xdf"
            )
        except Exception as e:
            print(f"[WARN] Could not set filename template: {e}")

        time.sleep(1)

        # ---------------------------------------------------------
        # ALWAYS PRESS START
        # ---------------------------------------------------------
        print("[INFO] Clicking Start...")
        win.child_window(
            title="Start",
            auto_id="MainWindow.centralwidget.groupBox_recording.startButton",
            control_type="Button",
        ).click_input()

        print("[OK] LabRecorder fully automated")
        return True

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

        print("[INFO] Clicking FOH participant field...")
        pyautogui.moveTo(*PARTICIPANT_FIELD, duration=0.3)
        pyautogui.click()
        time.sleep(0.5)

        print("[INFO] Clearing old participant ID...")
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.press("backspace")
        time.sleep(0.2)

        print(f"[INFO] Pasting participant ID exactly: {participant_id}")
        pyperclip.copy(participant_id)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.5)

        print("[INFO] Clicking Training as final automated step...")
        pyautogui.moveTo(*TRAINING_BTN, duration=0.3)
        pyautogui.click()

        print(
            "[OK] FOH stopped on Training screen. "
            "User can now click Back and Start VR manually."
        )

    except Exception as e:
        print(f"[ERROR] FOH automation failed: {e}")
        raise