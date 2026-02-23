@echo off
:: HeatSync installer for Windows
setlocal enabledelayedexpansion

echo === HeatSync Installer ===

:: Create virtual environment
echo [1/3] Creating Python virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo ERROR: Failed to create venv. Make sure Python 3.10+ is installed.
    pause
    exit /b 1
)
echo       Virtual environment created at .venv\

:: Install dependencies
echo [2/3] Installing dependencies...
.venv\Scripts\pip install --upgrade pip -q
.venv\Scripts\pip install -r requirements.txt -q
echo       Dependencies installed.

:: Autostart via Windows registry
echo [3/3] Setting up autostart...
set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "SCRIPT=%~dp0HeatSync.py"
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" ^
    /v "HeatSync" /t REG_SZ ^
    /d "\"%PYTHON%\" \"%SCRIPT%\"" /f >nul 2>&1
if errorlevel 1 (
    echo       WARNING: Could not add autostart registry entry.
) else (
    echo       Autostart registry entry created.
)

echo.
echo === Done! ===
echo Run HeatSync with:  run.bat
echo Or directly:        .venv\Scripts\python.exe HeatSync.py
pause
