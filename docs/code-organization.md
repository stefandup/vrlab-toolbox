# Code Organization

Coming from [Development Setup](dev-setup.md)? This page explains how
the code you just installed is actually laid out, so you can find your way
around it.

## What this toolbox does

The Mobi Mooi Toolbox turns raw recordings — physiology signals, VR event
logs, and questionnaire answers — into one clean, per-participant data file
that's ready for analysis. It does this with a **pipeline**: a fixed
sequence of steps (find files → import → process → combine → save) that
every participant's data passes through, in the same order, every time.

## The workspace, at a glance

"The workspace" just means the top-level project folder — the one you open
in your editor, containing everything below:

| File / folder | What it's for |
| --- | --- |
| `pyproject.toml` | The project's main settings file: build info, the CLI commands (`[project.scripts]`), and config for tools like `ruff` and `pytest`. |
| `requirements.txt` | The exact package versions needed to **run** the toolbox. This is what you install first. |
| `requirements-dev.txt` | Extra tools only needed for **developing** the toolbox (not for just running it) — currently `pyright`, `ruff`, `mkdocs`, `mkdocs-material`. |
| `src/mooi_toolbox/` | All the toolbox's Python code. |
| `tests/` | The automated test suite (see [Testing](testing.md)). |
| `docs/` | This documentation site. |

!!! note "Going further"
    "Dev requirements" is a common convention: packages a *user* of the
    toolbox never needs (a linter, a type checker, a docs builder), but a
    *contributor* does. Splitting them out keeps the toolbox itself
    lightweight to install.

### How `pyproject.toml` works

`pyproject.toml` is the standard, modern place Python projects put their
build/packaging config — one file instead of the older scattered
`setup.py`/`setup.cfg`/`MANIFEST.in`. The sections that matter here:

