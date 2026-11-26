"""
Entrena el detector de especies (modo "una etapa") con una exportación de
Roboflow en formato YOLOv8 y lo exporta a ONNX.

    python laboratorio_ia/scripts_entrenamiento/entrenar_detector.py RUTA\\data.yaml
    python laboratorio_ia/scripts_entrenamiento/entrenar_detector.py RUTA\\data.yaml --epocas 80 --lote 8

Resultado: modelos/detector_aves.pt y modelos/detector_aves.onnx.
Las métricas (mAP, matriz de confusión) quedan en laboratorio_ia/runs/detect/detector_aves*/;
sirven como evidencia del rendimiento real del modelo.
"""
import argparse
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
LABORATORIO = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from config.settings import TAMANO_ENTRADA_DETECTOR  # noqa: E402
from laboratorio_ia.scripts_entrenamiento.exportar_onnx import main as exportar, revisar_clases  # noqa: E402
from laboratorio_ia.scripts_entrenamiento.preparar_dataset_roboflow import leer_nombres  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("data_yaml", type=Path, help="data.yaml de la exportación de Roboflow")
    parser.add_argument("--base", type=Path, default=LABORATORIO / "pesos_pytorch" / "yolov8n.pt", help="Modelo de partida")
    parser.add_argument("--epocas", type=int, default=60)
    parser.add_argument("--lote", type=int, default=8)
    args = parser.parse_args()

    if not args.data_yaml.is_file():
        print(f"No existe {args.data_yaml}")
        return 1
    if not args.base.is_file():
        print(f"No existe el modelo de partida: {args.base}")
        return 1
    try:
        import torch
        import yaml
        from ultralytics import YOLO
    except ImportError:
        print("Falta el entorno de entrenamiento:\n"
              "    .venv\\Scripts\\python.exe -m pip install -r laboratorio_ia\\requirements-entrenamiento.txt")
        return 1
    try:
        datos = yaml.safe_load(args.data_yaml.read_text(encoding="utf-8-sig"))
        if not isinstance(datos, dict) or not datos.get("train") or not datos.get("val"):
            raise ValueError("data.yaml necesita train y val.")
        revisar_clases(leer_nombres(args.data_yaml), "detector")
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"Dataset de detección inválido: {error}")
        return 1

    dispositivo = 0 if torch.cuda.is_available() else "cpu"
    print(f"Entrenando en {'GPU' if dispositivo == 0 else 'CPU (puede tardar horas)'}")
    modelo = YOLO(str(args.base))
    resultado = modelo.train(
        data=str(args.data_yaml.resolve()),
        epochs=args.epocas,
        imgsz=TAMANO_ENTRADA_DETECTOR,
        batch=args.lote,
        name="detector_aves",
        project=str(LABORATORIO / "runs" / "detect"),
        device=dispositivo,
        workers=0,  # Windows: evita problemas de multiprocessing
        patience=15,
        seed=0,
    )
    mejor = Path(resultado.save_dir) / "weights" / "best.pt"
    if datos.get("test"):
        YOLO(str(mejor)).val(data=str(args.data_yaml.resolve()), split="test", imgsz=TAMANO_ENTRADA_DETECTOR,
                            device=dispositivo, project=str(resultado.save_dir), name="test")

    destino = RAIZ / "modelos" / "detector_aves.pt"
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mejor, destino)
    print(f"Mejor modelo copiado a {destino.relative_to(RAIZ)}")

    return exportar(["--detector", str(destino)])


if __name__ == "__main__":
    sys.exit(main())
