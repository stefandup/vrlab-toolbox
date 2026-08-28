# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import copy_metadata

REPO_ROOT = os.path.join(SPECPATH, "..")

a = Analysis(
    [os.path.join(REPO_ROOT, "src", "mooi_toolbox", "cli", "plot_subject_target_scr_bars.py")],
    pathex=[],
    binaries=[],
    datas=[
        *copy_metadata("mooi-toolbox")
    ],
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
    a.binaries,
    a.datas,
    [],
    name='vrlab_plot_target_data',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
