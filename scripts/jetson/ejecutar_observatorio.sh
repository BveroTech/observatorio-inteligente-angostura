#!/usr/bin/env bash
# ==========================================================
# Observatorio completo en el Jetson (equivale a ejecutar_observatorio.bat):
# kiosco (Pantalla 1), pantalla táctil (Pantalla 2: catálogo y trivia) y, si no
# está corriendo como servicio, el portal de administración.
#
#   scripts/jetson/ejecutar_observatorio.sh                 cámara según config/settings.py
#   scripts/jetson/ejecutar_observatorio.sh --fuente video  video de demostración
#
# Las opciones agregadas al ejecutar reemplazan a las de abajo.
# Los monitores se eligen en config/pantallas.conf (SALIDA_KIOSCO, SALIDA_TACTIL).
#
# CONFIGURACIÓN (editar aquí)
# ==========================================================
# si = el kiosco ocupa todo su monitor (F11 alterna, Esc sale)
PANTALLA_COMPLETA="si"
# si = el portal se abre desde OTROS computadores de la red (http://NOMBRE-DEL-JETSON:5000)
PORTAL_EN_RED="si"
# si = aplica config/pantallas.conf (xrandr y paneles táctiles) antes de abrir
CONFIGURAR_PANTALLAS="si"
# ==========================================================
set -u
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ" || exit 1
export DISPLAY="${DISPLAY:-:0}"
PY="$RAIZ/.venv/bin/python"
if [ ! -x "$PY" ]; then
    echo "El entorno virtual no existe. Ejecuta primero scripts/jetson/instalar.sh"
    exit 1
fi

[ "$CONFIGURAR_PANTALLAS" = "si" ] && bash "$RAIZ/scripts/jetson/configurar_pantallas.sh" >/dev/null

# Portal: lo normal en el Jetson es el servicio observatorio-admin (systemd). Si
# no hay nada escuchando en el puerto 5000, se abre aquí en segundo plano.
if ! ss -ltn 2>/dev/null | grep -q ':5000 '; then
    HOST="127.0.0.1"; [ "$PORTAL_EN_RED" = "si" ] && HOST="0.0.0.0"
    nohup "$PY" main_admin.py --sin-navegador --host "$HOST" >"$RAIZ/data/portal.log" 2>&1 &
    echo "Portal de administración iniciado (registro en data/portal.log)"
fi

OPCIONES=()
[ "$PANTALLA_COMPLETA" = "si" ] && OPCIONES+=(--pantalla-completa)
exec "$PY" main_kiosco.py "${OPCIONES[@]}" "$@"
