@echo off
rem Muestra los monitores conectados y su numero en grande sobre cada uno.
rem Esos numeros son los que se escriben en ejecutar_observatorio.bat y
rem probar_sistema_con_pantalla.bat (MONITOR_KIOSCO, MONITOR_TACTIL, MONITOR_CAMARA).
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" (
    echo El entorno virtual no existe. Ejecuta primero scripts\lanzadores_windows\instalar_windows.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -X utf8 scripts\cli_admin\detectar_pantallas.py %*
pause
