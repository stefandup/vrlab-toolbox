# vrlab_toolbox

This repo holds a set of submodules and utilities developed for VRLab workflows, released publicly under a noncommercial license — see [License](#license) below.

---

## Getting the code

### Clone the repository

"Cloning" just means downloading a full copy of this repo, with its git history, onto your machine. A sensible default location is your **home directory** — a predictable place you can always find by running `echo $HOME` (works the same in PowerShell and bash) — usually `C:\Users\<your-username>` on Windows, `/Users/<your-username>` on macOS, or `/home/<your-username>` on Linux.

From there:

```bash
cd ~
git clone <repo-url> vrlab_toolbox
cd vrlab_toolbox
```

(Get `<repo-url>` from this repo's GitHub page — the green "Code" button.)

**On Windows:** use **PowerShell**, not the older `cmd.exe` — the commands throughout this README and the docs site assume it. For Python itself, installing from the **Microsoft Store** (search "Python" in the Start menu) is the simplest route — no manual installer, no PATH setup for `python.exe` itself. One known gotcha with Store Python specifically: its Tk/Tcl install can be incomplete, which shows up as intermittent plotting-related test failures — see the docs site's Testing page for the workaround if you hit it.

**On macOS:** the usual route — Terminal.app, Python already present or installed via [python.org](https://www.python.org/) or Homebrew.

### Getting the latest changes later

Once cloned, pull in everyone else's latest committed changes any time with:

```bash
git pull
```

Run this from inside the `vrlab_toolbox` folder. See the docs site's Testing page for more git basics, and For Contributors for branching/merging.

### Just want to run the compiled `.exe`, not the full source?

Three routes end up with the toolbox's commands available as typed commands, and they get onto your **`PATH`** (the list of folders your terminal searches when you type a command name) differently:

- **Clone + `pip install -e .`** (the [Setup](#setup) section below) — once your virtual environment is active, every command (`vrlab_crane_process`, `vrlab_foh_assess_data`, etc.) just works. That's because activating a venv automatically adds its own `Scripts/`(Windows)/`bin/`(macOS/Linux) folder — where `pip install` put the commands — onto your `PATH` for you. Nothing to configure by hand.
- **The VRLab Toolbox installer** (`VRLabToolboxSetup.exe`, attached to this repo's GitHub Releases — built with PyInstaller + Inno Setup, no Python install needed — see the docs site's Building & Releasing page for how) — installs every tool into one folder, adds that folder to your `PATH` automatically (current user only, no admin rights needed), and puts a desktop shortcut on your desktop for a launcher with a button per GUI tool. CLIs still run from a terminal, exactly like the commands used throughout this README, once you've opened a **new** terminal window after installing.
- **A single standalone `.exe`** downloaded on its own (also attached to each Release, for when you only need one tool) — this one **isn't** on your `PATH` automatically like the installer above. You either run it by typing its full path every time, or add its containing folder to `PATH` yourself:

  **Windows, using the GUI (no PowerShell needed):**

  1. Press the Windows key and search for **"Edit the system environment variables"**, then open it.
  2. Click the **Environment Variables...** button.
  3. Under **User variables**, select **Path**, then click **Edit...**.
  4. Click **New**, paste in the folder containing the `.exe` (e.g. `C:\path\to\folder`), then click **OK** on every open dialog.
  5. Open a **new** terminal window — the change only applies to terminals opened after this point.

  For a fuller walkthrough with screenshots: [ComputerHope: How to add a directory to the Windows PATH](https://www.computerhope.com/issues/ch000549.htm).

  **macOS/Linux, add to your shell profile:**

  ```bash
  echo 'export PATH="$PATH:/path/to/folder/containing/vrlab_crane_process"' >> ~/.bashrc
  source ~/.bashrc
  ```

  Once that folder is on `PATH`, you can type the command name from any terminal, in any folder, same as the pip-installed version.

---

## Setup

From the project root, install the package in editable mode so imports like `vrlab_toolbox` work in scripts and notebooks:

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

`examples/` is a plain **raw** folder (the same shape `crane_convert_to_bids`
expects as input) -- add `--bids-folder examples/crane_bids_dummy` to also
convert it into the BIDS folder the test suite reads from, in the same
command, instead of running `crane_convert_to_bids` separately afterward:

```bash
crane_generate_sample_data examples/crane_templates examples --with-errors --seed 42 --bids-folder examples/crane_bids_dummy
```

`examples/` still ends up holding the plain raw files either way -- the BIDS
folder is purely additional. This is a development/testing tool only, not
part of the crosscheck GUI. Note that Crane's own pipeline doesn't read this
BIDS layout yet (see the docs site's Testing page) -- generating it is what
gives the in-progress BIDS refactor real data to run tests against.

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

#### FOH sample data

FOH's raw recording is a single `.xdf` (Lab Streaming Layer) file rather than
a `.mat`/`.csv` pair, so its generator builds recordings from scratch instead
of cloning a template:

```bash
foh_generate_sample_data foh_examples --with-errors --seed 42
```

Writes straight into the already-BIDS-shaped layout FOH's recording software
produces (`sub-XXX/ses-S001/beh/...`) -- no separate BIDS conversion step, so
`foh_examples` can be pointed at directly by `vrlab_foh_process` or the
FOH crosscheck GUI. `--with-errors` adds one participant per known scenario
(missing streams, a sampling-rate mismatch, incomplete target trials, ...).
See the docs site's Testing page for what each one is for.

---

## Current functionality

The toolbox currently supports internal VRLab workflows around VR physiology and behavioural data processing.

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
vrlab_check_xdf path/to/sub-P00018_ses-S001_task-Default_run-001_eeg.xdf
```

With stream details:

```bash
vrlab_check_xdf path/to/file.xdf --verbose
```

If no file is supplied, the command uses the default XDF path configured in `pyproject.toml`.

### Batch-process FOH XDF recordings

Process all `.xdf` files found recursively under an input folder.

```bash
vrlab_foh_process local_lsl_data local_lsl_data/_out
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

This README covers setup and command-line usage. For a fuller, browsable guide — why the toolbox exists, getting started, how the code is organized, the design patterns behind the pipeline, testing, and more — see the docs site, built with [MkDocs](https://www.mkdocs.org/):

**📖 [stefandup.github.io/vrlab-toolbox](https://stefandup.github.io/vrlab-toolbox/)**

It redeploys automatically on every push to `master` that touches `docs/` or `mkdocs.yml`. To preview changes locally before pushing:

```bash
pip install -r requirements-dev.txt
mkdocs serve
```

Then open `http://127.0.0.1:8000/` in a browser.

---

## Package layout

The codebase is organized into submodules (e.g. `window_manager`, `processing`, …) that can be reused and, when ready, published as standalone or combined public packages. What stays private vs. public is decided later.

Important package areas:

- `src/vrlab_toolbox/cli/` - command-line entry points.
- `src/vrlab_toolbox/processing/` - physiology, behaviour, interval, and pipeline code.
- `src/vrlab_toolbox/read_mobi_xdf/` - XDF stream loading helpers.
- `src/vrlab_toolbox/window_manager/` - window layout and lab automation utilities.

---

## Build executable

This project includes PyInstaller spec files (in `specs/`) for building every
toolbox command — CLI and GUI — as a standalone executable, plus a launcher
GUI and an Inno Setup script that bundles all of them into one
`VRLabToolboxSetup.exe` installer.

The useful part is portability: the built executables in
`build_output/dist/vrlab_toolbox/` can be copied to another folder, including
a folder on your `PATH`, without copying the rest of this project's source
code. See the docs site's Building & Releasing page for *why* PyInstaller
specifically, what the spec file bundles, how the installer works, how
version tags flow through it, and how this build runs automatically on a tag
push.

Install PyInstaller in your active virtual environment first:

```bash
python -m pip install pyinstaller
```

On Windows, run `.\build.ps1 -Full` (in PowerShell). It builds
`specs/toolbox.spec`, gathers the resulting exes into a
`build_output/toolbox/` folder, and — if [Inno Setup 6](https://jrsoftware.org/isinfo.php)
is installed — compiles `toolbox_installer.iss` into
`build_output\installer\VRLabToolboxSetup.exe`. Running `.\build.ps1` with no
flag just prints usage and builds nothing. `.\build.ps1 -Exe` builds just the
exes (no Inno Setup needed at all); once that's succeeded, `.\build.ps1
-Inno` recompiles just the installer (e.g. after editing
`toolbox_installer.iss`) without rerunning the slow PyInstaller step. Every
artifact from any of these lands under the single gitignored
`build_output/` folder, not scattered across the workspace root.

On macOS or Linux:

```bash
bash build_mac.sh
```

This only builds two of the toolbox's tools (`vrlab_crane_process`,
`vrlab_foh_assess_data`) as plain `--onefile` builds — there's no macOS/Linux
equivalent of the full toolbox build or the installer yet, since Inno Setup
is Windows-only.

PyInstaller writes temporary build files to `build_output/work/` and the
executables to `build_output/dist/`. If PyInstaller reports that the
obsolete `pathlib` backport is installed in the virtual environment,
uninstall that package:

```bash
python -m pip uninstall pathlib
```

Modern Python already includes `pathlib` in the standard library, so removing
the old backport should not break normal imports such as
`from pathlib import Path`.

---

## Window manager: `auto_arrange_windows.py`

Lives under `src/vrlab_toolbox/window_manager/`. It is meant as an **automated and easily adjustable** way to manage window positions **across multiple monitors**: define which windows to control via a JSON file, save a layout, then reapply it anytime.

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
python -m vrlab_toolbox.window_manager.auto_arrange_windows save

# Save to a custom config file
python -m vrlab_toolbox.window_manager.auto_arrange_windows save --config my_layout.json
```

Run from the project root (or from `src/vrlab_toolbox/window_manager/` if your default path is there). Ensure the JSON file already has the correct **`titles`** for the windows you want to capture, or create the file with a `titles` array and run save once so the file is created.

### Apply

- Reads the layout JSON (must exist).
- Optionally minimizes some “default” windows (e.g. PowerShell) so they don’t cover the layout.
- Finds windows by the **`titles`** in the JSON.
- Brings those windows to the front, then applies the **`windows`** positions/sizes from the file (by index: first title → first window entry, etc.).

**Examples:**

```bash
# Apply layout from default window_layout.json
python -m vrlab_toolbox.window_manager.auto_arrange_windows apply

# Apply from a custom config file
python -m vrlab_toolbox.window_manager.auto_arrange_windows apply --config my_layout.json
```

### Workflow summary

1. Create or open **`window_layout.json`** (or your `--config` file).
2. **Edit the `titles` array** with the exact window titles you want to control (as they appear in the taskbar/title bar, or partial matches).
3. Arrange those windows on screen as you want them, then run **save** to record the layout into the JSON.
4. Whenever you want that layout back, run **apply** (with the same config path if you didn’t use the default).

---

## License

VRLab Toolbox is available for noncommercial use under the
[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0).

Copyright Stellenbosch University.

See [`LICENSE.md`](LICENSE.md) for details.

## Citation

If you use VRLab Toolbox in published research, please cite the software:

> du Plessis, S. *VRLab Toolbox*. Stellenbosch University.
> https://github.com/stefandup/vrlab_toolbox

Citation metadata is also provided in [`CITATION.cff`](CITATION.cff).

---