- **`[project]`** — package metadata: name, and `dynamic = ["version"]`
  (the version isn't written by hand — see next point).
- **`[tool.setuptools_scm]`** — its presence tells `setuptools` to derive
  the package's version automatically from **git tags**, rather than a
  hand-maintained version string anywhere in the code. Push a tag like
  `v1.2.0`, and that becomes the installed package's version. More on why
  that matters in [Building & Releasing](packaging.md).
- **`[tool.setuptools.dynamic]`** — points `dependencies` at
  `requirements.txt`, which is why `pip install -e .` alone is enough (see
  [Getting Started](getting-started.md)).
- **`[project.scripts]`** — declares each CLI command as
  `command_name = "python.module.path:function"`, e.g.
  `vrlab_crane_process = "mooi_toolbox.cli.vrlab_crane_process:main"`. This
  is what turns a plain Python function into a command you can type on its
  own.

!!! note "Going further"
    When you `pip install -e .`, every name under `[project.scripts]` gets
    written as an actual small executable/script file **inside your
    virtual environment** — `.venv\Scripts\` on Windows,
    `.venv/bin/` on macOS/Linux (see [Development Setup](dev-setup.md#1-set-up-a-virtual-environment)
    for what a venv is). That's genuinely why typing `vrlab_crane_process`
    works once your venv is active: your shell finds that file on its
    `PATH`. Worth browsing that folder once, next to `site-packages/` — it
    demystifies where CLI commands actually come from.

### Building and previewing this documentation site

This site (`docs/`) is built with `mkdocs`. From the workspace root:

```
# 1. Install the dev tools (mkdocs + mkdocs-material), if you haven't already
pip install -r requirements-dev.txt

# 2. Start a live-reload preview server
mkdocs serve
```

Step 2 prints a local address (usually `http://127.0.0.1:8000/`) — open it
in a browser. The page reloads automatically as you edit files in `docs/`.
`Ctrl+C` stops the server.

For a static build instead of a live server, use `mkdocs build` — this
produces a `site/` folder (already git-ignored; see [Testing](testing.md#quick-git-basics)).

!!! note "Going further"
    For now, this site is **local-only** — there's no public link to it yet.
    The plan is to eventually host it with **GitHub Pages**: a free feature
    of GitHub that takes a folder of built HTML (like `mkdocs build`'s
    `site/` output) and serves it at its own web address, usually
    `https://<user-or-org>.github.io/<repo-name>/`. We can't turn that on
    yet because GitHub Pages only builds automatically from a **private**
    repository on paid GitHub plans (Pro/Team/Enterprise) — on the free
    plan, the repo has to be public first. Once this repo is public (or the
    plan changes), the plan is to add a small GitHub Actions workflow that
    runs `mkdocs build` and publishes the result automatically, so the site
    stays in sync with `docs/` without a manual step.

## Inside `src/mooi_toolbox/`

| Folder | What lives there |
| --- | --- |
| `cli/` | Small command-line scripts users run directly. |
| `processing/` | The actual pipeline logic: loading data, building trial intervals, computing physiology metrics, and wiring it all together. |
| `read_mobi_xdf/` | Loading `.xdf` (LSL) recording files. |

!!! note "Going further"
    Two folders are mid-cleanup, worth knowing about if you see them
    referenced elsewhere: `qc/` is dead code (unused, scheduled for
    removal), and `read_mobi_xdf/` is planned to move into `processing/`,
    living next to `biopac.py` — the same place `.mat` loading lives —
    since both are just physiology-file loaders for different formats.

## Why `pipeline.py`, then `crane_pipeline.py`?

`processing/pipeline.py` holds the **generic, reusable machinery** —
`PipelineTemplate` and the `Sequential*Steps` containers — that don't know
anything about one specific experiment. `processing/crane_pipeline.py` is
where one experiment ("Crane") wires that generic machinery together with
its own concrete steps, via `run_pipeline()`. Other experiments (`foh_pipeline.py`,
`long_walk_pipeline.py`) follow the same pattern: reuse the shared
machinery, supply experiment-specific steps.

One call to `run_pipeline()` processes **exactly one participant**,
returning one row of output. Combining many participants into the final
combined CSV/SPSS file happens separately, at the CLI level — see
[Design Patterns](design-patterns.md#one-participant-at-a-time) for exactly
where that split happens in the code.

### Where the actual steps live

`crane_pipeline.py` itself is mostly *wiring* — it imports each step from
the module that actually implements it:

| Step | Implemented in |
| --- | --- |
| Find a participant's files | `crane_pipeline.py` (`FindCraneParticipantFilesStrategyStep`) |
| Import/process Crane behaviour data | `crane_behaviour.py` |
| Import/process debrief data | `crane_debrief_behaviour.py` |
| Import physiology data | `biopac.py` |
| Build trial intervals | `crane_trial_intervals.py` |
| Process EDA physiology | `eda.py` |

If you're trying to find where a specific piece of logic actually runs,
start from this table rather than `crane_pipeline.py` — that file mostly
just imports and assembles the pieces above.
(See [Pipeline Concepts](pipeline-concepts.md) for *why* it's built this way.)

`foh_pipeline.py` is wired the same way, for FOH's own steps:

| Step | Implemented in |
| --- | --- |
| Find a participant's files | `foh_pipeline.py` (`FindFohParticipantFilesStrategyStep`) |
| Import/process FOH trial + target behaviour data | `foh_behaviour.py`, `foh_target_behaviour.py` |
| Import physiology data | `lsl.py` (`FohLslPhysiologyDataImportStrategy`) |
| Build trial intervals | `foh_trial_intervals.py`, using event definitions from `foh_config.py` |
| Process EDA physiology | `eda.py` — the *same* `ProcessEdaPhysiologyDataStrategyStep` Crane uses, unmodified |

See [Lab Streaming (LSL/XDF)](lab-streaming.md) for what's different about
FOH's data (one `.xdf` file instead of separate `.mat`/CSV files) and why
that only changes the import/interval steps, not the processing steps.

### How `eda.py` processes a signal

[EDA & SCRs](eda.md) covers what EDA/SCRs are and how to read the QC plot,
in plain terms; this is the code behind it. The processing chain, from raw
signal to one row of output:

1. **Slice** — `run_eda_intervals` uses `trial_intervals.slice_data_frame`
   to cut the full EDA recording into one chunk per trial interval.
2. **Clean, decompose, find peaks** — for each interval,
   `run_nk_eda_processing` wraps three NeuroKit2 calls in order:
   `nk.eda_clean` (remove noise) → `nk.eda_phasic` (split into
   tonic/phasic components) → `nk.eda_peaks` (detect SCRs in the phasic
   component).
3. **Count** — `get_eda_data_out` counts detected SCR peaks for that
   interval and divides by the interval's length in minutes, producing one
   `..._SCR_per_min` value.
4. **Tidy column names** — `correct_order` cleans up the resulting column
   names so repeated interval labels (e.g. two `ITI` columns) don't
   collide.
5. **QC plot** — separately, `run_eda_qc` runs the *same* cleaning/decompose
   steps over the **whole, unsliced** recording (not per interval) purely to
   draw the QC figure — it doesn't feed into the numeric output.

`eda.py` calls NeuroKit2 with this project's chosen methods
(`clean_method="biosppy"`, `peak_detect_method="vanhalem2020"`) and
reshapes the result — see [EDA & SCRs](eda.md#the-neurokit2-toolbox) for
what NeuroKit2 itself is.

`ProcessEdaPhysiologyDataStrategyStep` (`eda.py`) is the concrete strategy
that satisfies `ProcessPhysiologyDataStrategyStep` from `pipeline.py` — see
[Design Patterns](design-patterns.md) for what that means. Like the
interval-matching step, it has its own `fallback_strategy`:

- **`ProcessEdaPhysiologyDataStrategyStep`** — the main path. Takes the
  already-matched `TrialIntervals` produced by the interval step and
  processes each labelled trial.
- **`ProcessEdaPhysiologyFallbackStrategyStep`** — used when no matched
  intervals are available. It derives its own raw, unlabelled trigger
  intervals directly from the physiology data
  (`trial_intervals.get_raw_biopac_trigger_intervals`) and processes those
  instead — the same "partial data beats no data" idea as the interval
  step's fallback (see item 5 in
  [Next Steps](pipeline_next_steps.md#5-add-a-fallback-for-partialmissing-behaviour-data-using-unlabelled-intervals)).

## The command-line tools

CLI scripts live in `src/mooi_toolbox/cli/` (e.g. `vrlab_crane_process.py`).
They're deliberately kept **thin**: read input, loop over files, call into
`processing/`, save the result. All the real decision-making lives in
`processing/`, not in the CLI. Two reasons:

1. **Testing** — code in `processing/` can be tested directly with `pytest`,
   without running a full command-line program.
2. **Reuse** — the same processing logic can be called from a CLI, a script,
   or a notebook, without rewriting it.

### How a CLI command receives input (`click`)

Each CLI file uses the [`click`](https://click.palletsprojects.com/) library
to turn a plain function into a command-line command. Take
`vrlab_crane_process.py`:

```python
@click.command()
@click.argument("input_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path))
@click.argument("output_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path))
@click.option("--subject_id", required=False, default="", help="Process a single participant")
@click.option("--verbose", is_flag=True, help="Give verbose output")
def main(input_folder: Path, output_folder: Path, verbose: bool, subject_id: str):
    ...
```

- `@click.argument(...)` — a **required, positional** value (order matters).
  `type=click.Path(...)` tells click to check the path exists and hand it
  back as a `pathlib.Path`, instead of a plain string you'd have to convert
  yourself.
- `@click.option(...)` — an **optional, named** value (`--subject_id ...`),
  with a default if it's left out. `is_flag=True` makes `--verbose`
  a simple on/off switch.
- Each decorator adds one parameter to `main(...)`, in the order they're
  declared as arguments (options can come in any order on the command line).

So running:

```
vrlab_crane_process C:\data\input C:\data\output --subject_id P00018
```

calls `main(input_folder=..., output_folder=..., subject_id="P00018", verbose=False)`.
The command name (`vrlab_crane_process`) itself comes from `[project.scripts]`
in `pyproject.toml`, which points at this `main` function.

## Code style

Two automatic tools help keep the code consistent — config for both lives in
`pyproject.toml`:

- **[ruff](https://docs.astral.sh/ruff/)** — checks for errors and style
  issues (e.g. unused imports) and can auto-format code. This project's
  ruff settings: 100-character line length, double-quote strings.
- **[pyright](https://microsoft.github.io/pyright/)** — checks type hints
  for mistakes before you run the code.

### Turning on Pylance type checking in VS Code

Running `pyright` from the terminal checks the whole project at once, but
you don't have to wait for that to see a problem — **Pylance**, the
extension VS Code already uses for Python (autocomplete, go-to-definition,
etc.), is built on the *same* `pyright` engine. It can underline type
errors live, in the editor, as you type, before you ever run the file or
the terminal check.

This project's own `.vscode/settings.json` doesn't set a
`python.analysis.typeCheckingMode` — it only configures the interpreter
path, the integrated terminal, and `ruff` as the on-save formatter:

```json
{
    "python.defaultInterpreterPath": "${workspaceFolder}\\.venv\\Scripts\\python.exe",
    "[python]": {
        "editor.defaultFormatter": "charliermarsh.ruff",
        "editor.formatOnSave": true
    }
}
```

So Pylance's live type checking currently runs at whichever level is the
extension's own built-in default on your machine — nothing in this repo
pins it. If you want it to check more (or less) as you type, that's a
setting you'd add to `.vscode/settings.json` yourself, e.g.:

```json
{
    "python.analysis.typeCheckingMode": "basic"
}
```

Pyright's three levels, from lightest to strictest: `"off"` (no live type
checking at all), `"basic"`, and `"strict"`. (Some pyright versions also
expose an in-between `"standard"` level — check what your installed
Pylance version offers via the setting's autocomplete in VS Code before
picking one.)

**Why this is worth turning on, not just noise to silence:** it catches
real mistakes *before* you run anything — passing the wrong concrete type
into a strategy step's `run()`, forgetting a required argument, or calling
a function marked `@deprecated` (see [Golden Rules](golden-rules.md#mark-old-code-deprecated--dont-just-delete-it-or-leave-it-silently)
for a real example of that last one). In a codebase built around typed
`Protocol` contracts like this one ([Design Patterns](design-patterns.md#strategy)),
that's exactly the class of bug type checking is designed to catch —
finding out at edit time, not after a participant's data has half-run
through the pipeline.

!!! note "Going further"
    Our style follows [PEP 8](https://realpython.com/python-pep8/), Python's
    official style guide — Real Python's PEP 8 guide is a good, readable
    walkthrough of the reasoning behind it.

See the [AI Style Guide](ai-style-guide.md) for this same stack — `click`,
`pandera`, `dataclasses`/`Protocol`, `pytest`, `rich` — written up as an
explicit reference for AI coding assistants, so a new tool or pattern
doesn't get introduced alongside what's already here.

---

**Next: [Golden Rules](golden-rules.md)** — a handful of coding rules of
thumb this codebase actually follows, with real examples.
