"""
Entrena el clasificador de especies (modo "dos etapas") con laboratorio_ia/dataset_aves/
y lo exporta a ONNX.

    python laboratorio_ia/scripts_entrenamiento/entrenar_clasificador.py
    python laboratorio_ia/scripts_entrenamiento/entrenar_clasificador.py --epocas 80
    python laboratorio_ia/scripts_entrenamiento/entrenar_clasificador.py --base yolo11m-cls.pt --tamano 320 \\
           --epocas 150 --paciencia 40 --nombre prueba --sin-desplegar

--base acepta un .pt local o un nombre oficial de Ultralytics (yolo11s-cls.pt,
yolo11m-cls.pt, yolo11l-cls.pt…), que se descarga a laboratorio_ia/pesos_pytorch/.
--reanudar continúa un entrenamiento cortado (corte de luz, reinicio) desde
runs/classify/<--nombre>/weights/last.pt, con los mismos parámetros.
--sin-desplegar entrena y evalúa sin tocar el modelo del kiosco; así se comparan
candidatos con evaluar_clasificador.py antes de elegir (ver laboratorio_ia/ENTRENAMIENTO.md).

laboratorio_ia/dataset_aves/{train,val,test}/<Especie>/ se arma con
laboratorio_ia/scripts_entrenamiento/preparar_dataset_roboflow.py (mínimo 20 imágenes por especie y
división). Los nombres de carpeta deben existir en config/clases_modelo.json.

Resultado: modelos/clasificador_aves.pt y modelos/clasificador_aves.onnx.
La exactitud top-1 en val y la evaluación en test quedan en
laboratorio_ia/runs/classify/clasificador_aves*/ como evidencia.
"""
import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
LABORATORIO = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

TAMANO = 224
BASE_POR_DEFECTO = "yolov8n-cls.pt"
MINIMO_POR_DIVISION = 20
DIVISIONES = ("train", "val", "test")
EXTENSIONES = (".jpg", ".jpeg", ".png")


def origen_recorte(ruta):
    """Recupera un identificador de origen cuando el importador lo conservó."""
    nombre = ruta.stem.lower()
    if nombre.startswith(("rf_", "inat_")):
        return "_".join(nombre.split("_")[:2])
    if ".rf." in nombre:
        return re.sub(r"_\d+$", "", nombre)
    return None


def revisar_dataset(carpeta, avisos=None):
    from laboratorio_ia.scripts_entrenamiento.limpiar_dataset import ESPECIES
    from src.procesamiento.inferencia_onnx import cargar_clases_modelo, clave_clase

    mapa = cargar_clases_modelo()
    problemas = []
    if avisos is None:
        avisos = []
    huellas = {}
    origenes = {}
    clases_train = set()
    for division in DIVISIONES:
        ruta = carpeta / division
        if not ruta.is_dir():
            problemas.append(f"falta la carpeta {division}/")
            continue
        especies = sorted(p for p in ruta.iterdir() if p.is_dir())
        nombres = {especie.name for especie in especies}
        faltantes = set(ESPECIES) - nombres
        if faltantes:
            problemas.append(f"{division}: faltan las carpetas {', '.join(sorted(faltantes))}")
        if division == "train":
            clases_train = nombres
        elif nombres != clases_train:
            problemas.append(f"{division}: las carpetas de clases deben coincidir con train")
        mapeadas = {}
        for especie in especies:
            cientifico = mapa.get(clave_clase(especie.name))
            if not cientifico:
                problemas.append(f"{division}/{especie.name}: no tiene correspondencia en el catálogo")
            else:
                anterior = mapeadas.setdefault(cientifico.casefold(), especie.name)
                if anterior != especie.name:
                    problemas.append(f"{division}: {anterior} y {especie.name} representan la misma especie")
            archivos = sorted(f for f in especie.iterdir() if f.is_file() and f.suffix.lower() in EXTENSIONES)
            if len(archivos) < MINIMO_POR_DIVISION:
                problemas.append(
                    f"{division}/{especie.name}: {len(archivos)} imágenes (mínimo {MINIMO_POR_DIVISION})"
                )
            for archivo in archivos:
                huella = hashlib.sha256(archivo.read_bytes()).digest()
                otra = huellas.setdefault(huella, archivo)
                if otra != archivo:
                    mensaje = f"imagen duplicada: {otra.relative_to(carpeta)} y {archivo.relative_to(carpeta)}"
                    (avisos if otra.parent == archivo.parent else problemas).append(mensaje)
                origen = origen_recorte(archivo)
                if origen is not None:
                    otra = origenes.setdefault(origen, archivo)
                    if otra.parent.parent != ruta:
                        problemas.append(f"origen en divisiones distintas: {otra.relative_to(carpeta)} y {archivo.relative_to(carpeta)}")
    return problemas


def resolver_base(base):
    """Ruta local de los pesos de partida; descarga los oficiales de Ultralytics si faltan."""
    ruta = Path(base)
    if ruta.is_file():
        return ruta
    local = LABORATORIO / "pesos_pytorch" / ruta.name
    if local.is_file():
        return local
    if ruta.parent != Path(".") or not ruta.name.endswith("-cls.pt"):
        return None
    from ultralytics.utils.downloads import attempt_download_asset

    local.parent.mkdir(parents=True, exist_ok=True)
    descargado = Path(attempt_download_asset(str(local)))
    return descargado if descargado.is_file() else None


