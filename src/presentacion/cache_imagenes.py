"""Fotos compartidas por las vistas de visitantes. Pillow trabaja fuera de Tk."""

import customtkinter as ctk
from PIL import Image, ImageOps

from src.persistencia.repositorio_sqlite import ruta_absoluta

MINIATURA_CATALOGO = (104, 78)
MINIATURA_HOY = (66, 50)
FOTO_FICHA = (200, 150)
FOTO_TRIVIA = (600, 440)
TAMANOS = (MINIATURA_CATALOGO, MINIATURA_HOY, FOTO_FICHA, FOTO_TRIVIA)


def clave_imagen(ruta):
    return ruta.replace("\\", "/") if isinstance(ruta, str) else ""


def preparar_imagenes(rutas):
    """Decodifica una vez por ruta y conserva solo las variantes reducidas."""
    preparadas = {}
    for clave in rutas:
        try:
            with Image.open(ruta_absoluta(clave)) as archivo:
                imagen = archivo.convert("RGB")
            preparadas[clave] = {
                tamano: ImageOps.contain(imagen, tamano, Image.Resampling.LANCZOS)
                if imagen.width > tamano[0] or imagen.height > tamano[1] else imagen
                for tamano in TAMANOS
            }
        except (OSError, ValueError, Image.DecompressionBombError):
            continue
    return preparadas


class CacheImagenes:
    def __init__(self):
        self._rutas = {}
        self.revision = 0

    def rutas_cargadas(self):
        return frozenset(self._rutas)

    def guardar(self, ruta, variantes):
        self._rutas[ruta] = {
            tamano: ctk.CTkImage(light_image=imagen, dark_image=imagen, size=imagen.size)
            for tamano, imagen in variantes.items()
        }
        self.revision += 1

    def conservar(self, rutas):
        for ruta in self._rutas.keys() - rutas:
            del self._rutas[ruta]

    def obtener(self, ruta, tamano):
        variantes = self._rutas.get(clave_imagen(ruta))
        return variantes.get(tamano) if variantes is not None else None


class EtiquetaFoto(ctk.CTkLabel):
    def destroy(self):
        # Una CTkImage compartida no debe retener el callback de una etiqueta destruida.
        if isinstance(self.cget("image"), ctk.CTkImage):
            self.configure(image=None)
        super().destroy()
