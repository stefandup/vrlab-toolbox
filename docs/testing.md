# Testing

Now that you've seen how the pipeline is built ([Pipeline Concepts](pipeline-concepts.md),
[Design Patterns](design-patterns.md)), here's how it's checked: each piece
can be tested on its own, which is exactly what the test suite does.

## What is "the workspace"?

"The workspace" means the top-level project folder — the one you open in
your editor, containing `src/`, `tests/`, `pyproject.toml`, and so on. Some
tests expect extra data folders to exist directly inside this workspace
folder, alongside those.

## Quick git basics

**Git** is a *version control system*: it keeps a history of every change
made to the project's files, so changes can be tracked, compared, and
undone. The project's history — every saved change ("commit") — lives in
a hidden `.git` folder inside the workspace. This project's copy of that
history is called a **repository** (or "repo").

Not every file belongs in that history. A **`.gitignore`** file (in the
workspace root) lists files and folders git should *never* track — even if
they exist in the workspace. Each line is a pattern; anything matching it
is skipped when you save changes. This project's `.gitignore` already
excludes things like `__pycache__/`, build output, and — importantly —
`/crane_data/`.

### The commands you actually need to get started

Git has a lot of commands, but you can be productive with a handful of
them. You don't need to learn git all at once — this short list covers
day-to-day work:

| Command | What it does |
| --- | --- |
| `git status` | Shows what's changed since your last commit. Safe to run anytime — it doesn't change anything. |
| `git add <file>` | Stages a file: marks it to be included in the next commit. |
| `git commit -m "message"` | Saves your staged changes as a new point in the project's history. |
| `git pull` | Fetches and merges in changes other people have committed. |
| `git push` | Sends your commits to the shared remote (e.g. GitHub). |
| `git log` | Shows the commit history. |
| `git diff` | Shows exactly what changed, line by line, before you stage it. |

For everyday work, `status` → `add` → `commit` → `pull`/`push` is most of
what you'll actually type.

### Installing GitHub CLI (`gh`)

`gh` is GitHub's own command-line tool — it lets you create pull requests,
check CI status, and more, without leaving the terminal.

```bash
# Windows (PowerShell)
winget install --id GitHub.cli

# macOS
brew install gh

# Linux (Debian/Ubuntu)
sudo apt install gh
```

If any of those don't work on your system (older Linux distros need an
extra step to add GitHub's package repository first), see the official
install instructions: <https://github.com/cli/cli#installation>.

This is just enough git to work day-to-day. For branching, merging, and
opening pull requests — i.e. actually *contributing* a change back — see
[For Contributors](contributing.md).

## The `crane_data` folder

`crane_data/` holds real participant recordings, which the Crane test suite
reads from directly. It is **not** included in the repository and never
will be: it's real participant data, and committing it to git would mean
it's kept in the project's history forever, on every clone of the repo —
exactly what `.gitignore` exists to prevent.

To run the full test suite, you need a `crane_data/` folder placed directly
in the workspace root yourself (ask a team member/supervisor for it if you
don't already have one). Without it, tests that read from `crane_data/`
will fail with a file-not-found style error — that's expected, not a bug.

## The `examples/` folder

`examples/` holds a small **synthetic** Crane dataset — no real participant
ever touched it, so unlike `crane_data/` nothing about it needs to stay
secret. It's still **not** checked into the repo, though: generated at
full length and full sampling rate, it runs to hundreds of MB, and git
handles large binary files badly — every regeneration would add another
full copy to the repo's history, forever. `examples/crane_templates/` (the
small seed files it's generated *from*) is *meant* to be committed as the
tracked exception — see the "Going further" note below, since right now it
isn't. `examples/` itself (`examples/*` in `.gitignore`) is gitignored and
built locally instead.

`tests/test_crane_pipeline.py` and `tests/test_crane_dummy_data.py` read
from `examples/crane_bids_dummy/` — a **BIDS-shaped** folder, not the flat
raw files directly — the same way the suite reads from `crane_data/`. So
you need to generate both the raw data and its BIDS conversion yourself
before running the full test suite (see below), much like you need someone
to hand you a `crane_data/` folder.

!!! warning "The pipeline itself doesn't read BIDS yet"
    Crane's own file-discovery (`ParticipantConfig.from_physiology_data`,
    driving `FindCraneParticipantFilesStrategyStep`) still only recognizes
    the old flat `{date}_{id}_CraneOut.{csv,mat}` filenames — not the BIDS
    layout `examples/crane_bids_dummy/` uses. Every test reading from it is
    currently expected to fail with a "no matching file" style error until
    that file-discovery is refactored to understand BIDS. That's
    intentional, not a sign something's broken: these are the failing
    tests meant to drive that refactor (test-driven development — see
    below). See `docs/pipeline_next_steps.md` and
    `docs/bids_converter_plan.md` for the planned shape of that change.

### Where it comes from

