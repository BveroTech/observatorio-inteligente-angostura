"""
Gestor de reproducción de audio (cantos de aves) para el Kiosco y la Pantalla 2.

Soporta Pygame (`pygame` / `pygame-ce`) para `.mp3`, `.ogg` y `.wav`, con
respaldo automático en `winsound` (estándar de Windows) para archivos `.wav`.
"""
import platform
import time
import wave
from pathlib import Path

from config.settings import CARPETA_SONIDOS_SIMULADOR
from src.persistencia.repositorio_sqlite import ruta_absoluta
from src.procesamiento.inferencia_onnx import clave_clase


class Reproductor:
    def __init__(self):
        self.motor = None
        self._pygame = None
        self._winsound = None
        self._ruta_actual = None
        self._fin_wav = 0.0
        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self._pygame = pygame
            self.motor = "pygame"
        except Exception:
            self._pygame = None
            if platform.system().lower() == "windows":
                try:
                    import winsound

                    self._winsound = winsound
                    self.motor = "winsound"
                except ImportError:
                    pass
        if self.motor is None:
            # En Linux/Jetson solo existe Pygame: sin él (o sin dispositivo de audio) no hay cantos.
            print("[AVISO] Sin audio: Pygame no pudo iniciar el mezclador (revise pygame-ce y la salida de sonido).")

    def puede_reproducir(self, ruta):
        if not ruta or self.motor is None:
            return False
        ruta = Path(ruta)
        if not ruta.is_file():
            return False
        if self.motor == "winsound":
            return ruta.suffix.lower() == ".wav"
        return ruta.suffix.lower() in (".wav", ".ogg", ".mp3")

    def reproducir(self, ruta):
        if not self.puede_reproducir(ruta):
            return False
        self.detener()
        try:
            if self.motor == "pygame":
                self._pygame.mixer.music.load(str(ruta))
                self._pygame.mixer.music.play()
            else:
                # winsound no expone una consulta de reproducción para WAV asíncrono.
                try:
                    with wave.open(str(ruta), "rb") as wav:
                        duracion = wav.getnframes() / wav.getframerate()
                except (OSError, EOFError, wave.Error):
                    duracion = float("inf")
                self._winsound.PlaySound(
                    str(ruta), self._winsound.SND_FILENAME | self._winsound.SND_ASYNC
                )
                self._fin_wav = time.monotonic() + duracion
            self._ruta_actual = Path(ruta)
            return True
        except Exception as error:
            print("No se pudo reproducir el canto:", error)
            return False

    def reproduciendo(self, ruta):
        if self._ruta_actual != Path(ruta):
            return False
        if self.motor == "pygame":
            return bool(self._pygame.mixer.get_init() and self._pygame.mixer.music.get_busy())
        return time.monotonic() < self._fin_wav

    def detener(self):
        self._ruta_actual = None
        try:
            if self.motor == "pygame" and self._pygame.mixer.get_init():
                self._pygame.mixer.music.stop()
                self._pygame.mixer.music.unload()
            elif self.motor == "winsound":
                self._winsound.PlaySound(None, 0)
        except Exception:
            pass


def buscar_audio_especie(especie, ficha=None):
    """
    Resuelve la ruta absoluta del archivo de canto de una especie desde su ficha
    en la base de datos o desde la carpeta de respaldo de sonidos.
    """
    ficha = ficha or {}
    ruta_ficha = ficha.get("ruta_audio_canto")
    if ruta_ficha is None:
        ruta_ficha = (especie or {}).get("ruta_audio_canto")
    if ruta_ficha == "":
        return None
    audio = ruta_absoluta(ruta_ficha)
    if audio is not None and audio.is_file():
        return audio
    if CARPETA_SONIDOS_SIMULADOR.is_dir():
        objetivos = {
            clave_clase((especie or {}).get("nombre_comun") or ficha.get("nombre_comun") or ""),
            clave_clase((especie or {}).get("nombre_cientifico") or ficha.get("nombre_cientifico") or ""),
        } - {""}
        for archivo in CARPETA_SONIDOS_SIMULADOR.iterdir():
            if archivo.is_file() and clave_clase(archivo.stem) in objetivos:
                return archivo
    return None
