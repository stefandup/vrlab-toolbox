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

  -Full   Build every tool in specs/*.spec from source, assemble toolbox/,
          then compile the installer. Slow -- rebuilds every exe.

  -Exe    Only build every tool in specs/*.spec from source into dist/.
          Skips assembling toolbox/ and compiling the installer -- use this
          when you just want the exes (e.g. iterating on tool code) without
          needing Inno Setup installed at all.

  -Inno   Skip the PyInstaller build. Reuses the exes already in dist/,
          reassembles toolbox/, and (re)compiles toolbox_installer.iss.
          Fast -- use this after a -Full or -Exe build already succeeded
          and only the Inno Setup script needs a fix.

No option given: prints this help and exits without building anything.
"@ | Write-Host
}

function Build-Exes {
    pip install -e . --no-deps
    Get-ChildItem -Path (Join-Path $PSScriptRoot "specs") -Filter *.spec | ForEach-Object { pyinstaller $_.FullName }
}

function Build-Installer {
    $version = (git describe --tags --always).Trim()

    $toolboxDir = Join-Path $PSScriptRoot "toolbox"
    if (Test-Path $toolboxDir) { Remove-Item $toolboxDir -Recurse -Force }
    New-Item -ItemType Directory -Path $toolboxDir | Out-Null
    Copy-Item (Join-Path $PSScriptRoot "dist\*.exe") $toolboxDir

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
    $distDir = Join-Path $PSScriptRoot "dist"
    if (-not (Test-Path $distDir)) {
        throw "dist/ not found -- run '.\build.ps1 -Full' first to build the exes."
    }
    Build-Installer
}
else {
    Show-Help
}
