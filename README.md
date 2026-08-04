# mobi_mooi_toolbox

**Private project.** This repo holds a set of submodules and utilities that we develop for internal use. Later we can choose which parts to extract or publish in separate public repositories.

---

## Getting the code

### Clone the repository

"Cloning" just means downloading a full copy of this repo, with its git history, onto your machine. A sensible default location is your **home directory** — a predictable place you can always find by running `echo $HOME` (works the same in PowerShell and bash) — usually `C:\Users\<your-username>` on Windows, `/Users/<your-username>` on macOS, or `/home/<your-username>` on Linux.

From there:

```bash
cd ~
git clone <repo-url> mobi_mooi_toolbox
cd mobi_mooi_toolbox
```

(Get `<repo-url>` from this repo's GitHub page — the green "Code" button.)

**On Windows:** use **PowerShell**, not the older `cmd.exe` — the commands throughout this README and the docs site assume it. For Python itself, installing from the **Microsoft Store** (search "Python" in the Start menu) is the simplest route — no manual installer, no PATH setup for `python.exe` itself. One known gotcha with Store Python specifically: its Tk/Tcl install can be incomplete, which shows up as intermittent plotting-related test failures — see the docs site's Testing page for the workaround if you hit it.

**On macOS:** the usual route — Terminal.app, Python already present or installed via [python.org](https://www.python.org/) or Homebrew.

### Getting the latest changes later

Once cloned, pull in everyone else's latest committed changes any time with:

```bash
git pull
```

Run this from inside the `mobi_mooi_toolbox` folder. See the docs site's Testing page for more git basics, and For Contributors for branching/merging.

### Just want to run the compiled `.exe`, not the full source?

Two different routes end up with `vrlab_crane_process` available as a typed command, and they get onto your **`PATH`** (the list of folders your terminal searches when you type a command name) differently:

- **Clone + `pip install -e .`** (the [Setup](#setup) section below) — once your virtual environment is active, `vrlab_crane_process` just works. That's because activating a venv automatically adds its own `Scripts/`(Windows)/`bin/`(macOS/Linux) folder — where `pip install` put the command — onto your `PATH` for you. Nothing to configure by hand.
- **A standalone `vrlab_crane_process.exe`** (built with PyInstaller, no Python install needed — see the docs site's Building & Releasing page for how and why) — this one **isn't** on your `PATH` automatically. You either run it by typing its full path every time, or add its containing folder to `PATH` yourself:

  **Windows, using the GUI (no PowerShell needed):**

  1. Press the Windows key and search for **"Edit the system environment variables"**, then open it.
  2. Click the **Environment Variables...** button.
  3. Under **User variables**, select **Path**, then click **Edit...**.
  4. Click **New**, paste in the folder containing `vrlab_crane_process.exe` (e.g. `C:\path\to\folder`), then click **OK** on every open dialog.
  5. Open a **new** terminal window — the change only applies to terminals opened after this point.

  For a fuller walkthrough with screenshots: [ComputerHope: How to add a directory to the Windows PATH](https://www.computerhope.com/issues/ch000549.htm).

  **macOS/Linux, add to your shell profile:**

  ```bash
  echo 'export PATH="$PATH:/path/to/folder/containing/vrlab_crane_process"' >> ~/.bashrc
  source ~/.bashrc
  ```

  Once that folder is on `PATH`, you can type `vrlab_crane_process` from any terminal, in any folder, same as the pip-installed version.

---

## Setup

From the project root, install the package in editable mode so imports like `mooi_toolbox` work in scripts and notebooks:

```bash
pip install -e .
```

This exposes the command-line scripts defined in `pyproject.toml` — see [Just want to run the compiled `.exe`?](#just-want-to-run-the-compiled-exe-not-the-full-source) above for what that means for your `PATH`.

### Generate sample data

Real Crane participant recordings (`crane_data/`) aren't in this repo and
never will be — it's real physiology/behavioural data, and committing it
would keep it in the project's git history forever, on every clone.

Instead, generate a small synthetic dataset locally, once your virtual
environment is active:

```bash
crane_generate_sample_data examples/crane_templates examples --with-errors --seed 42
```

This clones the templates in `examples/crane_templates/` and perturbs
the numbers, writing the result into `examples/`. `--seed` makes it
reproducible (same seed, same output); `--with-errors` also generates one
participant per known pipeline error scenario (missing files, date
mismatches, bad triggers, ...). Run `crane_generate_sample_data --help`
for all options. See the docs site's Testing page for what `examples/` is
used for.

#### Reproducing a real participant's trigger anomaly, without exposing their data

Chasing a specific trigger-pattern bug from a real `crane_data/`
participant (missing initial trigger, missing last trigger, double initial
trigger)? You don't need to check that participant's file into the repo or
share it to debug it. `--reference-folder`/`--reference-subject-id`/
`--reference-error-type` read *only* that one file's trigger-pulse timing
and reproduce the same anomaly shape on a synthetic template — the
reference file's actual signal never leaves your machine:

```bash
crane_generate_sample_data examples/crane_templates examples \
  --reference-folder crane_data \
  --reference-subject-id PID16186 \
  --reference-error-type missing_initial_trigger
```

See the docs site's Testing page for the full list of supported
`--reference-error-type` values and how this differs from `--with-errors`.

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

The processing code is still being actively refactored. See `docs/pipeline_next_steps.md` for the current direction, especially the planned Pandera dataframe-contract work.

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

### Process VRLab Crane Biopac files

Run the Crane pipeline for Biopac `.mat` files and matching behaviour data.
Crane now uses one command for both batch-style processing and single-subject
processing, and searches a single input folder recursively for both the
`.mat` files and the behaviour/debrief CSV files:

```bash
vrlab_crane_process path/to/crane_data_folder path/to/output_folder
```

By default, the command searches recursively under the input folder for all
files matching `*_CraneOut.mat`, processes each subject it can, saves QC plots,
and writes combined participant-level output files.

To process one participant, pass the subject ID:

```bash
vrlab_crane_process path/to/crane_data_folder path/to/output_folder --subject_id P00018
```

With verbose output:

```bash
vrlab_crane_process path/to/crane_data_folder path/to/output_folder --verbose
```

The combined Crane output files are written as:

```text
vrlab_crane_process_batch_data_out.csv
vrlab_crane_process_batch_data_out.sav
```

When `--subject_id` is supplied, the output filenames are prefixed with that
subject ID. The FOH workflow is intended to move toward this same single-script
pattern, where one command can handle either one participant or all matching
files.

---

## Documentation

This README covers setup and command-line usage. For a fuller, browsable guide — why the toolbox exists, getting started, how the code is organized, the design patterns behind the pipeline, testing, and more — see the docs site in `docs/`, built with [MkDocs](https://www.mkdocs.org/):

```bash
pip install -r requirements-dev.txt
mkdocs serve
```

Then open `http://127.0.0.1:8000/` in a browser. It's local-only for now (see the docs site's Code Organization page for why); there's no public link yet.

---

## Package layout

The codebase is organized into submodules (e.g. `window_manager`, `processing`, …) that can be reused and, when ready, published as standalone or combined public packages. What stays private vs. public is decided later.

Important package areas:

- `src/mooi_toolbox/cli/` - command-line entry points.
- `src/mooi_toolbox/processing/` - physiology, behaviour, interval, and pipeline code.
- `src/mooi_toolbox/read_mobi_xdf/` - XDF stream loading helpers.
- `src/mooi_toolbox/window_manager/` - window layout and lab automation utilities.

---

## Build executable

This project includes small PyInstaller wrapper scripts for building the
`vrlab_crane_process` command as a single executable.

The useful part is portability: the built executable in `dist/` can be copied
to another folder, including a folder on your `PATH`, without copying the rest
of this project source code. See the docs site's Building & Releasing page
for *why* PyInstaller specifically, what the `.spec` file actually bundles,
how version tags work, and how this build runs automatically on a tag push.

Install PyInstaller in your active virtual environment first:

```bash
python -m pip install pyinstaller
```

On Windows, run `.\build.ps1` (in PowerShell).

On macOS or Linux:

```bash
bash build_mac.sh
```

Both scripts run:

```bash
pyinstaller --onefile src/mooi_toolbox/cli/vrlab_crane_process.py
```

PyInstaller writes temporary build files to `build/` and the executable to
`dist/`. If PyInstaller reports that the obsolete `pathlib` backport is
installed in the virtual environment, uninstall that package:

```bash
python -m pip uninstall pathlib
```

Modern Python already includes `pathlib` in the standard library, so removing
the old backport should not break normal imports such as
`from pathlib import Path`.

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
