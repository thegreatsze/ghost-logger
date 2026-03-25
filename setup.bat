@echo off
echo ================================================
echo  Ghost Activity ^& Time Logger — Setup
echo ================================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Download it from https://python.org
    pause
    exit /b 1
)

echo Installing dependencies...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Installation failed. Check the output above.
    pause
    exit /b 1
)

echo.
echo Setup complete!
echo.
echo To start Ghost Logger silently (no console window):
echo   Double-click run_ghost.vbs
echo.
echo To start with a visible console (for debugging):
echo   python ghost_logger.py
echo.

set /p LAUNCH="Launch Ghost Logger now? (y/n): "
if /i "%LAUNCH%"=="y" (
    echo Starting Ghost Logger in background...
    wscript run_ghost.vbs
    echo Ghost Logger is now running in your system tray.
)

pause
