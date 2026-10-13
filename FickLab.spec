# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['launch_splash.py'],
    pathex=[],
    binaries=[],
    datas=[('github_repo.txt', '.')],
    hiddenimports=['diffusion_app', 'splash_window', 'scenario1', 'scenario2', 'scenario3', 'updater', 'app_version', 'arrhenius'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

splash = Splash(
    'splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(48, 352),
    text_size=12,
    text_color='#99f6e4',
    text_default='Starting FickLab…',
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    splash.binaries,
    [],
    name='FickLab',
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
