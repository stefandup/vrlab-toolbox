# mobi_mooi_toolbox

**Private project.** This repo holds a set of submodules and utilities that we develop for internal use. Later we can choose which parts to extract or publish in separate public repositories.

---

## Submodules

The codebase is organized into submodules (e.g. `window_manager`, `processing`, …) that can be reused and, when ready, published as standalone or combined public packages. What stays private vs. public is decided later.

---

## Window manager: `auto_arrange_windows.py`

Lives under `src/mooi_toolbox/window_manager/`. It is meant as an **automated and easily adjustable** way to manage window positions **across multiple monitors**: define which windows to control via a JSON file, save a layout, then reapply it anytime.

It has two modes:

- **save** — Capture current positions and sizes of selected windows into a JSON file.
- **apply** — Read that JSON and move/resize the matching windows to the saved layout.

It uses helpers from **`python_window_management.py`**, which is intended as a **general, transportable window management library** for use in this project or others.

### JSON layout file

Layouts are stored in a JSON file. The default path is **`window_layout.json`** in the directory you run the script from (or use `--config` to point to another file).

**Structure:**

- **`titles`** — List of window title strings. Only these windows are controlled. **You must edit this list manually** with the exact (or partial) window titles you want (e.g. `"Notepad"`, `"Example Python Window 1"`, `"python.exe"`).
- **`windows`** — Array of `{ "hwnd", "left", "top", "width", "height" }`. Filled/updated by **save**; used by **apply** to set position and size. Order matches the order of `titles`.
- **`version`** — Layout format version (e.g. `1`).

**Example `window_layout.json` (after editing `titles` and running save):**

```json
{
  "version": 1,
  "titles": [
    "Example Python Window 1",
    "Example Python Window 2",
    "Notepad",
    "Ubuntu"
  ],
  "windows": [
    { "hwnd": 12345, "left": -7, "top": 0, "width": 974, "height": 523 },
    { "hwnd": 67890, "left": 953, "top": 0, "width": 974, "height": 1039 }
  ]
}
```

You **edit `titles` manually** with the window names you want to control. The script finds windows by matching these strings (partial match). If a title matches multiple windows, the first match is used; missing windows are skipped with a warning.

### Save

- Reads **`titles`** from the layout JSON (or uses built‑in defaults if the file is missing or has no `titles`).
- Finds all windows whose titles match the list.
- Writes their current position and size into the **`windows`** array of the same JSON file.
- If the file had no `titles` yet, it adds the list it used so you can then edit it.

**Examples:**

```bash
# Save current layout to default window_layout.json
python -m mooi_toolbox.window_manager.auto_arrange_windows save

# Save to a custom config file
python -m mooi_toolbox.window_manager.auto_arrange_windows save --config my_layout.json
```

Run from the project root (or from `src/mooi_toolbox/window_manager/` if your default path is there). Ensure the JSON file already has the correct **`titles`** for the windows you want to capture, or create the file with a `titles` array and run save once so the file is created.

### Apply

- Reads the layout JSON (must exist).
- Optionally minimizes some “default” windows (e.g. PowerShell) so they don’t cover the layout.
- Finds windows by the **`titles`** in the JSON.
- Brings those windows to the front, then applies the **`windows`** positions/sizes from the file (by index: first title → first window entry, etc.).

**Examples:**

```bash
# Apply layout from default window_layout.json
python -m mooi_toolbox.window_manager.auto_arrange_windows apply

# Apply from a custom config file
python -m mooi_toolbox.window_manager.auto_arrange_windows apply --config my_layout.json
```

### Workflow summary

1. Create or open **`window_layout.json`** (or your `--config` file).
2. **Edit the `titles` array** with the exact window titles you want to control (as they appear in the taskbar/title bar, or partial matches).
3. Arrange those windows on screen as you want them, then run **save** to record the layout into the JSON.
4. Whenever you want that layout back, run **apply** (with the same config path if you didn’t use the default).
