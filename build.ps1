Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

pip install -e . --no-deps
pyinstaller --copy-metadata mooi-toolbox --onefile src/mooi_toolbox/cli/vrlab_crane_process.py
