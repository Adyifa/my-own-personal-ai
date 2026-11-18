# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['tray_assistant.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['settings_gui', 'mika.ui.settings', 'tkinter', 'edge_tts', 'pygame', 'pyttsx3.drivers', 'pyttsx3.drivers.sapi5', 'comtypes.stream'],
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
    name='MikaAssistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
