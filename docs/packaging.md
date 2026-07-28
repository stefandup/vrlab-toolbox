# Building & Releasing (PyInstaller)

[For Contributors](contributing.md) covered getting a change merged. This
page covers the last step for the Crane CLI specifically: turning it into
a standalone `.exe` other people can run without installing Python at all.

## Why PyInstaller?

Not everyone who needs to run `vrlab_crane_process` is a Python developer
with a `.venv` set up (see [Getting Started](getting-started.md#1-set-up-a-virtual-environment)).
[PyInstaller](https://pyinstaller.org/) bundles the Python interpreter,
every dependency, and the script itself into one executable file. The
result — `vrlab_crane_process.exe` — can be copied to any folder, including
one on the `PATH`, and just run. No Python install, no venv, no `pip
install` on the machine that runs it.

## The current setup

The build is driven by `vrlab_crane_process.spec` (in the workspace root),
a PyInstaller "spec file" — a small Python script that says exactly what
to bundle:

```python
a = Analysis(
    ['src\\mooi_toolbox\\cli\\vrlab_crane_process.py'],
    datas=[
        ("references/matched_debug_df_testa.parquet", "references"),
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

Two `datas` entries worth knowing about:

- **`matched_debug_df_testa.parquet`** — a reference data file some
  processing code reads at runtime; without listing it here explicitly,
  PyInstaller wouldn't know to bundle it (only actual Python imports are
  detected automatically).
- **`copy_metadata("mooi-toolbox")`** — bundles this package's installed
  metadata (version, name, …) into the exe. This is specifically because
  `@click.version_option(package_name="mooi-toolbox")` (`vrlab_crane_process.py`)
  looks up the installed package's version via `importlib.metadata` at
  runtime — and a frozen exe doesn't have a normal `site-packages/`
  layout unless you tell PyInstaller to keep this piece of it.

## Building it yourself

```bash
python -m pip install pyinstaller   # not in requirements-dev.txt — rarely needed
```

```powershell
# Windows — build.ps1
pip install -e . --no-deps
pyinstaller vrlab_crane_process.spec
```

```bash
# macOS/Linux — build_mac.sh
pyinstaller --onefile src/mooi_toolbox/cli/vrlab_crane_process.py
```

The output lands in `dist/`. If PyInstaller complains about an obsolete
`pathlib` backport package being installed, `pip uninstall pathlib` — modern
Python already includes `pathlib` in the standard library.

!!! note "Going further"
    Notice the macOS/Linux script doesn't use the `.spec` file — it's a
    plain `--onefile` build, so it doesn't currently bundle the reference
    `.parquet` file or the version metadata the Windows build does. A known
    gap, not an intentional platform difference.

## Version tags

[Code Organization](code-organization.md#how-pyprojecttoml-works) covered
`setuptools_scm`: this package's version isn't written by hand anywhere —
it's derived from **git tags** automatically. To cut a new version:

```bash
git tag v1.2.0
git push origin v1.2.0
```

That single tag push does two things: `setuptools_scm` picks it up as the
installed package's version (which is what ends up embedded in the exe via
`copy_metadata`, above, and shown by `vrlab_crane_process --version`), *and*
it triggers an automatic build — next section.

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
      - run: pyinstaller vrlab_crane_process.spec
      - uses: softprops/action-gh-release@v2
        with:
          files: dist/vrlab_crane_process.exe
```

Pushing any tag matching `v*` (e.g. `v1.2.0`) makes GitHub check out the
repo on a fresh Windows machine, install everything, run the exact same
`pyinstaller vrlab_crane_process.spec` build from above, and attach the
resulting `.exe` to a GitHub Release — automatically, with no one needing
to run the build script by hand.

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
