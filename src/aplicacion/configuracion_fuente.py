"""
Fuente de video elegida en el portal (cámara IP, captura de pantalla, cámara USB o video).

El portal la guarda en config/observatorio.ini ([camara]) y la dirección RTSP en
config/camara_local.json. El kiosco revisa esos archivos cada 2 segundos y, si cambian,
pasa a la nueva fuente en vivo (FuenteVideo.cambiar). El kiosco deja su estado en
data/estado_kiosco.json para que el portal muestre qué está usando.
"""
import configparser
import json
import os
import re
import tempfile
import time
from pathlib import Path

from config import settings

TIPOS = {
    "rtsp": "Cámara IP (RTSP)",
    "pantalla": "Captura de pantalla",
    "ventana": "Captura de una aplicación",
    "camara": "Cámara USB",
    "video": "Video de demostración",
}
ARCHIVO_CAMARA = settings.obtener_ruta_datos("config/camara_local.json")
ARCHIVO_ESTADO = settings.obtener_ruta_datos("data/estado_kiosco.json")


def _escribir_atomico(ruta, texto):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=ruta.parent, delete=False, suffix=".tmp") as archivo:
        archivo.write(texto)
        temporal = Path(archivo.name)
    os.replace(temporal, ruta)


def leer_fuente():
    """{tipo, monitor, indice, region} según observatorio.ini (o settings.py si no existe)."""
    datos = {
        "tipo": settings.FUENTE_VIDEO, "monitor": settings.MONITOR_CAPTURA,
        "indice": settings.INDICE_CAMARA, "region": None,
        "programa": settings.VENTANA_PROGRAMA, "titulo": settings.VENTANA_TITULO,
    }
    lector = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    try:
        lector.read(settings.ARCHIVO_CONFIGURACION, encoding="utf-8-sig")
    except configparser.Error:
        return datos
    tipo = lector.get("camara", "fuente", fallback="").strip().lower()
    if tipo in TIPOS:
        datos["tipo"] = tipo
    for clave, opcion in (("monitor", "monitor_captura"), ("indice", "indice_camara")):
        valor = lector.get("camara", opcion, fallback="").strip()
        if valor.isdigit():
            datos[clave] = int(valor)
    for clave, opcion in (("programa", "ventana_programa"), ("titulo", "ventana_titulo")):
        if lector.has_option("camara", opcion):
            datos[clave] = lector.get("camara", opcion).strip()
    return datos


def origen_de(datos):
    """(tipo, origen) para FuenteVideo."""
    tipo = datos["tipo"]
    if tipo == "rtsp":
        return tipo, settings.url_rtsp()
    if tipo == "pantalla":
        return tipo, {"monitor": datos.get("monitor") or 1, "region": datos.get("region")}
    if tipo == "camara":
        return tipo, int(datos.get("indice") or 0)
    if tipo == "ventana":
        return tipo, {"programa": datos.get("programa") or "", "titulo": datos.get("titulo") or ""}
    return "video", settings.VIDEO_DEMOSTRACION


def url_rtsp_enmascarada(url=None):
    """rtsp://usuario:****@ip/... para mostrar sin revelar la contraseña."""
    url = settings.url_rtsp() if url is None else url
    return re.sub(r"(rtsp://[^:/@]+:)[^@]*(@)", r"\1****\2", url or "")


