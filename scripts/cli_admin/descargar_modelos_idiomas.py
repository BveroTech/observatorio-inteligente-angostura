"""
Descarga los modelos para leer y traducir las fichas en español, inglés y alemán.
Se ejecuta UNA vez (necesita internet); después todo funciona sin conexión.

    python scripts/cli_admin/descargar_modelos_idiomas.py

Deja en modelos/:
  tessdata/{spa,eng,deu,osd}.traineddata   idiomas de Tesseract (lector de documentos, OCR)
  voces/                                   voces Piper para leer la ficha en voz alta
                                           (es_MX-claude-high, en_US-lessac-medium, de_DE-thorsten-medium)
  traduccion/{es_en,en_de,en_es,de_en}/    traductores sin conexión (OPUS-MT empaquetados por
                                           Argos Translate; CTranslate2 + SentencePiece).
                                           Español <-> alemán pasa por el inglés.

Licencias: Tesseract tessdata Apache-2.0; modelos OPUS-MT CC-BY 4.0 (Tiedemann y Thottingal, 2020).
Tesseract (el programa) se instala aparte: winget install -e --id UB-Mannheim.TesseractOCR
"""
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from config.settings import CARPETA_TESSDATA, CARPETA_TRADUCCION, CARPETA_VOCES, VOCES  # noqa: E402

TESSDATA = "https://github.com/tesseract-ocr/tessdata/raw/main/{}.traineddata"
# Voces Piper (rhasspy/piper-voices). Licencias en el .onnx.json de cada voz.
URL_VOCES = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{familia}/{region}/{nombre}/{calidad}/{voz}{ext}"
IDIOMAS_TESSERACT = ["spa", "eng", "deu", "osd"]
# Versiones con tokenizador SentencePiece (las 1.9 de es_en usan BPE de otro formato).
TRADUCTORES = {
    "es_en": "https://argos-net.com/v1/translate-es_en-1_0.argosmodel",
    "en_es": "https://argos-net.com/v1/translate-en_es-1_0.argosmodel",
    "en_de": "https://argos-net.com/v1/translate-en_de-1_3.argosmodel",
    "de_en": "https://argos-net.com/v1/translate-de_en-1_3.argosmodel",
}


def descargar(url, destino):
    print(f"  {url}")
    temporal = destino.with_suffix(destino.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as respuesta, open(temporal, "wb") as archivo:
        shutil.copyfileobj(respuesta, archivo, 1 << 20)
    temporal.replace(destino)


def instalar_traductor(par, url):
    destino = CARPETA_TRADUCCION / par
    if (destino / "model.bin").is_file() and (destino / "sentencepiece.model").is_file():
        print(f"Traductor {par}: ya está.")
        return
    print(f"Traductor {par}: descargando...")
    with tempfile.TemporaryDirectory() as temporal:
        paquete = Path(temporal) / f"{par}.argosmodel"
        descargar(url, paquete)
        with zipfile.ZipFile(paquete) as zip_modelo:
            nombres = zip_modelo.namelist()
            raiz = nombres[0].split("/")[0]
            if destino.exists():
                shutil.rmtree(destino)
            destino.mkdir(parents=True)
            for nombre in nombres:
                if nombre.endswith("/"):
                    continue
                relativo = nombre[len(raiz) + 1:]
                if relativo.startswith("model/"):
                    salida = destino / relativo[len("model/"):]
                elif relativo in ("sentencepiece.model", "metadata.json", "README.md"):
                    salida = destino / relativo
                else:
                    continue  # stanza/ (separador de oraciones con PyTorch): no se usa
                with zip_modelo.open(nombre) as origen, open(salida, "wb") as archivo:
                    shutil.copyfileobj(origen, archivo)
    print(f"Traductor {par}: listo en {destino}")


def main():
    CARPETA_TESSDATA.mkdir(parents=True, exist_ok=True)
    for idioma in IDIOMAS_TESSERACT:
        archivo = CARPETA_TESSDATA / f"{idioma}.traineddata"
        if archivo.is_file() and archivo.stat().st_size > 1_000_000:
            print(f"Tesseract {idioma}: ya está.")
            continue
        print(f"Tesseract {idioma}: descargando...")
        descargar(TESSDATA.format(idioma), archivo)
    for par, url in TRADUCTORES.items():
        instalar_traductor(par, url)
    CARPETA_VOCES.mkdir(parents=True, exist_ok=True)
    for voz in VOCES.values():
        region, nombre, calidad = voz.split("-")
        for ext in (".onnx", ".onnx.json"):
            destino = CARPETA_VOCES / f"{voz}{ext}"
            if destino.is_file() and destino.stat().st_size > 1000:
                continue
            print(f"Voz {voz}{ext}: descargando...")
            descargar(URL_VOCES.format(familia=region.split("_")[0], region=region, nombre=nombre,
                                       calidad=calidad, voz=voz, ext=ext), destino)
    print("Voces: listas.")
    print("\nModelos de idiomas listos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
