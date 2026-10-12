@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" diffusion_app.py
    exit /b 0
)

where pyw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pyw -3 diffusion_app.py
    exit /b 0
)

where pythonw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pythonw diffusion_app.py
    exit /b 0
)

if exist "dist\FickLab.exe" (
    start "" "dist\FickLab.exe"
    exit /b 0
)

echo FickLab is not built and Python could not be found.
echo Install Python or double-click build_exe.bat to build the standalone app.
pause
