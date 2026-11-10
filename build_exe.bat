@echo off
chcp 65001 >nul
title Build EXE - TakyLive
color 0E

echo ============================================================
echo    Building TakyLive.exe
echo    This takes 2-5 minutes on first run, please wait...
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed!
    echo Install it from https://python.org/downloads
    echo Check the box "Add Python to PATH" during install.
    pause
    exit /b
)

echo [1/3] Installing build tools and libraries...
python -m pip install --quiet --no-warn-script-location -U pyinstaller aiohttp TikTokLive "edge-tts>=7.3.1" imageio-ffmpeg

echo [2/3] Building exe (the longest step)...
python -m PyInstaller --noconfirm --onefile --console --name "TakyLive" --icon web\takylive.ico --collect-all TikTokLive --collect-all imageio_ffmpeg --collect-all edge_tts --exclude-module numpy --exclude-module setuptools app.py
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. See messages above.
    pause
    exit /b
)

echo [3/3] Cleaning up...
copy /Y dist\TakyLive.exe . >nul
rmdir /S /Q build >nul 2>&1
rmdir /S /Q dist >nul 2>&1
del /Q TakyLive.spec >nul 2>&1

echo.
echo ============================================================
echo    DONE! TakyLive.exe created in this folder.
echo.
echo    To share: send the WHOLE folder (exe + web, media, mods + gift_icons.json).
echo    Friends just double-click the exe - no Python needed!
echo ============================================================
pause
