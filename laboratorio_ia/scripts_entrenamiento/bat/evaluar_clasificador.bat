@echo off
cd /d "%~dp0..\..\.."
if not exist ".venv\Scripts\python.exe" (
    echo El entorno virtual no existe. Ejecuta primero scripts\lanzadores_windows\instalar_windows.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -X utf8 laboratorio_ia\scripts_entrenamiento\evaluar_clasificador.py %*
pause
