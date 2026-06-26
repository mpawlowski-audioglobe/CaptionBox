@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ========================================
echo CaptionBox AV v0.2.0 - Stabilizer update
echo ========================================
echo Folder: %CD%
echo.

git status >nul 2>nul
if errorlevel 1 (
    echo ERROR: To nie jest folder repozytorium Git.
    echo Uruchom ten plik z folderu C:\AI\CaptionBox.
    pause
    exit /b 1
)

echo Dodaje zmiany do Git...
git add .
if errorlevel 1 goto error

echo Tworze commit...
git commit -m "Add word-based stabilizer v0.2.0"
if errorlevel 1 (
    echo Brak zmian do commita albo commit sie nie udal.
)

echo.
echo Wysylam na GitHub...
git push
if errorlevel 1 goto error

echo.
echo ========================================
echo Gotowe. v0.2.0 stabilizer jest na GitHubie.
echo ========================================
pause
exit /b 0

:error
echo.
echo ========================================
echo ERROR: Wystapil blad powyzej.
echo Wyslij screen z tego okna.
echo ========================================
pause
exit /b 1
