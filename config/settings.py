"""
Parámetros del Observatorio Inteligente de Aves (Parque Angostura).

Soporta ejecución directa desde código fuente y ejecución empaquetada (.exe)
mediante PyInstaller utilizando `sys._MEIPASS` para recursos de solo lectura
y el directorio del ejecutable para datos persistentes.
"""
import json
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path

# ==========================================================
# PLATAFORMA
# ==========================================================
# Desarrollo en Windows; producción en NVIDIA Jetson Orin Nano (JetPack 6,
# Ubuntu 22.04 ARM64, Python 3.10). El código es el mismo en ambas.
ES_WINDOWS = platform.system().lower() == "windows"
ES_LINUX = platform.system().lower() == "linux"
ES_JETSON = ES_LINUX and platform.machine() == "aarch64" and Path("/etc/nv_tegra_release").exists()

# ==========================================================
# RESOLUCIÓN DINÁMICA DE RUTAS (SOPORTE PYINSTALLER _MEIPASS)
# ==========================================================

ES_EMPAQUETADO = bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))

BASE_DIR = (
    Path(sys.executable).resolve().parent
    if ES_EMPAQUETADO
    else Path(__file__).resolve().parent.parent
)
RECURSOS_DIR = (
    Path(getattr(sys, "_MEIPASS", BASE_DIR)).resolve()
    if ES_EMPAQUETADO
    else BASE_DIR
)


def obtener_ruta_recurso(ruta_relativa):
    """
    Resuelve un recurso estático o de solo lectura (modelos ONNX, assets, semillas,
    plantillas web). Prioriza archivos locales junto al ejecutable para permitir
    reemplazos en terreno y cae en `sys._MEIPASS` cuando está empaquetado.
    """
    rel = Path(ruta_relativa)
    if rel.is_absolute():
        return rel
    candidato_local = BASE_DIR / rel
    if candidato_local.exists():
        return candidato_local
    return RECURSOS_DIR / rel


def obtener_ruta_datos(ruta_relativa):
    """
    Resuelve rutas de lectura/escritura (base de datos SQLite, capturas, JSON,
    clave secreta) siempre relativas a `BASE_DIR` para evitar errores de escritura
    en directorios temporales de `sys._MEIPASS`.
    """
    rel = Path(ruta_relativa)
    if rel.is_absolute():
        return rel
    return BASE_DIR / rel


# ==========================================================
# RUTAS DE DATOS, MODELOS Y ACTIVOS
# ==========================================================

CARPETA_DATOS = obtener_ruta_datos("data")
CARPETA_CAPTURAS = obtener_ruta_datos("data/capturas")
CARPETA_CACHE_TENSORRT = obtener_ruta_datos("data/cache_tensorrt")
# Salidas de video y paneles táctiles en Linux/Jetson (lo leen el programa y
# scripts/jetson/configurar_pantallas.sh). Ver config/pantallas.conf.
ARCHIVO_PANTALLAS = BASE_DIR / "config" / "pantallas.conf"
# Recortes de aves que el modelo no reconoce, para identificarlas en el portal.
CARPETA_POR_IDENTIFICAR = obtener_ruta_datos("data/por_identificar")
CARPETA_SECRETOS = obtener_ruta_datos("data/secretos")
CARPETA_SEMILLAS = obtener_ruta_recurso("data/semillas")

CARPETA_MODELOS = obtener_ruta_recurso("modelos")
CARPETA_ASSETS = obtener_ruta_recurso("assets")
CARPETA_FOTOS = obtener_ruta_datos("assets/fotos") if not ES_EMPAQUETADO else obtener_ruta_recurso("assets/fotos")
CARPETA_SONIDOS = obtener_ruta_datos("assets/sonidos") if not ES_EMPAQUETADO else obtener_ruta_recurso("assets/sonidos")
CARPETA_VIDEOS = obtener_ruta_recurso("assets/videos")
CARPETA_FUENTES = obtener_ruta_recurso("assets/fuentes")
CARPETA_SONIDOS_SIMULADOR = obtener_ruta_recurso("laboratorio_ia/simulador_pantalla2/sonidos")
CARPETA_WEB = obtener_ruta_recurso("web")

ARCHIVO_BASE_DATOS = CARPETA_DATOS / "observatorio.db"
ARCHIVO_AVES_HOY = CARPETA_DATOS / "aves_hoy.json"
ARCHIVO_PUENTE_TRIVIA = ARCHIVO_AVES_HOY
ARCHIVO_CLAVE_SECRETA = CARPETA_SECRETOS / "clave_secreta.txt"

