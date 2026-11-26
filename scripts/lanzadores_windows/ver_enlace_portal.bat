@echo off
rem Muestra el enlace para abrir el portal de administracion desde otro computador de la red.
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" (
    echo El entorno virtual no existe. Ejecuta primero scripts\lanzadores_windows\instalar_windows.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -X utf8 main_admin.py --mostrar-enlace
pause
