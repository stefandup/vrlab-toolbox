#!/usr/bin/env bash
set -euo pipefail

echo "Building VR Lab Toolbox for Linux..."

rm -rf build_output/work/linux
rm -rf build_output/dist/vrlab_toolbox_linux

python -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --name "vrlab_toolbox_linux" \
  --distpath build_output/dist \
  --workpath build_output/work/linux \
  --copy-metadata vrlab-toolbox \
  --add-data "assets/vrlab_icon.ico:assets" \
  --hidden-import "vrlab_toolbox.gui.foh_bids_crosscheck_gui" \
  --hidden-import "vrlab_toolbox.gui.crane_bids_crosscheck_gui" \
  --hidden-import "vrlab_toolbox.gui.longwalk_bids_crosscheck_gui" \
  --hidden-import "vrlab_toolbox.gui.crane_process_results_gui" \
  --hidden-import "vrlab_toolbox.gui.foh_process_results_gui" \
  --hidden-import "vrlab_toolbox.gui.longwalk_process_results_gui" \
  --hidden-import "vrlab_toolbox.gui.redcap_pull_gui" \
  src/vrlab_toolbox/gui/toolbox_launcher.py

echo "Linux build complete:"
echo "build_output/dist/vrlab_toolbox_linux"