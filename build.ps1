param(
    [switch]$Full,
    [switch]$Exe,
    [switch]$Inno
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Every build artifact (PyInstaller's intermediate work files, its onedir output, the
# assembled installer payload, and the compiled installer itself) lives under this one
# gitignored root instead of four separate top-level folders (build/, dist/, toolbox/,
# Output/) -- see docs/packaging.md.
$BuildOutput = Join-Path $PSScriptRoot "build_output"
$WorkPath = Join-Path $BuildOutput "work"
$DistPath = Join-Path $BuildOutput "dist"
$ToolboxPath = Join-Path $BuildOutput "toolbox"
# toolbox_installer.iss's OutputDir also points here (relative to that script's own directory,
# which is always the repo root regardless of who invokes ISCC -- this script or release.yml).
# Tracked here too so Build-Installer can clear it before each compile -- installer filenames
# now carry the version (MooiToolboxSetup-<version>.exe), so unlike ignoreversion file copies,
# stale exes from older versions won't just get overwritten in place; they'd otherwise pile up.
$InstallerPath = Join-Path $BuildOutput "installer"

# Resolved once, up front, rather than calling bare `pip`/`pyinstaller` and hoping PATH
# resolves both to the same interpreter -- a machine with more than one Python on PATH (a
# global install, a scoop/pyenv shim, ...) can easily have `pip install -e .` write fresh
# setuptools_scm version metadata into a *different* site-packages than the one `pyinstaller`
# actually reads it back from via `copy_metadata`, silently baking a stale version into the
# exe with no error at all. Routing both through the exact same python.exe via `-m` closes
# that gap. Falls back to whatever `python` is on PATH if .venv doesn't exist yet (fresh
# clone) -- still an improvement, since both steps then at least agree on the same
# interpreter as each other.
$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

function Show-Help {
    @"
Usage: .\build.ps1 -Full | -Exe | -Inno

  -Full   Build every tool from specs/toolbox.spec, assemble
          build_output/toolbox/, then compile the installer.

  -Exe    Only build specs/toolbox.spec from source into
          build_output/dist/mooi_toolbox/. Skips assembling
          build_output/toolbox/ and compiling the installer -- use this
          when you just want the exes (e.g. iterating on tool code) without
          needing Inno Setup installed at all.

  -Inno   Skip the PyInstaller build. Reuses build_output/dist/mooi_toolbox/
          from a previous build, reassembles build_output/toolbox/, and
          (re)compiles toolbox_installer.iss. Fast -- use this after a -Full
          or -Exe build already succeeded and only the Inno Setup script
          needs a fix.

No option given: prints this help and exits without building anything.
"@ | Write-Host
}

function Build-Exes {
    & $Python -m pip install -e . --no-deps
    # --noconfirm: skip PyInstaller's interactive "output directory ... will be REMOVED!
    # Continue? (y/N)" prompt when $DistPath\mooi_toolbox already exists from a previous
    # build -- this script has no stdin to answer it with, so without this flag it just
    # blocks. Safe here: $DistPath is build output this script owns, never a place a human
    # would have unsaved work.
    & $Python -m PyInstaller --noconfirm --workpath $WorkPath --distpath $DistPath `
        (Join-Path $PSScriptRoot "specs\toolbox.spec")
}

function Build-Installer {
    $version = (git describe --tags --always).Trim()

    $bundleDir = Join-Path $DistPath "mooi_toolbox"
    if (-not (Test-Path $bundleDir)) {
        throw "$bundleDir not found -- run '.\build.ps1 -Full' or '-Exe' first."
    }

    if (Test-Path $ToolboxPath) { Remove-Item $ToolboxPath -Recurse -Force }
    New-Item -ItemType Directory -Path $ToolboxPath | Out-Null
    Copy-Item (Join-Path $bundleDir "*") $ToolboxPath -Recurse

    if (Test-Path $InstallerPath) { Remove-Item $InstallerPath -Recurse -Force }

    $iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $iscc)) {
        $isccCmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if (-not $isccCmd) {
            throw "ISCC.exe (Inno Setup 6 compiler) not found. Install Inno Setup 6 or add ISCC.exe to PATH."
        }
        $iscc = $isccCmd.Source
    }

    & $iscc (Join-Path $PSScriptRoot "toolbox_installer.iss") "/DMyAppVersion=$version"
}

if ($Full) {
    Build-Exes
    Build-Installer
}
elseif ($Exe) {
    Build-Exes
}
elseif ($Inno) {
    Build-Installer
}
else {
    Show-Help
}
