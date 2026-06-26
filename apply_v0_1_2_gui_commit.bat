@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ========================================
echo CaptionBox AV - commit v0.1.2 GUI LIVE
echo ========================================
echo Folder: %CD%
echo.

where git >nul 2>nul
if errorlevel 1 (
    echo ERROR: Git nie jest dostepny w PATH.
    pause
    exit /b 1
)

git status >nul 2>nul
if errorlevel 1 (
    echo ERROR: Ten folder nie jest repozytorium Git.
    echo Najpierw wykonaj git init i ustaw remote origin.
    pause
    exit /b 1
)

echo Dodaje zmiany...
git add app/operator_window.py app/caption_worker.py CHANGELOG.md apply_v0_1_2_gui_commit.bat
if errorlevel 1 goto error

echo Tworze commit...
git commit -m "Add operator LIVE status and audio meter"
if errorlevel 1 (
    echo Brak zmian do commita albo commit sie nie udal.
)

echo Wysylam na GitHub...
git push
if errorlevel 1 goto error

echo.
echo ========================================
echo Gotowe. v0.1.2 GUI LIVE jest na GitHubie.
echo ========================================
pause
exit /b 0

:error
echo.
echo ========================================
echo BLAD - skopiuj komunikat powyzej i wyslij go do mnie.
echo ========================================
pause
exit /b 1
