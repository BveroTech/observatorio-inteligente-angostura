"""
Evalúa el clasificador de especies tal como lo usa el kiosco y deja un reporte.

    python laboratorio_ia/scripts_entrenamiento/evaluar_clasificador.py
    python laboratorio_ia/scripts_entrenamiento/evaluar_clasificador.py --modelo RUTA\\best.pt
    python laboratorio_ia/scripts_entrenamiento/evaluar_clasificador.py --division val

Usa la clase Clasificador de src/procesamiento/inferencia_onnx.py (mismo
preprocesamiento que en el kiosco) sobre laboratorio_ia/dataset_aves/<division>/,
imágenes que el modelo no vio al entrenar. Calcula:

  - Exactitud top-1: % de recortes de ave cuya especie se acierta.
  - Con el umbral UMBRAL_CONFIANZA de config/settings.py:
      cobertura  = % de recortes que el kiosco identificaría (confianza ≥ umbral)
      precisión  = % de esas identificaciones que son correctas
  - Exactitud por especie y matriz de confusión.

Con --modelo *.pt primero exporta ese modelo a ONNX (junto al .pt) para
evaluar un candidato antes de desplegarlo en modelos/.

El reporte queda en laboratorio_ia/reportes/evaluacion_<fecha>.md.
"""
import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
LABORATORIO = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from config.settings import MODELO_CLASIFICADOR, UMBRAL_CONFIANZA  # noqa: E402
from src.procesamiento.inferencia_onnx import Clasificador  # noqa: E402

EXTENSIONES = (".jpg", ".jpeg", ".png")
META = 0.90


def leer_imagen(ruta):
    # cv2.imread no abre rutas con tildes en Windows.
    datos = np.fromfile(str(ruta), dtype=np.uint8)
    return cv2.imdecode(datos, cv2.IMREAD_COLOR)


def onnx_de(modelo):
    if modelo.suffix.lower() == ".onnx":
        return modelo
    from ultralytics import YOLO

    from laboratorio_ia.scripts_entrenamiento.exportar_onnx import TAMANO_CLASIFICADOR, tamano_entrenado

    imgsz = tamano_entrenado(modelo, TAMANO_CLASIFICADOR)
    return Path(YOLO(str(modelo)).export(format="onnx", imgsz=imgsz, opset=12, simplify=False, dynamic=False, batch=1))


def evaluar(ruta_onnx, carpeta, umbral):
    clasificador = Clasificador(ruta_onnx)
    nombres = clasificador.nombres
    indice_de = {nombre: i for i, nombre in nombres.items()}
    filas = []  # (real, predicha, confianza, archivo)
    for especie in sorted(p for p in carpeta.iterdir() if p.is_dir()):
        if especie.name not in indice_de:
            print(f"AVISO: {especie.name} no es una clase del modelo; se omite.")
            continue
        for archivo in sorted(especie.iterdir()):
            if archivo.suffix.lower() not in EXTENSIONES:
                continue
            imagen = leer_imagen(archivo)
            if imagen is None:
                print(f"AVISO: no se pudo leer {archivo}")
                continue
            indice, confianza = clasificador.clasificar(imagen)
            filas.append((especie.name, nombres.get(indice, "?"), confianza, archivo))
    total = len(filas)
    aciertos = sum(r == p for r, p, _, _ in filas)
    aceptadas = [(r, p) for r, p, c, _ in filas if c >= umbral]
    por_clase = defaultdict(lambda: [0, 0])
    confusion = Counter()
    for real, pred, _, _ in filas:
        por_clase[real][1] += 1
        por_clase[real][0] += real == pred
        confusion[(real, pred)] += 1
    return {
        "modelo": ruta_onnx,
        "proveedor": clasificador.proveedor,
        "tamano": clasificador.tamano,
        "clases": [nombres[i] for i in sorted(nombres)],
        "total": total,
        "exactitud": aciertos / total if total else 0.0,
        "cobertura": len(aceptadas) / total if total else 0.0,
        "precision": sum(r == p for r, p in aceptadas) / len(aceptadas) if aceptadas else 0.0,
        "por_clase": dict(por_clase),
        "confusion": confusion,
        "errores": sorted((f for f in filas if f[0] != f[1]), key=lambda f: -f[2]),
    }