ARCHIVO_CATALOGO = CARPETA_SEMILLAS / "catalogo_aves_chile.csv"
ARCHIVO_EXCEL_AVES = CARPETA_SEMILLAS / "base_datos_aves_chile.xlsx"
ARCHIVO_CLASES_MODELO = obtener_ruta_recurso("config/clases_modelo.json")

# Modelos ONNX (se generan con exportar_modelos.bat).
MODELO_DETECTOR = CARPETA_MODELOS / "detector_aves.onnx"
MODELO_CLASIFICADOR = CARPETA_MODELOS / "clasificador_aves.onnx"

# ==========================================================
# IDIOMAS: fichas en español, inglés y alemán
# ==========================================================
# Las fichas se escriben en español; al guardarlas en el portal se traducen
# solas al inglés y al alemán (sin internet) y se pueden corregir a mano.
# En la pantalla táctil el visitante elige el idioma.
# Modelos: scripts/cli_admin/descargar_modelos_idiomas.py
IDIOMAS = {"es": "Español", "en": "English", "de": "Deutsch"}
IDIOMA_ORIGINAL = "es"
TRADUCIR_AL_GUARDAR = True
CARPETA_TRADUCCION = CARPETA_MODELOS / "traduccion"
# Lector de fichas técnicas (OCR) con Tesseract. Idiomas en modelos/tessdata.
CARPETA_TESSDATA = CARPETA_MODELOS / "tessdata"
# Lectura en voz alta de la ficha (botón «Leer ficha» de la pantalla táctil), sin
# internet, con voces Piper en modelos/voces (descargar_modelos_idiomas.py).
CARPETA_VOCES = CARPETA_MODELOS / "voces"
VOCES = {
    "es": "es_MX-claude-high",
    "en": "en_US-lessac-medium",
    "de": "de_DE-thorsten-medium",
}
# Ruta de tesseract.exe; vacío = se busca solo (variable TESSERACT_CMD, carpeta
# tesseract/ junto al programa, C:\Program Files\Tesseract-OCR, PATH).
TESSERACT_CMD = ""

# ==========================================================
# FUENTE DE VIDEO
# ==========================================================
#
# "rtsp"    cámara IP del humedal (operación normal).
# "camara"  cámara USB o integrada, para desarrollo.
# "video"   archivo de video en bucle, para desarrollo y presentaciones.
# "pantalla" captura un monitor del PC, para probar sin cámara con videos
#           de aves reproducidos en pantalla (ver probar_con_pantalla.bat).
#
# La URL RTSP con usuario y contraseña NO se escribe aquí: se lee de la
# variable de entorno OBSERVATORIO_RTSP_URL o del archivo
# config/camara_local.json ({"rtsp_url": "rtsp://..."}), que no se comparte.

FUENTE_VIDEO = "camara"
INDICE_CAMARA = 0
# Monitor que se captura con FUENTE_VIDEO = "pantalla" (1, 2, 3…).
MONITOR_CAPTURA = 1
# FUENTE_VIDEO = "ventana": captura la ventana de UNA aplicación (solo Windows), elegida
# por su programa (p. ej. "chrome.exe") y, si se quiere, un texto de su título ("YouTube").
VENTANA_PROGRAMA = ""
VENTANA_TITULO = ""
# Backend de la cámara USB en Windows: "auto" prueba DirectShow y Media
# Foundation y se queda con el que entrega imagen real (no negra) más rápido.
# Si la imagen sale negra o lenta, se puede fijar "dshow" o "msmf".
BACKEND_CAMARA = "auto"


def _resolver_video_demo():
    """Resuelve la ruta del video de demostración soportando assets/videos/ y assets/video/."""
    for ruta_rel in ("assets/videos/demo.mp4", "assets/video/demo.mp4"):
        candidato = obtener_ruta_recurso(ruta_rel)
        if candidato.exists():
            return candidato
    return CARPETA_ASSETS / "videos" / "demo.mp4"


VIDEO_DESARROLLO = _resolver_video_demo()
VIDEO_DEMOSTRACION = _resolver_video_demo()

# Segundos sin cuadros válidos antes de pasar a Modo Demostración.
SEGUNDOS_FAILOVER = 5

