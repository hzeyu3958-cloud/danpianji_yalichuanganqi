# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['pressure_monitor.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['serial.tools.list_ports_windows'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PressureMonitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
