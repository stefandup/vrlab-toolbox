# Development Setup

[Getting Started](getting-started.md) covers running the toolbox's tools —
installer or standalone `.exe`, no Python required. This page is the other
path: setting up a full Python development environment so you can read,
change, and run the code itself from source.

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
(e.g. `vrlab_crane_process`), and `import mooi_toolbox` in scripts,
available in your environment.

!!! note "Going further"
    See [Code Organization](code-organization.md#how-pyprojecttoml-works)
    for how `pyproject.toml` turns this one command into working CLI
    commands, and
    [Code Organization](code-organization.md#where-the-actual-steps-live)
    for where the actual per-step processing code lives.

## 3. Run a pipeline from source

With the venv active, the CLI commands work exactly as described in
[Process Your Data](processing.md) — the only
difference is you're now running your own local copy of the code instead
of a built `.exe`, so any change you make takes effect the next time you
run the command:

```bash
vrlab_crane_process crane_data crane_data/output
```

## Extra dev-only tools

`requirements-dev.txt` lists packages a contributor needs that a plain user
never does — a linter, a type checker, a docs builder. Install them the
same way:

```bash
pip install -r requirements-dev.txt
```

This is also what lets you build and preview this documentation site
locally — see
[Code Organization](code-organization.md#building-and-previewing-this-documentation-site).

---

**Next: [Code Organization](code-organization.md)** — now that your
environment is set up, see how the code itself is laid out.
