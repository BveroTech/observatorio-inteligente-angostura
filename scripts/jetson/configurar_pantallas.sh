#!/usr/bin/env bash
# ==========================================================
# Configura las dos pantallas del Observatorio en el Jetson (X11).
#
#   scripts/jetson/configurar_pantallas.sh            aplica config/pantallas.conf
#   scripts/jetson/configurar_pantallas.sh --listar   solo muestra salidas y paneles táctiles
#
# 1. Lista las salidas de video (xrandr). Con el hub DisplayPort MST, la única
#    salida DP del Jetson aparece como DOS salidas (p. ej. DP-1-1 y DP-1-2).
# 2. Pone el monitor del kiosco a la izquierda (principal) y el de la Pantalla 2
#    a su derecha, cada uno con su resolución.
# 3. Asigna cada panel táctil a su monitor (xinput map-to-output); sin esto,
#    un toque en la Pantalla 2 se repartiría sobre todo el escritorio.
# 4. Desactiva el protector de pantalla y el apagado del monitor (kiosco 24/7).
#
# Los nombres de salida y de paneles táctiles se configuran en
# config/pantallas.conf, no en este archivo. Requiere sesión gráfica X11
# (DISPLAY=:0); en Wayland xrandr/xinput no funcionan.
# ==========================================================
set -u
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONF="$RAIZ/config/pantallas.conf"
export DISPLAY="${DISPLAY:-:0}"

for comando in xrandr xinput; do
    command -v "$comando" >/dev/null || { echo "[ERROR] Falta $comando: sudo apt install x11-xserver-utils xinput"; exit 1; }
done
if [ "${XDG_SESSION_TYPE:-x11}" = "wayland" ]; then
    echo "[AVISO] La sesión es Wayland: xrandr y xinput no controlan las pantallas. Use 'Ubuntu on Xorg' al iniciar sesión."
fi

SALIDA_KIOSCO=""; SALIDA_TACTIL=""; RESOLUCION_KIOSCO="auto"; RESOLUCION_TACTIL="auto"
TACTIL_KIOSCO=""; TACTIL_PANTALLA2=""; DESACTIVAR_AHORRO_ENERGIA="si"
# shellcheck source=/dev/null
[ -f "$CONF" ] && . "$CONF"

conectadas=()
while read -r salida; do conectadas+=("$salida"); done < <(xrandr --query | awk '/ connected/{print $1}')

listar() {
    echo "Salidas de video conectadas:"
    xrandr --query | awk '/ connected/{print "   " $0}'
    echo
    echo "Monitores activos (lo que usa el programa):"
    xrandr --listmonitors | sed 's/^/   /'
    echo
    echo "Dispositivos de entrada (los paneles táctiles suelen llamarse ILITEK, eGalax, Goodix, Weida, 'Touch'...):"
    xinput list --name-only | sed 's/^/   /'
}

if [ "${1:-}" = "--listar" ]; then
    listar
    exit 0
fi

echo "Salidas conectadas: ${conectadas[*]:-ninguna}"
if [ "${#conectadas[@]}" -lt 2 ]; then
    echo "[AVISO] Hay menos de 2 salidas conectadas. Con el hub MST deberían verse dos (una por monitor)."
    echo "        Si solo aparece una, el hub podría estar en modo 'espejo' o el Jetson no lo maneja como MST:"
    echo "        revisar el hub y anotar el resultado (la opción A depende de esta prueba)."
fi
[ -z "$SALIDA_KIOSCO" ] && SALIDA_KIOSCO="${conectadas[0]:-}"
[ -z "$SALIDA_TACTIL" ] && SALIDA_TACTIL="${conectadas[1]:-}"

modo() { [ "$1" = "auto" ] && echo "--auto" || echo "--mode $1"; }

if [ -n "$SALIDA_KIOSCO" ]; then
    # shellcheck disable=SC2046
    if [ -n "$SALIDA_TACTIL" ] && [ "$SALIDA_TACTIL" != "$SALIDA_KIOSCO" ]; then
        xrandr --output "$SALIDA_KIOSCO" $(modo "$RESOLUCION_KIOSCO") --primary --pos 0x0 \
               --output "$SALIDA_TACTIL" $(modo "$RESOLUCION_TACTIL") --right-of "$SALIDA_KIOSCO" \
            && echo "Kiosco en $SALIDA_KIOSCO (principal, izquierda) · Pantalla 2 en $SALIDA_TACTIL (derecha)"
    else
        xrandr --output "$SALIDA_KIOSCO" $(modo "$RESOLUCION_KIOSCO") --primary --pos 0x0 \
            && echo "Kiosco en $SALIDA_KIOSCO (solo un monitor)"
    fi
fi

asignar_tactil() {   # $1 = nombre del panel en xinput, $2 = salida de video
    [ -z "$1" ] || [ -z "$2" ] && return 0
    if xinput list --name-only | grep -Fxq "$1"; then
        xinput map-to-output "$1" "$2" && echo "Panel táctil '$1' -> $2"
    else
        echo "[AVISO] No se encontró el panel táctil '$1' (ver: $0 --listar)"
    fi
}
asignar_tactil "$TACTIL_KIOSCO" "$SALIDA_KIOSCO"
asignar_tactil "$TACTIL_PANTALLA2" "$SALIDA_TACTIL"

if [ "$DESACTIVAR_AHORRO_ENERGIA" = "si" ]; then
    xset s off -dpms s noblank 2>/dev/null && echo "Protector de pantalla y apagado del monitor desactivados."
    command -v gsettings >/dev/null && {
        gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null
        gsettings set org.gnome.desktop.screensaver lock-enabled false 2>/dev/null
    }
fi
echo
xrandr --listmonitors
