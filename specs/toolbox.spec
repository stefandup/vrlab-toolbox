# -*- mode: python ; coding: utf-8 -*-
# Builds every CLI/GUI tool as one onedir bundle so they share a single copy
# of their dependencies (numpy, scipy, mne, PySide6, ...) instead of each
# tool carrying its own full copy, as separate --onefile builds used to.
import os

from PyInstaller.utils.hooks import copy_metadata

REPO_ROOT = os.path.join(SPECPATH, "..")
SRC_ROOT = os.path.join(REPO_ROOT, "src", "vrlab_toolbox")
ICON = os.path.join(REPO_ROOT, "assets", "vrlab_icon.ico")

# (exe_name, script path relative to src/vrlab_toolbox, console window?, extra datas)
TOOLS = [
    ("vrlab_check_xdf", os.path.join("cli", "check_xdf.py"), True, []),
    ("vrlab_crane_bids_crosscheck", os.path.join("gui", "crane_bids_crosscheck_gui.py"), False, []),
    ("vrlab_crane_convert_to_bids", os.path.join("cli", "crane_convert_to_bids.py"), True, []),
    ("vrlab_crane_generate_sample_data", os.path.join("cli", "crane_generate_sample_data.py"), True, []),
    ("vrlab_crane_process", os.path.join("cli", "vrlab_crane_process.py"), True, []),
    (
        "vrlab_crane_process_GUI",
        os.path.join("gui", "crane_process_results_gui.py"),
        False,
        [],
    ),
    ("vrlab_foh_assess_data", os.path.join("cli", "FOH_assess_data.py"), True, []),
    ("vrlab_foh_process", os.path.join("cli", "vrlab_foh_process.py"), True, []),
    (
        "vrlab_foh_process_GUI",
        os.path.join("gui", "foh_process_results_gui.py"),
        False,
        [],
    ),
    ("vrlab_foh_bids_crosscheck", os.path.join("gui", "foh_bids_crosscheck_gui.py"), False, []),
    ("vrlab_foh_import_to_bids", os.path.join("cli", "foh_import_to_bids.py"), True, []),
    (
        "vrlab_longwalk_bids_crosscheck",
        os.path.join("gui", "longwalk_bids_crosscheck_gui.py"),
        False,
        [],
    ),
    (
        "vrlab_longwalk_convert_to_bids",
        os.path.join("cli", "longwalk_convert_to_bids.py"),
        True,
        [],
    ),
    (
        "vrlab_longwalk_process",
        os.path.join("cli", "vrlab_longwalk_process.py"),
        True,
        [],
    ),
    (
        "vrlab_longwalk3_generate_sample_data",
        os.path.join("cli", "longwalk3_generate_sample_data.py"),
        True,
        [],
    ),
    (
        "vrlab_longwalk3_bids_crosscheck",
        os.path.join("gui", "longwalk3_bids_crosscheck_gui.py"),
        False,
        [],
    ),
    (
        "vrlab_longwalk_process_GUI",
        os.path.join("gui", "longwalk_process_results_gui.py"),
        False,
        [],
    ),
    ("vrlab_plot_target_data", os.path.join("cli", "plot_subject_target_scr_bars.py"), True, []),
    ("vrlab_redcap_pull", os.path.join("gui", "redcap_pull_gui.py"), False, []),
    (
        "vrlab_toolbox_launcher",
        os.path.join("gui", "toolbox_launcher.py"),
        False,
        [(ICON, "assets")],
    ),
]

collect_args = []

for name, script, console, extra_datas in TOOLS:
    a = Analysis(
        [os.path.join(SRC_ROOT, script)],
        pathex=[],
        binaries=[],
        datas=[*extra_datas, *copy_metadata("vrlab-toolbox")],
        hiddenimports=[],
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=[],
        noarchive=False,
        optimize=0,
    )
    pyz = PYZ(a.pure)
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        console=console,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=ICON,
    )
    collect_args.extend([exe, a.binaries, a.zipfiles, a.datas])

# A single COLLECT for every tool: identical dependency files (same
# destination path) are only written to disk once, so the shared
# scientific-Python stack stops being duplicated 11x.
COLLECT(
    *collect_args,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="vrlab_toolbox",
)
