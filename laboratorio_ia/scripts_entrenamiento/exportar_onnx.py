"""Exporta los pesos YOLO a los ONNX que usa el kiosco.

Sin argumentos, busca detector_aves.pt (o los pesos COCO yolov8n.pt) y
clasificador_aves.pt en modelos/ y laboratorio_ia/pesos_pytorch/. Con
--detector o --clasificador se exporta el modelo indicado.

ONNX Runtime comprueba cada candidato antes de sustituir los archivos.
"""
import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[2]
LABORATORIO = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from config.settings import (  # noqa: E402
    ARCHIVO_CLASES_MODELO,
    MODELO_CLASIFICADOR,
    MODELO_DETECTOR,
    TAMANO_ENTRADA_DETECTOR,
)
from src.procesamiento.inferencia_onnx import _nombres_de_metadatos, cargar_clases_modelo, clave_clase  # noqa: E402

TAMANO_CLASIFICADOR = 224  # solo si el .pt no guarda el tamaño con que se entrenó


def tamano_entrenado(ruta_pt, defecto):
    """Tamaño de imagen con que se entrenó el .pt (el kiosco lo lee luego del ONNX)."""
    try:
        import torch

        ckpt = torch.load(str(ruta_pt), map_location="cpu", weights_only=False)
        imgsz = (ckpt.get("train_args") or {}).get("imgsz")
        if isinstance(imgsz, (list, tuple)):
            imgsz = imgsz[0]
        return int(imgsz) if imgsz else defecto
    except Exception:
        return defecto


def exportar(ruta_pt, temporal, imgsz, rol):
    from ultralytics import YOLO

    # Ultralytics escribe el ONNX junto al .pt. Aísla esa escritura de los modelos activos.
    entrada = temporal / f"{rol}.pt"
    shutil.copyfile(ruta_pt, entrada)
    modelo = YOLO(str(entrada))
    tarea = "detect" if rol == "detector" else "classify"
    if modelo.task != tarea:
        raise ValueError(f"{ruta_pt.name}: se esperaba un modelo {tarea}, se recibió {modelo.task}.")
    nombres = modelo.names
    nombres = dict(sorted(nombres.items())) if isinstance(nombres, dict) else dict(enumerate(nombres))
    revisar_clases(nombres.values(), rol)
    opciones = {"format": "onnx", "imgsz": imgsz, "opset": 12, "simplify": False, "dynamic": False, "batch": 1}
    if rol == "detector":
        opciones["nms"] = False
    salida = Path(modelo.export(**opciones))
    validar_onnx(salida, imgsz, rol, nombres)
    print(f"  Exportación validada ({len(nombres)} clases)")
    return salida


def revisar_clases(nombres, rol):
    """Exige una salida por especie para los modelos de especies."""
    nombres = tuple(nombres)
    if rol == "detector" and any(clave_clase(n) == "bird" for n in nombres):
        print("  Detector genérico (COCO): se usará solo la clase 'bird'.")
        return
    conocidas = cargar_clases_modelo()
    faltan = [n for n in nombres if clave_clase(n) not in conocidas]
    if faltan:
        raise ValueError(f"Clases del {rol} sin correspondencia en {ARCHIVO_CLASES_MODELO.name}: {', '.join(faltan)}")
    canonicas = {}
    for nombre in nombres:
        cientifico = conocidas[clave_clase(nombre)].casefold()
        if cientifico in canonicas:
            raise ValueError(f"Las clases «{canonicas[cientifico]}» y «{nombre}» del {rol} identifican la misma especie.")
        canonicas[cientifico] = nombre


def validar_onnx(ruta, imgsz, rol, nombres_esperados=None):
    import onnxruntime as ort

    sesion = ort.InferenceSession(str(ruta), providers=["CPUExecutionProvider"])
    entradas = sesion.get_inputs()
    forma = [1, 3, imgsz, imgsz]
    if len(entradas) != 1 or entradas[0].shape != forma or entradas[0].type != "tensor(float)":
        raise ValueError(f"El ONNX del {rol} requiere una entrada float32 {forma}.")
    nombres = _nombres_de_metadatos(sesion)
    if not nombres or sorted(nombres) != list(range(len(nombres))):
        raise ValueError(f"Metadatos ONNX del {rol} sin clases consecutivas.")
    if nombres_esperados is not None and nombres != nombres_esperados:
        raise ValueError(f"El ONNX del {rol} cambió los índices o nombres de clase durante la exportación.")
    salidas = sesion.run(None, {entradas[0].name: np.zeros(forma, dtype=np.float32)})
    if len(salidas) != 1 or not np.isfinite(salidas[0]).all():
        raise ValueError(f"El ONNX del {rol} requiere una sola salida finita.")
    salida = salidas[0]
    if rol == "detector":
        valida = salida.ndim == 3 and salida.shape[0] == 1 and 4 + len(nombres) in salida.shape[1:]
    else:
        valida = salida.shape == (1, len(nombres))
    if not valida:
        raise ValueError(f"Salida ONNX del {rol} incompatible con el kiosco: {salida.shape}.")
    return nombres


