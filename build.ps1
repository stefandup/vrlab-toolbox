Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

pip install -e . --no-deps
pyinstaller vrlab_crane_process.spec
