"""
Lector de fichas técnicas (OCR) en español, inglés y alemán, con Tesseract.

Lee una foto, un escaneo o un PDF de una ficha técnica de un ave y reconoce sus
secciones (hábitat, medidas, estado de conservación...) para rellenar la ficha en
el portal. El idioma del documento lo elige quien la sube: Tesseract lee mejor
cuando sabe el idioma.

Tesseract es un programa aparte (winget install -e --id UB-Mannheim.TesseractOCR).
Se busca en este orden: config TESSERACT_CMD, variable de entorno TESSERACT_CMD,
carpeta tesseract/ junto al programa (versión instalada), C:\\Program Files\\Tesseract-OCR,
y el PATH. Los idiomas (spa, eng, deu) están en modelos/tessdata.
"""
import io
import os
import re
import shutil
import subprocess
from pathlib import Path

from config import settings

IDIOMA_TESSERACT = {"es": "spa", "en": "eng", "de": "deu"}
EXTENSIONES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".pdf"}
MAXIMO_PAGINAS_PDF = 8

# Títulos de cada sección en los tres idiomas (se aceptan todos, sea cual sea el idioma elegido).
ETIQUETAS = {
    "nombre_comun": ["nombre común", "nombre comun", "nombre vulgar", "common name", "english name",
                     "deutscher name", "trivialname"],
    "nombre_cientifico": ["nombre científico", "nombre cientifico", "scientific name", "binomial name",
                          "wissenschaftlicher name", "lateinischer name"],
    "genero": ["género", "genero", "genus", "gattung"],
    "familia": ["familia", "family", "familie"],
    "orden": ["orden", "order", "ordnung"],
    "tamano_cm": ["tamaño", "tamano", "longitud", "largo", "size", "length", "body length", "größe", "grösse",
                  "länge", "körperlänge"],
    "peso_g": ["peso", "weight", "mass", "body mass", "gewicht", "körpergewicht"],
    "envergadura_cm": ["envergadura", "wingspan", "wing span", "flügelspannweite", "spannweite"],
    "conservacion_uicn": ["estado de conservación uicn", "estado de conservación", "estado de conservacion",
                          "conservación", "conservacion", "uicn", "iucn", "iucn status", "conservation status",
                          "gefährdungsstatus", "rote liste", "schutzstatus", "iucn-status"],
    "conservacion_rce": ["rce", "estado en chile", "clasificación nacional", "clasificacion nacional",
                         "categoría nacional", "status in chile", "status in chile (rce)"],
    "caracteristicas": ["características distintivas", "caracteristicas distintivas", "características",
                        "caracteristicas", "descripción", "descripcion", "identificación", "identificacion",
                        "description", "identification", "appearance", "field marks", "beschreibung",
                        "merkmale", "kennzeichen", "aussehen", "erkennungsmerkmale"],
    "habitat": ["hábitat", "habitat", "lebensraum"],
    "distribucion": ["distribución", "distribucion", "distribution", "range", "geographic range",
                     "verbreitung", "verbreitungsgebiet"],
    "migracion": ["migración", "migracion", "movimientos", "migration", "movements", "zug", "zugverhalten",
                  "wanderung", "wanderverhalten"],
    "comportamiento": ["comportamiento", "conducta", "behavior", "behaviour", "verhalten"],
    "alimentacion": ["alimentación", "alimentacion", "dieta", "diet", "food", "feeding", "ernährung",
                     "nahrung"],
}
MEDIDAS = {"tamano_cm": "cm", "envergadura_cm": "cm", "peso_g": "g"}

_TODAS = sorted(((e, c) for c, lista in ETIQUETAS.items() for e in lista), key=lambda x: -len(x[0]))
_PATRON_ETIQUETA = re.compile(
    r"^\s*[•\-–*]?\s*(" + "|".join(re.escape(e) for e, _ in _TODAS) + r")\b\s*(?:\(([^)]{0,20})\))?\s*[:.\-–]?\s*(.*)$",
    re.IGNORECASE,
)
_CAMPO_DE = {e: c for e, c in _TODAS}


class LectorNoDisponible(RuntimeError):
    pass


# ----------------------------------------------------------------------
# Tesseract
# ----------------------------------------------------------------------

