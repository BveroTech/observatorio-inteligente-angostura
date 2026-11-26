"""
Descarga fotos de aves desde iNaturalist y las agrega a laboratorio_ia/dataset_aves/.

    python laboratorio_ia/scripts_entrenamiento/descargar_fotos_inaturalist.py
    python laboratorio_ia/scripts_entrenamiento/descargar_fotos_inaturalist.py --cantidad 150
    python laboratorio_ia/scripts_entrenamiento/descargar_fotos_inaturalist.py --especies "Chincol" "Torcaza"

Qué hace, para cada una de las 10 especies foco:
  1. Busca observaciones de "grado investigación" (identificación confirmada
     por la comunidad) con fotos de licencia libre (CC0, CC BY, CC BY-NC).
  2. Descarga una foto por observación, hasta completar --cantidad imágenes
     por especie (cuenta las que ya tienes).
  3. Recorta el ave con YOLO (yolov8n.pt detecta "bird"), igual que hará la
     cámara. Descarta fotos sin una detección única y de tamaño suficiente.
  4. Reparte: primero completa test y val (mínimo 20 cada una) y el resto va
     a train. Una observación nunca queda en dos carpetas.
  5. Anota autor y licencia de cada foto en laboratorio_ia/dataset_aves/creditos_inaturalist.csv
     (cítalo en el informe).

Para especies con pocas fotos libres (p. ej. Pato anteojillo, ~330 observaciones):

    python ... --especies "Pato anteojillo" --cantidad 400 --fotos-por-observacion 4 \\
               --foto-grande --parejas --licencias cc0,cc-by,cc-by-nc,cc-by-sa,cc-by-nc-sa

  --fotos-por-observacion  también baja la 2.ª, 3.ª… foto de cada observación
                           (inat_<id>_<n>.jpg), siempre en la MISMA división
                           que la primera, para no filtrar datos entre train y test.
  --foto-grande            1024 px en vez de 500 px (aves lejanas pasan el filtro).
  --parejas                acepta fotos con varias aves si la mayor duplica en área
                           a la siguiente. Puede colar otra especie: revisar después
                           con revisar_etiquetas.py.
  No se usan licencias ND (sin derivados): recortar la foto es una obra derivada.

Se puede interrumpir y volver a ejecutar: no repite fotos ya descargadas y
cada crédito se guarda en el momento (ninguna foto queda sin autor/licencia).
Requiere internet y el entorno de entrenamiento (instalar_entrenamiento.bat).
"""
import argparse
import csv
import io
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
LABORATORIO = Path(__file__).resolve().parents[1]
DATASET = LABORATORIO / "dataset_aves"
CREDITOS = DATASET / "creditos_inaturalist.csv"
PESOS_YOLO = LABORATORIO / "pesos_pytorch" / "yolov8n.pt"
API = "https://api.inaturalist.org/v1/observations"
AGENTE = "ObservatorioAvesAngostura/1.0 (proyecto de titulo INACAP)"
LICENCIAS = "cc0,cc-by,cc-by-nc"
DIVISIONES = ("train", "val", "test")
MINIMO_EVAL = 20          # mínimo de imágenes en val y en test
MINIMO_TRAIN = 20
FRACCION_EVAL = 0.15
LADO_MINIMO = 64
EXTENSIONES = (".jpg", ".jpeg", ".png")
DESCARGAS_PARALELAS = 8   # fotos simultáneas (las consultas a la API siguen siendo de a una)

# Ajustables desde la línea de comandos (ver main).
OPCIONES = {
    "licencias": LICENCIAS,
    "fotos_por_observacion": 1,   # >1: también las fotos 2, 3… de cada observación
    "tamano_foto": "medium",      # medium (500 px) o large (1024 px)
    "parejas": False,             # admitir fotos con 2+ aves si una domina
}

