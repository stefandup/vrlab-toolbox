#!/usr/bin/env bash
set -euo pipefail

echo "Building VR Lab Toolbox for macOS..."

rm -rf build_output/work/mac
rm -rf "build_output/dist/VR Lab Toolbox"
rm -rf "build_output/dist/VR Lab Toolbox.app"

python -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --onedir \
  --name "VR Lab Toolbox" \
  --osx-bundle-identifier "za.ac.sun.vrlab.toolbox" \
  --distpath build_output/dist \
  --workpath build_output/work/mac \
  --copy-metadata vrlab-toolbox \
  --add-data "assets/vrlab_icon.ico:assets" \
  --add-data "assets/crane_icon.png:assets" \
  --add-data "assets/FOH_icon.png:assets" \
  --add-data "assets/longwalk_icon.png:assets" \
  --add-data "assets/longwalkv3_icon.png:assets" \
  --hidden-import "vrlab_toolbox.gui.foh_bids_crosscheck_gui" \
  --hidden-import "vrlab_toolbox.gui.crane_bids_crosscheck_gui" \
  --hidden-import "vrlab_toolbox.gui.longwalk_bids_crosscheck_gui" \
  --hidden-import "vrlab_toolbox.gui.longwalk3_bids_crosscheck_gui" \
  --hidden-import "vrlab_toolbox.gui.crane_process_results_gui" \
  --hidden-import "vrlab_toolbox.gui.foh_process_results_gui" \
  --hidden-import "vrlab_toolbox.gui.longwalk_process_results_gui" \
  src/vrlab_toolbox/gui/toolbox_launcher.py

echo "macOS build complete:"
echo "build_output/dist/VR Lab Toolbox.app"