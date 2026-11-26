@echo off
rem Prueba el reconocimiento sin camara: analiza un video de aves reproducido en otro monitor.
rem Uso: probar_con_pantalla.bat            (pregunta el monitor)
rem      probar_con_pantalla.bat --monitor 2
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" (
    echo El entorno virtual no existe. Ejecuta primero scripts\lanzadores_windows\instalar_windows.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import mss" 2>nul || ".venv\Scripts\python.exe" -m pip install -q mss
".venv\Scripts\python.exe" -X utf8 scripts\cli_admin\probar_con_pantalla.py %*
pause
