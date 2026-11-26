import logging
import os
import platform
import re
import threading
import time

# Transporte TCP para RTSP: más estable que UDP en redes con pérdidas.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from config.settings import (  # noqa: E402
    ALTO_CAMARA,
    ANCHO_CAMARA,
    BACKEND_CAMARA,
    CODEC_RTSP,
    ES_JETSON,
    LATENCIA_RTSP_MS,
    LECTURAS_PARA_VOLVER,
    RECORTAR_BORDES_NEGROS,
    RTSP_GSTREAMER,
    RTSP_TIMEOUT_MS,
    SEGUNDOS_ENTRE_RECONEXIONES,
    SEGUNDOS_FAILOVER,
    obtener_ruta_recurso,
)

registro = logging.getLogger("observatorio.video")


class RecorteBordes:
    UMBRAL = 12        # nivel de gris máximo que se considera "negro"
    CADA = 30
    MARGEN_MINIMO = 0.02

    def __init__(self):
        self.caja = None
        self.contador = 0

    def aplicar(self, cuadro):
        if self.contador % self.CADA == 0:
            self.caja = self._calcular(cuadro)
        self.contador += 1
        if self.caja is None:
            return cuadro
        x1, y1, x2, y2 = self.caja
        if y2 > cuadro.shape[0] or x2 > cuadro.shape[1]:
            self.caja = None
            return cuadro
        return cuadro[y1:y2, x1:x2]

    def _calcular(self, cuadro):
        alto, ancho = cuadro.shape[:2]
        gris = cv2.cvtColor(cuadro, cv2.COLOR_BGR2GRAY)[::2, ::2]
        filas = np.where(gris.max(axis=1) > self.UMBRAL)[0]
        columnas = np.where(gris.max(axis=0) > self.UMBRAL)[0]
        if len(filas) == 0 or len(columnas) == 0:
            return None
        y1, y2 = int(filas[0]) * 2, min(alto, (int(filas[-1]) + 1) * 2)
        x1, x2 = int(columnas[0]) * 2, min(ancho, (int(columnas[-1]) + 1) * 2)
        arriba, abajo, izquierda, derecha = y1, alto - y2, x1, ancho - x2
        if max(arriba, abajo) < alto * self.MARGEN_MINIMO and max(izquierda, derecha) < ancho * self.MARGEN_MINIMO:
            return None  # sin bordes
        if abs(arriba - abajo) > alto * 0.04 or abs(izquierda - derecha) > ancho * 0.04:
            return None  # no son franjas simétricas: probablemente la escena es oscura
        if (x2 - x1) * (y2 - y1) < 0.3 * ancho * alto:
            return None
        return (x1, y1, x2, y2)


def _probar_camara(captura, segundos=3.0):
    inicio = time.monotonic()
    leidos = con_imagen = 0
    while time.monotonic() - inicio < segundos and leidos < 15:
        correcto, cuadro = captura.read()
        if not correcto or cuadro is None:
            continue
        leidos += 1
        # Un cuadro "negro" (cámara tapada, ocupada o backend que falla) no
        # tiene ningún píxel claro.
        if int(cuadro.max()) > 25:
            con_imagen += 1
    transcurrido = max(time.monotonic() - inicio, 1e-3)
    return con_imagen, leidos / transcurrido


