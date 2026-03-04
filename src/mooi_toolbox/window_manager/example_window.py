import tkinter as tk

# Predefined randomish sizes, all close to 800x600
window_sizes = [
    (790, 590),
    (810, 605),
    (800, 615)
]

windows = []
for i in range(3):
    root = tk.Tk()
    root.title(f"Example Python Window {i+1}")
    w, h = window_sizes[i]
    root.geometry(f"{w}x{h}")
    windows.append(root)

# Start the event loop for all windows
for win in windows:
    win.update()

windows[0].mainloop()