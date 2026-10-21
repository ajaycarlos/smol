# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

# SPECPATH is set by PyInstaller to the directory of this spec file (packaging/)
ROOT = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(ROOT / "smol" / "cli.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "PIL",
        "pillow_heif",
        "platformdirs",
        "Xlib",
        "tomli_w",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="smol",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="smol",
)
