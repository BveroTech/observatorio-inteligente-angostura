"""
Lectura en voz alta de las fichas (español, inglés, alemán) sin internet, con Piper.

Piper es una voz neuronal que corre con ONNX Runtime (el mismo motor de la IA), en
Windows y en el Jetson. Las voces están en modelos/voces y se descargan con
scripts/cli_admin/descargar_modelos_idiomas.py:
    es_MX-claude-high · en_US-lessac-medium · de_DE-thorsten-medium

La ficha se lee por partes: mientras suena una, se prepara la siguiente, así la
lectura empieza en uno o dos segundos. Los audios quedan guardados en data/cache_voz
(la segunda vez que se lee una ficha empieza al instante). Usa el mismo reproductor
que los cantos: si se toca «Escuchar canto», la lectura se detiene, y viceversa.
"""
import hashlib
import logging
import queue
import threading
import wave
from pathlib import Path

from config import settings

registro = logging.getLogger("observatorio.voz")

_voces = {}
_candado_voces = threading.Lock()
CARPETA_CACHE = settings.obtener_ruta_datos("data/cache_voz")
MAXIMO_CACHE_MB = 300


def ruta_voz(idioma):
    nombre = settings.VOCES.get(idioma)
    return settings.CARPETA_VOCES / f"{nombre}.onnx" if nombre else None


def voz_disponible(idioma):
    ruta = ruta_voz(idioma)
    if ruta is None or not ruta.is_file() or not Path(str(ruta) + ".json").is_file():
        return False
    try:
        import piper  # noqa: F401
    except ImportError:
        return False
    return True


def _cargar(idioma):
    with _candado_voces:
        if idioma not in _voces:
            from piper import PiperVoice

            _voces[idioma] = PiperVoice.load(str(ruta_voz(idioma)))
            registro.info("Voz %s cargada (%s)", idioma, settings.VOCES[idioma])
        return _voces[idioma]


def precargar(idioma):
    """Carga la voz en segundo plano (tarda 2-3 s) para que el botón responda al instante."""
    if voz_disponible(idioma):
        threading.Thread(target=_cargar, args=(idioma,), daemon=True, name=f"voz_{idioma}").start()


def sintetizar(texto, idioma):
    """Ruta de un WAV con el texto leído (desde la caché si ya existe)."""
    clave = hashlib.sha1(f"{settings.VOCES.get(idioma)}|{texto}".encode("utf-8")).hexdigest()[:20]
    destino = CARPETA_CACHE / f"{idioma}_{clave}.wav"
    if destino.is_file():
        return destino
    CARPETA_CACHE.mkdir(parents=True, exist_ok=True)
    voz = _cargar(idioma)
    temporal = destino.with_suffix(".tmp")
    with wave.open(str(temporal), "wb") as salida:
        voz.synthesize_wav(texto, salida)
    temporal.replace(destino)
    return destino


def limpiar_cache():
    """Borra los audios más antiguos si la caché supera MAXIMO_CACHE_MB."""
    try:
        archivos = sorted(CARPETA_CACHE.glob("*.wav"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in archivos)
        while archivos and total > MAXIMO_CACHE_MB * 2**20:
            viejo = archivos.pop(0)
            total -= viejo.stat().st_size
            viejo.unlink(missing_ok=True)
    except OSError:
        pass


class LectorFicha:
    """
    Lee una lista de párrafos con el reproductor de la pantalla táctil.
    La síntesis corre en un hilo; la reproducción se encadena desde la interfaz (after),
    porque el mezclador de audio se usa desde el hilo de Tk.
    """

    def __init__(self, widget, reproductor, al_cambiar=None):
        self.widget = widget
        self.reproductor = reproductor
        self.al_cambiar = al_cambiar or (lambda leyendo: None)
        self._generacion = 0
        self._cola = None
        self._actual = None
        self._termino_sintesis = True
        self._pendiente = None
        self.leyendo = False

    def leer(self, parrafos, idioma):
        self.detener()
        parrafos = [p.strip() for p in parrafos if p and p.strip()]
        if not parrafos or not voz_disponible(idioma):
            return False
        self._generacion += 1
        generacion = self._generacion
        self._cola = queue.Queue()
        self._termino_sintesis = False
        self.leyendo = True
        self.al_cambiar(True)

        def producir():
            try:
                for parrafo in parrafos:
                    if generacion != self._generacion:
                        return
                    self._cola.put(sintetizar(parrafo, idioma))
            except Exception:
                registro.exception("No se pudo leer la ficha en voz alta")
            finally:
                if generacion == self._generacion:
                    self._termino_sintesis = True
                limpiar_cache()

        threading.Thread(target=producir, daemon=True, name="lectura_ficha").start()
        self._pendiente = self.widget.after(100, self._avanzar, generacion)
        return True

    def _avanzar(self, generacion):
        self._pendiente = None
        if generacion != self._generacion or not self.leyendo:
            return
        try:
            if not self.widget.winfo_exists():
                return
        except Exception:
            return
        sonando = self._actual is not None and self.reproductor.reproduciendo(self._actual)
        if self._actual is not None and not sonando and self.reproductor._ruta_actual not in (None, self._actual):
            self.detener()  # otro audio (un canto) tomó el reproductor
            return
        if not sonando:
            try:
                siguiente = self._cola.get_nowait()
            except queue.Empty:
                if self._termino_sintesis:
                    self._finalizar()
                    return
                siguiente = None
            if siguiente is not None:
                self._actual = siguiente
                if not self.reproductor.reproducir(siguiente):
                    self._finalizar()
                    return
        self._pendiente = self.widget.after(120, self._avanzar, generacion)

    def _finalizar(self):
        self.leyendo = False
        self._actual = None
        self.al_cambiar(False)

    def detener(self):
        self._generacion += 1
        if self._pendiente is not None:
            try:
                self.widget.after_cancel(self._pendiente)
            except Exception:
                pass
            self._pendiente = None
        if self.leyendo:
            if self._actual is not None and self.reproductor.reproduciendo(self._actual):
                self.reproductor.detener()
            self._finalizar()
