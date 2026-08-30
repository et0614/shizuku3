@echo off
rem Starts the web GUI; a browser opens automatically.
rem Start Shizuku3.exe first, and run setup.bat once before using this.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)
.venv\Scripts\python.exe gui\server.py
pause
