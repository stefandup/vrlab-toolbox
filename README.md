# mobi_mooi_toolbox

**Private project.** This repo holds a set of submodules and utilities that we develop for internal use. Later we can choose which parts to extract or publish in separate public repositories.

---

## Current functionality

The toolbox currently supports internal MOBI/MOOI workflows around VR physiology and behavioural data processing.

Main areas:

- **FOH LSL/XDF processing**: process FOH VR task recordings from `.xdf` files, including OpenSignals physiology, VR marker streams, VR trial events, and FOH target behaviour where available.
- **VRLab Crane / Biopac processing**: process Crane paradigm physiology from Biopac `.mat` files, derive trigger-based intervals, and run interval-based EDA processing.
- **EDA processing and QC plots**: run NeuroKit2-based EDA cleaning, decomposition, SCR-per-minute summaries, and QC plotting across VR intervals.
- **VR interval extraction**: create analysis intervals from configured VR marker/trial-event definitions, including fallback behaviour for known missing-marker cases.
- **Batch processing**: process folders of FOH `.xdf` files or Crane `.mat` files and write participant-level CSV outputs.
- **Target/SCR plotting**: create per-subject plots from FOH batch output showing target latency values alongside SCR-per-minute summaries.
- **Window management utilities**: save and reapply multi-monitor window layouts for lab workflow setup.

The processing code is still being actively refactored. See `project_next_steps.md` for the current direction, especially the planned Pandera dataframe-contract work.

---

## Setup

From the project root, install the package in editable mode so imports like `mooi_toolbox` work in scripts and notebooks:

```bash
pip install -e .
```

This exposes the command-line scripts defined in `pyproject.toml`.

---

## Command-line examples

### Inspect an XDF file

Use this first when checking whether an `.xdf` file contains the expected LSL streams.

```bash
mobi_check_xdf path/to/sub-P00018_ses-S001_task-Default_run-001_eeg.xdf
```

With stream details:

```bash
mobi_check_xdf path/to/file.xdf --verbose
```

If no file is supplied, the command uses the default XDF path configured in `pyproject.toml`.

### Process one FOH XDF recording

Run the FOH pipeline for a single `.xdf` file and save the QC plot to the output folder.

```bash
mobi_foh_process path/to/file.xdf path/to/output_folder
```

With verbose output:

```bash
mobi_foh_process path/to/file.xdf path/to/output_folder --verbose
```

If the output folder is omitted, the script derives an `_out` folder from the XDF path.

### Batch-process FOH XDF recordings

Process all `.xdf` files found recursively under an input folder.

```bash
mobi_foh_batch_process local_lsl_data local_lsl_data/_out
```

If the output folder is omitted, the script writes to `<input_folder>_out`.

The batch output CSV is written as:

```text
FOH_process_batch_out.csv
```

### Plot FOH target and SCR summaries

Create per-subject PNG plots from the FOH batch CSV.

```bash
plot_target_data --input-csv local_lsl_data/_out/FOH_process_batch_out.csv --output-dir local_lsl_data/_out/plots
```

If no arguments are supplied, the script uses its default paths under `local_lsl_data/_out`.

### Process one VRLab Crane Biopac file

Run the Crane pipeline for one Biopac `.mat` file.

```bash
vrlab_crane_process path/to/subject_file.mat path/to/output_folder
```

With verbose output:

```bash
vrlab_crane_process path/to/subject_file.mat path/to/output_folder --verbose
```

### Batch-process VRLab Crane Biopac files

Process all `.mat` files found recursively under an input folder.

```bash
vrlab_crane_batch crane_data crane_data_out
```

If the output folder is omitted, the script writes to `<input_folder>_out`.

The batch output CSV is written as:

```text
vrlab_crane_process_batch_out.csv
```

---

## Package layout

The codebase is organized into submodules (e.g. `window_manager`, `processing`, …) that can be reused and, when ready, published as standalone or combined public packages. What stays private vs. public is decided later.

Important package areas:

- `src/mooi_toolbox/cli/` - command-line entry points.
- `src/mooi_toolbox/processing/` - physiology, behaviour, interval, and pipeline code.
- `src/mooi_toolbox/read_mobi_xdf/` - XDF stream loading helpers.
- `src/mooi_toolbox/window_manager/` - window layout and lab automation utilities.

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

---

## TODO

- Handle VR restarts more robustly so LSL reconnects and picks the stream up again after the VR app is restarted.
- Consider adding a dedicated restart button for the VR/LSL workflow instead of relying on manual restart steps.
- Consider moving launcher scripts to Python and using `subprocess` so process startup, restart, and reconnection logic are easier to manage in one place.
