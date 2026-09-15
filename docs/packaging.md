# Building & Releasing (PyInstaller + Inno Setup)

[For Contributors](contributing.md) covered getting a change merged. This
page covers the last step: turning the toolbox's commands — CLI and GUI —
into standalone `.exe` files other people can run without installing Python
at all, and bundling all of them into one installer.

## Why PyInstaller?

Not everyone who needs to run a tool like `vrlab_crane_process` is a Python
developer with a `.venv` set up (see [Development Setup](dev-setup.md#1-set-up-a-virtual-environment)).
[PyInstaller](https://pyinstaller.org/) bundles the Python interpreter,
every dependency, and the script itself into one executable file. The
result — `vrlab_crane_process.exe` — can be copied to any folder, including
one on the `PATH`, and just run. No Python install, no venv, no `pip
install` on the machine that runs it.

## The current setup

Every buildable command is bundled by one single PyInstaller "spec file" —
`specs/toolbox.spec` — rather than one spec per tool. It loops over a plain
`TOOLS` list (`(exe_name, script path relative to src/vrlab_toolbox, console
window?, extra datas)` per tool, covering both CLI tools and the two
PySide6 crosscheck GUIs plus the launcher below) and runs one `Analysis` +
`EXE` per entry, but feeds every tool's outputs into a single shared
`COLLECT` at the end:

```python
TOOLS = [
    ("vrlab_check_xdf", os.path.join("cli", "check_mobi_xdf.py"), True, []),
    ("vrlab_crane_bids_crosscheck", os.path.join("gui", "crane_bids_crosscheck_gui.py"), False, []),
    (
        "vrlab_crane_process",
        os.path.join("cli", "vrlab_crane_process.py"),
        True,
        [(os.path.join(REPO_ROOT, "references", "matched_debug_df_testa.parquet"), "references")],
    ),
    # ... one entry per console-script command in pyproject.toml's [project.scripts]
]

for name, script, console, extra_datas in TOOLS:
    a = Analysis([os.path.join(SRC_ROOT, script)], datas=[*extra_datas, *copy_metadata("vrlab-toolbox")], ...)
    pyz = PYZ(a.pure)
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=name, console=console, ...)
    collect_args.extend([exe, a.binaries, a.zipfiles, a.datas])

COLLECT(*collect_args, name="vrlab_toolbox")
```

A few things worth knowing:

- **One `COLLECT`, not one per tool.** Every tool used to be its own
  `--onedir` build (or its own spec file, before 2026-08-28), each carrying
  a full copy of the shared scientific-Python stack (numpy, scipy, mne,
  PySide6, …). Feeding all eleven tools' `EXE`/`binaries`/`datas` into one
  `COLLECT` instead means identical dependency files are only written to
  disk once, under a single `build_output/dist/vrlab_toolbox/` folder — see
  [The installer](#the-installer) below.
- **`REPO_ROOT = os.path.join(SPECPATH, "..")`** — `SPECPATH` is a variable
  PyInstaller injects automatically, set to the spec file's own directory.
  Since the spec lives in `specs/`, one level below the workspace root,
  entry-point and data paths are built from `REPO_ROOT` rather than
  hardcoded relative paths, regardless of what directory `pyinstaller` is
  actually invoked from.
- **`matched_debug_df_testa.parquet`** (`vrlab_crane_process`'s entry only)
  — a reference data file some processing code reads at runtime; without
  listing it here explicitly, PyInstaller wouldn't know to bundle it (only
  actual Python imports are detected automatically).
- **`copy_metadata("vrlab-toolbox")`** — bundles this package's installed
  metadata (version, name, …) into every tool. This is specifically because
  `@click.version_option(package_name="vrlab-toolbox")` looks up the
  installed package's version via `importlib.metadata` at runtime — and a
  frozen exe doesn't have a normal `site-packages/` layout unless you tell
  PyInstaller to keep this piece of it.
- The two GUI entries (`vrlab_crane_bids_crosscheck`,
  `vrlab_foh_bids_crosscheck`) and the launcher's entry
  (`vrlab_toolbox_launcher`, see below) pass `console=False` — a normal
  windowed app, no console window popping up behind it.

## The toolbox launcher

`src/vrlab_toolbox/gui/toolbox_launcher.py` (console-script
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
# Windows — build.ps1 -Full  (equivalent to what it runs internally, from an activated .venv)
pip install -e . --no-deps
pyinstaller --workpath build_output/work --distpath build_output/dist specs/toolbox.spec
```

`build.ps1` itself doesn't call bare `pip`/`pyinstaller` like the snippet above -- it resolves
`.venv\Scripts\python.exe` once up front and runs both steps through `python -m pip ...`/
`python -m PyInstaller ...`. On a machine with more than one Python on `PATH` (a global
install, a scoop/pyenv shim, ...), calling bare `pip`/`pyinstaller` risks `pip install -e .`
writing fresh `setuptools_scm` version metadata into a *different* site-packages than the one
`pyinstaller` reads it back from via `copy_metadata` -- silently baking a stale version into
the exe, with no error. Pinning both to the same interpreter closes that gap; this only
matters when running the raw commands above by hand outside of `build.ps1`.

`build.ps1` itself takes a flag rather than always doing a full rebuild:

- `.\build.ps1` (no flag) — prints usage and builds nothing.
- `.\build.ps1 -Full` — the full pipeline above: rebuild every exe, then
  assemble and compile the installer (see below). Slow, since PyInstaller
  re-bundles every tool from scratch.
- `.\build.ps1 -Exe` — only the PyInstaller step, into `build_output/dist/`.
  Skips assembling `build_output/toolbox/` and compiling the installer, so
  it doesn't need Inno Setup installed at all — useful when you're
  iterating on a tool's code and just want to check the exe builds.
- `.\build.ps1 -Inno` — skips the PyInstaller step entirely and reuses
  whatever's already in `build_output/dist/`; just reassembles
  `build_output/toolbox/` and recompiles `toolbox_installer.iss`. Use this
  after a `-Full` or `-Exe` build already succeeded and you're only
  iterating on the Inno Setup script itself — recompiling just the
  installer takes seconds instead of minutes.

Every artifact from any of the above — PyInstaller's intermediate work
files, its exe output, the assembled installer payload, and the compiled
installer — lands under one gitignored `build_output/` folder
(`build_output/work/`, `build_output/dist/`, `build_output/toolbox/`,
`build_output/installer/` respectively) instead of four separate top-level
folders.

```bash
# macOS/Linux — build_mac.sh
pyinstaller --onefile src/vrlab_toolbox/cli/vrlab_crane_process.py
pyinstaller --onefile src/vrlab_toolbox/cli/mobi_FOH_assess_data.py
```

The output lands in `build_output/dist/`. If PyInstaller complains about an
obsolete `pathlib` backport package being installed, `pip uninstall
pathlib` — modern Python already includes `pathlib` in the standard
library.

!!! note "Going further"
    `build_mac.sh` only builds two of the toolbox's tools, as plain
    `--onefile` builds — so it doesn't bundle the reference `.parquet` file
    or the version metadata the `specs/` builds do, and there's no
    macOS/Linux equivalent of the toolbox-wide build or the installer below
    (Inno Setup, which does the installer packaging, is Windows-only). A
    known gap, not an intentional platform difference.

## The installer

`build.ps1` doesn't stop at building exes — after `specs/toolbox.spec`
builds, it also:

1. Resolves a version string by reading `vrlab-toolbox`'s installed package
   metadata back out of the venv (`importlib.metadata.version(...)` via the
   same interpreter used for the PyInstaller build) -- the same version
   PyInstaller's `copy_metadata` already baked into the exe, so the
   installer can't disagree with what's actually running inside it.
2. Copies `build_output/dist/vrlab_toolbox/*` into a fresh
   `build_output/toolbox/` folder.
3. Compiles `toolbox_installer.iss` (an [Inno Setup](https://jrsoftware.org/isinfo.php)
   script, in the workspace root) with `ISCC.exe`, producing
   `build_output\installer\VRLabToolboxSetup-<version>.exe`, e.g.
   `VRLabToolboxSetup-v1.2.0.exe` (`OutputDir`/`OutputBaseFilename` in
   `toolbox_installer.iss`'s `[Setup]` section — `MyAppVersion` is passed
   in via `/DMyAppVersion=<version>`, resolved in step 1 above).

`toolbox_installer.iss` is deliberately a **current-user, no-admin** install
(`PrivilegesRequired=lowest`) — appropriate for lab machines where installing
software as an administrator often isn't an option:

- Installs to `{localappdata}\Programs\VRLabToolbox`, a location any user can
  write to.
- Adds that folder to the current user's `PATH` (`HKEY_CURRENT_USER\Environment`,
  not the system-wide `HKLM` one) via a small Pascal Script block, and
  removes it again on uninstall. It also broadcasts a `WM_SETTINGCHANGE`
  message so this doesn't strictly require a logoff — though a **new**
  terminal window is still needed to pick up the change, since already-open
  terminals cached their environment at launch.
- Puts a desktop shortcut to `vrlab_toolbox_launcher.exe` (the launcher
  above) on the current user's desktop.
- `CloseApplications=yes` (Inno 6's own default, stated explicitly so it can't be silently
  turned off later) means Setup checks every file it's about to write for a process holding it
  open and prompts to close it before touching anything -- so a toolbox window left running
  during an upgrade gets caught here, not partway through file copying.
- On top of that, `[Code]`'s `IsUpgrade`/`UninstallOldVersion` detect a previous install of the
  same product (matched by `AppId`, via its own `HKCU` uninstall registry entry) and run its
  uninstaller fully silently (`/VERYSILENT /NORESTART /SUPPRESSMSGBOXES`) before the new
  version's files are copied. Inno's default behavior on an upgrade is an in-place file
  overwrite, which never removes a file the *old* version shipped that the *new* version
  doesn't (e.g. a renamed or dropped tool's stale `.exe`) -- the explicit uninstall-first step
  avoids that buildup instead.

`toolbox_installer.iss` produces a single `VRLabToolboxSetup-<version>.exe`
— no disk spanning, so there's no separate `.bin` payload file to keep
track of or lose. If the combined toolbox ever grows past Inno's ~2 GB single-file
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
      - run: pyinstaller --workpath build_output/work --distpath build_output/dist specs/toolbox.spec
      - run: |
          New-Item -ItemType Directory -Path build_output/toolbox | Out-Null
          Copy-Item build_output\dist\vrlab_toolbox\* build_output\toolbox -Recurse
      - run: choco install innosetup -y
      - run: |
          $version = "${{ github.ref_name }}" -replace '^v',''
          & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" toolbox_installer.iss "/DMyAppVersion=$version"
      - uses: softprops/action-gh-release@v2
        with:
          files: build_output/installer/*.exe
```

Pushing any tag matching `v*` (e.g. `v1.2.0`) makes GitHub check out the
repo on a fresh Windows machine, install everything, build every tool's exe
from the single `specs/toolbox.spec`, install Inno Setup via
[Chocolatey](https://chocolatey.org/) (not present on the runner by
default), compile the installer — using the pushed tag itself as the
installer's version, rather than `git describe` — and attach the compiled
installer (`build_output/installer/*.exe`, resolved via `OutputDir` in
`toolbox_installer.iss`) to a GitHub Release. All of it automatic, with no
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
