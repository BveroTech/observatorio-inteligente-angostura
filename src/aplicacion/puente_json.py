import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

from config.settings import ARCHIVO_AVES_HOY

CAMPOS = (
    "id_especie",
    "nombre_comun",
    "nombre_cientifico",
    "familia",
    "orden",
    "ruta_audio_canto",
    "ruta_foto",
    "ultimo_avistamiento",
    "veces",
)


def escribir_atomico(ruta, datos, intentos=10):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(prefix=ruta.name + ".", suffix=".tmp", dir=str(ruta.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
            json.dump(datos, archivo, ensure_ascii=False, indent=2)
            archivo.flush()
            os.fsync(archivo.fileno())
        for intento in range(intentos):
            try:
                os.replace(temporal, ruta)
                return True
            except PermissionError:
                time.sleep(0.05 * (intento + 1))
        return False
    finally:
        if os.path.exists(temporal):
            os.remove(temporal)


def publicar_aves_hoy(especies_del_dia, ruta=ARCHIVO_AVES_HOY):
    especies = []
    for fila in especies_del_dia:
        entrada = {campo: fila.get(campo) for campo in CAMPOS}
        entrada["ruta_captura"] = fila.get("ultima_captura") or ""
        especies.append(entrada)
    return escribir_atomico(
        ruta,
        {
            "fecha": datetime.now().strftime("%Y-%m-%d"),
            "actualizado": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "especies": especies,
        },
    )


class LectorAvesHoy:
    def __init__(self, ruta=ARCHIVO_AVES_HOY):
        self.ruta = Path(ruta)
        self.ultimo = {"fecha": "", "especies": []}
        self._marca = None

    def leer(self):
        try:
            marca = self.ruta.stat().st_mtime_ns
        except FileNotFoundError:
            return {"fecha": "", "especies": []}
        if marca != self._marca:
            try:
                with open(self.ruta, "r", encoding="utf-8") as archivo:
                    datos = json.load(archivo)
                if isinstance(datos, dict) and isinstance(datos.get("especies"), list):
                    self.ultimo = datos
                    self._marca = marca
            except (OSError, json.JSONDecodeError):
                pass
        if self.ultimo.get("fecha") != datetime.now().strftime("%Y-%m-%d"):
            return {"fecha": "", "especies": []}
        return self.ultimo