def reporte_md(res, division, umbral):
    pct = lambda v: f"{v * 100:.1f} %"  # noqa: E731
    lineas = [
        f"# Evaluación del clasificador de especies · {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"- Modelo: `{Path(res['modelo']).relative_to(RAIZ) if Path(res['modelo']).is_relative_to(RAIZ) else res['modelo']}`"
        f" ({res['tamano']} px, {res['proveedor']})",
        f"- Conjunto: `dataset_aves/{division}/` · {res['total']} recortes de ave no vistos al entrenar",
        f"- Meta del proyecto: exactitud ≥ {pct(META)} → **{'CUMPLE' if res['exactitud'] >= META else 'NO CUMPLE'}**",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Exactitud top-1 | **{pct(res['exactitud'])}** |",
        f"| Cobertura con umbral {umbral:.2f} (el kiosco identifica) | {pct(res['cobertura'])} |",
        f"| Precisión con umbral {umbral:.2f} (identificaciones correctas) | {pct(res['precision'])} |",
        "",
        "## Exactitud por especie",
        "",
        "| Especie | Aciertos | Total | Exactitud |",
        "|---|---:|---:|---:|",
    ]
    for especie in res["clases"]:
        ok, n = res["por_clase"].get(especie, (0, 0))
        lineas.append(f"| {especie} | {ok} | {n} | {pct(ok / n) if n else '—'} |")
    abreviar = lambda n: n[:14]  # noqa: E731
    lineas += ["", "## Matriz de confusión (fila = real, columna = predicha)", "",
               "| Real \\ Predicha | " + " | ".join(abreviar(c) for c in res["clases"]) + " |",
               "|---|" + "---:|" * len(res["clases"])]
    for real in res["clases"]:
        celdas = [str(res["confusion"].get((real, pred), 0) or "·") for pred in res["clases"]]
        lineas.append(f"| {real} | " + " | ".join(celdas) + " |")
    if res["errores"]:
        lineas += ["", "## Errores con mayor confianza (revisar si la foto está mal etiquetada)", "",
                   "| Archivo | Real | Predicha | Confianza |", "|---|---|---|---:|"]
        for real, pred, conf, archivo in res["errores"][:15]:
            lineas.append(f"| `{archivo.parent.name}/{archivo.name}` | {real} | {pred} | {conf:.2f} |")
    return "\n".join(lineas) + "\n"


def main(argumentos=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--modelo", type=Path, default=MODELO_CLASIFICADOR, help=".onnx o .pt (por defecto, el del kiosco)")
    parser.add_argument("--dataset", type=Path, default=LABORATORIO / "dataset_aves")
    parser.add_argument("--division", default="test", choices=("test", "val", "train"))
    parser.add_argument("--umbral", type=float, default=UMBRAL_CONFIANZA)
    parser.add_argument("--salida", type=Path, default=None, help="Archivo .md del reporte")
    args = parser.parse_args(argumentos)

    if not args.modelo.is_file():
        print(f"No existe el modelo: {args.modelo}")
        return 1
    carpeta = args.dataset / args.division
    if not carpeta.is_dir():
        print(f"No existe {carpeta}")
        return 1
    res = evaluar(onnx_de(args.modelo), carpeta, args.umbral)
    texto = reporte_md(res, args.division, args.umbral)
    salida = args.salida or LABORATORIO / "reportes" / f"evaluacion_{datetime.now():%Y%m%d_%H%M}.md"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(texto, encoding="utf-8")
    print(f"Exactitud top-1: {res['exactitud'] * 100:.1f} % en {res['total']} imágenes de {args.division}"
          f" · con umbral {args.umbral:.2f}: cobertura {res['cobertura'] * 100:.1f} %,"
          f" precisión {res['precision'] * 100:.1f} %")
    print(f"Reporte: {salida.relative_to(RAIZ) if salida.is_relative_to(RAIZ) else salida}")
    return 0 if res["exactitud"] >= META else 2


if __name__ == "__main__":
    sys.exit(main())
