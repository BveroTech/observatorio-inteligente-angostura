@echo off
rem Construye el instalador del Observatorio para el NVIDIA Jetson Orin Nano:
rem   dist\observatorio-angostura_<version>_arm64.deb
rem Copiarlo al Jetson (pendrive o red) e instalarlo con:
rem   sudo apt install ./observatorio-angostura_<version>_arm64.deb
rem Opciones: --version 1.0.1   --descargar (renueva las librerias de Python)
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" (
    echo El entorno virtual no existe. Ejecuta primero scripts\lanzadores_windows\instalar_windows.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -X utf8 scripts\jetson\construir_paquete.py %*
explorer dist
pause
