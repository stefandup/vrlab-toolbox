#!/usr/bin/env bash
set -euo pipefail

pyinstaller --onefile src/vrlab_toolbox/cli/vrlab_crane_process.py
pyinstaller --onefile src/vrlab_toolbox/cli/FOH_assess_data.py
