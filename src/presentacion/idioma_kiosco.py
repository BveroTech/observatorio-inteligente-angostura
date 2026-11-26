"""
Idioma de la pantalla táctil (español, inglés, alemán).

El visitante lo elige en el encabezado de la Pantalla 2. Las fichas se escriben en
español en el portal y sus traducciones están en la tabla FICHA_TRADUCCION
(ver src/aplicacion/servicio_traduccion.py). Aquí están los textos fijos de la ficha
y la superposición de las traducciones sobre los datos del catálogo.
"""
import sqlite3

from config.settings import IDIOMA_ORIGINAL, IDIOMAS
from src.persistencia.repositorio_sqlite import aplicar_traduccion

TEXTOS = {
    "es": {
        "leer_ficha": "Leer ficha", "detener_lectura": "Detener lectura", "preparando": "Preparando voz…",
        "conservacion": "Estado de conservación", "nombre_cientifico": "Nombre científico", "a": "a",
        "cm": "centímetros", "g": "gramos",
        "volver": "Volver", "escuchar": "Escuchar canto", "detener": "Detener audio",
        "ficha_educativa": "Ficha educativa", "sin_foto": "Sin fotografía", "sin_dato": "Sin dato",
        "orden": "Orden", "familia": "Familia", "genero": "Género", "rce": "Chile (RCE)",
        "tamano": "Tamaño", "peso": "Peso", "envergadura": "Envergadura",
        "habitat": "Hábitat", "distribucion": "Distribución", "caracteristicas": "Características distintivas",
        "comportamiento": "Comportamiento", "migracion": "Migración", "alimentacion": "Alimentación",
        "en_observatorio": "EN ESTE OBSERVATORIO", "sin_registros": "La cámara aún no ha registrado esta especie.",
        "hoy": "hoy", "en_total": "en total", "dias": "días con registro", "mejor_confianza": "mejor confianza",
        "primera_vez": "Primera vez", "ultima_vez": "Última vez", "en_demo": "en modo demostración",
        "idioma": "Idioma",
    },
    "en": {
        "leer_ficha": "Read aloud", "detener_lectura": "Stop reading", "preparando": "Preparing voice…",
        "conservacion": "Conservation status", "nombre_cientifico": "Scientific name", "a": "to",
        "cm": "centimetres", "g": "grams",
        "volver": "Back", "escuchar": "Play call", "detener": "Stop audio",
        "ficha_educativa": "Species sheet", "sin_foto": "No photo", "sin_dato": "No data",
        "orden": "Order", "familia": "Family", "genero": "Genus", "rce": "Chile (RCE)",
        "tamano": "Length", "peso": "Weight", "envergadura": "Wingspan",
        "habitat": "Habitat", "distribucion": "Distribution", "caracteristicas": "Distinctive features",
        "comportamiento": "Behaviour", "migracion": "Migration", "alimentacion": "Diet",
        "en_observatorio": "AT THIS OBSERVATORY", "sin_registros": "The camera has not recorded this species yet.",
        "hoy": "today", "en_total": "in total", "dias": "days recorded", "mejor_confianza": "best confidence",
        "primera_vez": "First seen", "ultima_vez": "Last seen", "en_demo": "in demo mode",
        "idioma": "Language",
    },
    "de": {
        "leer_ficha": "Vorlesen", "detener_lectura": "Vorlesen stoppen", "preparando": "Stimme wird geladen…",
        "conservacion": "Gefährdungsstatus", "nombre_cientifico": "Wissenschaftlicher Name", "a": "bis",
        "cm": "Zentimeter", "g": "Gramm",
        "volver": "Zurück", "escuchar": "Ruf anhören", "detener": "Audio stoppen",
        "ficha_educativa": "Artensteckbrief", "sin_foto": "Kein Foto", "sin_dato": "Keine Angabe",
        "orden": "Ordnung", "familia": "Familie", "genero": "Gattung", "rce": "Chile (RCE)",
        "tamano": "Länge", "peso": "Gewicht", "envergadura": "Spannweite",
        "habitat": "Lebensraum", "distribucion": "Verbreitung", "caracteristicas": "Merkmale",
        "comportamiento": "Verhalten", "migracion": "Zugverhalten", "alimentacion": "Nahrung",
        "en_observatorio": "IN DIESEM OBSERVATORIUM", "sin_registros": "Die Kamera hat diese Art noch nicht erfasst.",
        "hoy": "heute", "en_total": "insgesamt", "dias": "Tage mit Nachweis", "mejor_confianza": "beste Sicherheit",
        "primera_vez": "Erstmals", "ultima_vez": "Zuletzt", "en_demo": "im Demo-Modus",
        "idioma": "Sprache",
    },
}


def tx(clave, idioma=IDIOMA_ORIGINAL):
    return TEXTOS.get(idioma, TEXTOS["es"]).get(clave) or TEXTOS["es"].get(clave, clave)


class TraduccionesCatalogo:
    """Superpone las traducciones a las fichas del catálogo; relee solo si la base cambió."""

    def __init__(self, base):
        self.base = base
        self._cache = {}

    def mapa(self, idioma):
        if idioma == IDIOMA_ORIGINAL or idioma not in IDIOMAS:
            return {}
        try:
            version = self.base.version_datos()
            clave = (idioma, version)
            if clave not in self._cache:
                self._cache = {clave: self.base.mapa_traducciones(idioma)}
            return self._cache[clave]
        except sqlite3.Error:
            return next(iter(self._cache.values()), {})

    def especie(self, especie, idioma):
        if not especie or idioma == IDIOMA_ORIGINAL:
            return especie
        return aplicar_traduccion(especie, self.mapa(idioma).get(especie.get("id_especie")))

    def lista(self, especies, idioma):
        if idioma == IDIOMA_ORIGINAL:
            return especies
        mapa = self.mapa(idioma)
        return [aplicar_traduccion(e, mapa.get(e.get("id_especie"))) for e in especies]


def _medida_hablada(valor, unidad, idioma):
    """'100-125' cm -> '100 a 125 centímetros' (to / bis en inglés y alemán)."""
    texto = str(valor).strip().replace("–", "-")
    texto = texto.replace("-", f" {tx('a', idioma)} ") if texto.count("-") == 1 else texto
    if idioma != "en":
        texto = texto.replace(".", ",")
    return f"{texto} {tx(unidad, idioma)}"


def parrafos_ficha(e, idioma):
    """Texto que se lee en voz alta, en párrafos (cada uno se sintetiza aparte)."""
    import re

    parrafos = [f"{e.get('nombre_comun', '')}."]
    estado = (e.get("conservacion_uicn") or "").strip()
    sigla = re.match(r"^[A-Z]{2} \((.*)\)$", estado)  # "LC (Least Concern)" -> "Least Concern"
    if sigla:
        estado = sigla.group(1)
    if estado:
        parrafos.append(f"{tx('conservacion', idioma)}: {estado}.")
    medidas = [f"{tx(nombre, idioma)}: {_medida_hablada(e[campo], unidad, idioma)}"
               for campo, nombre, unidad in (("tamano_cm", "tamano", "cm"), ("peso_g", "peso", "g"),
                                             ("envergadura_cm", "envergadura", "cm")) if e.get(campo)]
    if medidas:
        parrafos.append(". ".join(medidas) + ".")
    for campo in ("habitat", "distribucion", "caracteristicas", "comportamiento", "migracion", "alimentacion"):
        texto = (e.get(campo) or "").strip()
        if texto:
            parrafos.append(f"{tx(campo, idioma)}. {texto.rstrip('.')}.")
    return parrafos
