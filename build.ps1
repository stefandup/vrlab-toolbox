Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

pyinstaller --onefile src/mooi_toolbox/cli/vrlab_crane_process.py
