"""
Construye la versión instalable del Observatorio para Windows.

    python scripts/windows/construir_ejecutable.py                       (o construir_ejecutable.bat)
    python scripts/windows/construir_ejecutable.py --version 1.1.0
    python scripts/windows/construir_ejecutable.py --incluir-base-datos  lleva el catálogo y usuarios de ESTE PC

Pasos:
  1. PyInstaller (observatorio.spec) -> dist/Observatorio/ con Observatorio.exe y Admin.exe.
  2. Copia junto a los .exe lo que se puede editar o reemplazar sin reconstruir:
     assets/ (fotos, sonidos, video demo, fuentes), modelos/*.onnx, web/ (plantillas),
     data/semillas/, config/ (clases del modelo, observatorio.ini, ejemplo de cámara).
  3. Instalador: dist/Instalar_Observatorio_<versión>.exe (Inno Setup 6, si está instalado);
     siempre deja además dist/Observatorio_<versión>_portable.zip.

NO lleva datos de este PC (base de datos, capturas, contraseñas, config/camara_local.json),
salvo --incluir-base-datos (catálogo editado + usuarios del portal + avistamientos).
"""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
VERSION = "1.0.0"
DIST = RAIZ / "dist"
APP = DIST / "Observatorio"

# (origen relativo a la raíz, destino relativo a la carpeta de la app)
COPIAR = [
    ("assets", "assets"),
    ("web/plantillas", "web/plantillas"),
    ("web/estaticos", "web/estaticos"),
    ("data/semillas", "data/semillas"),
    ("laboratorio_ia/simulador_pantalla2/sonidos", "laboratorio_ia/simulador_pantalla2/sonidos"),
    ("config/clases_modelo.json", "config/clases_modelo.json"),
    ("config/camara_local.ejemplo.json", "config/camara_local.ejemplo.json"),
    ("config/observatorio.ejemplo.ini", "config/observatorio.ejemplo.ini"),
    ("config/observatorio.ejemplo.ini", "config/observatorio.ini"),
]
IGNORAR = shutil.ignore_patterns("__pycache__", "*.pyc", "Thumbs.db", "desktop.ini")

LEEME = """OBSERVATORIO INTELIGENTE DE AVES - versión {version}
=====================================================

Abrir
  Observatorio.exe   kiosco (video en vivo) + pantalla táctil (catálogo y trivia).
                     También abre el portal de administración en segundo plano.
  Admin.exe          abre el portal de administración en el navegador.

Primera vez
  1. Crear el usuario del portal:  acceso directo "Crear usuario del portal"
     (o en una consola: Admin.exe --crear-usuario)
  2. Cámara IP: copiar config\\camara_local.ejemplo.json como config\\camara_local.json
     y escribir la dirección rtsp:// de la cámara.
  3. Monitores, pantalla completa, portal en red, fuente de video:
     config\\observatorio.ini (Bloc de notas). Los números de monitor se ven con
     el acceso directo "Ver monitores" (Admin.exe --detectar-pantallas).

Datos (se conservan al actualizar o desinstalar)
  data\\observatorio.db       base de datos (catálogo, avistamientos, usuarios)
  data\\capturas\\            fotos de los avistamientos
  data\\por_identificar\\     aves que el sistema no reconoció
  data\\kiosco.log            registro del kiosco (para revisar errores)
  assets\\fotos, assets\\sonidos   fichas de las especies (se editan en el portal)
  modelos\\*.onnx             IA (se reemplazan por una versión nueva sin reinstalar)
  modelos\\traduccion, modelos\\tessdata   traductor y lector de fichas técnicas

Idiomas (español, inglés, alemán)
  Las fichas se escriben en español en el portal y se traducen solas al inglés y al
  alemán al guardarlas (sin internet); se pueden corregir en la misma página.
  En la pantalla táctil el visitante elige el idioma.
  "Leer ficha técnica" (portal, al editar una especie) lee una foto, escaneo o PDF
  en español, inglés o alemán y rellena los campos.
  Traducir todo el catálogo de una vez: acceso directo "Traducir fichas"
  (Admin.exe --traducir-fichas).

Portal desde otro computador de la red: http://NOMBRE-DE-ESTE-PC:5000
(con [portal] en_red = si en config\\observatorio.ini y el firewall permitido,
 opción que ofrece el instalador).
"""


def paso(texto):
    print(f"\n== {texto} ==", flush=True)


def ejecutar(comando, **opciones):
    print(">", " ".join(str(c) for c in comando), flush=True)
    resultado = subprocess.run([str(c) for c in comando], **opciones)
    if resultado.returncode != 0:
        sys.exit(f"[ERROR] Falló: {' '.join(str(c) for c in comando)}")


