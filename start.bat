@echo off
chcp 65001 >nul
title TakyLive
color 0B

echo ============================================================
echo    TakyLive
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed!
    echo.
    echo 1. Download Python: https://python.org/downloads
    echo 2. IMPORTANT: check the box "Add Python to PATH" during install
    echo 3. Run start.bat again
    echo.
    pause
    exit /b
)

echo Starting... First run will auto-install libraries, please wait.
echo.

python app.py

pause
