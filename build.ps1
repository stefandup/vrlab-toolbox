Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

pip install -e . --no-deps
pyinstaller vrlab_crane_process.spec
pyinstaller mobi_FOH_assess_data.spec
