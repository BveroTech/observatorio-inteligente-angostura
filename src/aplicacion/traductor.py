"""
Traducción sin conexión entre español, inglés y alemán (fichas de especies).

Usa modelos OPUS-MT (CC-BY 4.0) empaquetados por Argos Translate, ejecutados con
CTranslate2 + SentencePiece (sin PyTorch). Están en modelos/traduccion/<origen>_<destino>
y se descargan con scripts/cli_admin/descargar_modelos_idiomas.py.

Pares directos: es->en, en->es, en->de, de->en. Español <-> alemán pasa por el inglés.

    from src.aplicacion.traductor import traducir, traductor_disponible
    traducir("Habita lagunas y ríos.", "es", "de")
"""
import logging
import re
import threading

from config.settings import CARPETA_TRADUCCION

registro = logging.getLogger("observatorio.traduccion")

_cache = {}
_candado = threading.Lock()
ultimo_error = ""  # por qué no está disponible (para mostrarlo al usuario)

# Separa oraciones: punto/!/? seguido de espacio y mayúscula, o salto de línea.
_FIN_ORACION = re.compile(r"(?<=[.!?…])\s+(?=[\"'«(¿¡]?[A-ZÁÉÍÓÚÑÄÖÜ0-9])")


def ruta_modelo(origen, destino):
    return CARPETA_TRADUCCION / f"{origen}_{destino}"


def _ruta_pares(origen, destino):
    """Lista de pares (origen, destino) a encadenar."""
    if origen == destino:
        return []
    if ruta_modelo(origen, destino).is_dir():
        return [(origen, destino)]
    if origen != "en" and destino != "en":
        return [(origen, "en"), ("en", destino)]
    return [(origen, destino)]


def traductor_disponible(origen="es", destino=None):
    """True si están los modelos para traducir de origen a destino (o a todos los idiomas)."""
    global ultimo_error
    try:
        import ctranslate2  # noqa: F401
        import sentencepiece  # noqa: F401
    except ImportError as error:
        ultimo_error = f"no se pudo cargar la librería de traducción: {error}"
        return False
    destinos = [destino] if destino else [d for d in ("es", "en", "de") if d != origen]
    for idioma in destinos:
        for par in _ruta_pares(origen, idioma):
            carpeta = ruta_modelo(*par)
            if not ((carpeta / "model.bin").is_file() and (carpeta / "sentencepiece.model").is_file()):
                ultimo_error = f"falta el traductor {par[0]}->{par[1]} en {carpeta}"
                return False
    ultimo_error = ""
    return True


def _modelo(origen, destino):
    clave = (origen, destino)
    with _candado:
        if clave not in _cache:
            import ctranslate2
            import sentencepiece

            carpeta = ruta_modelo(origen, destino)
            if not (carpeta / "model.bin").is_file():
                raise FileNotFoundError(
                    f"Falta el traductor {origen}->{destino} en {carpeta}. "
                    "Ejecuta scripts/cli_admin/descargar_modelos_idiomas.py")
            traductor = ctranslate2.Translator(str(carpeta), device="cpu", inter_threads=1, intra_threads=0)
            tokenizador = sentencepiece.SentencePieceProcessor(model_file=str(carpeta / "sentencepiece.model"))
            _cache[clave] = (traductor, tokenizador)
            registro.info("Traductor %s->%s cargado", origen, destino)
        return _cache[clave]


def _oraciones(parrafo):
    return [o.strip() for o in _FIN_ORACION.split(parrafo) if o.strip()]


def _traducir_par(texto, origen, destino):
    traductor, tokenizador = _modelo(origen, destino)
    parrafos = texto.split("\n")
    oraciones, mapa = [], []
    for indice, parrafo in enumerate(parrafos):
        for oracion in _oraciones(parrafo):
            mapa.append(indice)
            oraciones.append(tokenizador.encode(oracion, out_type=str))
    if not oraciones:
        return texto
    resultados = traductor.translate_batch(oraciones, beam_size=4, max_decoding_length=256,
                                           replace_unknowns=True, max_batch_size=16)
    salida = [[] for _ in parrafos]
    for indice, resultado in zip(mapa, resultados):
        salida[indice].append(tokenizador.decode(resultado.hypotheses[0]))
    return "\n".join(" ".join(partes) for partes in salida)


def traducir(texto, origen, destino):
    """Traduce texto (puede tener varios párrafos). Devuelve el mismo texto si origen == destino."""
    if not texto or not texto.strip() or origen == destino:
        return texto
    resultado = texto
    for par in _ruta_pares(origen, destino):
        resultado = _traducir_par(resultado, *par)
    return resultado
