import platform

from config.settings import CARPETA_ASSETS

# ----------------------------------------------------------
# Textos de marca
# ----------------------------------------------------------

TITULO = "Observatorio Inteligente de Aves"
SUBTITULO = "Embalse Angostura · Región del Biobío"
PIE = "Proyecto de título INACAP · Prototipo académico, no es un producto oficial de Colbún"

# Si existe assets/logo.png se muestra en el encabezado.
ARCHIVO_LOGO = "logo.png"
ALTO_LOGO = 44

# ----------------------------------------------------------
# Colores del manual
# ----------------------------------------------------------

AZUL = "#00B2E6"          # primario · RGB 0-178-230
VERDE = "#8BBB2F"         # primario · RGB 138-187-47
NARANJA = "#FF8031"       # primario · RGB 255-128-49
GRIS = "#706F6F"          # primario · RGB 112-111-111
AMARILLO = "#FFCD00"      # secundario · RGB 255-205-0
AZUL_OSCURO = "#3662B2"   # secundario · RGB 54-98-178

# Degradado de marca (barra superior y marca del encabezado).
DEGRADADO = (AZUL, VERDE, NARANJA)

# ----------------------------------------------------------
# Usos en la interfaz
# ----------------------------------------------------------

ACENTO = AZUL_OSCURO          # botones, enlaces, títulos de sección, cifras
ACENTO_HOVER = AZUL           # botón con el puntero encima
ACENTO_CLARO = "#D9F3FB"      # azul al 15 %: selección en listas y tablas

TEXTO = "#3C3C3B"             # títulos y texto principal
GRIS_CLARO = "#9D9C9C"        # ayudas y texto terciario

FONDO = "#FFFFFF"
FONDO_SUAVE = "#F2FBFE"       # azul al 5 %: fondo de página y recuadros
BORDE = "#E2E2E2"             # gris al 20 %

# Superficies del Centro Interactivo. Los tonos ya incluyen la mezcla acrílica.
ESCRITORIO = "#E5F0F5"
DIVISOR = "#C9DEE9"
CRISTAL = "#E5F5FC"
CRISTAL_ACCION = "#C9EBF8"
CRISTAL_REFLEJO = "#FAFEFF"
CRISTAL_BORDE = "#92D7F0"
CRISTAL_HOVER = "#B6E4F7"
CRISTAL_TEXTO = "#143D55"
ESTILO_TARJETA_CRISTAL = {
    "fg_color": CRISTAL,
    "border_color": CRISTAL_BORDE,
    "border_width": 2,
    "corner_radius": 16,
}

PIE_FONDO = GRIS
PIE_TEXTO = "#FFFFFF"

VIDEO_FONDO = "#1E1E1E"
VIDEO_TEXTO = "#E2E2E2"

# Fondos de etiquetas (el texto de las etiquetas va siempre en TEXTO).
ETIQUETA_BIEN = "#E8F1D5"     # verde al 20 %: preocupación menor, reconocida
ETIQUETA_ATENCION = "#FFF0B2" # amarillo al 30 %: casi amenazada, rara
ETIQUETA_RIESGO = "#FFD9C1"   # naranja al 30 %: vulnerable, en peligro, Ley de Caza
ETIQUETA_INFO = "#CCF0FA"     # azul al 20 %
ETIQUETA_NEUTRA = "#F1F1F1"   # gris al 10 %

# Colores de las cajas sobre el video (RGB).
CAJA_IDENTIFICADA = (139, 187, 47)    # verde
CAJA_IDENTIFICANDO = (240, 240, 240)  # blanco
CAJA_SIN_FICHA = (255, 128, 49)       # naranja
CAJA_DESCARTADA = (157, 156, 156)     # gris
TEXTO_ETIQUETA = (30, 30, 30)

# ----------------------------------------------------------
# Tipografía (basada en CARPETA_ASSETS con soporte _MEIPASS)
# ----------------------------------------------------------

CARPETA_FUENTES = CARPETA_ASSETS / "fuentes"

if platform.system().lower() == "windows":
    FAMILIA = "Arial"
elif platform.system().lower() == "darwin":
    FAMILIA = "Arial"
else:
    FAMILIA = "DejaVu Sans"


def configurar_fuente(root):
    global FAMILIA
    import tkinter.font as tkfont

    if platform.system().lower() == "windows" and CARPETA_FUENTES.is_dir():
        try:
            import ctypes

            FR_PRIVATE = 0x10
            for ruta in CARPETA_FUENTES.glob("*.ttf"):
                ctypes.windll.gdi32.AddFontResourceExW(str(ruta), FR_PRIVATE, 0)
        except Exception as error:
            print("No se pudo cargar Montserrat:", error)

    try:
        if "Montserrat" in tkfont.families(root):
            FAMILIA = "Montserrat"
    except Exception:
        pass
    return FAMILIA


def fuente(tamano, *estilos):
    return (FAMILIA, tamano) + tuple(estilos)


def fuente_ctk(tamano, peso="normal", inclinada=False):
    import customtkinter as ctk
    return ctk.CTkFont(family=FAMILIA, size=tamano, weight=peso, slant="italic" if inclinada else "roman")


def fuente_pil(tamano, negrita=True):
    from PIL import ImageFont
    archivo = CARPETA_FUENTES / ("Montserrat-Bold.ttf" if negrita else "Montserrat-Regular.ttf")
    try:
        return ImageFont.truetype(str(archivo), tamano)
    except OSError:
        return ImageFont.load_default()


def mezclar(color_a, color_b, proporcion):
    a = [int(color_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(color_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02X%02X%02X" % tuple(round(x + (y - x) * proporcion) for x, y in zip(a, b))


def color_en_degradado(posicion):
    tramos = len(DEGRADADO) - 1
    posicion = min(max(posicion, 0.0), 1.0) * tramos
    indice = min(int(posicion), tramos - 1)
    return mezclar(DEGRADADO[indice], DEGRADADO[indice + 1], posicion - indice)
