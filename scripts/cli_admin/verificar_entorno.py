"""Revisa que el equipo tenga todo lo necesario para el Observatorio."""
import platform
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


def linea(estado, nombre, detalle=""):
    print(f"[{estado:^6}] {nombre}{': ' + str(detalle) if detalle else ''}")


def _version_instalada(paquetes):
    from importlib.metadata import PackageNotFoundError, version as version_paquete

    if isinstance(paquetes, str):
        paquetes = (paquetes,)
    for pkg in paquetes:
        try:
            return version_paquete(pkg)
        except PackageNotFoundError:
            continue
    return "instalado"


def main():
    print("=== Verificación del Observatorio Inteligente de Aves ===")
    linea("OK", "Sistema", platform.platform())
    version = sys.version_info
    linea("OK" if (version.major, version.minor) >= (3, 11) else "AVISO", "Python", sys.version.split()[0])
    errores = 0

    modulos = [
        ("customtkinter", "customtkinter", "CustomTkinter (interfaz)", True),
        ("onnxruntime", "onnxruntime", "ONNX Runtime (inferencia)", True),
        ("cv2", "opencv-python", "OpenCV (video)", True),
        ("numpy", "numpy", "NumPy", True),
        ("PIL", "Pillow", "Pillow", True),
        ("flask", "Flask", "Flask (portal)", True),
        ("werkzeug", "Werkzeug", "Werkzeug (hash de contraseñas)", True),
        ("pygame", ("pygame-ce", "pygame"), "Pygame (cantos .mp3/.ogg)", False),
        ("openpyxl", "openpyxl", "openpyxl (importar Excel)", False),
        ("ultralytics", "ultralytics", "Ultralytics (solo entrenar/exportar)", False),
    ]
    for modulo, paquete, nombre, obligatorio in modulos:
        try:
            __import__(modulo)
            detalle = _version_instalada(paquete)
            linea("OK", nombre, detalle)
        except Exception as error:
            linea("ERROR" if obligatorio else "-", nombre, "no instalado" if isinstance(error, ImportError) else error)
            errores += obligatorio

    try:
        import onnxruntime as ort
        linea("OK", "Proveedores ONNX", ", ".join(ort.get_available_providers()))
    except Exception:
        pass

    from config import settings

    for nombre, ruta, obligatorio in (
        ("Detector ONNX", settings.MODELO_DETECTOR, True),
        ("Clasificador ONNX", settings.MODELO_CLASIFICADOR, False),
        ("Catálogo CSV", settings.ARCHIVO_CATALOGO, True),
        ("Video de demostración", settings.VIDEO_DEMOSTRACION, False),
    ):
        ruta_path = Path(ruta)
        rel = ruta_path.relative_to(RAIZ) if ruta_path.is_relative_to(RAIZ) else ruta_path
        if ruta_path.exists() and ruta_path.stat().st_size > 0:
            linea("OK", nombre, rel)
        else:
            linea("FALTA" if obligatorio else "-", nombre, rel)
            errores += obligatorio
    if not Path(settings.MODELO_DETECTOR).exists():
        print("         -> Ejecuta laboratorio_ia\\scripts_entrenamiento\\bat\\exportar_modelos.bat para generar los .onnx")

    linea("OK" if settings.url_rtsp() else "-", "URL RTSP", "configurada" if settings.url_rtsp() else
          "sin configurar (usa cámara USB o config/camara_local.json)")

    from src.persistencia.repositorio_sqlite import preparar_base

    base = preparar_base()
    linea("OK", "Base de datos", f"{base.total_especies()} especies, {base.total_usuarios()} usuarios")
    if base.total_usuarios() == 0:
        print("         -> Crea el primer usuario del portal con scripts\\lanzadores_windows\\crear_usuario.bat")
    base.cerrar()
    print("Todo listo." if not errores else f"{errores} problema(s) por resolver.")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
