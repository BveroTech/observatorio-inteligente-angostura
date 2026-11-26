"""
Traducción de las fichas de especies del español al inglés y al alemán.

- Al guardar una ficha en el portal se traducen los campos de texto que cambiaron
  (en segundo plano, sin internet). Ver traducir_en_segundo_plano().
- Lo que el personal corrige a mano en el portal queda marcado como "manual" y no
  se vuelve a traducir solo; si después cambia el texto en español, el portal avisa.
- Los estados de conservación (UICN y RCE) se traducen con un diccionario fijo con
  los nombres oficiales de las categorías, no con el traductor automático.

    python scripts/cli_admin/traducir_fichas.py          traduce todo el catálogo
"""
import hashlib
import logging
import re
import threading

from src.persistencia.repositorio_sqlite import CAMPOS_TRADUCIBLES, IDIOMAS_TRADUCCION, BaseDatos

registro = logging.getLogger("observatorio.traduccion")

CAMPOS_CONSERVACION = ("conservacion_uicn", "conservacion_rce")

# Categorías UICN / RCE y lugares frecuentes en el catálogo. Orden: de lo más largo a lo más corto.
CONSERVACION = [
    ("En Peligro Crítico", "Critically Endangered", "Vom Aussterben bedroht"),
    ("Preocupación Menor", "Least Concern", "Nicht gefährdet"),
    ("Datos Insuficientes", "Data Deficient", "Unzureichende Datenlage"),
    ("Especie Introducida", "Introduced species", "Eingeführte Art"),
    ("Casi Amenazado", "Near Threatened", "Potenziell gefährdet"),
    ("Casi Amenazada", "Near Threatened", "Potenziell gefährdet"),
    ("Fuera de Peligro", "Out of Danger", "Nicht mehr gefährdet"),
    ("Menor Riesgo", "Lower Risk", "Geringes Risiko"),
    ("No Evaluado", "Not Evaluated", "Nicht beurteilt"),
    ("Extinto", "Extinct", "Ausgestorben"),
    ("En Peligro", "Endangered", "Stark gefährdet"),
    ("Vulnerable", "Vulnerable", "Gefährdet"),
    ("Rara", "Rare", "Selten"),
    ("Chile central y norte", "central and northern Chile", "Zentral- und Nordchile"),
    ("Chile continental", "mainland Chile", "Festland-Chile"),
    ("Chile central", "central Chile", "Zentralchile"),
    ("Global", "Global", "Weltweit"),
    (" en ", " in ", " in "),
    ("(en ", "(in ", "(in "),
]

_en_curso = set()
_candado = threading.Lock()


def huella(texto):
    """Identifica el texto en español del que salió una traducción."""
    return hashlib.sha1((texto or "").strip().encode("utf-8")).hexdigest()[:16]


def traducir_conservacion(texto, idioma):
    """Traduce un estado de conservación con el diccionario; None si queda algo sin reconocer."""
    columna = 1 if idioma == "en" else 2
    resultado, sin_reconocer = texto, texto
    for fila in CONSERVACION:
        # Las preposiciones distinguen mayúsculas: "EN" es la sigla UICN de En Peligro.
        opciones = 0 if fila[0].strip(" (") == "en" else re.IGNORECASE
        patron = re.escape(fila[0])
        resultado = re.sub(patron, fila[columna], resultado, flags=opciones)
        sin_reconocer = re.sub(patron, " ", sin_reconocer, flags=opciones)
    # Si quedan palabras que el diccionario no conoce, se usa el traductor automático.
    sin_reconocer = re.sub(r"\b(LC|NT|VU|EN|CR|DD|NE|EX|EW|Chile|y)\b", " ", sin_reconocer)
    return None if re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{2,}", sin_reconocer) else resultado


def conservacion_a_espanol(texto, idioma):
    """Inverso del diccionario: 'Least Concern' / 'nicht gefährdet' -> 'Preocupación Menor'."""
    columna = 1 if idioma == "en" else 2
    resultado = texto
    for fila in sorted(CONSERVACION, key=lambda f: -len(f[columna])):
        if fila[columna].strip(" (") in ("in",):
            continue
        resultado = re.sub(rf"\b{re.escape(fila[columna])}\b", fila[0], resultado, flags=re.IGNORECASE)
    return resultado


