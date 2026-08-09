@echo off
chcp 65001 >nul
title Dialaw TV Live
cd /d "%~dp0"

echo.
echo   ================================
echo     DIALAW TV LIVE - demarrage
echo   ================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo   [ERREUR] Python n'est pas installe ou absent du PATH.
    echo   Telechargez-le sur https://www.python.org/downloads/
    pause
    exit /b 1
)

python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo   Installation des dependances...
    python -m pip install -r requirements.txt
    echo.
)

start "" http://127.0.0.1:5000/
python app.py

pause
