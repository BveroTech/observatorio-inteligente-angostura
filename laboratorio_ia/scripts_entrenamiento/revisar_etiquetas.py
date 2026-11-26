"""
Busca fotos posiblemente mal etiquetadas en laboratorio_ia/dataset_aves/ para revisarlas a mano.

    python laboratorio_ia/scripts_entrenamiento/revisar_etiquetas.py --modelo RUTA\\best.pt
    python laboratorio_ia/scripts_entrenamiento/revisar_etiquetas.py --modelo RUTA\\best.pt --apartar lista.txt

Paso 1 (sin --apartar): clasifica todas las fotos de train, val y test con un
modelo ya entrenado y lista las que el modelo asigna con confianza ≥ --confianza
a OTRA especie. Deja en laboratorio_ia/reportes/revision_etiquetas/:
    sospechosas.csv          archivo; etiqueta; predicha; confianza
    hoja_<especie>.jpg       miniaturas numeradas para mirarlas
El modelo solo SUGIERE: hay que abrir cada foto y decidir. Una foto se
aparta solo si claramente no es la especie de su carpeta (otra especie,
no es un ave, ave irreconocible). Si el modelo se equivoca, la foto se queda.

Paso 2 (--apartar lista.txt): mueve las fotos de la lista (una ruta relativa a
dataset_aves por línea) a laboratorio_ia/dataset_aves_anterior/mal_etiquetadas/,
conservando la carpeta. No borra nada y anota cada movimiento en
laboratorio_ia/dataset_aves_anterior/mal_etiquetadas/registro.csv.
"""
import argparse
import csv
import shutil
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
LABORATORIO = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

DATASET = LABORATORIO / "dataset_aves"
APARTADAS = LABORATORIO / "dataset_aves_anterior" / "mal_etiquetadas"
SALIDA = LABORATORIO / "reportes" / "revision_etiquetas"
DIVISIONES = ("train", "val", "test")
EXTENSIONES = (".jpg", ".jpeg", ".png")


def buscar(modelo, confianza):
    from ultralytics import YOLO

    clasificador = YOLO(str(modelo))
    nombres = clasificador.names
    archivos = [f for d in DIVISIONES for f in sorted((DATASET / d).glob("*/*")) if f.suffix.lower() in EXTENSIONES]
    sospechosas = []
    for inicio in range(0, len(archivos), 64):
        lote = archivos[inicio:inicio + 64]
        for archivo, resultado in zip(lote, clasificador.predict([str(f) for f in lote], verbose=False)):
            indice = int(resultado.probs.top1)
            prob = float(resultado.probs.top1conf)
            if nombres[indice] != archivo.parent.name and prob >= confianza:
                sospechosas.append((archivo, nombres[indice], prob))
    return sorted(sospechosas, key=lambda s: (s[0].parent.name, -s[2]))


def hojas(sospechosas):
    from PIL import Image, ImageDraw

    por_especie = {}
    for s in sospechosas:
        por_especie.setdefault(s[0].parent.name, []).append(s)
    for especie, filas in por_especie.items():
        columnas, lado = 8, 160
        hoja = Image.new("RGB", (columnas * lado, ((len(filas) - 1) // columnas + 1) * (lado + 30)), "white")
        dibujo = ImageDraw.Draw(hoja)
        for i, (archivo, predicha, prob) in enumerate(filas):
            x, y = (i % columnas) * lado, (i // columnas) * (lado + 30)
            imagen = Image.open(archivo).convert("RGB")
            imagen.thumbnail((lado - 4, lado - 4))
            hoja.paste(imagen, (x + 2, y + 2))
            dibujo.text((x + 3, y + lado + 1), f"#{i + 1} {predicha[:16]}", fill="black")
            dibujo.text((x + 3, y + lado + 14), f"{prob:.2f} {archivo.parent.parent.name}", fill="gray")
        hoja.save(SALIDA / f"hoja_{especie}.jpg", quality=90)


def apartar(lista):
    APARTADAS.mkdir(parents=True, exist_ok=True)
    registro = APARTADAS / "registro.csv"
    nuevo = not registro.exists()
    movidas = 0
    with open(registro, "a", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.writer(archivo, delimiter=";")
        if nuevo:
            escritor.writerow(["fecha", "archivo", "motivo"])
        for linea in Path(lista).read_text(encoding="utf-8").splitlines():
            ruta, _, motivo = linea.partition("#")
            ruta = ruta.strip()
            if not ruta:
                continue
            origen = DATASET / ruta
            if not origen.is_file():
                print(f"  no existe: {ruta}")
                continue
            destino = APARTADAS / ruta
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origen), str(destino))
            escritor.writerow([f"{datetime.now():%Y-%m-%d %H:%M}", ruta, motivo.strip()])
            movidas += 1
    print(f"{movidas} fotos apartadas en {APARTADAS.relative_to(RAIZ)} (registro.csv)")


def main(argumentos=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--modelo", type=Path, help="best.pt de un clasificador entrenado")
    parser.add_argument("--confianza", type=float, default=0.6)
    parser.add_argument("--apartar", type=Path, help="Lista de fotos revisadas a mano para apartar")
    args = parser.parse_args(argumentos)

    if args.apartar:
        apartar(args.apartar)
        return 0
    if not args.modelo or not args.modelo.is_file():
        print("Indica --modelo con un best.pt entrenado.")
        return 1
    SALIDA.mkdir(parents=True, exist_ok=True)
    sospechosas = buscar(args.modelo, args.confianza)
    with open(SALIDA / "sospechosas.csv", "w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.writer(archivo, delimiter=";")
        escritor.writerow(["n", "archivo", "etiqueta", "predicha", "confianza"])
        contador = {}
        for archivo_img, predicha, prob in sospechosas:
            especie = archivo_img.parent.name
            contador[especie] = contador.get(especie, 0) + 1
            escritor.writerow([contador[especie], archivo_img.relative_to(DATASET).as_posix(), especie, predicha,
                               f"{prob:.3f}"])
    hojas(sospechosas)
    print(f"{len(sospechosas)} fotos sospechosas. Revisa {SALIDA.relative_to(RAIZ)}\\hoja_*.jpg y sospechosas.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
