# -*- mode: python ; coding: utf-8 -*-
"""Package FickLab as a Windows onefile exe.

The bootloader Splash target is intentionally omitted. Onefile + splash
extracts Tcl/Tk before python312.dll is loadable, which shows
"Failed to load Python DLL ... LoadLibrary: The specified module could
not be found" on machines without a matching VC runtime next to that DLL.
launch_splash.py still shows the Tk splash once Python is running.
"""

import os
import sys
from pathlib import Path

PYTHON_DLL = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
REQUIRED_DLLS = (PYTHON_DLL, "vcruntime140.dll")
OPTIONAL_DLLS = (
    "python3.dll",
    "vcruntime140_1.dll",
    "msvcp140.dll",
)


def _dll_search_roots() -> list[Path]:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    roots = [
        Path(getattr(sys, "base_prefix", sys.prefix)),
        Path(sys.prefix),
        Path(getattr(sys, "base_prefix", sys.prefix)) / "DLLs",
        Path(sys.prefix) / "DLLs",
        windir / "System32",
    ]
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def collect_runtime_dlls() -> list[tuple[str, str]]:
    wanted = list(REQUIRED_DLLS) + list(OPTIONAL_DLLS)
    found: list[tuple[str, str]] = []
    found_names: set[str] = set()
    for name in wanted:
        key = name.lower()
        for root in _dll_search_roots():
            candidate = root / name
            if candidate.is_file():
                found.append((str(candidate.resolve()), "."))
                found_names.add(key)
                break
    missing = {name.lower() for name in REQUIRED_DLLS} - found_names
    if missing:
        searched = ", ".join(str(root) for root in _dll_search_roots())
        raise SystemExit(
            "FickLab.spec could not find "
            + ", ".join(sorted(missing))
            + f". Searched: {searched}. "
            "The packaged exe would fail with Failed to load Python DLL."
        )
    return found


runtime_binaries = collect_runtime_dlls()

a = Analysis(
    ['launch_splash.py'],
    pathex=[],
    binaries=runtime_binaries,
    datas=[('github_repo.txt', '.')],
    hiddenimports=['diffusion_app', 'splash_window', 'scenario1', 'scenario2', 'scenario3', 'updater', 'app_version', 'arrhenius'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

collected = {str(entry[0]).replace("\\", "/").split("/")[-1].lower() for entry in a.binaries}
missing_after_analysis = {name.lower() for name in REQUIRED_DLLS} - collected
if missing_after_analysis:
    raise SystemExit(
        "PyInstaller Analysis dropped required DLLs: "
        + ", ".join(sorted(missing_after_analysis))
    )

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='FickLab',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[PYTHON_DLL, "python3.dll", "vcruntime140.dll", "vcruntime140_1.dll", "ucrtbase.dll"],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