def abrir_camara_usb(indice):
    sistema = platform.system().lower()
    if sistema == "windows":
        nombres = {"dshow": ("CAP_DSHOW",), "msmf": ("CAP_MSMF",)}.get(
            str(BACKEND_CAMARA).lower(), ("CAP_DSHOW", "CAP_MSMF")
        )
    elif sistema == "darwin":
        nombres = ("CAP_AVFOUNDATION",)
    else:
        nombres = ("CAP_V4L2",)
    mejor, mejor_puntaje = None, None
    for nombre in nombres + ("CAP_ANY",):
        captura = cv2.VideoCapture(indice, getattr(cv2, nombre, cv2.CAP_ANY))
        if not captura.isOpened():
            captura.release()
            continue
        # MJPG antes del tamaño: con YUY2 muchas webcams bajan a 5 FPS o menos en 720p.
        captura.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        captura.set(cv2.CAP_PROP_FRAME_WIDTH, ANCHO_CAMARA)
        captura.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTO_CAMARA)
        captura.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        con_imagen, fps = _probar_camara(captura)
        print(f"Cámara {indice} con {nombre}: {con_imagen} cuadros con imagen, {fps:.1f} FPS")
        puntaje = (con_imagen > 0, fps)
        if mejor is None or puntaje > mejor_puntaje:
            if mejor is not None:
                mejor.release()
            mejor, mejor_puntaje = captura, puntaje
        else:
            captura.release()
        if con_imagen > 0 and fps >= 10:
            break  # suficientemente bueno; no hace falta probar más
    if mejor is not None and not mejor_puntaje[0]:
        print("AVISO: la cámara solo entrega imagen negra. Revisa que no esté tapada, "
              "que otra aplicación no la esté usando y los permisos de cámara de Windows.")
    return mejor


_GSTREAMER_EN_OPENCV = None
_AVISO_GSTREAMER = False


def opencv_tiene_gstreamer():
    global _GSTREAMER_EN_OPENCV
    if _GSTREAMER_EN_OPENCV is None:
        info = cv2.getBuildInformation()
        _GSTREAMER_EN_OPENCV = bool(re.search(r"GStreamer:\s+YES", info))
    return _GSTREAMER_EN_OPENCV


def usar_gstreamer_rtsp():
    """GStreamer con decodificación por hardware: en el Jetson ("auto") o si se fuerza con "si"."""
    global _AVISO_GSTREAMER
    modo = str(RTSP_GSTREAMER).lower()
    if modo == "no" or (modo == "auto" and not ES_JETSON):
        return False
    if opencv_tiene_gstreamer():
        return True
    if not _AVISO_GSTREAMER:
        _AVISO_GSTREAMER = True
        registro.warning("OpenCV no tiene GStreamer: el RTSP se decodifica por FFmpeg en la CPU. "
                         "En el Jetson use el OpenCV de JetPack (ver scripts/jetson/LEEME_JETSON.md).")
    return False


def pipeline_rtsp(url, timeout_ms=RTSP_TIMEOUT_MS):
    """Pipeline GStreamer: RTSP por TCP -> decodificador NVDEC (nvv4l2decoder) -> BGR para OpenCV.

    appsink drop=true max-buffers=1: se queda siempre con el cuadro más reciente.
    El último caps (format=BGR) es el formato que espera OpenCV tras videoconvert.
    """
    codec = "h265" if str(CODEC_RTSP).lower() in ("h265", "hevc") else "h264"
    espera_us = int(timeout_ms) * 1000
    ubicacion = str(url).replace('"', "%22")
    return (
        f'rtspsrc location="{ubicacion}" protocols=tcp latency={int(LATENCIA_RTSP_MS)} '
        f"timeout={espera_us} tcp-timeout={espera_us} ! "
        f"rtp{codec}depay ! {codec}parse ! nvv4l2decoder ! nvvidconv ! video/x-raw,format=BGRx ! "
        "videoconvert ! video/x-raw,format=BGR ! appsink drop=true max-buffers=1 sync=false"
    )


def abrir_rtsp(url, timeout_ms=RTSP_TIMEOUT_MS):
    if usar_gstreamer_rtsp():
        captura = cv2.VideoCapture(pipeline_rtsp(url, timeout_ms), cv2.CAP_GSTREAMER)
        if captura.isOpened():
            registro.info("RTSP abierto con GStreamer y decodificación por hardware (NVDEC, %s).", CODEC_RTSP)
            return captura
        captura.release()
        registro.warning("No se pudo abrir el RTSP con GStreamer (revise CODEC_RTSP=%s y la URL); "
                         "se usa FFmpeg.", CODEC_RTSP)
    parametros = [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(timeout_ms),
        cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(timeout_ms),
    ]
    return cv2.VideoCapture(str(url), cv2.CAP_FFMPEG, parametros)


