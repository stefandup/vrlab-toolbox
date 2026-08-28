# Getting Started

This page sets up a Python environment, gets the toolbox installed, and
walks through running one real pipeline — the Crane pipeline — end to end,
as a worked example. The other command-line tools (FOH and friends) follow
the same overall shape; see [Other pipelines](#other-pipelines) below.

If you just want to *run* the pipeline, not set any of that up, skip ahead
to [Just want to run the compiled binary?](#just-want-to-run-the-compiled-binary)
below.

## Just want to run the compiled binary?

If you're a data collector and just need to run `vrlab_crane_process` —
not read, change, or even clone the code — you don't need Python, a venv,
or any of the setup below. A `MooiToolboxSetup.exe` installer, plus every
tool's standalone `.exe` on its own, is built automatically and attached to
this repo's **GitHub Releases** page every time a version tag is pushed (the
[Building & Releasing](packaging.md) page covers how, if you're curious).

To get it:

1. On GitHub, open this repo's **Releases** page (the "Releases" link in
   the right-hand sidebar of the repo's main page, or `.../releases` at
   the end of the repo URL).
2. Pick the release you want — usually the latest one at the top.
3. Under **Assets**, download `MooiToolboxSetup.exe` and run it.

The installer puts every tool's `.exe` in one folder, adds that folder to
your `PATH` automatically (current user only — no admin rights needed), and
adds a desktop shortcut to a launcher with a button for each GUI tool. Once
it's done, open a **new** terminal window (the `PATH` change only applies to
terminals opened after installing) and run it exactly like the commands used
throughout the rest of this page:

```bash
vrlab_crane_process crane_data crane_data/output
```

### Just want the one file, no installer?

Each tool's standalone `.exe` (e.g. `vrlab_crane_process.exe`) is also
attached to the release on its own, if you don't want the rest of the
toolbox. That file *is* the tool — no Python install, no `pip install`,
nothing else to download — but unlike the installer above, it **isn't**
added to your `PATH` automatically. Run it by its full path:

```bash
C:\path\to\vrlab_crane_process.exe crane_data crane_data/output
```

...or add its containing folder to `PATH` yourself, the same way the
installer does it for you:

**Windows, using the GUI (no PowerShell needed):**

1. Press the Windows key and search for **"Edit the system environment
   variables"**, then open it.
2. Click the **Environment Variables...** button.
3. Under **User variables**, select **Path**, then click **Edit...**.
4. Click **New**, paste in the folder containing the `.exe`
   (e.g. `C:\path\to\folder`), then click **OK** on every open dialog.
5. Open a **new** terminal window — the change only applies to terminals
   opened after this point.

