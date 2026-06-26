#!/usr/bin/env bash
set -euo pipefail

pyinstaller --onefile src/mooi_toolbox/cli/vrlab_crane_process.py
