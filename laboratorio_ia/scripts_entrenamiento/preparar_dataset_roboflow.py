"""
Convierte una exportación de Roboflow en formato YOLOv8 (cajas o polígonos)
en la carpeta del clasificador (modo "dos etapas"):

    laboratorio_ia/dataset_aves/{train,val,test}/<Especie>/

Cada ave anotada se recorta con su caja exacta, igual que en la inferencia.

Si prefieres el modo "una etapa" (el detector reconoce la especie
directamente), no necesitas este script: usa laboratorio_ia/scripts_entrenamiento/entrenar_detector.py
con el data.yaml de Roboflow.

La división train/val/test se rehace aquí por foto de origen (los recortes
de una misma foto nunca quedan en divisiones distintas). Se busca repartir
la evidencia de cada especie entre train, val y test sin dividir esos grupos.

Uso (desde la carpeta del proyecto, con el entorno virtual activado):

    python laboratorio_ia/scripts_entrenamiento/preparar_dataset_roboflow.py RUTA_EXPORTACION_ROBOFLOW
"""
import argparse
import ast
import hashlib
import random
import re
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

LABORATORIO = Path(__file__).resolve().parents[1]

# Clase en Roboflow -> nombre de carpeta en dataset_aves (= clase del
# clasificador). config/clases_modelo.json traduce ese nombre a la especie
# del catálogo (comparando sin tildes, espacios ni mayúsculas).
ESPECIES = {
    "Cisne Cuello Negro": "Cisne de cuello negro",
    "Gaviota franklin": "Gaviota de Franklin",
    "Huala": "Huala",
    "Pato Cuchara": "Pato cuchara",
    "Pato jergongrande": "Pato jergon grande",
    "Pato rana pico delgado": "Pato rana de pico delgado",
    "Tagua": "Tagua común",
    "Yeco": "Yeco",
    "Pato anteojillo": "Pato anteojillo",
    "Martin pescador": "Martin pescador",
}

DIVISIONES_ORIGEN = ("train", "valid", "test")
DIVISIONES = ("train", "val", "test")
MINIMO_POR_DIVISION = 20
FRACCION_VAL = 0.15
FRACCION_TEST = 0.15
SEMILLA = 0
LADO_MINIMO = 40
EXTENSIONES = (".jpg", ".jpeg", ".png")


def clave(nombre):
    texto = unicodedata.normalize("NFKD", str(nombre).strip().lower())
    return re.sub(r"[^a-z0-9]", "", texto)


def leer_nombres(ruta_yaml):
    texto = ruta_yaml.read_text(encoding="utf-8-sig")
    try:
        import yaml

        nombres = yaml.safe_load(texto)["names"]
    except ImportError:
        coincidencia = re.search(r"^names:\s*(\[.*\])\s*$", texto, re.MULTILINE)
        if not coincidencia:
            raise SystemExit("No se pudo leer 'names' de data.yaml; instala pyyaml.")
        nombres = ast.literal_eval(coincidencia.group(1))
    if isinstance(nombres, dict):
        por_indice = {int(indice): nombre for indice, nombre in nombres.items()}
        if len(por_indice) != len(nombres) or set(por_indice) != set(range(len(nombres))):
            raise ValueError("Los índices de clase de data.yaml deben comenzar en 0 y ser consecutivos.")
        nombres = [por_indice[indice] for indice in range(len(nombres))]
    if not isinstance(nombres, list) or not nombres or any(not isinstance(n, str) or not n.strip() for n in nombres):
        raise ValueError("data.yaml debe incluir nombres de clase válidos.")
    return nombres