def carga_datos(procesos):
    """Parámetros de lectura de imágenes. Con varios procesos (lo más rápido: la
    CPU prepara y aumenta imágenes en paralelo mientras la GPU entrena) no se usa
    cache="ram", porque en Windows cada proceso copiaría el dataset en memoria."""
    if procesos > 0:
        return {"workers": procesos, "cache": False}
    return {"workers": 0, "cache": "ram"}


def main(argumentos=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dataset", type=Path, default=LABORATORIO / "dataset_aves")
    parser.add_argument("--base", default=BASE_POR_DEFECTO,
                        help="Pesos de partida: ruta a un .pt o nombre Ultralytics (yolo11s-cls.pt se descarga a "
                             "laboratorio_ia/pesos_pytorch/)")
    parser.add_argument("--tamano", type=int, default=TAMANO, help="Lado de la imagen de entrada (px)")
    parser.add_argument("--epocas", type=int, default=100)
    parser.add_argument("--paciencia", type=int, default=25, help="Épocas sin mejorar antes de detenerse")
    parser.add_argument("--lote", type=int, default=32)
    parser.add_argument("--nombre", default="clasificador_aves", help="Carpeta del run en laboratorio_ia/runs/classify/")
    parser.add_argument("--sin-desplegar", action="store_true",
                        help="Solo entrena y evalúa; no reemplaza modelos/clasificador_aves.onnx")
    parser.add_argument("--procesos", type=int, default=8,
                        help="Procesos que preparan las imágenes en paralelo (0 = uno solo, más lento)")
    parser.add_argument("--reanudar", action="store_true",
                        help="Continúa el run --nombre desde su last.pt (tras un corte)")
    parser.add_argument("--forzar", action="store_true", help="Admite clases adicionales válidas en las tres divisiones")
    args = parser.parse_args(argumentos)

    from laboratorio_ia.scripts_entrenamiento.limpiar_dataset import diagnosticar

    desorden = diagnosticar(args.dataset)
    if desorden and not args.forzar:
        print("El dataset tiene carpetas que no corresponden a las 10 especies de entrenamiento:")
        for problema in desorden[:20]:
            print("  -", problema)
        if len(desorden) > 20:
            print(f"  … y {len(desorden) - 20} más")
        print("\nOrdénalo primero con:  .\\limpiar_dataset.bat   y vuelve a entrenar.")
        return 1

    avisos = []
    problemas = revisar_dataset(args.dataset, avisos)
    if problemas:
        print("Revisa el dataset antes de entrenar:")
        for problema in problemas[:20]:
            print("  -", problema)
        if len(problemas) > 20:
            print(f"  … y {len(problemas) - 20} más")
        return 1
    for aviso in avisos:
        print("AVISO -", aviso)
    try:
        import torch
        from ultralytics import YOLO
    except ImportError:
        print("Falta el entorno de entrenamiento: ejecuta laboratorio_ia\\scripts_entrenamiento\\bat\\"
              "instalar_entrenamiento.bat")
        return 1
    dispositivo = 0 if torch.cuda.is_available() else "cpu"
    if args.reanudar:
        ultimo = LABORATORIO / "runs" / "classify" / args.nombre / "weights" / "last.pt"
        if not ultimo.is_file():
            print(f"No hay entrenamiento que reanudar: falta {ultimo}")
            return 1
        from laboratorio_ia.scripts_entrenamiento.exportar_onnx import tamano_entrenado

        args.tamano = tamano_entrenado(ultimo, args.tamano)
        print(f"Reanudando {args.nombre} desde {ultimo.name} ({args.tamano} px)")
        resultado = YOLO(str(ultimo)).train(resume=True, **carga_datos(args.procesos))
        return evaluar_y_desplegar(resultado, args, dispositivo, YOLO)

    base = resolver_base(args.base)
    if base is None:
        print(f"No existe el modelo de partida: {args.base}")
        return 1

    print(f"Base {base.name} · {args.tamano} px · "
          f"{'GPU ' + torch.cuda.get_device_name(0) if dispositivo == 0 else 'CPU (puede tardar horas)'}")
    modelo = YOLO(str(base))
    resultado = modelo.train(
        data=str(args.dataset.resolve()),
        epochs=args.epocas,
        imgsz=args.tamano,
        batch=args.lote,
        name=args.nombre,
        project=str(LABORATORIO / "runs" / "classify"),
        device=dispositivo,
        **carga_datos(args.procesos),
        patience=args.paciencia,
        cos_lr=True,
        label_smoothing=0.1,  # reduce la sobreconfianza; ayuda con especies parecidas
        seed=0,
        deterministic=True,
    )
    return evaluar_y_desplegar(resultado, args, dispositivo, YOLO)


def evaluar_y_desplegar(resultado, args, dispositivo, YOLO):
    mejor = Path(resultado.save_dir) / "weights" / "best.pt"
    print("Evaluación en test (imágenes que el modelo no vio):")
    YOLO(str(mejor)).val(data=str(args.dataset.resolve()), split="test", imgsz=args.tamano, device=dispositivo,
                        project=str(resultado.save_dir), name="test")
    if args.sin_desplegar:
        print(f"Modelo entrenado en {mejor}. No se desplegó (--sin-desplegar).")
        return 0

    destino = RAIZ / "modelos" / "clasificador_aves.pt"
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mejor, destino)
    print(f"Mejor modelo copiado a {destino.relative_to(RAIZ)}")

    from laboratorio_ia.scripts_entrenamiento.exportar_onnx import main as exportar

    return exportar(["--clasificador", str(destino)])


if __name__ == "__main__":
    sys.exit(main())