def ruta_tesseract():
    candidatos = [settings.TESSERACT_CMD, os.environ.get("TESSERACT_CMD", ""),
                  str(settings.BASE_DIR / "tesseract" / "tesseract.exe"),
                  str(settings.BASE_DIR / "tesseract" / "tesseract")]
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidatos.append(os.path.join(base, "Tesseract-OCR", "tesseract.exe"))
            candidatos.append(os.path.join(base, "Programs", "Tesseract-OCR", "tesseract.exe"))
    candidatos.append(shutil.which("tesseract") or "")
    return next((c for c in candidatos if c and Path(c).is_file()), None)


def carpeta_idiomas(ejecutable=None):
    """modelos/tessdata si trae los idiomas; si no, la carpeta tessdata de Tesseract."""
    if (settings.CARPETA_TESSDATA / "spa.traineddata").is_file():
        return settings.CARPETA_TESSDATA
    if ejecutable:
        propia = Path(ejecutable).parent / "tessdata"
        if propia.is_dir():
            return propia
    return None


def estado():
    """Para el portal: si se puede leer y en qué idiomas."""
    ejecutable = ruta_tesseract()
    info = {"disponible": False, "ruta": ejecutable, "version": "", "idiomas": [], "faltan": []}
    if not ejecutable:
        info["error"] = "Tesseract no está instalado (winget install -e --id UB-Mannheim.TesseractOCR)."
        return info
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        info["error"] = "Falta la librería pytesseract (pip install pytesseract)."
        return info
    idiomas = carpeta_idiomas(ejecutable)
    if idiomas:
        presentes = {p.stem for p in Path(idiomas).glob("*.traineddata")}
    else:
        presentes = set()
    info["idiomas"] = [i for i, t in IDIOMA_TESSERACT.items() if t in presentes]
    info["faltan"] = [i for i, t in IDIOMA_TESSERACT.items() if t not in presentes]
    try:
        salida = subprocess.run([ejecutable, "--version"], capture_output=True, text=True, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        info["version"] = (salida.stdout or salida.stderr).splitlines()[0].strip()
    except (OSError, subprocess.SubprocessError, IndexError):
        pass
    info["disponible"] = bool(info["idiomas"])
    if info["faltan"]:
        info["error"] = ("Faltan idiomas de Tesseract: " + ", ".join(info["faltan"])
                         + " (python scripts/cli_admin/descargar_modelos_idiomas.py)")
    return info


def _ocr_imagen(imagen, idioma):
    import pytesseract
    from PIL import ImageOps

    ejecutable = ruta_tesseract()
    if not ejecutable:
        raise LectorNoDisponible("Tesseract no está instalado.")
    pytesseract.pytesseract.tesseract_cmd = ejecutable
    codigo = IDIOMA_TESSERACT.get(idioma, "spa")
    carpeta = carpeta_idiomas(ejecutable)
    if carpeta is None or not (Path(carpeta) / f"{codigo}.traineddata").is_file():
        raise LectorNoDisponible(f"Falta el idioma «{codigo}» de Tesseract (descargar_modelos_idiomas.py).")
    imagen = ImageOps.exif_transpose(imagen).convert("L")
    if imagen.width < 1600:  # Tesseract lee mejor con letras de ~30 px
        factor = 1600 / imagen.width
        imagen = imagen.resize((1600, int(imagen.height * factor)))
    # TESSDATA_PREFIX y no --tessdata-dir: en Windows las comillas de una ruta con
    # espacios (p. ej. la carpeta de instalación) llegan literales a Tesseract.
    os.environ["TESSDATA_PREFIX"] = str(carpeta)
    return pytesseract.image_to_string(imagen, lang=codigo, config="--psm 3")


def leer_documento(datos, nombre_archivo, idioma):
    """Texto de una imagen o PDF (bytes). Usa el texto del PDF si lo tiene; si es escaneado, OCR."""
    from PIL import Image

    extension = Path(nombre_archivo or "").suffix.lower()
    if extension not in EXTENSIONES:
        raise ValueError("Formato no admitido. Usa una foto (JPG, PNG, TIFF) o un PDF.")
    if extension != ".pdf":
        with Image.open(io.BytesIO(datos)) as imagen:
            imagen.load()
            return _ocr_imagen(imagen, idioma)
    try:
        import fitz  # PyMuPDF
    except ImportError as error:
        raise LectorNoDisponible("Falta la librería PyMuPDF para leer PDF (pip install pymupdf).") from error
    textos = []
    with fitz.open(stream=datos, filetype="pdf") as documento:
        for pagina in list(documento)[:MAXIMO_PAGINAS_PDF]:
            texto = pagina.get_text("text")
            if len(texto.strip()) >= 40:
                textos.append(texto)  # PDF con texto: no hace falta OCR
                continue
            mapa = pagina.get_pixmap(dpi=300)
            imagen = Image.frombytes("RGB", (mapa.width, mapa.height), mapa.samples)
            textos.append(_ocr_imagen(imagen, idioma))
    return "\n".join(textos)


# ----------------------------------------------------------------------
# Del texto a los campos de la ficha
# ----------------------------------------------------------------------

def _numero(texto):
    return float(texto.replace(",", "."))


def normalizar_medida(valor, campo):
    """'102–124 cm' -> '102-124'; convierte mm/m a cm y kg a g. Devuelve el texto original si no entiende."""
    destino = MEDIDAS[campo]
    texto = valor.replace("–", "-").replace("—", "-")
    coincidencia = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:(?:-|a|bis|to)\s*(\d+(?:[.,]\d+)?))?\s*(mm|cm|kg|g|m)\b", texto, re.IGNORECASE)
    if not coincidencia:
        return valor.strip()
    desde, hasta, unidad = coincidencia.group(1), coincidencia.group(2), coincidencia.group(3).lower()
    factores = {("mm", "cm"): 0.1, ("m", "cm"): 100, ("cm", "cm"): 1, ("kg", "g"): 1000, ("g", "g"): 1}
    factor = factores.get((unidad, destino))
    if factor is None:
        return valor.strip()

    def formato(numero):
        resultado = _numero(numero) * factor
        return str(int(round(resultado))) if abs(resultado - round(resultado)) < 0.05 else f"{resultado:.1f}"

    return formato(desde) + (f"-{formato(hasta)}" if hasta else "")