# Carpeta en dataset_aves  ->  nombres científicos a buscar (el primero que tenga fotos)
ESPECIES = {
    "Cisne de cuello negro": ["Cygnus melancoryphus"],
    "Gaviota de Franklin": ["Leucophaeus pipixcan"],
    "Huala": ["Podiceps major"],
    "Pato cuchara": ["Spatula platalea"],
    "Pato jergon grande": ["Anas georgica"],
    "Pato rana de pico delgado": ["Oxyura vittata"],
    "Tagua común": ["Fulica armillata"],
    "Yeco": ["Nannopterum brasilianum", "Phalacrocorax brasilianus"],
    "Pato anteojillo": ["Speculanas specularis"],
    "Martin pescador": ["Megaceryle torquata"],
}


def pedir(url, intentos=3):
    for intento in range(intentos):
        try:
            solicitud = urllib.request.Request(url, headers={"User-Agent": AGENTE})
            with urllib.request.urlopen(solicitud, timeout=30) as respuesta:
                return respuesta.read()
        except Exception as error:
            if intento == intentos - 1:
                raise
            print(f"    reintentando ({error})")
            time.sleep(3 * (intento + 1))


def observaciones(nombre_cientifico, pagina):
    parametros = {
        "taxon_name": nombre_cientifico,
        "quality_grade": "research",
        "photos": "true",
        "photo_license": OPCIONES["licencias"],
        "per_page": 100,
        "page": pagina,
        "order_by": "votes",
    }
    datos = json.loads(pedir(API + "?" + urllib.parse.urlencode(parametros)))
    time.sleep(1.0)  # respetar el límite de la API (~60 consultas por minuto)
    return datos.get("results", []), datos.get("total_results", 0)


class Recortador:
    """Recorta la caja exacta de la única ave detectable de tamaño suficiente."""

    def __init__(self, activo=True):
        self.modelo = None
        if not activo:
            return
        try:
            from ultralytics import YOLO
        except ImportError:
            raise SystemExit("Falta Ultralytics. Instálalo o elige --sin-recorte explícitamente.")
        ruta_pesos = PESOS_YOLO if PESOS_YOLO.exists() else RAIZ / "yolov8n.pt"
        self.modelo = YOLO(str(ruta_pesos))

    def recortar(self, imagen):
        """imagen PIL RGB -> recorte PIL o None si no hay ave.

        Normalmente exige una sola ave. Con OPCIONES["parejas"], si hay varias
        se queda con la mayor cuando duplica en área a la siguiente (típico de
        parejas fotografiadas: el ave principal domina la foto)."""
        if self.modelo is None:
            return imagen
        resultado = self.modelo.predict(imagen, classes=[14], conf=0.25, verbose=False)[0]
        cajas = resultado.boxes.xyxy.tolist() if resultado.boxes is not None else []
        cajas_validas = []
        ancho, alto = imagen.size
        for x1, y1, x2, y2 in cajas:
            caja = (max(0, int(x1)), max(0, int(y1)), min(ancho, int(x2)), min(alto, int(y2)))
            if min(caja[2] - caja[0], caja[3] - caja[1]) >= LADO_MINIMO:
                cajas_validas.append(caja)
        if len(cajas_validas) == 1:
            return imagen.crop(cajas_validas[0])
        if OPCIONES["parejas"] and len(cajas_validas) > 1:
            area = lambda c: (c[2] - c[0]) * (c[3] - c[1])  # noqa: E731
            cajas_validas.sort(key=area, reverse=True)
            if area(cajas_validas[0]) >= 2 * area(cajas_validas[1]):
                return imagen.crop(cajas_validas[0])
        return None


class Creditos:
    """CSV de créditos que se guarda fila a fila: si la descarga se interrumpe,
    ninguna foto queda sin su autor y licencia."""

    def __init__(self, archivo):
        self.archivo = archivo
        self.escritor = csv.writer(archivo, delimiter=";")

    def writerow(self, fila):
        self.escritor.writerow(fila)
        self.archivo.flush()


def contar(carpeta):
    return sum(1 for f in carpeta.iterdir() if f.suffix.lower() in EXTENSIONES) if carpeta.is_dir() else 0


def ya_descargadas():
    """id de observación -> división donde ya tiene fotos (inat_<id>.jpg o inat_<id>_<n>.jpg)."""
    return {
        f.stem.split("_", 2)[1]: division for division in DIVISIONES
        for f in (DATASET / division).glob("*/inat_*") if f.is_file() and f.suffix.lower() in EXTENSIONES
    }


