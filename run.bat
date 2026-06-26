@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ========================================
echo CaptionBox AV 1.0 - start
echo ========================================
echo Folder: %CD%
echo.

if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Brak srodowiska venv.
    echo Najpierw uruchom setup.bat
    pause
    exit /b 1
)

call "venv\Scripts\activate.bat"
if errorlevel 1 goto error

echo Uruchamiam aplikacje...
python app\desktop_app.py
if errorlevel 1 goto error

exit /b 0

:error
echo.
echo ========================================
echo CaptionBox AV zatrzymal sie z bledem.
echo Skopiuj tresc bledu i wyslij ja do mnie.
echo ========================================
pause
exit /b 1
