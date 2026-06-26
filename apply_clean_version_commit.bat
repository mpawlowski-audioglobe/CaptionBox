@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ========================================
echo CaptionBox AV - commit clean version
echo ========================================

git status >nul 2>nul
if errorlevel 1 (
    echo ERROR: Ten folder nie jest repozytorium Git.
    echo Najpierw wykonaj git init / albo sklonuj repo.
    pause
    exit /b 1
)

echo Usuwam z indeksu cache Pythona, jesli istnieje...
git rm -r --cached app/__pycache__ 2>nul

echo Dodaje zmiany...
git add .

echo Tworze commit...
git commit -m "Clean CaptionBox AV 2.0 stable base"
if errorlevel 1 (
    echo Brak zmian do commita albo wystapil blad.
)

echo Wysylam na GitHub...
git push

echo.
echo Gotowe.
pause
