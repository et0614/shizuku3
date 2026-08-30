@echo off
rem Opens a command prompt with the virtual environment activated,
rem ready to run the examples (python examples\01_onoff_control.py).
rem Run setup.bat once before using this.
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)
cmd /k .venv\Scripts\activate.bat