The data isn't handwritten — two steps produce it. First,
`generate_dummy_dataset()` in
`src/vrlab_toolbox/processing/crane_dummy_data.py` builds the raw, flat
layout, starting from the two real-*shaped*-but-not-real template files in
`examples/crane_templates/` (`*_CraneOut.csv` + matching `.mat`). For each
requested participant it copies a template, then randomises the numbers
that matter (ratings, outcome counts, physiology noise) with a seeded
`numpy` random generator — seeded, so the same call always produces
byte-identical output. Second, `convert_crane_to_bids()` in
`src/vrlab_toolbox/cli/crane_convert_to_bids.py` copies that raw layout into
the real `sub-XXX/ses-01/beh/...` BIDS structure (see
`docs/bids_converter_plan.md` for the naming decisions behind it) —
`examples/crane_bids_dummy/` is that BIDS output, and the one the test
suite actually reads from.

!!! note "Going further"
    `.gitignore` still carries a tracked-exception rule for
    `/sample_data/crane_templates/*.csv` — a stale path from before the
    templates moved to `examples/crane_templates/`. Worth cleaning up
    next time someone's touching `.gitignore`; not urgent on its own,
    and not fixed as part of this page's update.

Besides clean participants, it can also deliberately mutate a copy to
reproduce one specific pipeline failure:

```python
ERROR_TYPES = (
    "missing_physiology",
    "missing_behaviour",
    "missing_debrief",
    "date_mismatch",
    "bad_trigger_count",
    "short_trigger",
)
```

Each name matches a status the pipeline is supposed to catch — see
`ERROR_SCENARIO_STATUS_KEY` in `tests/test_crane_dummy_data.py` for exactly
which `ProcessingStatus` each one should produce.

### Generate it yourself

`generate_dummy_dataset()` is wrapped by a CLI command, so you don't need
to write any Python to build `examples/` — see the README's "Generate
sample data" section:

```bash
crane_generate_sample_data examples/crane_templates examples --with-errors --seed 42
```

`--seed` makes the output reproducible — same seed, same bytes, every
time. Bump `--n-clean` and rerun to see how new `DUMMY0XX` participants get
added; drop `--with-errors` for clean participants only.

`examples/` (the `output_folder` argument) is a plain **raw** folder — the
same shape `cli/crane_convert_to_bids.py` expects as input. Add
`--bids-folder examples/crane_bids_dummy` to also convert it into the BIDS
folder the test suite reads from, in the same call:

```bash
crane_generate_sample_data examples/crane_templates examples --with-errors --seed 42 --bids-folder examples/crane_bids_dummy
```

`examples/` still ends up holding the plain raw files either way; the BIDS
folder is purely additional, printed as a second summary table alongside the
"Generated crane dummy data" one. `convert_crane_to_bids()` is incremental —
subjects already present in `examples/crane_bids_dummy/` are skipped, not
re-copied — so re-running this after bumping `--n-clean` only adds the new
participants. This is a development/testing convenience only — the
generator itself has no connection to the crosscheck GUI (see
docs/bids_converter_plan.md).

!!! note "Going further"
    `tests/test_crane_dummy_data.py` calls `generate_dummy_dataset()`
    directly (not the CLI) into a throwaway `tempfile` folder on every test
    run — that copy is separate from, and never touches, your local
    `examples/`.

### Reproducing a real participant's trigger anomaly

`ERROR_TYPES` above are randomly-placed mutations — good for exercising the
pipeline's error handling in general, but they don't reproduce any
*specific* real participant's trigger pattern. For that,
`generate_dummy_participant_matching_reference()` (same file) reads one
real `.mat` file's trigger-pulse *timing* — pulse count and gap lengths
only, via `characterize_reference_trigger_pattern()` — and reproduces that
shape on a synthetic template. None of the reference file's actual
physiological signal is read or copied, so it's designed to be pointed
straight at a local, gitignored `crane_data/` participant without that
participant's data needing to go anywhere else.

```python
REFERENCE_ERROR_TYPES = (
    "missing_initial_trigger",
    "missing_last_trigger",
    "double_initial_trigger",
)
```

Wrapped by the same CLI command, as an alternate mode:

```bash
crane_generate_sample_data examples/crane_templates examples \
  --reference-folder crane_data \
  --reference-subject-id PID16186 \
  --reference-error-type missing_initial_trigger
```

`--reference-folder`, `--reference-subject-id`, and `--reference-error-type`
must be given together — the command validates that before generating
anything, rather than silently ignoring a partially-specified reference.
Repeated calls into the same `output_folder` accumulate (each adds one more
synthetic participant, debrief rows included) instead of overwriting
participants already there.

!!! note "Going further"
    One anomaly per call — there's no way yet to reproduce a participant
    with *two* combined anomalies (e.g. missing both the first and last
    trigger) in a single synthetic file. Each call rebuilds fresh from the
    template rather than stacking onto a previous mutation.

## The `foh_examples` folder

