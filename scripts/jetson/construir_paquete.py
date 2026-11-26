"""
Construye el instalador del Observatorio para el Jetson: un paquete .deb (arm64)
que se instala como cualquier aplicación de Ubuntu, sin copiar la carpeta del proyecto.

    python scripts/jetson/construir_paquete.py                  -> dist/observatorio-angostura_<versión>_arm64.deb
    python scripts/jetson/construir_paquete.py --version 1.0.1
    python scripts/jetson/construir_paquete.py --descargar      vuelve a descargar las librerías

Funciona en Windows y en Linux (no necesita dpkg-deb). Incluye:
  - el programa en /opt/observatorio-angostura (código, modelos ONNX, fotos, sonidos, catálogo);
  - las librerías de Python para el Jetson (Python 3.10 y 3.12, aarch64; onnxruntime-gpu de Jetson AI Lab para JetPack 6 y 7, y onnxruntime de CPU de respaldo),
    descargadas aquí, así la instalación no necesita internet para ellas;
  - comandos (observatorio, observatorio-portal, observatorio-pantallas, observatorio-usuario,
    observatorio-medir), íconos en el menú, fuentes Montserrat y los servicios systemd.

En el Jetson:   sudo apt install ./observatorio-angostura_<versión>_arm64.deb
NO incluye datos locales de este equipo: base de datos, capturas, contraseñas ni config/camara_local.json.
"""
import argparse
import hashlib
import io
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
PLANTILLAS = RAIZ / "scripts" / "jetson" / "paquete"
PAQUETE = "observatorio-angostura"
APP = "opt/observatorio-angostura"
VERSION = "1.0.1"

# Lo que se instala del proyecto (rutas relativas a la raíz).
INCLUIR = [
    "main_kiosco.py", "main_admin.py", "requirements-jetson.txt", "README.md",
    "config", "src", "web", "assets", "data/semillas",
    "scripts/cli_admin", "scripts/jetson",
    "laboratorio_ia/__init__.py", "laboratorio_ia/simulador_pantalla2/sonidos",
]
EXCLUIR = {
    "config/camara_local.json",  # credenciales de la cámara de ESTE equipo
    "scripts/jetson/paquete", "scripts/jetson/construir_paquete.py",
}
EXCLUIR_NOMBRES = {"__pycache__", ".pytest_cache", "Thumbs.db", "desktop.ini"}
EXCLUIR_EXTENSIONES = {".pyc", ".pyo", ".log", ".bak"}
# Archivos de texto que Linux necesita con saltos de línea LF.
TEXTO_LF = {".sh", ".service", ".desktop", ".conf"}

DEPENDE = ("python3 (>= 3.10), python3-venv, python3-tk, x11-xserver-utils, xinput, fontconfig, "
           "iproute2, procps, gstreamer1.0-tools, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad")
RECOMIENDA = "nano, xdg-utils"  # OpenCV: lo revisa postinst (los nombres cambian entre JetPack 6 y 7)

PLATAFORMAS_PIP = ["linux_aarch64", "manylinux2014_aarch64", "manylinux_2_17_aarch64",
                   "manylinux_2_28_aarch64", "manylinux_2_35_aarch64"]
# Python del sistema de cada JetPack: 6 = Ubuntu 22.04 (3.10), 7 = Ubuntu 24.04 (3.12).
VERSIONES_PYTHON = ["3.10", "3.12"]
# onnxruntime-gpu compilado para el Jetson, por versión de CUDA (lo elige instalar_onnxruntime.sh).
# Verificado el 22-11-2026 en https://pypi.jetson-ai-lab.io
ONNXRUNTIME_GPU = [
    ("jp6-cu126", "3.10", "https://pypi.jetson-ai-lab.io/jp6/cu126/+simple", "onnxruntime-gpu==1.24.0"),
    ("jp7-cu130", "3.12", "https://pypi.jetson-ai-lab.io/sbsa/cu130/+simple", "onnxruntime-gpu==1.24.0"),
]
# Dependencias de onnxruntime(-gpu), para instalarlo sin internet.
DEPENDENCIAS_ONNX = ["flatbuffers", "packaging", "protobuf", "sympy", "coloredlogs"]


def _pip_descargar(destino, version_py, paquetes, indice=None, sin_dependencias=False):
    abi = "cp" + version_py.replace(".", "")
    comando = [sys.executable, "-m", "pip", "download", "-q", "-d", str(destino), "--only-binary=:all:",
               "--python-version", version_py, "--implementation", "cp", "--abi", abi, "--abi", "abi3",
               "--abi", "none", "--disable-pip-version-check"]
    for plataforma in PLATAFORMAS_PIP:
        comando += ["--platform", plataforma]
    if indice:
        comando += ["--index-url", indice]
    if sin_dependencias:
        comando.append("--no-deps")
    resultado = subprocess.run(comando + paquetes)
    if resultado.returncode != 0:
        sys.exit(f"[ERROR] pip no pudo descargar {paquetes} para Python {version_py} (¿hay internet?).")


