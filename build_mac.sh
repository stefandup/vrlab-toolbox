#!/usr/bin/env bash
set -euo pipefail

pyinstaller --onefile src/mooi_toolbox/cli/vrlab_crane_process.py
pyinstaller --onefile src/mooi_toolbox/cli/mobi_FOH_assess_data.py
