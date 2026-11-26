"""
Captura de pantalla como fuente de video, para probar el reconocimiento sin cámara:
se reproduce un video de aves (YouTube, eBird, Macaulay Library…) en un monitor y
el programa analiza lo que aparece ahí.

Imita la interfaz de cv2.VideoCapture (read, release, isOpened) para que
FuenteVideo la trate igual que una cámara.

Un monitor completo se captura con dxcam (Desktop Duplication de DirectX:
30 cuadros/s casi sin usar CPU). Si dxcam no está disponible, o se pide una
región o el escritorio completo, se usa mss (GDI: ~25 ms por cuadro).
"""
import threading
import time

import numpy as np


def listar_monitores():
    """[(numero, izquierda, arriba, ancho, alto)]: el 0 es el escritorio completo y el
    resto usa el número de Windows (Configuración > Pantalla > Identificar)."""
    import mss

    from src.aplicacion.gestor_monitores import monitores_numerados

    with mss.MSS() as captura:
        todo = captura.monitors[0]
        lista = [(0, todo["left"], todo["top"], todo["width"], todo["height"])]
        numerados = monitores_numerados()
        if numerados:
            return lista + [(n, *numerados[n]) for n in sorted(numerados)]
        return lista + [(i, m["left"], m["top"], m["width"], m["height"]) for i, m in enumerate(captura.monitors[1:], 1)]


def interpretar_region(texto):
    """'x,y,ancho,alto' -> (x, y, ancho, alto) en píxeles del escritorio."""
    partes = [int(p) for p in str(texto).replace(" ", "").split(",")]
    if len(partes) != 4 or partes[2] <= 0 or partes[3] <= 0:
        raise ValueError("La región debe ser x,y,ancho,alto (por ejemplo 0,0,1920,1080)")
    return tuple(partes)


class CapturaPantalla:
    """Captura un monitor (1, 2, 3…) o una región x,y,ancho,alto del escritorio."""

    def __init__(self, monitor=1, region=None, fps_maximo=None):
        import mss  # noqa: F401  (falla aquí si no está instalado)

        self.monitor = monitor
        self.region = region
        if fps_maximo is None:
            from config.settings import FPS_VIDEO as fps_maximo
        self.intervalo = 1.0 / fps_maximo if fps_maximo else 0.0
        self._ultimo = 0.0
        self._local = threading.local()  # mss en Windows debe usarse en el hilo que lo creó
        self._abierta = True
        self.zona = self._zona()
        self.fps_maximo = fps_maximo
        self._dxcam = None if region or not monitor else self._abrir_dxcam(int(monitor), fps_maximo or 30)
        self.metodo = "dxcam" if self._dxcam is not None else "mss"

    @staticmethod
    def _abrir_dxcam(numero, fps):
        """Cámara dxcam del monitor DISPLAY<numero>, o None si no se puede."""
        try:
            import dxcam
        except ImportError:
            return None
        try:
            fabrica = getattr(dxcam, "__factory")
            for dispositivo, salidas in enumerate(fabrica.outputs):
                for indice, salida in enumerate(salidas):
                    if str(salida.devicename).upper().endswith(f"DISPLAY{numero}"):
                        camara = dxcam.create(device_idx=dispositivo, output_idx=indice, output_color="BGR")
                        camara.start(target_fps=int(fps), video_mode=True)
                        return camara
        except Exception as error:
            print(f"[AVISO] dxcam no pudo abrir el monitor {numero} ({error}); se usa mss.")
        return None

    def _zona(self):
        if self.region:
            x, y, ancho, alto = self.region
            return {"left": x, "top": y, "width": ancho, "height": alto}
        monitores = {m[0]: m[1:] for m in listar_monitores()}
        if int(self.monitor) not in monitores:
            raise ValueError(f"No existe el monitor {self.monitor}. Hay: {', '.join(str(n) for n in monitores if n)}.")
        x, y, ancho, alto = monitores[int(self.monitor)]
        return {"left": x, "top": y, "width": ancho, "height": alto}

    def _mss(self):
        import mss

        if getattr(self._local, "captura", None) is None:
            self._local.captura = mss.MSS()
        return self._local.captura

    def isOpened(self):  # noqa: N802  (misma interfaz que cv2.VideoCapture)
        return self._abierta

    def read(self):
        if not self._abierta:
            return False, None
        if self._dxcam is not None:
            try:
                imagen = self._dxcam.get_latest_frame()  # espera el próximo cuadro (ritmo fps_maximo)
            except Exception:
                return False, None
            return (True, imagen.copy()) if imagen is not None else (False, None)
        espera = self.intervalo - (time.monotonic() - self._ultimo)
        if espera > 0:
            time.sleep(espera)
        self._ultimo = time.monotonic()
        try:
            imagen = np.asarray(self._mss().grab(self.zona))
        except Exception:
            return False, None
        return True, np.ascontiguousarray(imagen[:, :, :3])  # BGRA -> BGR

    def release(self):
        self._abierta = False
        if self._dxcam is not None:
            try:
                self._dxcam.stop()
                self._dxcam.release()
            except Exception:
                pass
            self._dxcam = None
        captura = getattr(self._local, "captura", None)
        if captura is not None:
            captura.close()
            self._local.captura = None

    def set(self, *_):
        return False