`foh_examples/` is FOH's counterpart to `crane_data`/`examples` above -- but shaped
differently, because FOH's raw recording is a single multi-stream `.xdf` file (Lab
Streaming Layer), not a `.mat`/`.csv` pair. `src/vrlab_toolbox/processing/foh_dummy_data.py`
builds synthetic recordings **from scratch** (like `longwalk_dummy_data.py`, not
`crane_dummy_data.py`'s clone-and-perturb-a-template approach) via a small private XDF
writer, since `pyxdf` can only read `.xdf` files, not write them.

The four streams it writes (`OpenSignals`, `VR_markers`, `VR_trial_events`, `FOH_target`),
their column names, the `VR_trial` event vocabulary, and the `FOH_target` CSV row shape are
all modelled on a real, de-identified example recording a human inspected and cleared for
this purpose -- session durations are compressed well below a real recording's length purely
to keep generated files small and fast to build; the event *sequence* and the
baseline/stress/recovery *ratios* follow the reference recording.

Like `crane_examples`/`longwalk_examples`, `foh_examples/` is gitignored -- generate it
locally rather than expecting it in a fresh clone.

### Generate it yourself

```bash
foh_generate_sample_data foh_examples --seed 42
```

Writes straight into the already-BIDS-shaped layout FOH's recording software produces
(`sub-XXX/ses-S001/beh/..._task-foh_run-001_beh.xdf`) -- there's no separate raw-to-BIDS
conversion step for FOH the way there is for crane/longwalk, so `foh_examples` can be pointed
at directly by `vrlab_foh_batch_process` or the FOH crosscheck GUI.

Add `--with-errors` to also generate one participant per known scenario:

```python
ERROR_TYPES = (
    "missing_physiology",
    "missing_behaviour",
    "missing_target",
    "missing_baseline_start_marker",
    "srate_mismatch",
    "incomplete_target_trials",
)
```

Each reproduces a specific, documented effect -- see `SCENARIO_DESCRIPTIONS` in
`foh_dummy_data.py` (also written into `foh_examples/dummy_data_log.txt` on every run) for
what each one is for. `missing_physiology` and `missing_target` are worth calling out
specifically: they reproduce genuine gaps in the current pipeline's error handling where a
missing stream raises an uncaught `KeyError` instead of being caught and flagged like every
other scenario here -- `tests/test_foh_dummy_data.py` asserts that's exactly what happens,
so a future fix to that handling has a failing test ready to turn green instead of needing
one written from scratch.

!!! note "Going further"
    `tests/test_foh_pipeline.py` still has a `TestFOHPipelineRealData` class reading from a
    real, gitignored `foh_data_copy/foh_bids_test` folder -- kept alongside the new
    self-contained `TestFOHPipelineDummyData` class rather than replacing it, the same way
    crane keeps both a dummy-data test class and a real-data one.

## Test-Driven Development (TDD), briefly

TDD means writing a **failing test first** — one that describes what the
code *should* do — before writing the code itself. Then you write just
enough code to make that test pass, and clean it up afterwards. The test
acts as a concrete, checkable definition of "done," written before you
start guessing at an implementation.

!!! note "Going further"
    Real Python's [Getting Started With Testing in Python](https://realpython.com/python-testing/)
    is a solid next read — it covers `pytest` basics and TDD in more depth
    than this page does.

## How the tests work here

- Tests live in `tests/`, one file roughly per module under test
  (`test_crane_pipeline.py`, `test_bids.py`, `test_long_walk_pipeline.py`).
- They're run with [`pytest`](https://docs.pytest.org/), the test framework
  this project uses. From the workspace root:

  ```
  pytest
  ```

- A single file or test can be run directly, e.g. `pytest tests/test_crane_pipeline.py`.
- Logging is turned on during tests (`pytest.ini_options` in
  `pyproject.toml`), so `logger.info(...)` calls show up in the test output
  — useful for seeing *why* a pipeline step failed, not just *that* it did.

### Running tests in VS Code

Rather than typing `pytest` in a terminal every time, VS Code can discover
and run tests through its own **Testing** panel (the flask/beaker icon in
the sidebar) — click a test to run just that one, with pass/fail shown
inline next to the code.

To enable it, add to `.vscode/settings.json` (the same file used for the
venv setting in [Development Setup](dev-setup.md#vs-code-auto-activate-this-venv-in-every-new-terminal)):

```json
{
  "python.testing.pytestEnabled": true,
  "python.testing.unittestEnabled": false,
  "python.testing.pytestArgs": ["tests"]
}
```

Or without editing JSON by hand: open the Command Palette
(`Ctrl+Shift+P` / `Cmd+Shift+P`), run **Python: Configure Tests**, choose
**pytest**, then point it at the `tests` folder — this writes the same
settings for you. Once configured, the Testing panel lists every test
found in `tests/`; running or debugging one from there uses the same
active virtual environment as your terminal.

!!! note "Going further"
    If tests fail intermittently with a `_tkinter`/`TclError` message,
    that's a known local-machine plotting-backend issue, not a real
    failure — see item 18 in `docs/pipeline_next_steps.md`.

---

**Next: [API Reference](api-reference.md)** for specifics on individual
functions and classes.