def buscar_tesseract():
    for base in (os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")):
        for sub in ("Tesseract-OCR", os.path.join("Programs", "Tesseract-OCR")):
            ruta = Path(base) / sub / "tesseract.exe"
            if base and ruta.is_file():
                return ruta
    encontrado = shutil.which("tesseract")
    return Path(encontrado) if encontrado else None


def buscar_inno_setup():
    candidatos = [shutil.which("ISCC.exe") or ""]
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base:
            candidatos.append(os.path.join(base, "Inno Setup 6", "ISCC.exe"))
    return next((Path(c) for c in candidatos if c and Path(c).is_file()), None)


def main(argumentos=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", default=VERSION)
    parser.add_argument("--incluir-base-datos", action="store_true",
                        help="incluye data/observatorio.db de este PC (catálogo editado, usuarios, avistamientos)")
    parser.add_argument("--sin-instalador", action="store_true", help="solo la carpeta y el .zip")
    args = parser.parse_args(argumentos)

    if sys.platform != "win32":
        sys.exit("Este script construye la versión de Windows. Para el Jetson: scripts/jetson/construir_paquete.py")
    for modelo in ("detector_aves.onnx", "clasificador_aves.onnx"):
        if not (RAIZ / "modelos" / modelo).is_file():
            sys.exit(f"[ERROR] Falta modelos/{modelo}")

    paso("PyInstaller")
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        ejecutar([sys.executable, "-m", "pip", "install", "pyinstaller>=6.10"])
    if APP.exists():
        shutil.rmtree(APP)
    ejecutar([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
              "--distpath", DIST, "--workpath", RAIZ / "build" / "pyinstaller", RAIZ / "observatorio.spec"],
             cwd=RAIZ)

    paso("Archivos editables junto a los .exe")
    for origen, destino in COPIAR:
        origen, destino = RAIZ / origen, APP / destino
        if origen.is_dir():
            shutil.copytree(origen, destino, ignore=IGNORAR, dirs_exist_ok=True)
        elif origen.is_file():
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origen, destino)
        else:
            print(f"[AVISO] No existe {origen}; se omite.")
    (APP / "modelos").mkdir(exist_ok=True)
    for modelo in sorted((RAIZ / "modelos").glob("*.onnx")):
        shutil.copy2(modelo, APP / "modelos" / modelo.name)

    paso("Idiomas: lector de fichas (Tesseract) y traductor (español, inglés, alemán)")
    for carpeta in ("tessdata", "traduccion", "voces"):
        origen = RAIZ / "modelos" / carpeta
        if origen.is_dir() and any(origen.iterdir()):
            shutil.copytree(origen, APP / "modelos" / carpeta, dirs_exist_ok=True)
        else:
            print(f"[AVISO] Falta modelos/{carpeta}: ejecuta scripts/cli_admin/descargar_modelos_idiomas.py")
    tesseract = buscar_tesseract()
    if tesseract is None:
        print("[AVISO] Tesseract no está instalado en este PC: el lector de fichas no irá en el ejecutable.")
        print("        Instalarlo con:  winget install -e --id UB-Mannheim.TesseractOCR")
    else:
        # Solo el programa y sus DLL (sin las herramientas de entrenamiento); los idiomas van en modelos/tessdata.
        destino = APP / "tesseract"
        destino.mkdir(exist_ok=True)
        for archivo in [tesseract, *tesseract.parent.glob("*.dll")]:
            shutil.copy2(archivo, destino / archivo.name)
        if (tesseract.parent / "doc").is_dir():
            shutil.copytree(tesseract.parent / "doc", destino / "doc", dirs_exist_ok=True)
        print(f"Tesseract incluido desde {tesseract.parent}")
    if args.incluir_base_datos:
        bd = RAIZ / "data" / "observatorio.db"
        if not bd.is_file():
            sys.exit("[ERROR] No existe data/observatorio.db")
        import sqlite3

        # Copia consistente aunque el programa esté abierto (incluye lo pendiente en el WAL).
        (APP / "data").mkdir(exist_ok=True)
        with sqlite3.connect(bd) as fuente, sqlite3.connect(APP / "data" / "observatorio.db") as copia:
            fuente.backup(copia)
        print("Base de datos de este PC incluida (catálogo, usuarios del portal y avistamientos).")
    (APP / "LEEME.txt").write_text(LEEME.format(version=args.version), encoding="utf-8-sig")
    shutil.copy2(RAIZ / "scripts" / "windows" / "observatorio.ico", APP / "observatorio.ico")

    paso("Comprobación rápida de Admin.exe")
    resultado = subprocess.run([str(APP / "Admin.exe"), "--mostrar-enlace"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", cwd=APP, timeout=120)
    print(resultado.stdout.strip() or resultado.stderr.strip())
    if resultado.returncode != 0:
        sys.exit("[ERROR] Admin.exe no arrancó (ver mensaje de arriba).")

    paso("Versión portable (.zip)")
    portable = DIST / f"Observatorio_{args.version}_portable.zip"
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archivo:
        for ruta in sorted(APP.rglob("*")):
            if ruta.is_file():
                archivo.write(ruta, Path("Observatorio") / ruta.relative_to(APP))
    print(f"{portable}  ({portable.stat().st_size / 2**20:.0f} MB)")

    instalador = None
    if not args.sin_instalador:
        paso("Instalador (Inno Setup)")
        iscc = buscar_inno_setup()
        if iscc is None:
            print("[AVISO] Inno Setup 6 no está instalado: no se generó el instalador, solo el .zip.")
            print("        Instalarlo con:  winget install -e --id JRSoftware.InnoSetup   y volver a construir.")
        else:
            ejecutar([iscc, "/Qp", f"/DVersion={args.version}", f"/DCarpetaApp={APP}", f"/DSalida={DIST}",
                      RAIZ / "scripts" / "windows" / "instalador.iss"])
            instalador = DIST / f"Instalar_Observatorio_{args.version}.exe"

    paso("Listo")
    print(f"Carpeta:    {APP}")
    print(f"Portable:   {portable}")
    if instalador and instalador.is_file():
        print(f"Instalador: {instalador}  ({instalador.stat().st_size / 2**20:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
