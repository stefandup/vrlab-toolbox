Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

pyinstaller vrlab_crane_process.spec src/mooi_toolbox/cli/vrlab_crane_process.py
