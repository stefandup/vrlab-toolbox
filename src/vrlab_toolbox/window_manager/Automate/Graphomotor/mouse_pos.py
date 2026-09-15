import pyautogui
import time

print("Move mouse to each button. Press Ctrl+C to stop.")

while True:
    print(pyautogui.position())
    time.sleep(1)