def a_espanol(campo, texto, idioma):
    """Texto leído de una ficha técnica en inglés o alemán, llevado al español."""
    from src.aplicacion.traductor import traducir

    if not texto or idioma == "es":
        return texto
    if campo in CAMPOS_CONSERVACION:
        directo = conservacion_a_espanol(texto, idioma)
        if directo != texto:
            return directo
    return traducir(texto, idioma, "es")


def traducir_texto(campo, texto, idioma):
    from src.aplicacion.traductor import traducir

    if campo in CAMPOS_CONSERVACION:
        directo = traducir_conservacion(texto, idioma)
        if directo is not None:
            return directo
    return traducir(texto, "es", idioma)


def estado_traducciones(base, especie):
    """
    Para el portal: {idioma: {campo: {"texto", "manual", "desactualizada", "falta"}}}.
    desactualizada = el español cambió después de traducir/corregir este campo.
    """
    estado = {}
    for idioma in IDIOMAS_TRADUCCION:
        filas = base.traducciones(especie["id_especie"], idioma) if especie.get("id_especie") else {}
        estado[idioma] = {}
        for campo in CAMPOS_TRADUCIBLES:
            original = (especie.get(campo) or "").strip()
            fila = filas.get(campo)
            estado[idioma][campo] = {
                "texto": (fila or {}).get("texto") or "",
                "manual": bool((fila or {}).get("manual")),
                "desactualizada": bool(fila and original and fila.get("huella_original") != huella(original)),
                "falta": bool(original and not (fila and fila.get("texto"))),
            }
    return estado


def traducir_especie(base, id_especie, idiomas=IDIOMAS_TRADUCCION, forzar=False, campos=None):
    """
    Traduce los campos de una especie que lo necesiten. Devuelve cuántos tradujo.
    forzar=True vuelve a traducir también lo corregido a mano.
    """
    especie = base.especie(id_especie)
    if especie is None:
        return 0
    total = 0
    for idioma in idiomas:
        existentes = base.traducciones(id_especie, idioma)
        for campo in campos or CAMPOS_TRADUCIBLES:
            original = (especie.get(campo) or "").strip()
            actual = existentes.get(campo)
            if not original:
                if actual and not actual.get("manual"):
                    base.guardar_traduccion(id_especie, idioma, campo, "", huella(""))
                continue
            if actual and not forzar:
                if actual.get("manual"):
                    continue  # corrección del personal: no se pisa
                if actual.get("huella_original") == huella(original) and actual.get("texto"):
                    continue  # ya está traducido este mismo texto
            texto = traducir_texto(campo, original, idioma)
            base.guardar_traduccion(id_especie, idioma, campo, texto, huella(original))
            total += 1
    return total


def traducir_en_segundo_plano(ruta_base, id_especie, forzar=False, campos=None):
    """Traduce sin bloquear el portal. Ignora la petición si esa especie ya se está traduciendo."""
    from src.aplicacion.traductor import traductor_disponible

    if not traductor_disponible():
        registro.warning("Faltan los modelos de traducción (scripts/cli_admin/descargar_modelos_idiomas.py)")
        return False
    with _candado:
        if id_especie in _en_curso:
            return True
        _en_curso.add(id_especie)

    def trabajo():
        base = None
        try:
            base = BaseDatos(ruta_base)
            cantidad = traducir_especie(base, id_especie, forzar=forzar, campos=campos)
            registro.info("Especie %s: %s campos traducidos", id_especie, cantidad)
        except Exception:
            registro.exception("No se pudo traducir la especie %s", id_especie)
        finally:
            if base is not None:
                base.cerrar()
            with _candado:
                _en_curso.discard(id_especie)

    threading.Thread(target=trabajo, daemon=True, name=f"traducir_{id_especie}").start()
    return True


def traduciendo(id_especie):
    with _candado:
        return id_especie in _en_curso
