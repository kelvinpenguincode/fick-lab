@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" launch_splash.py
    exit /b 0
)

where pyw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pyw -3 launch_splash.py
    exit /b 0
)

where pythonw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pythonw launch_splash.py
    exit /b 0
)

echo Could not find Python. Install Python and the app dependencies first:
echo python -m pip install -r requirements-app.txt
echo Then run: python launch_splash.py
pause
