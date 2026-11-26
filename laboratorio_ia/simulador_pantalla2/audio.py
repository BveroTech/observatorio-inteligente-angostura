"""Reexportación de compatibilidad del gestor de audio hacia la capa de aplicación."""
from src.aplicacion.gestor_audio import Reproductor, buscar_audio_especie

__all__ = ["Reproductor", "buscar_audio_especie"]
