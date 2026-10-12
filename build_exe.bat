@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating the project virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 goto :failed
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 goto :failed
python -m pip install -r requirements-app.txt
if errorlevel 1 goto :failed

python -m PyInstaller --noconfirm --clean FickLab.spec
if errorlevel 1 goto :failed

echo.
echo Build complete: %CD%\dist\FickLab.exe
echo Copy FickLab.exe anywhere and double-click it to run.
pause
exit /b 0

:failed
echo.
echo Build failed. Review the error messages above.
pause
exit /b 1
