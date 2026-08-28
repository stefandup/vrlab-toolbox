# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import copy_metadata

REPO_ROOT = os.path.join(SPECPATH, "..")

a = Analysis(
    [os.path.join(REPO_ROOT, "src", "mooi_toolbox", "cli", "crane_convert_to_bids.py")],
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
    name='vrlab_crane_convert_to_bids',
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
