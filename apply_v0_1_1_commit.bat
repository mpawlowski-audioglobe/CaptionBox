@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ========================================
echo CaptionBox AV v0.1.1 - Git commit
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
    echo Najpierw wykonaj git init / remote albo sklonuj repo.
    pause
    exit /b 1
)

echo Dodaje zmiany do Git...
git add .
if errorlevel 1 goto error

echo Tworze commit...
git commit -m "Release v0.1.1 stabilizer polish"
if errorlevel 1 goto maybe_no_changes

echo Wysylam na GitHub...
git push
if errorlevel 1 goto error

echo.
echo ========================================
echo Gotowe. v0.1.1 jest na GitHubie.
echo ========================================
pause
exit /b 0

:maybe_no_changes
echo.
echo Git nie utworzyl commita. Mozliwe, ze nie ma zmian do zapisania.
echo Pokazuje status:
git status
pause
exit /b 0

:error
echo.
echo ========================================
echo Wystapil blad. Skopiuj tresc i wyslij ja do mnie.
echo ========================================
pause
exit /b 1
