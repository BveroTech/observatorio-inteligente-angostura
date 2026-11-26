@echo off
rem Copia al dataset las aves identificadas en el portal (menu "Por identificar").
rem Opciones: --simular (solo muestra), --incluir-simulacion (tambien video/pantalla).
cd /d "%~dp0..\..\.."
if not exist ".venv\Scripts\python.exe" (
    echo El entorno virtual no existe. Ejecuta primero scripts\lanzadores_windows\instalar_windows.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -X utf8 laboratorio_ia\scripts_entrenamiento\importar_identificadas.py %*
pause