def abrir_captura(tipo, origen, timeout_ms=RTSP_TIMEOUT_MS):
    """Abre una cámara RTSP o USB, o la captura de pantalla. Devuelve el objeto o None si no se pudo."""
    if tipo == "rtsp":
        if not origen:
            return None
        captura = abrir_rtsp(origen, timeout_ms)
    elif tipo == "camara":
        captura = abrir_camara_usb(int(origen))
        if captura is None:
            return None
    elif tipo == "pantalla":
        from src.adquisicion.captura_pantalla import CapturaPantalla

        opciones = origen if isinstance(origen, dict) else {"monitor": int(origen or 1)}
        captura = CapturaPantalla(opciones.get("monitor", 1), opciones.get("region"))
    elif tipo == "ventana":
        from src.adquisicion.captura_ventana import CapturaVentana

        opciones = origen if isinstance(origen, dict) else {"programa": str(origen or "")}
        captura = CapturaVentana(opciones.get("programa", ""), opciones.get("titulo", ""))
    else:
        raise ValueError(f"Tipo de cámara desconocido: {tipo}")

    if not captura.isOpened():
        captura.release()
        return None
    captura.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return captura


class VideoEnBucle:
    def __init__(self, ruta):
        ruta_resuelta = obtener_ruta_recurso(ruta) if ruta else None
        self.ruta = str(ruta_resuelta) if ruta_resuelta is not None else ""
        if not self.ruta or not ruta_resuelta.is_file():
            raise FileNotFoundError(f"No se pudo abrir el video {ruta}")
        self.captura = cv2.VideoCapture(self.ruta)
        if not self.captura.isOpened():
            self.captura.release()
            raise FileNotFoundError(f"No se pudo abrir el video {ruta}")
        fps = self.captura.get(cv2.CAP_PROP_FPS)
        self.intervalo = 1.0 / fps if fps and 1 <= fps <= 120 else 1.0 / 25
        self._proximo = time.monotonic()
        self._reinicio_pendiente = False

    def leer(self):
        espera = self._proximo - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        self._proximo = max(self._proximo + self.intervalo, time.monotonic() - self.intervalo)
        try:
            correcto, cuadro = self.captura.read()
            if not correcto or cuadro is None:
                self._reinicio_pendiente = True
                self.captura.set(cv2.CAP_PROP_POS_FRAMES, 0)
                correcto, cuadro = self.captura.read()
            if correcto and cuadro is not None:
                reinicio = self._reinicio_pendiente
                self._reinicio_pendiente = False
                return True, cuadro, reinicio
            return False, None, False
        except cv2.error:
            self._reinicio_pendiente = True
            return False, None, False

    def cerrar(self):
        try:
            self.captura.release()
        except Exception:
            pass


