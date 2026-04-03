@echo off
REM start.bat – Launch the Darts-V2 server on Windows
REM Usage:  start.bat [port]

echo ==================================================
echo   Darts-V2 - Real-Time Dart Detection
echo ==================================================

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not on PATH.
    pause
    exit /b 1
)

if not exist "%VENV_DIR%" (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
)

call "%VENV_DIR%\Scripts\activate.bat"

echo Installing / verifying dependencies...
pip install --quiet --upgrade pip
pip install --quiet -r "%SCRIPT_DIR%requirements.txt"

echo.
echo Starting server on http://localhost:5000
echo Press Ctrl+C to stop.
echo.

cd /d "%SCRIPT_DIR%backend"
python app.py
pause