def descargar_librerias(destino, forzar):
    """
    destino/comunes                 librerías de requirements-jetson.txt (cp310 y cp312)
    destino/onnxruntime/<cuda>      onnxruntime-gpu de Jetson AI Lab para esa CUDA
    destino/onnxruntime/cpu         onnxruntime de CPU (respaldo)
    """
    if (destino / "comunes").is_dir() and (destino / "onnxruntime").is_dir() and not forzar:
        print(f"Librerías ya descargadas en {destino} (usar --descargar para renovarlas)")
        return
    if destino.exists():
        shutil.rmtree(destino)
    requisitos = ["-r", str(RAIZ / "requirements-jetson.txt")]
    for version_py in VERSIONES_PYTHON:
        print(f"Descargando librerías para el Jetson (Python {version_py}, ARM64)...")
        _pip_descargar(destino / "comunes", version_py, requisitos + DEPENDENCIAS_ONNX + ["numpy<2"])
        _pip_descargar(destino / "onnxruntime" / "cpu", version_py, ["onnxruntime"], sin_dependencias=True)
    for carpeta, version_py, indice, paquete in ONNXRUNTIME_GPU:
        print(f"Descargando {paquete} ({carpeta}, Python {version_py})...")
        _pip_descargar(destino / "onnxruntime" / carpeta, version_py, [paquete], indice=indice, sin_dependencias=True)


def con_lf(datos):
    return datos.replace(b"\r\n", b"\n")


def archivos_del_proyecto():
    """(ruta en el paquete, ruta de origen) de cada archivo del programa."""
    for entrada in INCLUIR:
        origen = RAIZ / entrada
        candidatos = [origen] if origen.is_file() else sorted(p for p in origen.rglob("*") if p.is_file())
        for ruta in candidatos:
            relativa = ruta.relative_to(RAIZ).as_posix()
            partes = set(ruta.relative_to(RAIZ).parts)
            if (partes & EXCLUIR_NOMBRES or ruta.suffix.lower() in EXCLUIR_EXTENSIONES
                    or any(relativa == e or relativa.startswith(e + "/") for e in EXCLUIR)):
                continue
            yield f"{APP}/{relativa}", ruta
    for modelo in sorted((RAIZ / "modelos").glob("*.onnx")):
        yield f"{APP}/modelos/{modelo.name}", modelo


def unidad_systemd(nombre):
    texto = (RAIZ / "scripts" / "jetson" / "systemd" / nombre).read_text(encoding="utf-8")
    texto = texto.replace("__RAIZ__", f"/{APP}")
    # El usuario lo fija postinst con un archivo adicional (drop-in), según el equipo.
    lineas = [linea for linea in texto.splitlines() if not linea.startswith("User=")]
    lineas = [linea.replace("Lo instala scripts/jetson/instalar.sh", "Lo instala el paquete .deb") for linea in lineas]
    return ("\n".join(lineas) + "\n").encode("utf-8")


def contenido(librerias):
    """Lista de (ruta en el paquete, bytes | Path, ejecutable)."""
    entradas = []
    for destino, origen in archivos_del_proyecto():
        ejecutable = origen.suffix == ".sh"
        if origen.suffix in TEXTO_LF:
            entradas.append((destino, con_lf(origen.read_bytes()), ejecutable))
        else:
            entradas.append((destino, origen, ejecutable))
    for rueda in sorted(librerias.rglob("*.whl")):
        entradas.append((f"{APP}/paquetes_python/{rueda.relative_to(librerias).as_posix()}", rueda, False))
    for comando in sorted((PLANTILLAS / "bin").iterdir()):
        entradas.append((f"usr/bin/{comando.name}", con_lf(comando.read_bytes()), True))
    for acceso in sorted((PLANTILLAS / "aplicaciones").glob("*.desktop")):
        entradas.append((f"usr/share/applications/{acceso.name}", con_lf(acceso.read_bytes()), False))
    entradas.append(("usr/share/icons/hicolor/scalable/apps/observatorio-angostura.svg",
                     (PLANTILLAS / "observatorio-angostura.svg").read_bytes(), False))
    for fuente in sorted((RAIZ / "assets" / "fuentes").glob("*.ttf")):
        entradas.append((f"usr/share/fonts/truetype/montserrat/{fuente.name}", fuente, False))
    entradas.append(("lib/systemd/system/observatorio-admin.service", unidad_systemd("observatorio-admin.service"), False))
    entradas.append(("usr/lib/systemd/user/observatorio-kiosco.service", unidad_systemd("observatorio-kiosco.service"), False))
    entradas.append((f"usr/share/doc/{PAQUETE}/LEEME_JETSON.md",
                     (RAIZ / "scripts" / "jetson" / "LEEME_JETSON.md").read_bytes(), False))
    return entradas


def _info(nombre, tamano, modo, tipo=tarfile.REGTYPE):
    info = tarfile.TarInfo(nombre)
    info.size, info.mode, info.type = tamano, modo, tipo
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mtime = int(time.time())
    return info