def caja_de_linea(valores, ancho, alto):
    """Devuelve (x1, y1, x2, y2) en píxeles para una línea de etiqueta."""
    try:
        numeros = np.array(valores, dtype=float)
    except ValueError:
        return None
    if not np.isfinite(numeros).all() or np.any((numeros < 0) | (numeros > 1)):
        return None
    if len(numeros) == 4:
        cx, cy, w, h = numeros
        x1, x2 = (cx - w / 2) * ancho, (cx + w / 2) * ancho
        y1, y2 = (cy - h / 2) * alto, (cy + h / 2) * alto
    elif len(numeros) >= 6 and len(numeros) % 2 == 0:
        xs, ys = numeros[0::2] * ancho, numeros[1::2] * alto
        x1, x2, y1, y2 = xs.min(), xs.max(), ys.min(), ys.max()
    else:
        return None
    x1, y1 = int(max(0, x1)), int(max(0, y1))
    x2, y2 = int(min(ancho, x2)), int(min(alto, y2))
    return x1, y1, x2, y2


def asignar_divisiones(recortes):
    """Asigna cada origen una sola vez, con balance aproximado por especie."""
    totales = Counter(especie for filas in recortes.values() for especie, *_ in filas)
    metas = {}
    for especie, total in totales.items():
        minimo = MINIMO_POR_DIVISION if total >= 3 * MINIMO_POR_DIVISION else 1
        test = max(minimo, round(total * FRACCION_TEST))
        val = max(minimo, round(total * FRACCION_VAL))
        metas[especie] = {"train": max(1, total - val - test), "val": val, "test": test}
    conteos = {division: Counter() for division in DIVISIONES}
    grupos = sorted(recortes)
    random.Random(SEMILLA).shuffle(grupos)
    grupos.sort(key=lambda foto: len(recortes[foto]), reverse=True)
    for foto in grupos:
        cantidades = Counter(especie for especie, *_ in recortes[foto])

        def costo(division):
            cambio = 0.0
            for especie, n in cantidades.items():
                meta = metas[especie][division]
                diferencia = conteos[division][especie] - meta
                cambio += ((diferencia + n) ** 2 - diferencia ** 2) / meta
            return cambio

        division = min(DIVISIONES, key=costo)
        conteos[division].update(cantidades)
        yield foto, division


