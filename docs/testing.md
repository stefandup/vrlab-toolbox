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

!!! note "Going further"
    If tests fail intermittently with a `_tkinter`/`TclError` message,
    that's a known local-machine plotting-backend issue, not a real
    failure — see item 18 in `docs/pipeline_next_steps.md`.

---

**Next: [API Reference](api-reference.md)** for specifics on individual
functions and classes.
