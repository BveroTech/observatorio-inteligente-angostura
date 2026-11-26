@echo off
setlocal
rem ==========================================================
rem  Sistema completo SIN CAMARA: el video de aves que se reproduzca
rem  en MONITOR_CAMARA se analiza como si fuera la camara del humedal.
rem  Lo detectado queda marcado como simulacion (no cuenta en las
rem  estadisticas reales).
rem
rem  CONFIGURACION DE PANTALLAS (editar aqui)
rem  Numeros de monitor de Windows: ejecutar detectar_pantallas.bat
rem  Los tres deben ser monitores distintos.
rem ==========================================================
set "MONITOR_KIOSCO=1"
set "MONITOR_TACTIL=2"
set "MONITOR_CAMARA=4"
rem ==========================================================

cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" (
    echo El entorno virtual no existe. Ejecuta primero scripts\lanzadores_windows\instalar_windows.bat
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import mss, dxcam" 2>nul || ".venv\Scripts\python.exe" -m pip install -q mss dxcam
call "%~dp0ejecutar_observatorio.bat" --fuente pantalla --monitor %MONITOR_CAMARA% --monitor-kiosco %MONITOR_KIOSCO% --monitor-tactil %MONITOR_TACTIL% %*