def extraer_campos(texto):
    """{campo: valor} de las secciones reconocidas. Una sección sigue hasta el próximo título."""
    campos, actual, partes = {}, None, []

    def cerrar():
        if actual and partes:
            valor = re.sub(r"[ \t]+", " ", " ".join(p.strip() for p in partes if p.strip())).strip()
            valor = re.sub(r"-\s+(?=[a-záéíóúñäöüß])", "", valor)  # une palabras cortadas al final de línea
            if valor and actual not in campos:
                campos[actual] = valor

    for linea in texto.splitlines():
        coincidencia = _PATRON_ETIQUETA.match(linea)
        # Un título es corto o va seguido de ":" (evita confundir "el hábitat de..." con un título).
        if coincidencia and (":" in linea[:60] or len(linea.strip()) <= 40):
            cerrar()
            actual = _CAMPO_DE.get(coincidencia.group(1).lower())
            partes = [coincidencia.group(3)]
            continue
        if actual:
            partes.append(linea)
    cerrar()

    # Taxonomía en latín, igual en todos los idiomas: "Entenvögel (Anatidae)" -> "Anatidae".
    for campo, final in (("familia", "idae"), ("orden", "formes")):
        if campo in campos:
            latin = re.search(rf"\b([A-Z][a-z]+{final})\b", campos[campo])
            if latin:
                campos[campo] = latin.group(1)
    for campo in MEDIDAS:
        if campo in campos:
            campos[campo] = normalizar_medida(campos[campo], campo)[:30]
    if "nombre_cientifico" not in campos:
        binomial = re.search(r"^\s*([A-Z][a-z]{2,} [a-z]{3,})\s*$", texto, re.MULTILINE)
        if binomial:
            campos["nombre_cientifico"] = binomial.group(1)
    if "nombre_cientifico" in campos:
        palabras = campos["nombre_cientifico"].split()
        campos["nombre_cientifico"] = " ".join(palabras[:2])
        campos.setdefault("genero", palabras[0])
    return campos