For a fuller walkthrough with screenshots: [ComputerHope: How to add a
directory to the Windows PATH](https://www.computerhope.com/issues/ch000549.htm).

**macOS/Linux**, add to your shell profile — see the project's
`README.md` (in the workspace root), section "Just want to run the
compiled `.exe`, not the full source?", for the exact command. Note the
installer itself is Windows-only (see the "Going further" note below).

### Checking it's the right file, and getting help

Two flags work without needing to run a full pipeline:

```bash
vrlab_crane_process --help       # lists every argument and option, with what each does
vrlab_crane_process --version    # confirms which version you downloaded
```

`--help` is the fastest way to check `input_folder`/`output_folder`
ordering or an option name (`--subject_id`, `--verbose`) without coming
back to this page. `--version` is worth checking against the release
you meant to download, especially if more than one version's `.exe` is
floating around a shared machine.

!!! note "Going further"
    Only a Windows build (`windows-latest` in the release workflow) is
    produced automatically right now — see
    [Building & Releasing](packaging.md#automatic-builds-on-tag-push) for
    the current gap on macOS/Linux. On those platforms, building it
    yourself (also covered on that page) is currently the only route to a
    standalone binary.

## 1. Set up a virtual environment

First, check which Python you actually have:

```bash
python --version
```

And where it lives — this matters if you have more than one Python
installed:

```bash
# Windows
where python

# macOS / Linux
which python
```

A **virtual environment ("venv")** is a private, isolated copy of Python
for just this project — its own installed packages, separate from anything
else on your machine or any other project. Create one in the workspace
root:

```bash
python -m venv .venv
```

Then activate it:

```bash
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

You'll know it worked because your terminal prompt gets a `(.venv)` prefix.
From here on, "install" always means "install into this active venv."

!!! note "Going further"
    A venv isn't magic — it's just a folder. `.venv/` (already git-ignored;
    see [Testing](testing.md#quick-git-basics)) contains an actual copy of
    the Python interpreter, plus a `Lib/site-packages/` (Windows) or
    `lib/pythonX.Y/site-packages/` (macOS/Linux) folder holding every
    package you `pip install` while it's active. Go browse it once it
    exists — seeing real, installed package source code sitting in a
    folder on your own disk demystifies a lot of "where does this code
    actually come from?" questions.

### VS Code: auto-activate this venv in every new terminal

Add this to `.vscode/settings.json` in the workspace root (create the file
— and the `.vscode/` folder — if they don't exist yet):

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/Scripts/python.exe"
}
```

(macOS/Linux: `"${workspaceFolder}/.venv/bin/python"` instead.) You can set
this by hand, or run VS Code's **Python: Select Interpreter** command and
pick `.venv` — either way updates the same setting. Once it's set, every
new integrated terminal you open activates this venv automatically, so you
don't have to remember to run the activate command yourself each time.

## 2. Install

From the workspace root, with your virtual environment active:

```bash
pip install -e .
```

This installs the toolbox itself in **editable mode** — code changes are
picked up immediately, no reinstalling needed — and pulls in everything
listed in `requirements.txt` along with it (`pyproject.toml` points at that
file as the dependency list). It's also what makes the command-line tools
below, and `import mooi_toolbox` in scripts, available in your environment.

## 3. Run the Crane pipeline

The Crane command is `vrlab_crane_process`:

```bash
vrlab_crane_process <input_folder> <output_folder>
```

- `input_folder` — searched **recursively** for each participant's Biopac
  `.mat` file (matching `*_CraneOut.mat`) *and* their behaviour/debrief CSV
  files. Both file types can live anywhere under this one folder.
- `output_folder` — where the combined participant-level output files are
  written.

Under the hood, the actual pipeline (`run_pipeline()`) only ever processes
**one participant at a time**, returning one row of output — see
[Design Patterns](design-patterns.md#one-participant-at-a-time). This CLI
command is what loops over every matching participant and combines their
rows together into the one file described below. By default it processes
**every** participant found under `input_folder`. To process just one, add
`--subject_id`:

```bash
vrlab_crane_process crane_data crane_data/output --subject_id P00018
```

Add `--verbose` for more detailed log output while it runs:

```bash
vrlab_crane_process crane_data crane_data/output --verbose
```

### What you get out

Two combined files land in `output_folder`:

```text
vrlab_crane_process_batch_data_out.csv
vrlab_crane_process_batch_data_out.sav
```

(`.sav` is an SPSS file.) When `--subject_id` is used, both filenames are
prefixed with that subject's ID instead.

!!! note "Going further"
    See [Code Organization](code-organization.md#how-a-cli-command-receives-input-click)
    for how `input_folder`/`output_folder`/`--subject_id` map onto Python
    function parameters via `click`, and
    [Code Organization](code-organization.md#where-the-actual-steps-live)
    for where the actual per-step processing code lives.

## Other pipelines

The other command-line tools (`mobi_foh_process`, `mobi_foh_batch_process`,
`mobi_check_xdf`, …) take the same rough shape — an input path, an output
folder, and a handful of options — just for a different experiment. See the
project's `README.md` (in the workspace root) for the full, current list of
commands and examples.

!!! note "Going further"
    Under the hood, FOH is migrating onto the same `run_pipeline()`/
    `PipelineTemplate` shape this page just walked through for Crane — same
    `find → import → process → combine → save` sequence, just reading one
    `.xdf` (LSL) file per participant instead of a Biopac `.mat` file plus
    behaviour CSVs. The two FOH CLIs are at different points in that
    migration: `mobi_foh_batch_process` now calls the new `run_pipeline()`;
    `mobi_foh_process` (the single-file CLI) still calls the older,
    `@deprecated` `run_lsl_pipeline`. See
    [Lab Streaming (LSL/XDF)](lab-streaming.md) for that pipeline's
    anticipated end state, and
    [Next Steps item 21](pipeline_next_steps.md#21-foh-pipeline-exception-handling-parity-with-crane-trial-interval-config-migration)
    for what's already true of the code today versus what's still being
    finished.

---

**Next: [Code Organization](code-organization.md)** — now that you've run
the pipeline, see how the code that just ran is actually laid out.
