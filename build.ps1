param(
    [switch]$Full,
    [switch]$Exe,
    [switch]$Inno
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Show-Help {
    @"
Usage: .\build.ps1 -Full | -Exe | -Inno

  -Full   Build every tool from specs/toolbox.spec, assemble toolbox/,
          then compile the installer.

  -Exe    Only build specs/toolbox.spec from source into dist/mooi_toolbox/.
          Skips assembling toolbox/ and compiling the installer -- use this
          when you just want the exes (e.g. iterating on tool code) without
          needing Inno Setup installed at all.

  -Inno   Skip the PyInstaller build. Reuses dist/mooi_toolbox/ from a
          previous build, reassembles toolbox/, and (re)compiles
          toolbox_installer.iss. Fast -- use this after a -Full or -Exe
          build already succeeded and only the Inno Setup script needs a
          fix.

No option given: prints this help and exits without building anything.
"@ | Write-Host
}

function Build-Exes {
    pip install -e . --no-deps
    pyinstaller (Join-Path $PSScriptRoot "specs\toolbox.spec")
}

function Build-Installer {
    $version = (git describe --tags --always).Trim()

    $bundleDir = Join-Path $PSScriptRoot "dist\mooi_toolbox"
    if (-not (Test-Path $bundleDir)) {
        throw "$bundleDir not found -- run '.\build.ps1 -Full' or '-Exe' first."
    }

    $toolboxDir = Join-Path $PSScriptRoot "toolbox"
    if (Test-Path $toolboxDir) { Remove-Item $toolboxDir -Recurse -Force }
    New-Item -ItemType Directory -Path $toolboxDir | Out-Null
    Copy-Item (Join-Path $bundleDir "*") $toolboxDir -Recurse

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
