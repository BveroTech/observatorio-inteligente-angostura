# -*- mode: python ; coding: utf-8 -*-
"""
Especificación de PyInstaller del Observatorio Inteligente de Aves (Windows).

NO se ejecuta a mano: lo hace scripts/windows/construir_ejecutable.py
(scripts/lanzadores_windows/construir_ejecutable.bat), que además copia junto a
los .exe las carpetas editables (assets, modelos, config, web, data/semillas) y
arma el instalador.

Resultado: dist/Observatorio/ (una sola carpeta, "onedir")
    Observatorio.exe   kiosco (Pantalla 1) + pantalla táctil (Pantalla 2) + IA ONNX; abre el portal
    Admin.exe          portal de administración (Flask + waitress); también --crear-usuario y
                       --detectar-pantallas
    _internal/         Python y librerías, COMPARTIDO por los dos .exe

Se usa "onedir" y no "onefile": un .exe de un solo archivo se descomprime en una
carpeta temporal cada vez que se abre (arranque lento) y no puede guardar datos
junto a sí mismo. Con onedir los datos quedan junto a los .exe (data/, assets/fotos…).
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
RAIZ = Path(SPECPATH).resolve()
ICONO = RAIZ / "scripts" / "windows" / "observatorio.ico"
ICONO = str(ICONO) if ICONO.is_file() else None

# Paquetes con datos o importaciones dinámicas que el análisis no ve solo.
datas_kiosco, binarios_kiosco, ocultos_kiosco = [], [], []
for paquete in ("customtkinter", "darkdetect", "onnxruntime", "dxcam", "comtypes", "mss", "pygame", "piper"):
    try:
        datos, binarios, ocultos = collect_all(paquete)
    except Exception:
        continue
    datas_kiosco += datos
    binarios_kiosco += binarios
    ocultos_kiosco += ocultos

ocultos_kiosco += collect_submodules("src") + collect_submodules("config") + [
    "laboratorio_ia",
    "laboratorio_ia.simulador_pantalla2",
    "laboratorio_ia.simulador_pantalla2.audio",
    "laboratorio_ia.simulador_pantalla2.trivia",
    "PIL._tkinter_finder",
    "winsound",
]

ocultos_admin = collect_submodules("web") + collect_submodules("config") + [
    "src.persistencia.repositorio_sqlite",
    "src.aplicacion.gestor_monitores",
    "waitress",
    # Herramientas de scripts/cli_admin que Admin.exe ejecuta con --crear-usuario / --detectar-pantallas
    "crear_usuario",
    "detectar_pantallas",
]
ocultos_admin += collect_submodules("waitress") + ["traducir_fichas", "src.aplicacion.lector_fichas",
                                                   "src.aplicacion.servicio_traduccion", "src.aplicacion.traductor"]
# Lector de fichas técnicas (Tesseract vía pytesseract, PDF con PyMuPDF) y traductor sin conexión.
datas_admin, binarios_admin = [], []
for paquete in ("ctranslate2", "sentencepiece", "pymupdf", "fitz", "pytesseract"):
    try:
        datos, binarios, ocultos = collect_all(paquete)
    except Exception:
        continue
    datas_admin += datos
    binarios_admin += binarios
    ocultos_admin += ocultos

# Las librerías empaquetadas con delvewheel traen sus DLL en "<paquete>.libs" (p. ej.
# sentencepiece.libs/msvcp140-<hash>.dll). PyInstaller a veces descarta alguna por
# parecerse a una DLL del sistema y la importación falla ("DLL load failed"): se copian todas.
import importlib.util  # noqa: E402

for paquete in ("sentencepiece", "ctranslate2", "pymupdf", "numpy", "onnxruntime", "cv2"):
    especificacion = importlib.util.find_spec(paquete)
    if especificacion is None or not especificacion.origin:
        continue
    carpeta_libs = Path(especificacion.origin).parent.parent / f"{paquete}.libs"
    for dll in carpeta_libs.glob("*.dll"):
        destino = (binarios_admin if paquete in ("sentencepiece", "ctranslate2", "pymupdf") else binarios_kiosco)
        destino.append((str(dll), f"{paquete}.libs"))

# Solo para entrenar: nunca van en el ejecutable.
excluir = ["torch", "torchvision", "ultralytics", "matplotlib", "scipy", "pandas", "IPython", "jupyter",
           "pytest", "PyInstaller"]

a_kiosco = Analysis(
    [str(RAIZ / "main_kiosco.py")],
    pathex=[str(RAIZ)],
    binaries=binarios_kiosco,
    datas=datas_kiosco,
    hiddenimports=list(dict.fromkeys(ocultos_kiosco)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluir,
    noarchive=False,
)

a_admin = Analysis(
    [str(RAIZ / "main_admin.py")],
    pathex=[str(RAIZ), str(RAIZ / "scripts" / "cli_admin")],
    binaries=binarios_admin,
    datas=datas_admin,
    hiddenimports=list(dict.fromkeys(ocultos_admin)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluir + ["onnxruntime", "cv2", "pygame", "dxcam"],
    noarchive=False,
)

pyz_kiosco = PYZ(a_kiosco.pure, a_kiosco.zipped_data, cipher=block_cipher)
pyz_admin = PYZ(a_admin.pure, a_admin.zipped_data, cipher=block_cipher)

exe_kiosco = EXE(
    pyz_kiosco,
    a_kiosco.scripts,
    [],
    exclude_binaries=True,
    name="Observatorio",
    icon=ICONO,
    console=False,          # sin ventana negra
    upx=False,              # UPX daña DLLs de onnxruntime/OpenCV y alarma a los antivirus
    disable_windowed_traceback=False,
)

exe_admin = EXE(
    pyz_admin,
    a_admin.scripts,
    [],
    exclude_binaries=True,
    name="Admin",
    icon=ICONO,
    console=True,           # muestra el enlace del portal y las herramientas por consola
    upx=False,
)

coll = COLLECT(
    exe_kiosco,
    a_kiosco.binaries,
    a_kiosco.datas,
    exe_admin,
    a_admin.binaries,
    a_admin.datas,
    strip=False,
    upx=False,
    name="Observatorio",
)
