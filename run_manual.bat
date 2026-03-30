@echo off
echo === REPORTE MARFIL — Ejecucion Manual ===
cd /d "%~dp0"

if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

python main.py
echo.
echo === Completado ===
pause