# Cada cuántos segundos se intenta reconectar la cámara mientras dura el
# Modo Demostración, y cuántas lecturas correctas seguidas se exigen para
# volver a la cámara.
SEGUNDOS_ENTRE_RECONEXIONES = 10
LECTURAS_PARA_VOLVER = 5

# Tiempos máximos de apertura y lectura del stream RTSP (milisegundos).
RTSP_TIMEOUT_MS = 5000

# RTSP por GStreamer con decodificación por hardware (NVDEC) en el Jetson:
#   "auto" = GStreamer si es un Jetson y OpenCV tiene GStreamer; si no, FFmpeg.
#   "si" / "no" para forzarlo.
# CODEC_RTSP: códec de la cámara IP ("h264" o "h265"; las Dahua permiten ambos,
# se ve en la configuración web de la cámara > Video > Codificación).
RTSP_GSTREAMER = "auto"
CODEC_RTSP = "h264"
LATENCIA_RTSP_MS = 200

ANCHO_CAMARA = 1280
ALTO_CAMARA = 720


def url_rtsp():
    """URL de la cámara IP, desde variable de entorno o archivo local."""
    url = os.environ.get("OBSERVATORIO_RTSP_URL", "").strip()
    if url:
        return url
    archivo = obtener_ruta_recurso("config/camara_local.json")
    try:
        with open(archivo, "r", encoding="utf-8") as datos:
            return str(json.load(datos).get("rtsp_url", "")).strip()
    except (FileNotFoundError, json.JSONDecodeError, AttributeError, OSError):
        return ""


# ==========================================================
# INFERENCIA (ONNX Runtime)
# ==========================================================

TAMANO_ENTRADA_DETECTOR = 640

# Confianza mínima para aceptar una identificación (0.0 a 1.0).
UMBRAL_CONFIANZA = 0.70

# Confianza mínima del detector cuando solo localiza "ave" y la especie la
# decide el clasificador (modo de dos etapas).
UMBRAL_DETECCION_AVE = 0.25

# Lado mínimo, en píxeles del cuadro original (120x120 px), para clasificar un ave.
# Las detecciones más pequeñas se descartan y se cuentan en las métricas.
TAMANO_MINIMO_PX = 120

UMBRAL_IOU_NMS = 0.45
UMBRAL_IOA_CONTENCION = 0.60

# ==========================================================
# CONFIRMACIÓN Y REGISTRO
# ==========================================================

# Confirma una especie con cinco votos en los últimos ocho cuadros de la pista.
CUADROS_PARA_CONFIRMAR = 5
VENTANA_CONFIRMACION = 8

# Segundos que una secuencia sigue viva sin volver a verse.
SEGUNDOS_SIN_VER_TRACK = 1.5

# Una misma especie se registra como máximo una vez dentro de esta ventana.
SEGUNDOS_ENTRE_AVISTAMIENTOS = 60

# Aves por identificar: si un ave se sigue al menos CUADROS_PARA_CONFIRMAR
# cuadros sin que el modelo la reconozca (confianza bajo el umbral o especie
# sin ficha), se guarda UN recorte de esa ave para identificarla en el portal
# (menú «Por identificar»). Lo identificado se suma al entrenamiento con
# laboratorio_ia/scripts_entrenamiento/importar_identificadas.py.
GUARDAR_AVES_DESCONOCIDAS = True
SEGUNDOS_ENTRE_DESCONOCIDAS = 20    # entre dos registros (evita guardar la misma bandada mil veces)
MAXIMO_DESCONOCIDAS_DIA = 300       # tope diario para no llenar el disco

# Las miniaturas del panel lateral se retiran tras este tiempo sin verse.
SEGUNDOS_AUTOLIMPIEZA_PANEL = 60

# Cada cuántos segundos se guarda una fila en METRICA_SISTEMA.
SEGUNDOS_ENTRE_METRICAS = 60

# ==========================================================
# PANTALLAS
# ==========================================================

# "auto": la segunda pantalla se abre en el segundo monitor si existe.
# "ventana": se abre en el monitor principal en modo kiosco.
# "no": no se abre.
PANTALLA_2 = "auto"

# Monitor de cada pantalla. Se configuran en los lanzadores de
# scripts/lanzadores_windows/ (ejecutar_observatorio.bat y
# probar_sistema_con_pantalla.bat); detectar_pantallas.bat muestra los números.
# Estos valores solo se usan si se ejecuta main_kiosco.py directamente.
# None = automático: kiosco en el monitor principal y Pantalla 2 en el otro.
MONITOR_KIOSCO = None
MONITOR_PANTALLA_2 = None