def elegir_division(conteo, meta_total):
    meta_eval = max(MINIMO_EVAL, round(meta_total * FRACCION_EVAL))
    if conteo["test"] < meta_eval:
        return "test"
    if conteo["val"] < meta_eval:
        return "val"
    return "train"


def procesar_especie(especie, nombres, cantidad, recortador, creditos, vistos):
    from PIL import Image

    for division in DIVISIONES:
        (DATASET / division / especie).mkdir(parents=True, exist_ok=True)
    conteo = {d: contar(DATASET / d / especie) for d in DIVISIONES}
    meta_eval = max(MINIMO_EVAL, round(cantidad * FRACCION_EVAL))
    deficit_eval = sum(max(0, meta_eval - conteo[d]) for d in ("val", "test"))
    deficit_train = max(0, MINIMO_TRAIN - conteo["train"])
    faltan = max(cantidad - sum(conteo.values()), deficit_eval + deficit_train)
    print(f"\n{especie}: tiene {sum(conteo.values())} (train {conteo['train']}, val {conteo['val']}, "
          f"test {conteo['test']})")
    if faltan <= 0:
        print("  ya tiene la cantidad pedida.")
        return 0
    agregadas = descartadas = 0
    procesadas = set()
    for nombre in nombres:
        pagina, total = 1, None
        while agregadas < faltan:
            try:
                resultados, total = observaciones(nombre, pagina)
            except Exception as error:
                print(f"  No se pudo consultar iNaturalist: {error}")
                return agregadas
            if pagina == 1:
                print(f"  {nombre}: {total} observaciones disponibles")
            if not resultados:
                break
            pendientes = []
            licencias = OPCIONES["licencias"].split(",")
            for obs in resultados:
                id_obs = str(obs.get("id") or "")
                fotos = [f for f in obs.get("photos", []) if f.get("url") and f.get("license_code") in licencias]
                if not id_obs or id_obs in procesadas or not fotos:
                    continue
                procesadas.add(id_obs)
                if id_obs in vistos and OPCIONES["fotos_por_observacion"] == 1:
                    continue
                for indice, foto in enumerate(fotos[:OPCIONES["fotos_por_observacion"]]):
                    if not (DATASET / vistos.get(id_obs, "-") / especie / nombre_archivo(id_obs, indice)).exists():
                        pendientes.append((id_obs, indice, foto))

            def bajar(pendiente):
                id_obs, _, foto = pendiente
                try:
                    url = foto["url"].replace("/square.", f"/{OPCIONES['tamano_foto']}.")
                    return Image.open(io.BytesIO(pedir(url))).convert("RGB")
                except Exception as error:
                    print(f"    no se pudo descargar la observación {id_obs}: {error}")
                    return None

            # Las fotos (servidor estático de iNaturalist) se bajan en paralelo;
            # el recorte con YOLO y el guardado siguen siendo en orden.
            with ThreadPoolExecutor(max_workers=DESCARGAS_PARALELAS) as grupo:
                imagenes = grupo.map(bajar, pendientes)
                for (id_obs, indice, foto), imagen in zip(pendientes, imagenes):
                    if agregadas >= faltan:
                        break
                    if imagen is None:
                        continue
                    agregadas, descartadas = guardar(
                        especie, nombre, id_obs, indice, foto, imagen, recortador, conteo, cantidad, creditos,
                        agregadas, descartadas, faltan, vistos,
                    )
            pagina += 1
            if total is not None and (pagina - 1) * 100 >= total:
                break
        if agregadas >= faltan:
            break
    print(f"  +{agregadas} fotos (train {conteo['train']}, val {conteo['val']}, test {conteo['test']})"
          f"{f' · {descartadas} sin ave detectable descartadas' if descartadas else ''}")
    if conteo["val"] < MINIMO_EVAL or conteo["test"] < MINIMO_EVAL:
        print(f"  AVISO: no alcanzó {MINIMO_EVAL} fotos en val/test; esta especie tiene pocas fotos libres en iNaturalist.")
    return agregadas