class FuenteVideo(threading.Thread):
    def __init__(
        self,
        tipo,
        origen,
        video_demo=None,
        segundos_failover=SEGUNDOS_FAILOVER,
        segundos_reconexion=SEGUNDOS_ENTRE_RECONEXIONES,
        lecturas_para_volver=LECTURAS_PARA_VOLVER,
        abrir=abrir_captura,
    ):
        super().__init__(daemon=True, name="captura")
        self.tipo = tipo
        self.origen = origen
        self.video_demo = video_demo
        self.segundos_failover = segundos_failover
        self.segundos_reconexion = segundos_reconexion
        self.lecturas_para_volver = lecturas_para_volver
        self._abrir = abrir

        self._candado = threading.Lock()
        self._recorte = RecorteBordes()
        self._origen_recorte = None
        self._cuadro = None
        self._id_cuadro = 0
        self._generacion = 0
        self._es_simulacion = tipo in ("video", "pantalla", "ventana")  # la pantalla no es el humedal: no cuenta como avistamiento real
        self._detener = threading.Event()
        # Cambio de fuente en vivo (portal > Fuente de video): el bucle actual termina y
        # el hilo sigue con la nueva fuente, sin reiniciar el programa.
        self._cambio = threading.Event()
        self._pendiente = None

        self.estado = "RECONECTANDO" if tipo != "video" else "ONLINE"
        self.ultimo_error = ""
        self.cuadros_recibidos = 0

    # ------------------------------------------------------
    # Lectura desde otros hilos
    # ------------------------------------------------------

    def ultimo_cuadro(self, despues_de=None):
        """Publica cuadro y generación juntos, aunque el consumidor pierda el primer cuadro del bucle."""
        with self._candado:
            copia = self._cuadro.copy() if self._cuadro is not None and self._id_cuadro != despues_de else None
            return self._id_cuadro, copia, self._es_simulacion, self._generacion

    @property
    def descripcion(self):
        if self.tipo == "rtsp":
            return "Cámara IP"
        if self.tipo == "camara":
            return f"Cámara {self.origen}"
        if self.tipo == "pantalla":
            opciones = self.origen if isinstance(self.origen, dict) else {"monitor": self.origen}
            return "Captura de región" if opciones.get("region") else f"Pantalla {opciones.get('monitor', 1)}"
        if self.tipo == "ventana":
            from src.adquisicion.captura_ventana import describir

            opciones = self.origen if isinstance(self.origen, dict) else {"programa": str(self.origen or "")}
            return describir(opciones.get("programa", ""), opciones.get("titulo", ""))
        return "Video de prueba"

    def detener(self):
        self._detener.set()

    def cambiar(self, tipo, origen):
        """Pasa a otra fuente (rtsp, camara, pantalla o video) sin detener el hilo."""
        if tipo not in ("rtsp", "camara", "pantalla", "ventana", "video"):
            raise ValueError(f"Fuente desconocida: {tipo}")
        with self._candado:
            self._pendiente = (tipo, origen)
        self._cambio.set()

    def _sigue(self):
        return not (self._detener.is_set() or self._cambio.is_set())

    # ------------------------------------------------------
    # Hilo
    # ------------------------------------------------------

    def _publicar(self, cuadro, es_simulacion, discontinuidad=False):
        if RECORTAR_BORDES_NEGROS:
            if discontinuidad or es_simulacion != self._origen_recorte:
                self._recorte = RecorteBordes()
                self._origen_recorte = es_simulacion
            cuadro = self._recorte.aplicar(cuadro)
        with self._candado:
            if discontinuidad or es_simulacion != self._es_simulacion:
                self._generacion += 1
            self._cuadro = cuadro
            self._es_simulacion = es_simulacion
            self._id_cuadro += 1
        self.cuadros_recibidos += 1

    def _abrir_principal(self):
        try:
            return self._abrir(self.tipo, self.origen)
        except Exception as error:
            self.ultimo_error = str(error)
            return None

    def _abrir_demo(self):
        if not self.video_demo:
            return None
        try:
            return VideoEnBucle(self.video_demo)
        except Exception as error:
            self.ultimo_error = str(error)
            return None

    def _probar_reconexion(self, resultado):
        """Se ejecuta en un hilo aparte durante el Modo Demostración."""
        captura = None
        try:
            captura = self._abrir_principal()
            if captura is None:
                resultado["captura"] = None
                return
            seguidas = 0
            limite = time.monotonic() + max(5.0, self.lecturas_para_volver)
            while seguidas < self.lecturas_para_volver and time.monotonic() < limite:
                if not self._sigue():
                    break
                correcto, cuadro = captura.read()
                seguidas = seguidas + 1 if correcto and cuadro is not None else 0
            with self._candado:
                if seguidas >= self.lecturas_para_volver and self._sigue():
                    resultado["captura"] = captura
                    captura = None
        except Exception as error:
            self.ultimo_error = str(error)
            resultado["captura"] = None
        finally:
            if captura is not None:
                try:
                    captura.release()
                except Exception:
                    pass

    def run(self):
        while True:
            try:
                if self.tipo == "video":
                    self._bucle_video()
                else:
                    self._bucle_camara()
            except Exception as error:
                self.ultimo_error = f"Error en hilo de captura: {error}"
                self.estado = "SIN_SENAL"
            if self._detener.is_set() or not self._cambio.is_set():
                return
            with self._candado:
                tipo, origen = self._pendiente
                self._pendiente = None
                self._cambio.clear()
                self.tipo, self.origen = tipo, origen
                self._generacion += 1  # el motor reinicia el seguimiento de aves
            self.estado = "RECONECTANDO" if tipo != "video" else "ONLINE"
            self.ultimo_error = ""
            print(f"Fuente de video cambiada a: {self.descripcion}")

    def _bucle_video(self):
        try:
            video = VideoEnBucle(self.origen)
        except Exception as error:
            self.ultimo_error = str(error)
            self.estado = "SIN_SENAL"
            return
        self.estado = "ONLINE"
        try:
            while self._sigue():
                correcto, cuadro, reinicio = video.leer()
                if correcto:
                    self._publicar(cuadro, True, discontinuidad=reinicio)
                else:
                    time.sleep(0.1)
        finally:
            video.cerrar()

    def _bucle_camara(self):
        principal = self._abrir_principal()
        nueva_conexion = True
        ultimo_correcto = time.monotonic()
        ultimo_intento = time.monotonic()
        ultimo_intento_demo = 0.0
        demo = None
        reconexion = None
        hilo_reconexion = None
        ultima_reconexion = 0.0

        try:
            while self._sigue():
                ahora = time.monotonic()

                # --- Cámara disponible -------------------------------------
                if principal is not None:
                    try:
                        correcto, cuadro = principal.read()
                    except cv2.error as error:
                        self.ultimo_error = str(error)
                        correcto, cuadro = False, None
                    if correcto and cuadro is not None:
                        self._publicar(cuadro, self.tipo in ("pantalla", "ventana"), discontinuidad=nueva_conexion)
                        nueva_conexion = False
                        ultimo_correcto = time.monotonic()
                        self.estado = "ONLINE"
                        continue
                    self.estado = "RECONECTANDO"
                    try:
                        principal.release()
                    except Exception:
                        pass
                    principal = None
                    nueva_conexion = True
                    ultimo_intento = time.monotonic()
                    continue

                # --- Cámara caída, todavía dentro del margen ------------------
                if ahora - ultimo_correcto < self.segundos_failover:
                    self.estado = "RECONECTANDO"
                    if ahora - ultimo_intento >= 1.0:
                        ultimo_intento = ahora
                        principal = self._abrir_principal()
                    else:
                        time.sleep(0.05)
                    continue

                # --- Modo Demostración (Failover Offline) ---------------------
                if hilo_reconexion is not None and not hilo_reconexion.is_alive():
                    captura = reconexion.pop("captura", None)
                    hilo_reconexion = None
                    if captura is not None:
                        principal = captura
                        nueva_conexion = True
                        if demo is not None:
                            demo.cerrar()
                            demo = None
                        ultimo_correcto = time.monotonic()
                        self.estado = "ONLINE"
                        continue

                if hilo_reconexion is None and ahora - ultima_reconexion >= self.segundos_reconexion:
                    ultima_reconexion = ahora
                    reconexion = {}
                    hilo_reconexion = threading.Thread(
                        target=self._probar_reconexion, args=(reconexion,), daemon=True, name="reconexion"
                    )
                    hilo_reconexion.start()

                nuevo_demo = False
                if demo is None and (ahora - ultimo_intento_demo >= 5.0):
                    ultimo_intento_demo = ahora
                    demo = self._abrir_demo()
                    nuevo_demo = demo is not None
                if demo is not None:
                    self.estado = "FAILOVER_DEMO"
                    correcto, cuadro, reinicio = demo.leer()
                    if correcto:
                        self._publicar(cuadro, True, discontinuidad=nuevo_demo or reinicio)
                    else:
                        demo.cerrar()
                        demo = None
                else:
                    self.estado = "SIN_SENAL"
                    time.sleep(0.2)
        finally:
            if not self._cambio.is_set():
                self._detener.set()
            if reconexion is not None:
                with self._candado:
                    pendiente = reconexion.pop("captura", None)
                if pendiente is not None:
                    try:
                        pendiente.release()
                    except Exception:
                        pass
            if principal is not None:
                try:
                    principal.release()
                except Exception:
                    pass
            if demo is not None:
                demo.cerrar()
