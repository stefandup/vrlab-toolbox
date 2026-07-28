# Code Organization

Coming from [Getting Started](getting-started.md)? This page explains how
the code you just ran is actually laid out, so you can find your way around
it.

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

!!! note "Going further"
    Our style follows [PEP 8](https://realpython.com/python-pep8/), Python's
    official style guide — Real Python's PEP 8 guide is a good, readable
    walkthrough of the reasoning behind it.

---

**Next: [Golden Rules](golden-rules.md)** — a handful of coding rules of
thumb this codebase actually follows, with real examples.
