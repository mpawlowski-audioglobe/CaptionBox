@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo ========================================
echo CaptionBox AV 0.1.1 - setup
echo ========================================
echo Folder: %CD%
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python nie jest dostepny w PATH.
    echo Zainstaluj Python 3.11 lub 3.12 i zaznacz "Add python.exe to PATH".
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo Tworze virtual environment...
    python -m venv venv
    if errorlevel 1 goto error
)

call "venv\Scripts\activate.bat"
if errorlevel 1 goto error

echo.
echo Aktualizuje pip...
python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto error

echo.
echo Instaluje zaleznosci...
python -m pip install -r requirements.txt
if errorlevel 1 goto error

echo.
echo Sprawdzam CUDA / NVIDIA...
python -c "from app.cuda_runtime import prepare_cuda_paths; prepare_cuda_paths(); import ctranslate2; print('CUDA devices:', ctranslate2.get_cuda_device_count())"
echo Jesli CUDA devices = 0, program nadal zadziala na CPU.

echo.
echo ========================================
echo Setup completed.
echo Teraz uruchom run.bat
echo ========================================
pause
exit /b 0

:error
echo.
echo ========================================
echo SETUP FAILED - wystapil blad powyzej.
echo Skopiuj tresc bledu i wyslij ja do mnie.
echo ========================================
pause
exit /b 1
