@echo off
rem Construye la version instalable del Observatorio para Windows:
rem   dist\Instalar_Observatorio_<version>.exe   instalador (si Inno Setup 6 esta instalado)
rem   dist\Observatorio_<version>_portable.zip   la misma app sin instalador
rem   dist\Observatorio\                         carpeta con Observatorio.exe y Admin.exe
rem Opciones: --version 1.1.0   --incluir-base-datos (lleva el catalogo y usuarios de este PC)
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" (
    echo El entorno virtual no existe. Ejecuta primero scripts\lanzadores_windows\instalar_windows.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -X utf8 scripts\windows\construir_ejecutable.py %*
if not errorlevel 1 explorer dist
pause