def desplegar(plan, temporal):
    """Sustituye cada ONNX mediante rename y restaura lo instalado si falla otro."""
    respaldos = {}
    for _, destino in plan:
        if destino.exists():
            respaldo = temporal / f"previo-{destino.name}"
            shutil.copyfile(destino, respaldo)
            respaldos[destino] = respaldo
    cambiados = []
    try:
        for salida, destino in plan:
            if salida is None:
                destino.unlink(missing_ok=True)
            else:
                os.replace(salida, destino)
            cambiados.append(destino)
    except OSError:
        for destino in reversed(cambiados):
            if destino in respaldos:
                os.replace(respaldos[destino], destino)
            else:
                destino.unlink(missing_ok=True)
        raise


def main(argumentos=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--detector", type=Path, help="Ruta a un .pt de detección")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--clasificador", type=Path, help="Ruta a un .pt de clasificación")
    grupo.add_argument("--sin-clasificador", action="store_true", help="Retira el ONNX del clasificador del kiosco")
    args = parser.parse_args(argumentos)

    try:
        import ultralytics  # noqa: F401
    except ImportError:
        print("Falta Ultralytics. Instala el entorno de entrenamiento:\n"
              "    .venv\\Scripts\\python.exe -m pip install -r laboratorio_ia\\requirements-entrenamiento.txt")
        return 1

    candidatos_detector = (
        RAIZ / "modelos" / "detector_aves.pt",
        LABORATORIO / "pesos_pytorch" / "yolov8n.pt",
        RAIZ / "yolov8n.pt",
    )
    candidatos_clasificador = (
        RAIZ / "modelos" / "clasificador_aves.pt",
        LABORATORIO / "pesos_pytorch" / "clasificador_aves.pt",
    )
    ambos_por_defecto = args.detector is None and args.clasificador is None and not args.sin_clasificador
    requiere_detector = bool(args.detector or ambos_por_defecto or args.sin_clasificador)
    detector = args.detector
    clasificador = args.clasificador
    if requiere_detector and detector is None:
        detector = next((r for r in candidatos_detector if r.is_file() and r.stat().st_size > 0), None)
    if ambos_por_defecto:
        clasificador = next((r for r in candidatos_clasificador if r.is_file() and r.stat().st_size > 0), None)
    if requiere_detector and detector is None:
        print("No se encontró un detector .pt (modelos/detector_aves.pt o laboratorio_ia/pesos_pytorch/yolov8n.pt).")
        return 1
    trabajos = [
        (ruta, destino, tamano, rol) for ruta, destino, tamano, rol in (
            (detector, MODELO_DETECTOR, TAMANO_ENTRADA_DETECTOR, "detector"),
            (clasificador, MODELO_CLASIFICADOR,
             tamano_entrenado(clasificador, TAMANO_CLASIFICADOR) if clasificador else TAMANO_CLASIFICADOR,
             "clasificador"),
        ) if ruta is not None
    ]
    for ruta, _, _, _ in trabajos:
        if not ruta.is_file() or ruta.stat().st_size == 0:
            print(f"El modelo no existe o está vacío: {ruta}")
            return 1

    try:
        MODELO_DETECTOR.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="exportacion-", dir=MODELO_DETECTOR.parent) as carpeta:
            temporal = Path(carpeta)
            plan = []
            for ruta, destino, tamano, rol in trabajos:
                print(f"{rol.capitalize()}: {ruta}")
                plan.append((exportar(ruta, temporal, tamano, rol), destino))
            if args.sin_clasificador:
                plan.append((None, MODELO_CLASIFICADOR))
            desplegar(plan, temporal)
    except Exception as error:
        print(f"No se completó la exportación: {error}")
        return 1
    print("Listo. Ejecuta scripts\\lanzadores_windows\\ejecutar_observatorio.bat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
