@echo off
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
    python -m pip install -r requirements-pc.txt
) else (
    py -m pip install -r requirements-pc.txt
)
if errorlevel 1 (
    echo Nao foi possivel instalar. Confira se o Python 3.10 ou superior esta instalado.
    pause
    exit /b 1
)
echo Instalacao concluida. Abra ABRIR_ROBO.bat.
pause
