@echo off
setlocal
rem ==========================================================
rem  Se ejecuta UNA SOLA VEZ en el PC del kiosco, como administrador.
rem  Abre el puerto 5000 del firewall de Windows (solo redes privadas
rem  o de dominio) para entrar al portal de administracion desde otros
rem  computadores de la red con el navegador.
rem  Para quitarlo:  habilitar_portal_en_red.bat quitar
rem ==========================================================
set "REGLA=Observatorio Aves - Portal admin (TCP 5000)"

net session >nul 2>&1
if errorlevel 1 (
    echo Se necesitan permisos de administrador. Acepta el aviso de Windows...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    exit /b
)
cd /d "%~dp0..\.."

netsh advfirewall firewall delete rule name="%REGLA%" >nul 2>&1
if /i "%~1"=="quitar" (
    echo Regla del firewall eliminada: el portal ya no se abre desde otros computadores.
    pause
    exit /b 0
)
netsh advfirewall firewall add rule name="%REGLA%" dir=in action=allow protocol=TCP localport=5000 profile=private,domain >nul
if errorlevel 1 (
    echo [ERROR] No se pudo crear la regla del firewall.
    pause
    exit /b 1
)
echo Firewall: puerto 5000 abierto para redes privadas y de dominio.
echo.
powershell -NoProfile -Command "$p = Get-NetConnectionProfile | Where-Object { $_.IPv4Connectivity -ne 'Disconnected' }; foreach ($r in $p) { if ($r.NetworkCategory -eq 'Public') { Write-Host ('[AVISO] La red ' + $r.Name + ' esta como PUBLICA: el portal no se vera desde otros equipos.'); Write-Host '        Cambiala a privada: Configuracion > Red e Internet > Ethernet o Wi-Fi > Perfil de red: Privada.' } else { Write-Host ('Red ' + $r.Name + ': ' + $r.NetworkCategory + ' (correcto)') } }"
echo.
if exist ".venv\Scripts\python.exe" ".venv\Scripts\python.exe" -X utf8 main_admin.py --mostrar-enlace
echo.
echo El portal queda abierto a la red cuando se inicia ejecutar_observatorio.bat (PORTAL_EN_RED=si).
echo Si Windows pregunta si permite que Python use la red, elige "Permitir" en redes privadas.
pause