def es_recorte_roboflow(ruta):
    return ruta.suffix.lower() in EXTENSIONES and (ruta.stem.startswith("rf_") or ".rf." in ruta.stem)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("origen", type=Path, help="Carpeta de la exportación de Roboflow")
    parser.add_argument("--destino", type=Path, default=LABORATORIO)
    parser.add_argument("--limpiar", action="store_true", help="Reemplaza los recortes de Roboflow de las especies seleccionadas")
    args = parser.parse_args()

    nombres = leer_nombres(args.origen / "data.yaml")
    carpeta_dataset = args.destino / "dataset_aves"

    destinos_por_nombre = {clave(n): destino for original, destino in ESPECIES.items() for n in (original, destino)}
    presentes = {i: destinos_por_nombre[clave(n)] for i, n in enumerate(nombres) if clave(n) in destinos_por_nombre}
    faltantes = sorted(set(ESPECIES.values()) - set(presentes.values()))
    if not presentes:
        raise SystemExit("Ninguna clase de data.yaml coincide con ESPECIES.")

    carpetas_destino = {carpeta_dataset / division / nombre for division in DIVISIONES for nombre in presentes.values()}
    existentes = [
        f for ruta in carpetas_destino if ruta.is_dir()
        for f in ruta.iterdir() if f.is_file() and es_recorte_roboflow(f)
    ]
    if existentes and not args.limpiar:
        raise SystemExit("Ya hay recortes de Roboflow en el destino. Usa --limpiar para regenerarlos o elige otro destino.")

    descartados = 0
    recortes = defaultdict(list)
    fotos_vistas = set()
    duplicados = 0
    cajas_duplicadas = 0

    for division_origen in (*DIVISIONES_ORIGEN, "val"):
        carpeta_imagenes = args.origen / division_origen / "images"
        carpeta_etiquetas = args.origen / division_origen / "labels"
        if not carpeta_imagenes.exists():
            continue
        for ruta_imagen in sorted(carpeta_imagenes.iterdir()):
            if ruta_imagen.suffix.lower() not in EXTENSIONES:
                continue
            ruta_etiqueta = carpeta_etiquetas / (ruta_imagen.stem + ".txt")
            if not ruta_etiqueta.exists():
                continue
            datos = ruta_imagen.read_bytes()
            huella = hashlib.sha256(datos).hexdigest()
            if huella in fotos_vistas:
                duplicados += 1
                continue
            imagen = cv2.imdecode(np.frombuffer(datos, dtype=np.uint8), cv2.IMREAD_COLOR)
            if imagen is None:
                print(f"No se pudo leer: {ruta_imagen}")
                continue
            alto, ancho = imagen.shape[:2]
            origen = ruta_imagen.stem.lower().split(".rf.", 1)[0]
            grupo = hashlib.sha256(origen.encode("utf-8")).hexdigest()[:24]
            cajas_vistas = {}
            for indice, texto in enumerate(ruta_etiqueta.read_text(encoding="utf-8-sig").splitlines()):
                linea = texto.split()
                if not linea:
                    continue
                try:
                    clase = int(linea[0])
                except ValueError:
                    descartados += 1
                    continue
                if clase not in presentes:
                    continue
                destino = presentes[clase]
                caja = caja_de_linea(linea[1:], ancho, alto)
                if caja is None:
                    descartados += 1
                    continue
                x1, y1, x2, y2 = caja
                if min(x2 - x1, y2 - y1) < LADO_MINIMO:
                    descartados += 1
                    continue
                anterior = cajas_vistas.get(caja)
                if anterior is not None:
                    if anterior != destino:
                        raise SystemExit(f"{ruta_etiqueta}: la misma caja identifica {anterior} y {destino}.")
                    cajas_duplicadas += 1
                    continue
                cajas_vistas[caja] = destino
                nombre = f"rf_{grupo}_{huella[:24]}_{indice}.jpg"
                correcto, jpg = cv2.imencode(".jpg", imagen[y1:y2, x1:x2], [cv2.IMWRITE_JPEG_QUALITY, 95])
                if not correcto:
                    raise OSError(f"No se pudo codificar {nombre}")
                recortes[grupo].append((destino, nombre, jpg.tobytes()))
                fotos_vistas.add(huella)

    if not recortes:
        raise SystemExit("No se encontraron recortes válidos. Revisa la exportación antes de limpiar el destino.")
    conteo = {d: {v: 0 for v in DIVISIONES} for d in presentes.values()}
    avisos = []
    args.destino.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="recortes-", dir=args.destino) as temporal:
        pendientes = {}
        for foto, division in asignar_divisiones(recortes):
            for destino, nombre, datos in recortes[foto]:
                salida = carpeta_dataset / division / destino / nombre
                temporal_jpg = Path(temporal) / division / destino / nombre
                temporal_jpg.parent.mkdir(parents=True, exist_ok=True)
                temporal_jpg.write_bytes(datos)
                pendientes[salida] = temporal_jpg
                conteo[destino][division] += 1
        for salida, temporal_jpg in pendientes.items():
            salida.parent.mkdir(parents=True, exist_ok=True)
            temporal_jpg.replace(salida)
        if args.limpiar:
            for anterior in set(existentes) - pendientes.keys():
                anterior.unlink()
    for destino, cantidades in conteo.items():
        cortas = [v for v in DIVISIONES if cantidades[v] < MINIMO_POR_DIVISION]
        if cortas:
            avisos.append(f"{destino}: menos de {MINIMO_POR_DIVISION} en {', '.join(cortas)} (total {sum(cantidades.values())})")

    print(f"{'especie':22}{'train':>7}{'val':>7}{'test':>7}")
    for destino, c in conteo.items():
        print(f"{destino:22}{c['train']:>7}{c['val']:>7}{c['test']:>7}")
    print(f"Recortes descartados por tamaño o formato: {descartados}")
    print(f"Fotos duplicadas por contenido omitidas: {duplicados}")
    print(f"Cajas duplicadas omitidas: {cajas_duplicadas}")
    for aviso in avisos:
        print("AVISO -", aviso)
    if faltantes:
        print("Especies de ESPECIES que aún no están en la exportación:")
        for nombre in faltantes:
            print(f"  - {nombre}")


if __name__ == "__main__":
    sys.exit(main())