# Tiempo máximo de inactividad táctil (segundos) en la Pantalla 2 antes de
# cerrar fichas/búsquedas y regresar automáticamente al Menú de Inicio.
SEGUNDOS_INACTIVIDAD_PANTALLA2 = 60

# Pantalla completa del kiosco (F11 alterna, Esc sale).
KIOSCO_PANTALLA_COMPLETA = False

# Video del kiosco: True = la imagen llena todo el recuadro (recorta un poco
# los costados si la proporción no calza); False = imagen completa con franjas.
VIDEO_LLENAR_RECUADRO = True

# Cuadros por segundo del video en el kiosco. El video se muestra a esta
# velocidad aunque la IA analice menos cuadros (los recuadros se actualizan
# al ritmo de la IA). También es el máximo de la captura de pantalla.
FPS_VIDEO = 30

# Hilos de CPU que usa la IA (ONNX Runtime). 0 = todos los núcleos: la IA va
# un poco más rápido pero el video del kiosco pierde fluidez. Por defecto usa
# la mitad de los núcleos lógicos y deja el resto para el video y la interfaz.
HILOS_IA = max(1, (os.cpu_count() or 2) // 2)

# ONNX Runtime con GPU en el Jetson: TensorRT -> CUDA -> CPU (el primero que
# funcione). TensorRT compila un motor optimizado la PRIMERA vez que abre cada
# modelo (puede tardar minutos) y lo guarda en CARPETA_CACHE_TENSORRT para los
# siguientes arranques. FP16 acelera en la GPU del Orin; tras activarlo conviene
# volver a evaluar el clasificador (evaluar_clasificador.py) en la placa.
USAR_TENSORRT = True
TENSORRT_FP16 = True

# Quita los bordes negros que algunas cámaras agregan alrededor de la imagen.
RECORTAR_BORDES_NEGROS = True

# La ficha modal se cierra sola tras este tiempo sin tocarla.
SEGUNDOS_CIERRE_FICHA = 90

# Especies foco del embalse Angostura (nombre científico del catálogo): son
# las que se entrenan en la IA y las del filtro «Especies del embalse» del
# catálogo.
ESPECIES_FOCO = [
    "Cygnus melancoryphus",     # Cisne de cuello negro
    "Leucophaeus pipixcan",     # Gaviota de Franklin
    "Podiceps major",           # Huala
    "Spatula platalea",         # Pato cuchara
    "Anas georgica",            # Pato jergón grande
    "Oxyura vittata",           # Pato rana de pico delgado
    "Fulica armillata",         # Tagua común
    "Nannopterum brasilianum",  # Yeco
    "Speculanas specularis",    # Pato anteojillo
    "Megaceryle torquata",      # Martín pescador
]

# ==========================================================
# PORTAL DE ADMINISTRACIÓN (Flask)
# ==========================================================

# "127.0.0.1": solo desde el PC anfitrión (decisión actual).
# "0.0.0.0": también desde otros equipos de la red local.
ADMIN_HOST = "127.0.0.1"
ADMIN_PUERTO = 5000

MINUTOS_SESION_ADMIN = 30
INTENTOS_LOGIN_MAXIMOS = 5
MINUTOS_BLOQUEO_LOGIN = 5
MAX_MB_ARCHIVO_SUBIDO = 10

# El kiosco abre el portal en segundo plano al iniciar (si no está abierto).
# En el código fuente lo hace ejecutar_observatorio.bat; en el ejecutable, el propio kiosco.
INICIAR_PORTAL_CON_KIOSCO = ES_EMPAQUETADO

# ==========================================================
# CONFIGURACIÓN EDITABLE SIN PROGRAMAR (config/observatorio.ini)
# ==========================================================
# En la versión instalada (ejecutable) estos valores se cambian en
# config/observatorio.ini, junto a Observatorio.exe, con el Bloc de notas.
# Si el archivo no existe (código fuente) se usan los valores de arriba.
# Plantilla: config/observatorio.ejemplo.ini

ARCHIVO_CONFIGURACION = obtener_ruta_datos("config/observatorio.ini")


def _aplicar_configuracion(ruta):
    import configparser

    lector = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    try:
        if not lector.read(ruta, encoding="utf-8-sig"):
            return
    except configparser.Error as error:
        print(f"[AVISO] {ruta} tiene un error y no se aplicó: {error}")
        return
    valores = globals()

    def texto(seccion, clave, nombre, opciones=None):
        valor = lector.get(seccion, clave, fallback="").strip()
        if valor and (opciones is None or valor.lower() in opciones):
            valores[nombre] = valor.lower() if opciones else valor

    def entero(seccion, clave, nombre, vacio_es_none=False):
        valor = lector.get(seccion, clave, fallback="").strip()
        if not valor:
            if vacio_es_none and lector.has_option(seccion, clave):
                valores[nombre] = None
            return
        try:
            valores[nombre] = int(valor)
        except ValueError:
            print(f"[AVISO] observatorio.ini: [{seccion}] {clave} debe ser un número ({valor!r}); se ignora.")

    def si_no(seccion, clave, nombre):
        valor = lector.get(seccion, clave, fallback="").strip().lower()
        if valor in ("si", "sí", "no", "true", "false", "1", "0"):
            valores[nombre] = valor in ("si", "sí", "true", "1")

    texto("camara", "fuente", "FUENTE_VIDEO", ("rtsp", "camara", "video", "pantalla", "ventana"))
    texto("camara", "ventana_programa", "VENTANA_PROGRAMA")
    texto("camara", "ventana_titulo", "VENTANA_TITULO")
    entero("camara", "indice_camara", "INDICE_CAMARA")
    entero("camara", "monitor_captura", "MONITOR_CAPTURA")
    texto("camara", "codec_rtsp", "CODEC_RTSP", ("h264", "h265"))
    entero("pantallas", "monitor_kiosco", "MONITOR_KIOSCO", vacio_es_none=True)
    entero("pantallas", "monitor_tactil", "MONITOR_PANTALLA_2", vacio_es_none=True)
    si_no("pantallas", "pantalla_completa", "KIOSCO_PANTALLA_COMPLETA")
    texto("pantallas", "pantalla_2", "PANTALLA_2", ("auto", "ventana", "no"))
    entero("pantallas", "fps_video", "FPS_VIDEO")
    if lector.has_option("portal", "en_red"):
        en_red = lector.get("portal", "en_red").strip().lower() in ("si", "sí", "true", "1")
        valores["ADMIN_HOST"] = "0.0.0.0" if en_red else "127.0.0.1"
    entero("portal", "puerto", "ADMIN_PUERTO")
    si_no("portal", "abrir_con_kiosco", "INICIAR_PORTAL_CON_KIOSCO")
    valor = lector.get("ia", "umbral_confianza", fallback="").strip().replace(",", ".")
    if valor:
        try:
            valores["UMBRAL_CONFIANZA"] = min(max(float(valor), 0.0), 1.0)
        except ValueError:
            print(f"[AVISO] observatorio.ini: umbral_confianza no válido ({valor!r}); se ignora.")
    si_no("ia", "guardar_aves_desconocidas", "GUARDAR_AVES_DESCONOCIDAS")


_aplicar_configuracion(ARCHIVO_CONFIGURACION)

# ==========================================================
# INICIALIZACIÓN DE DIRECTORIOS PERSISTENTES
# ==========================================================

for _carpeta in (
    CARPETA_DATOS,
    CARPETA_CAPTURAS,
    CARPETA_SECRETOS,
    obtener_ruta_datos("assets/fotos") if not ES_EMPAQUETADO else CARPETA_DATOS,
    obtener_ruta_datos("assets/sonidos") if not ES_EMPAQUETADO else CARPETA_DATOS,
    obtener_ruta_datos("assets/videos") if not ES_EMPAQUETADO else CARPETA_DATOS,
):
    try:
        _carpeta.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

if ES_EMPAQUETADO and not ARCHIVO_BASE_DATOS.exists():
    _bd_empacada = RECURSOS_DIR / "data" / "observatorio.db"
    if _bd_empacada.is_file():
        try:
            with tempfile.NamedTemporaryFile(dir=CARPETA_DATOS, suffix=".db.tmp", delete=False) as _archivo:
                _bd_temporal = Path(_archivo.name)
            try:
                shutil.copy2(_bd_empacada, _bd_temporal)
                # Publica la copia completa sin reemplazar la base de otro proceso.
                if os.name == "nt":
                    _bd_temporal.rename(ARCHIVO_BASE_DATOS)
                else:
                    os.link(_bd_temporal, ARCHIVO_BASE_DATOS)
            finally:
                _bd_temporal.unlink(missing_ok=True)
        except OSError:
            pass
