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

echo Could not find Python. Install Python and the app dependencies first:
echo python -m pip install -r requirements-app.txt
echo Then run: python diffusion_app.py
pause