def escribir_tar(ruta_tar, entradas):
    """tar.gz con dueño root y permisos de Linux. Devuelve (md5sums, tamaño instalado en KiB)."""
    md5, total = [], 0
    carpetas = set()
    for destino, _, _ in entradas:
        partes = destino.split("/")[:-1]
        for i in range(1, len(partes) + 1):
            carpetas.add("/".join(partes[:i]))
    with tarfile.open(ruta_tar, "w:gz", format=tarfile.GNU_FORMAT) as tar:
        tar.addfile(_info(".", 0, 0o755, tarfile.DIRTYPE))
        for carpeta in sorted(carpetas):
            tar.addfile(_info(f"./{carpeta}", 0, 0o755, tarfile.DIRTYPE))
        for destino, origen, ejecutable in entradas:
            modo = 0o755 if ejecutable else 0o644
            suma = hashlib.md5()
            if isinstance(origen, Path):
                tamano = origen.stat().st_size
                with open(origen, "rb") as archivo:
                    for bloque in iter(lambda: archivo.read(1 << 20), b""):
                        suma.update(bloque)
                with open(origen, "rb") as archivo:
                    tar.addfile(_info(f"./{destino}", tamano, modo), archivo)
            else:
                tamano = len(origen)
                suma.update(origen)
                tar.addfile(_info(f"./{destino}", tamano, modo), io.BytesIO(origen))
            md5.append(f"{suma.hexdigest()}  {destino}")
            total += tamano
    return "\n".join(md5) + "\n", total // 1024 + len(carpetas)


def escribir_control(ruta_tar, version, instalado_kib, md5sums):
    control = f"""Package: {PAQUETE}
Version: {version}
Architecture: arm64
Maintainer: Observatorio Inteligente Angostura <observatorio@localhost>
Installed-Size: {instalado_kib}
Depends: {DEPENDE}
Recommends: {RECOMIENDA}
Section: science
Priority: optional
Description: Observatorio Inteligente de Aves (kiosco, pantalla tactil y portal)
 Identifica aves en vivo desde la camara IP (detector + clasificador ONNX con
 TensorRT/CUDA en NVIDIA Jetson Orin Nano), muestra el kiosco y la pantalla
 tactil (catalogo y trivia) en dos monitores, y ofrece el portal de
 administracion web en la red local (puerto 5000).
"""
    archivos = {
        "control": (control.encode("utf-8"), 0o644),
        "md5sums": (md5sums.encode("utf-8"), 0o644),
        "conffiles": (f"/{APP}/config/pantallas.conf\n".encode("utf-8"), 0o644),
    }
    for script in ("postinst", "prerm", "postrm"):
        archivos[script] = (con_lf((PLANTILLAS / "DEBIAN" / script).read_bytes()), 0o755)
    with tarfile.open(ruta_tar, "w:gz", format=tarfile.GNU_FORMAT) as tar:
        tar.addfile(_info(".", 0, 0o755, tarfile.DIRTYPE))
        for nombre, (datos, modo) in archivos.items():
            tar.addfile(_info(f"./{nombre}", len(datos), modo), io.BytesIO(datos))


def escribir_ar(ruta_deb, miembros):
    """Formato ar de un .deb: debian-binary, control.tar.gz, data.tar.gz."""
    with open(ruta_deb, "wb") as deb:
        deb.write(b"!<arch>\n")
        for nombre, ruta in miembros:
            tamano = ruta.stat().st_size
            cabecera = (f"{nombre:<16}{int(time.time()):<12}{0:<6}{0:<6}{'100644':<8}{tamano:<10}`\n").encode("ascii")
            deb.write(cabecera)
            with open(ruta, "rb") as origen:
                shutil.copyfileobj(origen, deb, 1 << 20)
            if tamano % 2:
                deb.write(b"\n")


def main(argumentos=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", default=VERSION)
    parser.add_argument("--descargar", action="store_true", help="vuelve a descargar las librerías de Python")
    parser.add_argument("--salida", type=Path, default=RAIZ / "dist")
    args = parser.parse_args(argumentos)

    for modelo in ("detector_aves.onnx", "clasificador_aves.onnx"):
        if not (RAIZ / "modelos" / modelo).is_file():
            sys.exit(f"[ERROR] Falta modelos/{modelo}")
    librerias = RAIZ / "build" / "paquetes_python_jetson"
    descargar_librerias(librerias, args.descargar)

    args.salida.mkdir(parents=True, exist_ok=True)
    deb = args.salida / f"{PAQUETE}_{args.version}_arm64.deb"
    with tempfile.TemporaryDirectory() as temporal:
        temporal = Path(temporal)
        (temporal / "debian-binary").write_bytes(b"2.0\n")
        print("Armando el paquete...")
        entradas = contenido(librerias)
        md5sums, instalado = escribir_tar(temporal / "data.tar.gz", entradas)
        escribir_control(temporal / "control.tar.gz", args.version, instalado, md5sums)
        escribir_ar(deb, [("debian-binary", temporal / "debian-binary"),
                          ("control.tar.gz", temporal / "control.tar.gz"),
                          ("data.tar.gz", temporal / "data.tar.gz")])
    print(f"\nListo: {deb}  ({deb.stat().st_size / 2**20:.0f} MB, {len(entradas)} archivos)")
    print("En el Jetson:  sudo apt install ./" + deb.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