def guardar_fuente(tipo, monitor=None, indice=None, url_rtsp=None, programa=None, titulo=None):
    """Escribe [camara] en observatorio.ini conservando el resto del archivo y sus comentarios."""
    if tipo not in TIPOS:
        raise ValueError("Fuente no válida.")
    valores = {"fuente": tipo}
    if monitor is not None:
        valores["monitor_captura"] = str(int(monitor))
    if indice is not None:
        valores["indice_camara"] = str(int(indice))
    if programa is not None:
        valores["ventana_programa"] = programa.strip().lower().replace("=", "")
    if titulo is not None:
        valores["ventana_titulo"] = titulo.strip().replace("\n", " ").replace("=", "")
    if tipo == "ventana" and not valores.get("ventana_programa") and not valores.get("ventana_titulo"):
        raise ValueError("Elige la aplicación que se va a capturar.")
    ruta = Path(settings.ARCHIVO_CONFIGURACION)
    lineas = ruta.read_text(encoding="utf-8-sig").splitlines() if ruta.is_file() else []
    inicio = next((i for i, linea in enumerate(lineas) if linea.strip().lower() == "[camara]"), None)
    if inicio is None:
        lineas += ([""] if lineas else []) + ["[camara]"] + [f"{c} = {v}" for c, v in valores.items()]
    else:
        fin = next((i for i in range(inicio + 1, len(lineas)) if lineas[i].strip().startswith("[")), len(lineas))
        pendientes = dict(valores)
        for i in range(inicio + 1, fin):
            clave = lineas[i].split("=", 1)[0].strip().lower()
            if "=" in lineas[i] and not lineas[i].lstrip().startswith(("#", ";")) and clave in pendientes:
                lineas[i] = f"{clave} = {pendientes.pop(clave)}"
        while fin > inicio + 1 and not lineas[fin - 1].strip():
            fin -= 1  # las claves nuevas van antes de la línea en blanco que separa las secciones
        lineas[fin:fin] = [f"{c} = {v}" for c, v in pendientes.items()]
    _escribir_atomico(ruta, "\n".join(lineas) + "\n")
    if url_rtsp is not None:
        url_rtsp = url_rtsp.strip()
        if url_rtsp and not url_rtsp.lower().startswith(("rtsp://", "rtsps://", "http://", "https://")):
            raise ValueError("La dirección de la cámara debe empezar con rtsp://")
        datos = {}
        try:
            datos = json.loads(ARCHIVO_CAMARA.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        datos["rtsp_url"] = url_rtsp
        _escribir_atomico(ARCHIVO_CAMARA, json.dumps(datos, ensure_ascii=False, indent=2) + "\n")


def huella_archivos():
    """Cambia cuando se edita observatorio.ini o camara_local.json."""
    huella = []
    for ruta in (settings.ARCHIVO_CONFIGURACION, ARCHIVO_CAMARA):
        try:
            estado = Path(ruta).stat()
            huella.append((estado.st_mtime_ns, estado.st_size))
        except OSError:
            huella.append(None)
    return tuple(huella)


def escribir_estado_kiosco(fuente):
    datos = {
        "tipo": fuente.tipo, "descripcion": fuente.descripcion, "estado": fuente.estado,
        "error": fuente.ultimo_error[:200], "actualizado": time.time(), "pid": os.getpid(),
    }
    try:
        _escribir_atomico(ARCHIVO_ESTADO, json.dumps(datos, ensure_ascii=False))
    except OSError:
        pass


def leer_estado_kiosco():
    """Estado del kiosco, o None si no está abierto (sin noticias en los últimos 10 s)."""
    try:
        datos = json.loads(ARCHIVO_ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return datos if time.time() - datos.get("actualizado", 0) < 10 else None


def vigilar(fuente, detener, intervalo=2.0):
    """Hilo del kiosco: aplica en vivo los cambios de fuente hechos en el portal y publica su estado."""
    ultima = huella_archivos()
    # Lo que usa el kiosco al abrir (puede venir de --fuente). Solo un cambio posterior en
    # los archivos lo reemplaza.
    configurada = (fuente.tipo, fuente.origen)
    while not detener.wait(intervalo):
        escribir_estado_kiosco(fuente)
        actual = huella_archivos()
        if actual == ultima:
            continue
        ultima = actual
        nueva = origen_de(leer_fuente())
        if nueva != configurada:
            configurada = nueva
            fuente.cambiar(*nueva)
