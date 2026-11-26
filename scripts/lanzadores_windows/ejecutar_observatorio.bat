@echo off
setlocal
rem ==========================================================
rem  Observatorio completo: kiosco (Pantalla 1), pantalla tactil
rem  (Pantalla 2: catalogo y trivia) y portal de administracion.
rem
rem  CONFIGURACION (editar aqui)
rem  Numeros de monitor de Windows: ejecutar detectar_pantallas.bat
rem  Vacio = automatico: kiosco en el monitor principal y pantalla
rem  tactil en el otro (lo normal en el Centro, con 2 monitores).
rem ==========================================================
set "MONITOR_KIOSCO="
set "MONITOR_TACTIL="
rem si = el kiosco ocupa todo su monitor (F11 alterna, Esc sale)
set "PANTALLA_COMPLETA=si"
rem si = el portal de administracion se abre desde OTROS computadores de la red,
rem      con el navegador en http://NOMBRE-DE-ESTE-PC:5000 (ver_enlace_portal.bat).
rem      Antes, ejecutar UNA VEZ habilitar_portal_en_red.bat (pide permisos de administrador).
rem no = el portal solo se abre desde este mismo PC (http://127.0.0.1:5000).
set "PORTAL_EN_RED=si"
rem ==========================================================

cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" (
    echo El entorno virtual no existe. Ejecuta primero scripts\lanzadores_windows\instalar_windows.bat
    pause
    exit /b 1
)
set "OPCIONES="
if defined MONITOR_KIOSCO set "OPCIONES=%OPCIONES% --monitor-kiosco %MONITOR_KIOSCO%"
if defined MONITOR_TACTIL set "OPCIONES=%OPCIONES% --monitor-tactil %MONITOR_TACTIL%"
if /i "%PANTALLA_COMPLETA%"=="si" set "OPCIONES=%OPCIONES% --pantalla-completa"
set "HOST_PORTAL=127.0.0.1"
if /i "%PORTAL_EN_RED%"=="si" set "HOST_PORTAL=0.0.0.0"

rem Portal de administracion en segundo plano, salvo que ya este abierto
netstat -ano | findstr /r /c:":5000 .*LISTENING" >nul
if errorlevel 1 start "Portal de administracion" /min ".venv\Scripts\python.exe" main_admin.py --sin-navegador --host %HOST_PORTAL%

rem Kiosco y pantalla tactil. Las opciones agregadas al ejecutar (%%*) reemplazan a las de arriba.
".venv\Scripts\python.exe" main_kiosco.py %OPCIONES% %*
if errorlevel 1 pause
