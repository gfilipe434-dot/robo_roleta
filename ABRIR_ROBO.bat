@echo off
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
    python robo_roleta.py --web
) else (
    py robo_roleta.py --web
)
if errorlevel 1 (
    echo Nao foi possivel abrir o painel. Execute INSTALAR.bat primeiro.
    pause
)
