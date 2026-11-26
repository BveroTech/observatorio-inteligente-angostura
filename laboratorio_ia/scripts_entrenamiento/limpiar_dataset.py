"""
Deja laboratorio_ia/dataset_aves/ solo con las 10 especies de entrenamiento, una carpeta por
especie y con el mismo nombre en train, val y test.

    python laboratorio_ia/scripts_entrenamiento/limpiar_dataset.py            ordena el dataset
    python laboratorio_ia/scripts_entrenamiento/limpiar_dataset.py --simular  solo muestra qué haría

Qué hace en train/, val/ y test/:
  - Repara nombres con tildes dañadas al descomprimir en Windows
    (por ejemplo «Tagua comÃºn» o «Tagua com├║n» -> «Tagua común»).
  - Junta en una sola carpeta las variantes de una misma especie
    («Tagua», «Tagua común», «Cisne», «Cisne de cuello negro»…).
  - Mueve las especies que ya no se entrenan (Torcaza, Chincol, etc.) a
    laboratorio_ia/dataset_aves_anterior/. No borra nada: se puede recuperar desde ahí.
  - Una foto repetida (mismo contenido para una especie)
    se deja una sola vez; la copia va a laboratorio_ia/dataset_aves_anterior/repetidas/.
"""
import argparse
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
LABORATORIO = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from descargar_fotos_inaturalist import ESPECIES  # noqa: E402  carpeta -> [nombres científicos]
from src.procesamiento.inferencia_onnx import cargar_clases_modelo, clave_clase  # noqa: E402

DATASET = LABORATORIO / "dataset_aves"
ANTERIOR = LABORATORIO / "dataset_aves_anterior"
DIVISIONES = ("train", "val", "test")
EXTENSIONES = (".jpg", ".jpeg", ".png")
MINIMO = 20


def variantes_nombre(nombre):
    """El nombre tal cual y sus posibles reparaciones si la tilde se dañó al
    descomprimir (UTF-8 leído como cp437, cp850 o cp1252)."""
    yield nombre
    for codificacion in ("cp437", "cp850", "cp1252"):
        try:
            reparado = nombre.encode(codificacion).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if reparado != nombre:
            yield reparado


def carpeta_destino(nombre, mapa, canonicas):
    """Nombre de carpeta oficial para una carpeta del dataset, o None si no se entrena."""
    for variante in variantes_nombre(nombre):
        cientifico = mapa.get(clave_clase(variante))
        if cientifico:
            return canonicas.get(cientifico.lower())
    return None


def diagnosticar(dataset=DATASET):
    """Lista de problemas que impiden un entrenamiento limpio (vacía si está bien)."""
    mapa = cargar_clases_modelo()
    canonicas = {n.lower(): carpeta for carpeta, nombres in ESPECIES.items() for n in nombres}
    problemas = []
    for division in DIVISIONES:
        ruta = dataset / division
        if not ruta.is_dir():
            continue
        for carpeta in sorted(p for p in ruta.iterdir() if p.is_dir()):
            destino = carpeta_destino(carpeta.name, mapa, canonicas)
            if destino is None:
                problemas.append(f"{division}/{carpeta.name}: no es una de las 10 especies de entrenamiento")
            elif destino != carpeta.name:
                problemas.append(f"{division}/{carpeta.name}: debería llamarse «{destino}»")
    return problemas


def mover(origen, destino, simular):
    if not simular:
        destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        base, n = destino, 2
        while destino.exists():
            destino = base.with_name(f"{base.stem}_{n}{base.suffix}")
            n += 1
    if not simular:
        shutil.move(str(origen), str(destino))


def main():
    parser = argparse.ArgumentParser(description="Ordena dataset_aves para las 10 especies de entrenamiento")
    parser.add_argument("--simular", action="store_true", help="Solo muestra lo que haría")
    args = parser.parse_args()

    if not DATASET.is_dir():
        print(f"No existe {DATASET}")
        return 1
    mapa = cargar_clases_modelo()
    canonicas = {n.lower(): carpeta for carpeta, nombres in ESPECIES.items() for n in nombres}
    vistos = {carpeta: {} for carpeta in ESPECIES}  # especie -> {huella de imagen: división}
    movidas = juntadas = repetidas = 0

    for division in DIVISIONES:
        ruta = DATASET / division
        if not ruta.is_dir():
            continue
        carpetas = [p for p in ruta.iterdir() if p.is_dir()]
        # Primero las carpetas que ya tienen el nombre correcto: son las que mandan.
        carpetas.sort(key=lambda p: (carpeta_destino(p.name, mapa, canonicas) != p.name, p.name))
        for carpeta in carpetas:
            destino = carpeta_destino(carpeta.name, mapa, canonicas)
            if destino is None:
                print(f"  fuera:   {division}/{carpeta.name}  ->  dataset_aves_anterior/{division}/")
                mover(carpeta, ANTERIOR / division / carpeta.name, args.simular)
                movidas += 1
                continue
            if destino != carpeta.name:
                print(f"  juntar:  {division}/{carpeta.name}  ->  {division}/{destino}")
                juntadas += 1
                canonica = ruta / destino
                if not args.simular and canonica.exists() and canonica.samefile(carpeta):
                    # Windows considera iguales dos rutas que difieren solo en mayúsculas.
                    with tempfile.TemporaryDirectory(dir=ruta) as temporal:
                        intermedia = Path(temporal) / carpeta.name
                        carpeta.rename(intermedia)
                        try:
                            intermedia.rename(canonica)
                        except OSError:
                            intermedia.rename(carpeta)
                            raise
                    carpeta = canonica
            for archivo in sorted(carpeta.iterdir()):
                if not archivo.is_file() or archivo.suffix.lower() not in EXTENSIONES:
                    continue
                huella = hashlib.sha256(archivo.read_bytes()).digest()
                anterior = vistos[destino].get(huella)
                if anterior is not None:
                    mover(archivo, ANTERIOR / "repetidas" / division / destino / archivo.name, args.simular)
                    repetidas += 1
                    continue
                vistos[destino][huella] = division
                if destino != carpeta.name:
                    mover(archivo, ruta / destino / archivo.name, args.simular)
            if destino != carpeta.name and not args.simular:
                restos = list(carpeta.iterdir())
                if restos:
                    mover(carpeta, ANTERIOR / division / carpeta.name, args.simular)
                else:
                    carpeta.rmdir()

    print(f"\nCarpetas fuera del entrenamiento: {movidas} · variantes juntadas: {juntadas} · "
          f"fotos repetidas apartadas: {repetidas}")
    print(f"\n{'especie':28}{'train':>7}{'val':>7}{'test':>7}")
    faltan = []
    for especie in ESPECIES:
        conteo = {d: sum(1 for n, div in vistos[especie].items() if div == d) for d in DIVISIONES}
        print(f"{especie:28}{conteo['train']:>7}{conteo['val']:>7}{conteo['test']:>7}")
        if min(conteo.values()) < MINIMO:
            faltan.append(especie)
    if faltan:
        print(f"\nCon menos de {MINIMO} fotos en alguna división (completa con descargar_fotos.bat):")
        for especie in faltan:
            print(f"  - {especie}")
        print('  Ejemplo: .\\descargar_fotos.bat --especies "' + '" "'.join(faltan) + '"')
    if args.simular:
        print("\n(simulación: no se movió nada)")
    else:
        print("\nListo. Siguiente paso: entrenar_clasificador.bat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
