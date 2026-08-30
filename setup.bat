@echo off
rem One-time setup: creates the Python virtual environment (.venv) and
rem installs the Shizuku3 client with all extras (web GUI + RL).
rem Just double-click this file. Requires Python 3.10+ installed with
rem "Add python.exe to PATH" checked.
cd /d "%~dp0"

set "PY=py"
where py >nul 2>nul || set "PY=python"
where %PY% >nul 2>nul || (
    echo Python not found. Install Python 3.10+ from https://www.python.org/
    echo and check "Add python.exe to PATH" in the installer.
    pause
    exit /b 1
)

if not exist .venv\Scripts\python.exe (
    echo Creating the virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 (pause & exit /b 1)
)

call .venv\Scripts\activate.bat
echo Installing the Python packages ^(this downloads PyTorch - be patient^)...
python -m pip install -e "client[all]"
if errorlevel 1 (pause & exit /b 1)

echo.
echo ============================================================
echo  Setup complete. This window is ready to use.
echo  Next: start Shizuku3.exe, then double-click start_gui.bat,
echo  or run the examples right here:
echo      python examples\01_onoff_control.py
echo ============================================================
cmd /k
