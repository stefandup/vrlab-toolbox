# Building & Releasing (PyInstaller + Inno Setup)

[For Contributors](contributing.md) covered getting a change merged. This
page covers the last step: turning the toolbox's commands — CLI and GUI —
into standalone `.exe` files other people can run without installing Python
at all, and bundling all of them into one installer.

## Why PyInstaller?

Not everyone who needs to run a tool like `vrlab_crane_process` is a Python
developer with a `.venv` set up (see [Getting Started](getting-started.md#1-set-up-a-virtual-environment)).
[PyInstaller](https://pyinstaller.org/) bundles the Python interpreter,
every dependency, and the script itself into one executable file. The
result — `vrlab_crane_process.exe` — can be copied to any folder, including
one on the `PATH`, and just run. No Python install, no venv, no `pip
install` on the machine that runs it.

## The current setup

Every buildable command gets its own PyInstaller "spec file" — a small
Python script that says exactly what to bundle — under `specs/` in the
workspace root, named after its console-script command
(`specs/vrlab_crane_process.spec`, `specs/vrlab_check_xdf.spec`, …), covering
both CLI tools and the two PySide6 crosscheck GUIs. Every command currently
registered in `pyproject.toml`'s `[project.scripts]` has one. (Two entries
were removed 2026-08-31: `vrlab_foh_process` and `vrlab_crane_summary_data`
pointed at `mobi_FOH_process.py`/`vrlab_crane_qc.py`, both real files
deleted in earlier commits (2026-08-14 and 2026-07-22 respectively) without
ever cleaning up the matching script registration -- see
`docs/pipeline_next_steps.md` if either capability is ever rebuilt.)

```python
a = Analysis(
    [os.path.join(REPO_ROOT, "src", "mooi_toolbox", "cli", "vrlab_crane_process.py")],
    datas=[
        (os.path.join(REPO_ROOT, "references", "matched_debug_df_testa.parquet"), "references"),
        *copy_metadata("mooi-toolbox"),
    ],
    ...
)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='vrlab_crane_process',
    ...
)
```

A few things worth knowing:

- **`REPO_ROOT = os.path.join(SPECPATH, "..")`** — `SPECPATH` is a variable
  PyInstaller injects automatically, set to the spec file's own directory.
  Since every spec now lives in `specs/`, one level below the workspace
  root, entry-point and data paths are built from `REPO_ROOT` rather than
  hardcoded relative paths — this is what makes it safe for the specs to
  live in their own folder instead of cluttering the workspace root,
  regardless of what directory `pyinstaller` is actually invoked from.
- **`matched_debug_df_testa.parquet`** (Crane's spec only) — a reference
  data file some processing code reads at runtime; without listing it here
  explicitly, PyInstaller wouldn't know to bundle it (only actual Python
  imports are detected automatically).
- **`copy_metadata("mooi-toolbox")`** — bundles this package's installed
  metadata (version, name, …) into the exe. This is specifically because
  `@click.version_option(package_name="mooi-toolbox")` looks up the
  installed package's version via `importlib.metadata` at runtime — and a
  frozen exe doesn't have a normal `site-packages/` layout unless you tell
  PyInstaller to keep this piece of it.
- The two GUI specs (`vrlab_foh_bids_crosscheck.spec`,
  `vrlab_crane_bids_crosscheck.spec`) and the launcher's spec
  (`vrlab_toolbox_launcher.spec`, see below) set `console=False` — a normal
  windowed app, no console window popping up behind it.

## The toolbox launcher

`src/mooi_toolbox/gui/toolbox_launcher.py` (console-script
`vrlab_toolbox_launcher`) is a small PySide6 window with one button per GUI
tool — currently "FOH BIDS Crosscheck" and "Crane BIDS Crosscheck" — each of
which just `subprocess.Popen`s that tool's exe from the launcher's own
folder. CLI tools aren't buttons; they're listed as plain text underneath,
since they're meant to be run from a terminal (which is why getting the
toolbox folder onto `PATH` matters — see the installer below). It's the exe
the installer puts a desktop shortcut to.

## Building it yourself

```bash
python -m pip install pyinstaller   # not in requirements-dev.txt — rarely needed
```

```powershell
# Windows — build.ps1 -Full  (equivalent to what it runs internally)
pip install -e . --no-deps
Get-ChildItem -Path specs -Filter *.spec | ForEach-Object { pyinstaller $_.FullName }
```

`build.ps1` itself takes a flag rather than always doing a full rebuild:

- `.\build.ps1` (no flag) — prints usage and builds nothing.
- `.\build.ps1 -Full` — the full pipeline above: rebuild every exe, then
  assemble and compile the installer (see below). Slow, since PyInstaller
  re-bundles every tool from scratch.
- `.\build.ps1 -Exe` — only the PyInstaller step, into `dist/`. Skips
  assembling `toolbox/` and compiling the installer, so it doesn't need
  Inno Setup installed at all — useful when you're iterating on a tool's
  code and just want to check the exe builds.
- `.\build.ps1 -Inno` — skips the PyInstaller step entirely and reuses
  whatever's already in `dist/`; just reassembles `toolbox/` and recompiles
  `toolbox_installer.iss`. Use this after a `-Full` or `-Exe` build already
  succeeded and you're only iterating on the Inno Setup script itself —
  recompiling just the installer takes seconds instead of minutes.

```bash
# macOS/Linux — build_mac.sh
pyinstaller --onefile src/mooi_toolbox/cli/vrlab_crane_process.py
pyinstaller --onefile src/mooi_toolbox/cli/mobi_FOH_assess_data.py
```

The output lands in `dist/`. If PyInstaller complains about an obsolete
`pathlib` backport package being installed, `pip uninstall pathlib` — modern
Python already includes `pathlib` in the standard library.

!!! note "Going further"
    `build_mac.sh` only builds two of the toolbox's tools, as plain
    `--onefile` builds — so it doesn't bundle the reference `.parquet` file
    or the version metadata the `specs/` builds do, and there's no
    macOS/Linux equivalent of the toolbox-wide build or the installer below
    (Inno Setup, which does the installer packaging, is Windows-only). A
    known gap, not an intentional platform difference.

## The installer

`build.ps1` doesn't stop at building exes — after every `specs/*.spec` file
builds, it also:

1. Resolves a version string via `git describe --tags --always`.
2. Copies every resulting `dist/*.exe` into a fresh `toolbox/` folder.
3. Compiles `toolbox_installer.iss` (an [Inno Setup](https://jrsoftware.org/isinfo.php)
   script, in the workspace root) with `ISCC.exe`, producing
   `Output\MooiToolboxSetup.exe`.

`toolbox_installer.iss` is deliberately a **current-user, no-admin** install
(`PrivilegesRequired=lowest`) — appropriate for lab machines where installing
software as an administrator often isn't an option:

- Installs to `{localappdata}\Programs\MooiToolbox`, a location any user can
  write to.
- Adds that folder to the current user's `PATH` (`HKEY_CURRENT_USER\Environment`,
  not the system-wide `HKLM` one) via a small Pascal Script block, and
  removes it again on uninstall. It also broadcasts a `WM_SETTINGCHANGE`
  message so this doesn't strictly require a logoff — though a **new**
  terminal window is still needed to pick up the change, since already-open
  terminals cached their environment at launch.
- Puts a desktop shortcut to `vrlab_toolbox_launcher.exe` (the launcher
  above) on the current user's desktop.

`toolbox_installer.iss` produces a single `MooiToolboxSetup.exe` — no disk
spanning, so there's no separate `.bin` payload file to keep track of or
lose. If the combined toolbox ever grows past Inno's ~2 GB single-file
limit, `DiskSpanning=yes` (with `DiskSliceSize=max`) would need to come
back, splitting the installer into a small `.exe` stub plus one or more
`.bin` parts users would have to download alongside it.

If `ISCC.exe` isn't found at its default install path, `build.ps1` falls
back to checking `PATH`, and errors out clearly if Inno Setup isn't
installed at all — the exe-building steps still succeed either way, you
just won't get a compiled installer.

## Version tags

[Code Organization](code-organization.md#how-pyprojecttoml-works) covered
`setuptools_scm`: this package's version isn't written by hand anywhere —
it's derived from **git tags** automatically. To cut a new version:

```bash
git tag v1.2.0
git push origin v1.2.0
```

That single tag push does two things: `setuptools_scm` picks it up as the
installed package's version (which is what ends up embedded in each exe via
`copy_metadata`, above, and shown by e.g. `vrlab_crane_process --version`),
*and* it triggers an automatic build — next section.

## Automatic builds on tag push

`.github/workflows/release.yml` is a [GitHub Actions](https://docs.github.com/actions)
workflow — config that tells GitHub's own servers to run steps
automatically in response to an event, rather than on your machine. This
one is the piece that actually reacts to the tag push above:

```yaml
on:
  push:
    tags:
      - "v*"

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: pip install -e . --no-deps
      - run: |
          pyinstaller specs/vrlab_crane_process.spec
          pyinstaller specs/vrlab_foh_assess_data.spec
      - run: |
          $built = @('vrlab_crane_process.spec', 'vrlab_foh_assess_data.spec')
          Get-ChildItem -Path specs -Filter *.spec |
            Where-Object { $built -notcontains $_.Name } |
            ForEach-Object { pyinstaller $_.FullName }
      - run: |
          New-Item -ItemType Directory -Path toolbox | Out-Null
          Copy-Item dist\*.exe toolbox
      - run: choco install innosetup -y
      - run: |
          $version = "${{ github.ref_name }}" -replace '^v',''
          & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" toolbox_installer.iss "/DMyAppVersion=$version"
      - uses: softprops/action-gh-release@v2
        with:
          files: |
            dist/vrlab_crane_process.exe
            dist/vrlab_foh_assess_data.exe
            Output/*.exe
            Output/*.bin
```

Pushing any tag matching `v*` (e.g. `v1.2.0`) makes GitHub check out the
repo on a fresh Windows machine, install everything, build every tool's exe,
install Inno Setup via [Chocolatey](https://chocolatey.org/) (not present on
the runner by default), compile the installer — using the pushed tag itself
as the installer's version, rather than `git describe` — and attach both the
two original raw exes and the compiled installer (`Output/*.exe`, plus any
`Output/*.bin` slice files Inno produces if the installer crosses its
size-splitting threshold) to a GitHub Release. All of it automatic, with no
one needing to run the build script by hand.

`pyproject.toml` itself doesn't trigger the build — that's this workflow
file, reacting to the tag. `pyproject.toml`'s part is narrower but load-bearing:
it's what turns that same tag into the correct version number, via
`setuptools_scm`.

!!! note "Going further"
    This workflow only runs on `windows-latest` — there's no automated
    macOS/Linux release build yet, matching the manual build gap noted
    above.

---

**Next: Project Notes** (in the sidebar) — the project's own history and
still-open work.
