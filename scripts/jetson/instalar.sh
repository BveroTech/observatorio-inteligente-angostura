#!/usr/bin/env bash
# ==========================================================
# Instalación del Observatorio en NVIDIA Jetson Orin Nano (JetPack 6.x).
# Ejecutar como el usuario que usará el kiosco (NO como root; pide sudo cuando hace falta):
#
#   bash scripts/jetson/instalar.sh                          instala todo y los servicios
#   bash scripts/jetson/instalar.sh --sin-servicios          sin systemd (pruebas)
#   bash scripts/jetson/instalar.sh --rendimiento-maximo N   además fija el modo de energía N
#                                                            y jetson_clocks al arrancar
#                                                            (N: ver "sudo nvpmodel -q" y LEEME_JETSON.md)
# ==========================================================
set -u
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$RAIZ" || exit 1
SERVICIOS="si"; MODO_ENERGIA=""
while [ $# -gt 0 ]; do
    case "$1" in
        --sin-servicios) SERVICIOS="no" ;;
        --rendimiento-maximo) MODO_ENERGIA="${2:-}"; shift ;;
        *) echo "Opción desconocida: $1"; exit 1 ;;
    esac
    shift
done
[ "$(id -u)" -eq 0 ] && { echo "[ERROR] Ejecuta este script como el usuario del kiosco, no como root."; exit 1; }

paso() { echo; echo "== $* =="; }
falla() { echo "[ERROR] $*"; exit 1; }

paso "Equipo"
if [ -f /etc/nv_tegra_release ]; then head -1 /etc/nv_tegra_release; else echo "[AVISO] No es un Jetson (/etc/nv_tegra_release no existe)."; fi
uname -m
python3 --version || falla "No hay python3."

paso "Paquetes del sistema (apt)"
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip python3-tk x11-xserver-utils xinput fontconfig \
    gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad || falla "apt-get no pudo instalar los paquetes."

paso "OpenCV de JetPack (con GStreamer)"
if python3 -c "import cv2" 2>/dev/null; then
    python3 -c "import cv2, re; i = cv2.getBuildInformation(); print('OpenCV', cv2.__version__, '| GStreamer:', 'SI' if re.search(r'GStreamer:\s+YES', i) else 'NO')"
else
    echo "[AVISO] El Python del sistema no tiene OpenCV. En JetPack se instala con el SDK"
    echo "        (sudo apt install nvidia-jetpack, o el componente OpenCV en SDK Manager)."
    echo "        Sin él no hay video. Vuelve a ejecutar este script después."
fi
gst-inspect-1.0 nvv4l2decoder >/dev/null 2>&1 && echo "Decodificador por hardware nvv4l2decoder: disponible" \
    || echo "[AVISO] GStreamer no encuentra nvv4l2decoder (decodificación por hardware)."

paso "Entorno virtual .venv (con los paquetes del sistema: OpenCV y TensorRT de JetPack)"
if [ -d .venv ] && ! .venv/bin/python -c "import sys" 2>/dev/null; then
    echo ".venv no funciona en este equipo (¿copiado desde Windows?); se vuelve a crear."
    rm -rf .venv
fi
[ -d .venv ] || python3 -m venv --system-site-packages .venv || falla "No se pudo crear .venv"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-jetson.txt || falla "pip no pudo instalar requirements-jetson.txt"
bash scripts/jetson/instalar_onnxruntime.sh "$RAIZ/.venv/bin/python" || falla "No se pudo instalar ONNX Runtime"

paso "Fuentes Montserrat (para que la interfaz se vea igual que en Windows)"
mkdir -p "$HOME/.local/share/fonts"
cp -u assets/fuentes/*.ttf "$HOME/.local/share/fonts/" 2>/dev/null && fc-cache -f >/dev/null && echo "Fuentes instaladas."

paso "Base de datos"
.venv/bin/python scripts/cli_admin/crear_base_datos.py || falla "No se pudo preparar la base de datos."
chmod +x scripts/jetson/*.sh

paso "Verificación"
.venv/bin/python - <<'PY'
import re, sqlite3, sys
print("Python", sys.version.split()[0])
print("SQLite", sqlite3.sqlite_version, "(OK)" if tuple(map(int, sqlite3.sqlite_version.split("."))) >= (3, 35) else "(se necesita >= 3.35)")
try:
    import cv2
    print("OpenCV", cv2.__version__, "| GStreamer:", "SI" if re.search(r"GStreamer:\s+YES", cv2.getBuildInformation()) else "NO")
except Exception as e:
    print("OpenCV: ERROR", e)
try:
    import onnxruntime as ort
    print("ONNX Runtime", ort.__version__, "| proveedores:", ", ".join(ort.get_available_providers()))
except Exception as e:
    print("ONNX Runtime: ERROR", e)
for modulo in ("tkinter", "customtkinter", "pygame", "flask", "waitress", "numpy"):
    try:
        m = __import__(modulo)
        print(modulo, getattr(m, "__version__", getattr(m, "TkVersion", "ok")))
    except Exception as e:
        print(modulo, ": ERROR", e)
PY

if command -v ufw >/dev/null && sudo ufw status | grep -q "Status: active"; then
    paso "Firewall (ufw activo): se abre el puerto 5000 del portal"
    sudo ufw allow 5000/tcp
fi

if [ "$SERVICIOS" = "si" ]; then
    paso "Servicios systemd"
    sed -e "s#__USUARIO__#$(id -un)#g" -e "s#__RAIZ__#$RAIZ#g" scripts/jetson/systemd/observatorio-admin.service \
        | sudo tee /etc/systemd/system/observatorio-admin.service >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable --now observatorio-admin.service && echo "Portal: servicio observatorio-admin activo."
    mkdir -p "$HOME/.config/systemd/user"
    sed -e "s#__RAIZ__#$RAIZ#g" scripts/jetson/systemd/observatorio-kiosco.service \
        > "$HOME/.config/systemd/user/observatorio-kiosco.service"
    systemctl --user daemon-reload
    systemctl --user enable observatorio-kiosco.service && echo "Kiosco: arrancará con la sesión gráfica."
    if [ -n "$MODO_ENERGIA" ]; then
        sed -e "s#__MODO__#$MODO_ENERGIA#g" scripts/jetson/systemd/observatorio-rendimiento.service \
            | sudo tee /etc/systemd/system/observatorio-rendimiento.service >/dev/null
        sudo systemctl daemon-reload
        sudo systemctl enable observatorio-rendimiento.service && echo "Modo de energía $MODO_ENERGIA + jetson_clocks al arrancar."
    fi
    echo
    echo "Falta activar el INICIO DE SESIÓN AUTOMÁTICO del usuario $(id -un) (el kiosco vive en su sesión gráfica):"
    echo "  Configuración > Usuarios > Inicio de sesión automático, o en /etc/gdm3/custom.conf:"
    echo "    AutomaticLoginEnable=true"
    echo "    AutomaticLogin=$(id -un)"
fi

paso "Siguiente"
echo "1. Monitores:   bash scripts/jetson/configurar_pantallas.sh --listar   y completar config/pantallas.conf"
echo "2. Usuario del portal:  .venv/bin/python scripts/cli_admin/crear_usuario.py"
echo "3. Probar:      bash scripts/jetson/ejecutar_observatorio.sh --fuente video"
echo "4. Medir:       .venv/bin/python scripts/jetson/medir.py --minutos 10 --fuente video"
.venv/bin/python main_admin.py --mostrar-enlace