def nombre_archivo(id_obs, indice):
    return f"inat_{id_obs}.jpg" if indice == 0 else f"inat_{id_obs}_{indice}.jpg"


def guardar(especie, nombre, id_obs, indice, foto, imagen, recortador, conteo, cantidad, creditos,
            agregadas, descartadas, faltan, vistos):
    """Recorta el ave, la guarda en su división y anota el crédito al instante.

    Todas las fotos de una observación van a la misma división (train, val o
    test): así el modelo nunca se evalúa con fotos del mismo momento que vio."""
    recorte = recortador.recortar(imagen)
    if recorte is None:
        return agregadas, descartadas + 1
    division = vistos.get(id_obs) or elegir_division(conteo, cantidad)
    vistos[id_obs] = division
    destino = DATASET / division / especie / nombre_archivo(id_obs, indice)
    if destino.exists():
        return agregadas, descartadas
    recorte.save(destino, quality=92)
    conteo[division] += 1
    agregadas += 1
    creditos.writerow([
        especie, nombre, division, destino.name, id_obs,
        f"https://www.inaturalist.org/observations/{id_obs}",
        foto.get("attribution", ""), foto.get("license_code", ""),
    ])
    if agregadas % 10 == 0:
        print(f"    {agregadas}/{faltan} agregadas…")
    return agregadas, descartadas


def main():
    parser = argparse.ArgumentParser(description="Descarga fotos de iNaturalist a dataset_aves")
    parser.add_argument("--cantidad", type=int, default=120, help="Imágenes totales por especie (default 120)")
    parser.add_argument("--especies", nargs="*", help="Solo estas carpetas (por defecto, las 10 especies foco)")
    parser.add_argument("--sin-recorte", action="store_true", help="Guardar la foto completa, sin recortar el ave")
    # Para especies con pocas fotos (p. ej. Pato anteojillo):
    parser.add_argument("--fotos-por-observacion", type=int, default=1,
                        help="Fotos por observación (las extra van a la misma división que la primera)")
    parser.add_argument("--foto-grande", action="store_true", help="Descargar 1024 px en vez de 500 px")
    parser.add_argument("--parejas", action="store_true", help="Admitir fotos con varias aves si una domina")
    parser.add_argument("--licencias", default=LICENCIAS,
                        help=f"Licencias aceptadas, separadas por coma (default {LICENCIAS})")
    args = parser.parse_args()
    OPCIONES.update(
        licencias=args.licencias,
        fotos_por_observacion=max(1, args.fotos_por_observacion),
        tamano_foto="large" if args.foto_grande else "medium",
        parejas=args.parejas,
    )
    if args.cantidad < 2 * MINIMO_EVAL + MINIMO_TRAIN:
        parser.error(f"--cantidad debe permitir {MINIMO_TRAIN} fotos de train y {MINIMO_EVAL} en val y test.")

    elegidas = {e: n for e, n in ESPECIES.items() if not args.especies or e in args.especies}
    if args.especies:
        desconocidas = [e for e in args.especies if e not in ESPECIES]
        if desconocidas:
            print("No conozco estas especies:", ", ".join(desconocidas))
            print("Opciones:", ", ".join(ESPECIES))
            return 1
    recortador = Recortador(activo=not args.sin_recorte)
    nuevo = not CREDITOS.exists()
    DATASET.mkdir(parents=True, exist_ok=True)
    total = 0
    vistos = ya_descargadas()
    with open(CREDITOS, "a", newline="", encoding="utf-8-sig") as archivo:
        creditos = Creditos(archivo)
        if nuevo:
            creditos.writerow(["especie", "nombre_cientifico", "division", "archivo", "id_observacion",
                               "url", "autor", "licencia"])
        for especie, nombres in elegidas.items():
            total += procesar_especie(especie, nombres, args.cantidad, recortador, creditos, vistos)
    print(f"\nListo: {total} fotos nuevas. Créditos en laboratorio_ia/dataset_aves/{CREDITOS.name}")
    print("Siguiente paso: revisa algunas fotos y ejecuta entrenar_clasificador.bat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
