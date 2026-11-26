#!/bin/bash
# ==========================================================
# Instala ONNX Runtime en el entorno del Observatorio eligiendo la versión que
# corresponde a ESTE Jetson (versión de Python y de CUDA de su JetPack).
# Lo usan el paquete .deb (postinst) e instalar.sh.
#
#   bash instalar_onnxruntime.sh <python-del-venv> [carpeta-de-librerías-incluidas]
#
# Orden de intento (se detiene en el primero que instala):
#   1. onnxruntime-gpu incluido en el paquete para esta CUDA y este Python (sin internet)
#   2. onnxruntime-gpu del índice de Jetson AI Lab para esta CUDA (con internet)
#   3. onnxruntime-gpu de PyPI (solo CUDA 13: esas versiones se compilan para CUDA 13)
#   4. onnxruntime de CPU (incluido o de PyPI). Funciona, pero sin GPU: avisa.
# Nunca falla por esto: el programa ya elige TensorRT -> CUDA -> CPU según lo que haya.
# ==========================================================
set -u
PY="${1:?Falta la ruta del python del entorno}"
LIBS="${2:-}"
PIP=("$PY" -m pip install --disable-pip-version-check -q)

VERSION_PY="$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
L4T="$(sed -n 's/^# R\([0-9]*\) .*/\1/p' /etc/nv_tegra_release 2>/dev/null | head -1)"
CUDA=""
if [ -f /usr/local/cuda/version.json ]; then
    CUDA="$(sed -n 's/.*"cuda"[^}]*"version" *: *"\([0-9]*\)\..*/\1/p' /usr/local/cuda/version.json | head -1)"
fi
[ -z "$CUDA" ] && command -v nvcc >/dev/null && CUDA="$(nvcc --version | sed -n 's/.*release \([0-9]*\)\..*/\1/p')"
[ -z "$CUDA" ] && [ -x /usr/local/cuda/bin/nvcc ] && CUDA="$(/usr/local/cuda/bin/nvcc --version | sed -n 's/.*release \([0-9]*\)\..*/\1/p')"
if [ -z "$CUDA" ]; then   # sin CUDA detectada: se deduce de la versión de Jetson Linux
    case "$L4T" in 36) CUDA=12 ;; 38|39|40) CUDA=13 ;; esac
fi
echo "Python $VERSION_PY · Jetson Linux R${L4T:-?} · CUDA ${CUDA:-no detectada}"

case "$CUDA" in
    12) CARPETA="jp6-cu126"; INDICE="https://pypi.jetson-ai-lab.io/jp6/cu126" ;;
    13) CARPETA="jp7-cu130"; INDICE="https://pypi.jetson-ai-lab.io/sbsa/cu130" ;;
    *)  CARPETA=""; INDICE="" ;;
esac

quitar() { "$PY" -m pip uninstall -y -q "$@" >/dev/null 2>&1 || true; }
instalado_ok() { "$PY" -c "import onnxruntime" 2>/dev/null; }

if [ -n "$CARPETA" ]; then
    quitar onnxruntime
    if [ -n "$LIBS" ] && [ -d "$LIBS/onnxruntime/$CARPETA" ] \
        && "${PIP[@]}" --no-index --find-links "$LIBS/onnxruntime/$CARPETA" --find-links "$LIBS/comunes" onnxruntime-gpu 2>/dev/null \
        && instalado_ok; then
        echo "onnxruntime-gpu: incluido en el paquete ($CARPETA)."
    elif "${PIP[@]}" --extra-index-url "$INDICE" onnxruntime-gpu "numpy<2" && instalado_ok; then
        echo "onnxruntime-gpu: descargado de $INDICE."
    elif [ "$CUDA" = "13" ] && "${PIP[@]}" onnxruntime-gpu "numpy<2" && instalado_ok; then
        echo "onnxruntime-gpu: descargado de PyPI (CUDA 13)."
    else
        echo "[AVISO] No hay onnxruntime-gpu para Python $VERSION_PY con CUDA $CUDA."
    fi
fi

if ! instalado_ok; then
    quitar onnxruntime-gpu
    if { [ -n "$LIBS" ] && "${PIP[@]}" --no-index --find-links "$LIBS/onnxruntime/cpu" --find-links "$LIBS/comunes" onnxruntime 2>/dev/null; } \
        || "${PIP[@]}" onnxruntime "numpy<2"; then
        echo "[AVISO] Se instaló ONNX Runtime de CPU: la IA funciona, pero sin la GPU (más lenta)."
    else
        echo "[ERROR] No se pudo instalar ONNX Runtime."
        exit 1
    fi
fi

# Comprobación real: abre el detector con CUDA y muestra qué proveedor queda en uso.
# (TensorRT no se prueba aquí: su primera compilación tarda minutos y la hace el programa.)
MODELO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/modelos/detector_aves.onnx"
"$PY" - "$MODELO" <<'PY' || true
import sys
import onnxruntime as ort
disponibles = ort.get_available_providers()
print("ONNX Runtime", ort.__version__, "| compilado con:", ", ".join(disponibles))
if "CUDAExecutionProvider" in disponibles:
    try:
        sesion = ort.InferenceSession(sys.argv[1], providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
        en_uso = sesion.get_providers()[0]
        print("Prueba con el detector: proveedor en uso =", en_uso)
        if en_uso != "CUDAExecutionProvider":
            print("[AVISO] CUDA no se pudo usar (¿faltan CUDA/cuDNN de JetPack? sudo apt install nvidia-jetpack)")
    except Exception as error:
        print("[AVISO] Prueba con CUDA fallida:", error)
PY
exit 0
