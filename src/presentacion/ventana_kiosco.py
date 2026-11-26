import sqlite3
import threading
import time
import tkinter as tk
from datetime import datetime

import customtkinter as ctk
import cv2
from PIL import Image, ImageTk

from config.settings import (
    CARPETA_ASSETS,
    FPS_VIDEO,
    KIOSCO_PANTALLA_COMPLETA,
    MONITOR_KIOSCO,
    SEGUNDOS_AUTOLIMPIEZA_PANEL,
    SEGUNDOS_CIERRE_FICHA,
    VIDEO_LLENAR_RECUADRO,
)
from src.aplicacion.gestor_monitores import rect_monitor
from src.persistencia.repositorio_sqlite import BaseDatos, ruta_absoluta
from src.presentacion.idioma_kiosco import tx
from src.presentacion import tema_visual as T
from src.presentacion.cache_imagenes import FOTO_FICHA, EtiquetaFoto

ALTO_BOTON = 52
TAMANO_MINIATURA = (112, 84)
ANCHO_PANEL = 360


def texto_uicn(valor):
    valor = (valor or "").strip()
    if len(valor) > 4 and valor[2:4] == " (" and valor.endswith(")") and valor.count("(") == 1:
        return valor[4:-1]
    return valor


def color_conservacion(texto):
    t = (texto or "").lower()
    # Primero "no amenazada" en alemán ("nicht gefährdet" contiene "gefährdet").
    if "nicht gefährdet" in t or "least concern" in t:
        return T.ETIQUETA_BIEN
    for clave in ("peligro", "vulnerable", "cr (", "en (", "vu (", "endangered", "gefährdet", "bedroht"):
        if clave in t:
            return T.ETIQUETA_RIESGO
    for clave in ("casi amenaz", "nt (", "rara", "menor riesgo", "near threatened", "rare", "lower risk",
                  "selten", "geringes risiko"):
        if clave in t:
            return T.ETIQUETA_ATENCION
    if "preocupación menor" in t or "preocupacion menor" in t or "lc (" in t:
        return T.ETIQUETA_BIEN
    return T.ETIQUETA_NEUTRA


def hace_cuanto(segundos):
    segundos = max(0, int(segundos))
    if segundos < 5:
        return "ahora"
    if segundos < 60:
        return f"hace {segundos} s"
    return f"hace {segundos // 60} min"


def abrir_imagen(ruta, tamano):
    ruta = ruta_absoluta(ruta)
    if ruta is None or not ruta.is_file():
        return None
    try:
        imagen = Image.open(ruta).convert("RGB")
    except OSError:
        return None
    imagen.thumbnail(tamano)
    return ctk.CTkImage(light_image=imagen, dark_image=imagen, size=imagen.size)


def barra_degradado(padre, alto=5, ancho=None, vertical=False):
    lienzo = tk.Canvas(padre, height=alto, highlightthickness=0, bd=0, bg=T.FONDO)
    if ancho:
        lienzo.configure(width=ancho)

    def dibujar(_evento=None):
        lienzo.delete("all")
        largo = lienzo.winfo_height() if vertical else lienzo.winfo_width()
        grosor = lienzo.winfo_width() if vertical else lienzo.winfo_height()
        for inicio in range(0, max(largo, 1), 3):
            color = T.color_en_degradado(inicio / max(largo - 1, 1))
            if vertical:
                lienzo.create_rectangle(0, inicio, grosor, inicio + 3, fill=color, outline="")
            else:
                lienzo.create_rectangle(inicio, 0, inicio + 3, grosor, fill=color, outline="")

    lienzo.bind("<Configure>", dibujar)
    return lienzo


class FichaEspecie(ctk.CTkToplevel):
    """Ventana modal con la ficha educativa de una especie."""

    def __init__(self, maestro, especie, ruta_captura="", resumen=None):
        super().__init__(maestro, fg_color=T.FONDO)
        self.title(especie["nombre_comun"])
        ancho = min(1040, maestro.winfo_width() - 80)
        alto = min(700, maestro.winfo_height() - 60)
        x = maestro.winfo_rootx() + (maestro.winfo_width() - ancho) // 2
        y = maestro.winfo_rooty() + (maestro.winfo_height() - alto) // 2
        self.geometry(f"{ancho}x{alto}+{max(0, x)}+{max(0, y)}")
        self.transient(maestro)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.cerrar)

        barra_degradado(self, alto=6).pack(fill="x")

        pie = ctk.CTkFrame(self, fg_color=T.FONDO)
        pie.pack(fill="x", side="bottom", padx=28, pady=(8, 20))
        ctk.CTkButton(
            pie,
            text="Cerrar",
            command=self.cerrar,
            height=ALTO_BOTON,
            width=200,
            corner_radius=26,
            fg_color=T.ACENTO,
            hover_color=T.ACENTO_HOVER,
            font=T.fuente_ctk(18, "bold"),
        ).pack(side="right")

        contenido = ctk.CTkScrollableFrame(self, fg_color=T.FONDO)
        try:
            contenido._scrollbar.configure(width=25)
        except (AttributeError, tk.TclError):
            pass
        contenido.pack(fill="both", expand=True, padx=12, pady=(6, 0))
        llenar_ficha(contenido, especie, ruta_captura, ancho, resumen)

        self._ultimo_toque = time.monotonic()
        # La ventana es parte de las etiquetas de eventos de todos sus hijos,
        # así que cualquier toque dentro de la ficha reinicia el contador.
        for evento in ("<Button-1>", "<Motion>", "<MouseWheel>"):
            self.bind(evento, self._toque, add="+")
        self.after(1000, self._vigilar_inactividad)
        self.after(50, self._tomar_foco)

    def _tomar_foco(self):
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except tk.TclError:
            pass

    def _toque(self, _evento=None):
        self._ultimo_toque = time.monotonic()

    def _vigilar_inactividad(self):
        if not self.winfo_exists():
            return
        if time.monotonic() - self._ultimo_toque > SEGUNDOS_CIERRE_FICHA:
            self.cerrar()
            return
        self.after(1000, self._vigilar_inactividad)

    def cerrar(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


def insignia_conservacion_cristal(padre, texto, estado, ancho, tamano=13):
    fondo = T.mezclar(color_conservacion(estado), T.CRISTAL_REFLEJO, 0.35)
    insignia = ctk.CTkFrame(padre, fg_color=fondo, border_color=T.CRISTAL_BORDE, border_width=2, corner_radius=12)
    ctk.CTkLabel(
        insignia, text=texto, font=T.fuente_ctk(tamano, "bold"), text_color=T.CRISTAL_TEXTO,
        justify="left", anchor="w", wraplength=max(1, ancho - 16), height=20,
    ).pack(fill="x", padx=8, pady=4)
    return insignia


def llenar_ficha(contenedor, e, ruta_captura, ancho, resumen=None, compacta=False, *, cristal=False,
                 obtener_imagen=abrir_imagen, idioma="es"):
    """
    Contenido completo de la ficha de una especie (lo usan el kiosco y el catálogo).
    idioma: "es", "en" o "de" para los títulos; los textos de `e` ya vienen traducidos.
    """
    ancho_texto = ancho - 120
    tamano_foto = FOTO_FICHA if compacta else (360, 270)
    margen = 12 if cristal else 0
    ancho_cabecera = max(120, ancho - tamano_foto[0] - 64 - 2 * margen) if compacta else ancho_texto - 380
    fondo = "transparent" if cristal else T.FONDO
    color_texto = T.CRISTAL_TEXTO if cristal else T.TEXTO
    estilo_panel = T.ESTILO_TARJETA_CRISTAL if cristal else {"fg_color": T.FONDO}

    cabecera = ctk.CTkFrame(contenedor, **estilo_panel)
    cabecera.pack(fill="x", padx=16, pady=(14, 0))

    imagen = obtener_imagen(e.get("ruta_foto"), tamano_foto) or obtener_imagen(ruta_captura, tamano_foto)
    if imagen is not None:
        foto = EtiquetaFoto(cabecera, text="", image=imagen)
    else:
        foto = ctk.CTkLabel(
            cabecera, text=tx("sin_foto", idioma), width=min(300, tamano_foto[0]), height=min(220, tamano_foto[1]),
            fg_color=T.CRISTAL_REFLEJO if cristal else T.FONDO_SUAVE,
            text_color=color_texto if cristal else T.GRIS_CLARO, corner_radius=12, font=T.fuente_ctk(14),
        )
    foto.pack(side="left", anchor="n", padx=(margen, 24), pady=margen)

    textos = ctk.CTkFrame(cabecera, fg_color=fondo)
    textos.pack(side="left", fill="both", expand=True, anchor="n", padx=(0, margen), pady=margen)
    ctk.CTkLabel(
        textos, text=e["nombre_comun"], font=T.fuente_ctk(32, "bold"), text_color=color_texto,
        anchor="w", justify="left", wraplength=ancho_cabecera,
    ).pack(fill="x")
    ctk.CTkLabel(
        textos, text=e["nombre_cientifico"], font=T.fuente_ctk(18, inclinada=True),
        text_color=T.GRIS, anchor="w", justify="left", wraplength=ancho_cabecera if compacta else 0,
    ).pack(fill="x")
    taxonomia = " · ".join(
        f"{tx(campo, idioma)} {e[campo]}" for campo in ("orden", "familia", "genero") if e.get(campo)
    )
    if taxonomia:
        ctk.CTkLabel(
            textos, text=taxonomia, font=T.fuente_ctk(14), text_color=T.GRIS, anchor="w",
            justify="left", wraplength=ancho_cabecera,
        ).pack(fill="x", pady=(8, 0))

    etiquetas = ctk.CTkFrame(textos, fg_color=fondo)
    etiquetas.pack(fill="x", pady=(14, 0))
    for prefijo, estado in (("UICN" if idioma == "es" else "IUCN", e.get("conservacion_uicn")),
                            (tx("rce", idioma), e.get("conservacion_rce"))):
        valor = texto_uicn(estado) if prefijo in ("UICN", "IUCN") else estado
        if not valor:
            continue
        if cristal:
            insignia_conservacion_cristal(etiquetas, f"{prefijo} · {valor}", estado, ancho_cabecera).pack(
                anchor="w", pady=(0, 4),
            )
        else:
            ctk.CTkLabel(
                etiquetas, text=f"  {prefijo} · {valor}  ", font=T.fuente_ctk(14, "bold"),
                fg_color=color_conservacion(valor), text_color=T.TEXTO, corner_radius=14, height=32,
                wraplength=ancho_cabecera if compacta else 0, justify="left",
            ).pack(side="top" if compacta else "left", anchor="w", padx=(0, 10), pady=(0, 4) if compacta else 0)

    medidas = ctk.CTkFrame(contenedor, fg_color=fondo)
    medidas.pack(fill="x", padx=16, pady=(22, 0))
    for columna, (campo, nombre, unidad) in enumerate(
        (("tamano_cm", tx("tamano", idioma), "cm"), ("peso_g", tx("peso", idioma), "g"),
         ("envergadura_cm", tx("envergadura", idioma), "cm"))
    ):
        medidas.grid_columnconfigure(columna, weight=1, uniform="medidas")
        estilo_caja = estilo_panel if cristal else {"fg_color": T.FONDO_SUAVE, "corner_radius": 12}
        caja = ctk.CTkFrame(medidas, **estilo_caja)
        caja.grid(row=0, column=columna, sticky="ew", padx=(0 if columna == 0 else 12, 0))
        valor = e.get(campo)
        ctk.CTkLabel(
            caja, text=f"{valor} {unidad}" if valor else tx("sin_dato", idioma), font=T.fuente_ctk(22, "bold"),
            text_color=color_texto if cristal else (T.ACENTO if valor else T.GRIS_CLARO), anchor="w",
        ).pack(fill="x", padx=18, pady=(12, 0))
        ctk.CTkLabel(caja, text=nombre, font=T.fuente_ctk(13), text_color=T.GRIS, anchor="w").pack(
            fill="x", padx=18, pady=(0, 12)
        )

    _registro(contenedor, resumen, ancho_texto if compacta else 0, cristal=cristal, idioma=idioma)

    secciones = ctk.CTkFrame(contenedor, fg_color=fondo)
    secciones.pack(fill="x", padx=16, pady=(22, 10))
    secciones.grid_columnconfigure((0, 1), weight=1, uniform="secciones")
    campos = ("habitat", "distribucion", "caracteristicas", "comportamiento", "migracion", "alimentacion")
    campos = [(tx(campo, idioma), e[campo]) for campo in campos if e.get(campo)]
    for indice, (titulo, texto) in enumerate(campos):
        bloque = ctk.CTkFrame(secciones, **estilo_panel)
        bloque.grid(
            row=indice // 2, column=indice % 2, sticky="nsew" if cristal else "nw",
            padx=(0, 24) if indice % 2 == 0 else 0, pady=(0, 16),
        )
        ctk.CTkLabel(
            bloque, text=titulo.upper(), font=T.fuente_ctk(13, "bold"), text_color=T.ACENTO, anchor="w"
        ).pack(fill="x", padx=margen, pady=(margen, 0))
        ctk.CTkLabel(
            bloque, text=texto, font=T.fuente_ctk(16), text_color=color_texto, anchor="w",
            justify="left", wraplength=ancho_texto // 2 - 20,
        ).pack(fill="x", padx=margen, pady=(2, margen))


def _registro(contenedor, resumen, ancho_texto=0, *, cristal=False, idioma="es"):
    """Cifras de avistamientos de la especie en este observatorio."""
    estilo = T.ESTILO_TARJETA_CRISTAL if cristal else {"fg_color": T.ETIQUETA_INFO, "corner_radius": 12}
    fondo = "transparent" if cristal else T.ETIQUETA_INFO
    caja = ctk.CTkFrame(contenedor, **estilo)
    caja.pack(fill="x", padx=16, pady=(16, 0))
    ctk.CTkLabel(
        caja, text=tx("en_observatorio", idioma), font=T.fuente_ctk(13, "bold"), text_color=T.ACENTO, anchor="w"
    ).pack(fill="x", padx=18, pady=(10, 0))
    total = (resumen or {}).get("total") or 0
    if not total:
        ctk.CTkLabel(
            caja, text=tx("sin_registros", idioma), font=T.fuente_ctk(15),
            text_color=T.TEXTO, anchor="w",
        ).pack(fill="x", padx=18, pady=(2, 12))
        return
    fila = ctk.CTkFrame(caja, fg_color=fondo)
    fila.pack(fill="x", padx=10, pady=(2, 4))

    def fecha(texto):
        try:
            return datetime.strptime(texto, "%Y-%m-%d %H:%M:%S").strftime("%d-%m-%Y %H:%M")
        except (TypeError, ValueError):
            return texto or "—"

    datos = [
        (str(resumen.get("hoy") or 0), tx("hoy", idioma)),
        (str(total), tx("en_total", idioma)),
        (str(resumen.get("dias") or 0), tx("dias", idioma)),
        (f"{(resumen.get('confianza_max') or 0) * 100:.0f} %", tx("mejor_confianza", idioma)),
    ]
    for columna, (valor, texto) in enumerate(datos):
        fila.grid_columnconfigure(columna, weight=1, uniform="registro")
        celda = ctk.CTkFrame(fila, fg_color=fondo)
        celda.grid(row=0, column=columna, sticky="ew", padx=8)
        ctk.CTkLabel(celda, text=valor, font=T.fuente_ctk(22, "bold"), text_color=T.ACENTO, anchor="w").pack(fill="x")
        ctk.CTkLabel(celda, text=texto, font=T.fuente_ctk(13), text_color=T.GRIS, anchor="w").pack(fill="x")
    demo = total - (resumen.get("reales") or 0)
    nota = (f"{tx('primera_vez', idioma)}: {fecha(resumen.get('primero'))} · "
            f"{tx('ultima_vez', idioma)}: {fecha(resumen.get('ultimo'))}")
    if demo:
        nota += f" · {demo} {tx('en_demo', idioma)}"
    ctk.CTkLabel(
        caja, text=nota, font=T.fuente_ctk(13), text_color=T.GRIS, anchor="w",
        justify="left", wraplength=ancho_texto,
    ).pack(
        fill="x", padx=18, pady=(2, 12)
    )


class PreparadorVideo(threading.Thread):
    """Publica un solo fotograma listo para Tk, al tamaño actual del visor.

    Toma cada cuadro nuevo directamente de la fuente (hasta FPS_VIDEO por
    segundo) y le dibuja encima los recuadros del último análisis del motor.
    Así el video avanza a la velocidad de la cámara aunque la IA analice
    menos cuadros por segundo; los recuadros se actualizan al ritmo de la IA.
    """

    def __init__(self, motor, fuente):
        super().__init__(name="preparacion_video", daemon=True)
        self.motor = motor
        self.fuente = fuente
        self.tamano = (0, 0)
        self.ultimo = None
        self.fin = threading.Event()

    def run(self):
        id_cuadro = None
        procesado = None
        contador = 0
        intervalo = 0.6 / FPS_VIDEO  # tope de velocidad, con margen para el vaivén de llegada de los cuadros
        anterior = 0.0
        while not self.fin.wait(0.003):
            if time.monotonic() - anterior < intervalo:
                continue
            nuevo_id, cuadro, _, _ = self.fuente.ultimo_cuadro(despues_de=id_cuadro)
            id_capas, tamano_capas, capas, _ = self.motor.capas_actuales()
            tamano = self.tamano
            if cuadro is not None:
                id_cuadro = nuevo_id
                self._cuadro = cuadro
            cuadro = getattr(self, "_cuadro", None)
            clave = (id_cuadro, id_capas, tamano)
            if cuadro is None or min(tamano) <= 20 or clave == procesado:
                continue
            procesado = clave
            anterior = time.monotonic()
            ancho, alto = tamano
            alto_cuadro, ancho_cuadro = cuadro.shape[:2]
            factor = max if VIDEO_LLENAR_RECUADRO else min
            escala = factor(ancho / ancho_cuadro, alto / alto_cuadro)
            medida = (max(1, round(ancho_cuadro * escala)), max(1, round(alto_cuadro * escala)))
            interpolacion = cv2.INTER_AREA if escala < 1 else cv2.INTER_LINEAR
            preparada = cv2.resize(cuadro, medida, interpolation=interpolacion) if medida != (ancho_cuadro, alto_cuadro) else cuadro
            dx = dy = 0
            if VIDEO_LLENAR_RECUADRO and medida != tamano:
                dx, dy = (medida[0] - ancho) // 2, (medida[1] - alto) // 2
                preparada = preparada[dy:dy + alto, dx:dx + ancho]
            imagen = Image.fromarray(cv2.cvtColor(preparada, cv2.COLOR_BGR2RGB))
            if tamano_capas == (alto_cuadro, ancho_cuadro):
                self.motor.dibujar_capas(imagen, capas, escala, (dx, dy), clave=id_capas)
            contador += 1
            self.ultimo = ((contador, tamano), imagen)


class Kiosco(ctk.CTk):
    def __init__(self, motor, fuente, pantalla_completa=KIOSCO_PANTALLA_COMPLETA, monitor=MONITOR_KIOSCO):
        ctk.set_appearance_mode("light")
        super().__init__(fg_color=T.FONDO_SUAVE)
        T.configurar_fuente(self)
        self.motor = motor
        self.fuente = fuente
        self.base = BaseDatos()
        self.pantalla_secundaria = None
        self.title(T.TITULO)
        self.geometry("1366x768")
        self.minsize(1100, 680)
        # Monitor y pantalla completa se eligen en scripts/lanzadores_windows/ejecutar_observatorio.bat.
        self._rect_monitor = rect_monitor(monitor)
        self._completa = False
        if self._rect_monitor is not None:
            x, y, ancho, alto = self._rect_monitor
            self.geometry(f"{min(1366, ancho)}x{min(768, alto)}+{x + 40}+{y + 40}")

            def ubicar():
                # CustomTkinter reubica la ventana al mostrarla por primera vez: se fija
                # de nuevo ya visible, y otra vez después de abrir la Pantalla 2.
                if self.cerrando or not self.winfo_exists():
                    return
                self._pantalla_completa(self._completa or pantalla_completa)

            self.after(400, ubicar)
            self.after(1500, ubicar)
        elif monitor is not None:
            print(f"[AVISO] No existe el monitor {monitor}; el kiosco se abre en el principal.")
        self.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.bind("<F11>", lambda _e: self._pantalla_completa(not self._completa))
        self.bind("<Escape>", lambda _e: self._pantalla_completa(False))
        if pantalla_completa and self._rect_monitor is None:
            self.after(200, lambda: self._pantalla_completa(True))

        self._tarjetas = {}
        self._version_catalogo = None
        self._orden_pendiente = None
        self._imagen_tk = None
        self._ultimo_id_imagen = 0
        self._ultimo_video = None
        self._preparador_video = PreparadorVideo(motor, fuente)
        self._ficha = None
        self.cerrando = False
        self._modo_informado = False

        self._crear_encabezado()
        self._crear_cuerpo()
        self._preparador_video.start()

        self.after(30, self._ciclo_video)
        self.after(200, self._ciclo_eventos)
        self.after(500, self._ciclo_estado)

    # ------------------------------------------------------
    # Construcción
    # ------------------------------------------------------

    def _maximizar(self):
        """Maximiza la ventana: state('zoomed') solo existe en Windows; en Linux (X11) es -zoomed."""
        try:
            if self.tk.call("tk", "windowingsystem") == "win32":
                self.state("zoomed")
            else:
                self.attributes("-zoomed", True)
        except tk.TclError as error:
            print("No se pudo maximizar la ventana:", error)

    def _pantalla_completa(self, activar):
        """Pantalla completa en el monitor elegido (F11 alterna, Esc sale).

        Tk pone «-fullscreen» siempre en el monitor principal; para usar otro
        monitor se quita el borde y se ocupa su rectángulo exacto (igual que la Pantalla 2).
        """
        if self.cerrando or not self.winfo_exists():
            return
        rect = self._rect_monitor
        if rect is None:
            self.attributes("-fullscreen", bool(activar))
            self._completa = bool(activar)
            return
        x, y, ancho, alto = rect
        self.attributes("-fullscreen", False)
        self.state("normal")
        if activar:
            self.overrideredirect(True)
            self.wm_geometry(f"{ancho}x{alto}+{x}+{y}")  # wm_geometry: sin el escalado de CustomTkinter
        else:
            self.overrideredirect(False)
            self.wm_geometry(f"+{x + 40}+{y + 40}")
            self.update_idletasks()
            self._maximizar()
        self.update_idletasks()
        # Al frente de otras ventanas de ese monitor (Windows no deja que una ventana
        # nueva se ponga encima sola): «siempre visible» un instante y luego normal.
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.winfo_exists() and self.attributes("-topmost", False))
        self.focus_force()
        self._completa = bool(activar)

    def _crear_encabezado(self):
        barra_degradado(self, alto=5).pack(fill="x", side="top")
        encabezado = ctk.CTkFrame(self, fg_color=T.FONDO, corner_radius=0, height=54)
        encabezado.pack(fill="x", side="top")
        encabezado.pack_propagate(False)

        marca = ctk.CTkFrame(encabezado, fg_color=T.FONDO)
        marca.pack(side="left", padx=20)
        logo = CARPETA_ASSETS / T.ARCHIVO_LOGO
        imagen = abrir_imagen(logo, (300, 34)) if logo.exists() else None
        if imagen is not None:
            ctk.CTkLabel(marca, text="", image=imagen).pack(side="left", padx=(0, 12))
        else:
            barra_degradado(marca, alto=34, ancho=6, vertical=True).pack(side="left", padx=(0, 10))
        textos = ctk.CTkFrame(marca, fg_color=T.FONDO)
        textos.pack(side="left")
        ctk.CTkLabel(textos, text=T.TITULO, font=T.fuente_ctk(17, "bold"), text_color=T.TEXTO, anchor="w",
                     height=20).pack(fill="x")
        ctk.CTkLabel(textos, text=T.SUBTITULO, font=T.fuente_ctk(11), text_color=T.GRIS, anchor="w",
                     height=14).pack(fill="x")

        derecha = ctk.CTkFrame(encabezado, fg_color=T.FONDO)
        derecha.pack(side="right", padx=20)
        self.reloj = ctk.CTkLabel(derecha, text="", font=T.fuente_ctk(17, "bold"), text_color=T.TEXTO)
        self.reloj.pack(side="right", padx=(14, 0))
        self.chip_estado = ctk.CTkLabel(
            derecha, text="", font=T.fuente_ctk(12, "bold"), text_color=T.TEXTO,
            fg_color=T.ETIQUETA_NEUTRA, corner_radius=13, height=26,
        )
        self.chip_estado.pack(side="right")

    def _crear_cuerpo(self):
        cuerpo = ctk.CTkFrame(self, fg_color=T.FONDO_SUAVE)
        cuerpo.pack(fill="both", expand=True, padx=10, pady=(8, 10))
        cuerpo.grid_columnconfigure(0, weight=1)
        cuerpo.grid_rowconfigure(0, weight=1)

        # El video ocupa todo el espacio disponible a la izquierda.
        self.zona_video = tk.Frame(cuerpo, bg=T.VIDEO_FONDO)
        self.zona_video.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.zona_video.pack_propagate(False)
        self.zona_video.bind("<Configure>", self._ajustar_visor_video, add="+")
        self.etiqueta_video = tk.Label(self.zona_video, bg=T.VIDEO_FONDO, bd=0)
        self.etiqueta_video.place(relx=0.5, rely=0.5, anchor="center")
        self.mensaje_video = tk.Label(
            self.zona_video, text="Iniciando la cámara…", bg=T.VIDEO_FONDO, fg=T.VIDEO_TEXTO,
            font=T.fuente(16), justify="center", wraplength=600,
        )
        self.mensaje_video.place(relx=0.5, rely=0.5, anchor="center")
        self.aviso_demo = ctk.CTkLabel(
            self.zona_video,
            text="  MODO DEMOSTRACIÓN · La cámara no responde: se muestra un video grabado  ",
            font=T.fuente_ctk(15, "bold"), fg_color=T.NARANJA, text_color=T.TEXTO, corner_radius=0, height=40,
        )

        panel = ctk.CTkFrame(cuerpo, fg_color=T.FONDO, corner_radius=18, width=ANCHO_PANEL)
        panel.grid(row=0, column=1, sticky="ns")
        panel.pack_propagate(False)
        ctk.CTkLabel(panel, text="Avistamientos Recientes", font=T.fuente_ctk(20, "bold"), text_color=T.TEXTO, anchor="w").pack(
            fill="x", padx=22, pady=(16, 0)
        )
        ctk.CTkLabel(
            panel, text="Últimas detecciones de la cámara", font=T.fuente_ctk(14), text_color=T.GRIS, anchor="w"
        ).pack(fill="x", padx=22, pady=(0, 10))

        self.lista = ctk.CTkFrame(panel, fg_color=T.FONDO)
        self.lista.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.lista.pack_propagate(False)
        tk.Misc.bind(self.lista, "<Configure>", self._programar_orden_panel, add="+")
        self.vacio = ctk.CTkLabel(
            self.lista, text="No hay avistamientos recientes.\nLas aves confirmadas\naparecerán aquí.",
            font=T.fuente_ctk(15), text_color=T.GRIS_CLARO, justify="center",
        )
        self.vacio.pack(pady=40)

    # ------------------------------------------------------
    # Panel de aves avistadas
    # ------------------------------------------------------

    def _tarjeta(self, id_especie, nombre):
        tarjeta = ctk.CTkFrame(self.lista, fg_color=T.FONDO, border_color=T.BORDE, border_width=1, corner_radius=14, cursor="hand2")
        foto = ctk.CTkLabel(
            tarjeta, text="Sin foto", width=TAMANO_MINIATURA[0],
            height=TAMANO_MINIATURA[1], fg_color=T.FONDO_SUAVE, corner_radius=10, text_color=T.GRIS_CLARO,
        )
        foto.pack(side="left", padx=10, pady=10)
        textos = ctk.CTkFrame(tarjeta, fg_color=T.FONDO)
        textos.pack(side="left", fill="both", expand=True, pady=10, padx=(0, 10))
        titulo = ctk.CTkLabel(
            textos, text=nombre, font=T.fuente_ctk(17, "bold"), text_color=T.TEXTO, anchor="w", justify="left", wraplength=170
        )
        titulo.pack(fill="x")
        detalle = ctk.CTkLabel(textos, text="", font=T.fuente_ctk(13), text_color=T.GRIS, anchor="w")
        detalle.pack(fill="x")
        for widget in (tarjeta, foto, textos, titulo, detalle):
            widget.bind("<Button-1>", lambda _e, i=id_especie: self.abrir_ficha(i))
        return {
            "marco": tarjeta, "titulo": titulo, "foto": foto, "detalle": detalle,
            "id_avistamiento": None, "miniatura": "", "ruta_foto": "",
        }

    def _programar_orden_panel(self, _evento=None):
        if self._orden_pendiente is None:
            self._orden_pendiente = self.after_idle(self._ordenar_panel)

    def _ordenar_panel(self):
        self._orden_pendiente = None
        altura = self.lista.winfo_height()
        margen = round(self.lista._apply_widget_scaling(6))
        visibles = []
        for datos in sorted(self._tarjetas.values(), key=lambda d: d["visto"], reverse=True):
            tarjeta = datos["marco"]
            altura -= tarjeta.winfo_reqheight() + 2 * margen
            if altura < 0:
                break
            visibles.append(tarjeta)
        actuales = self.lista.pack_slaves()
        deseadas = visibles if self._tarjetas else [self.vacio]
        if actuales == deseadas:
            return
        for widget in actuales:
            widget.pack_forget()
        for tarjeta in visibles:
            tarjeta.pack(fill="x", padx=8, pady=6)
        if not self._tarjetas:
            self.vacio.pack(pady=40)

    def _evento(self, evento):
        id_especie = evento["id_especie"]
        id_avistamiento = evento.get("id_avistamiento")
        nombre_cientifico = evento.get("nombre_cientifico")
        datos = self._tarjetas.get(id_especie)
        cambia_registro = datos is None or datos["id_avistamiento"] != id_avistamiento
        cambia_identidad = datos is not None and nombre_cientifico and datos["cientifico"] != nombre_cientifico.casefold()
        if cambia_registro or cambia_identidad or evento.get("tipo") == "nuevo":
            especie = self.base.especie(id_especie)
            if especie is None or not especie["activo"]:
                return
            cientifico = especie["nombre_cientifico"].casefold()
            if nombre_cientifico and nombre_cientifico.casefold() != cientifico:
                return
            if id_avistamiento is not None and not self.base.ids_avistamientos_existentes([id_avistamiento]):
                return
            if datos is None:
                datos = self._tarjeta(id_especie, especie["nombre_comun"])
                self._tarjetas[id_especie] = datos
            datos["id_avistamiento"] = id_avistamiento
            datos["cientifico"] = cientifico
            datos["titulo"].configure(text=especie["nombre_comun"])
            self._actualizar_foto_tarjeta(datos, evento.get("miniatura") or "", especie.get("ruta_foto"))
        datos["visto"] = time.monotonic()
        datos["confianza"] = evento.get("confianza", 0)
        self._actualizar_tarjeta(datos)
        self._programar_orden_panel()

    @staticmethod
    def _actualizar_foto_tarjeta(datos, miniatura, ruta_foto):
        if (miniatura, ruta_foto) == (datos["miniatura"], datos["ruta_foto"]):
            return
        datos["miniatura"], datos["ruta_foto"] = miniatura, ruta_foto
        imagen = abrir_imagen(miniatura, TAMANO_MINIATURA) or abrir_imagen(ruta_foto, TAMANO_MINIATURA)
        datos["foto"].configure(text="" if imagen else "Sin foto", image=imagen or "")

    def _refrescar_catalogo_panel(self):
        version = self.base.version_datos()
        if version == self._version_catalogo:
            return
        ids = [d["id_avistamiento"] for d in self._tarjetas.values() if d["id_avistamiento"] is not None]
        existentes = self.base.ids_avistamientos_existentes(ids)
        for id_especie, datos in list(self._tarjetas.items()):
            especie = self.base.especie(id_especie)
            id_avistamiento = datos["id_avistamiento"]
            if (
                not especie or not especie["activo"] or especie["nombre_cientifico"].casefold() != datos["cientifico"]
                or (id_avistamiento is not None and id_avistamiento not in existentes)
            ):
                self._tarjetas.pop(id_especie)["marco"].destroy()
            else:
                datos["titulo"].configure(text=especie["nombre_comun"])
                self._actualizar_foto_tarjeta(datos, datos["miniatura"], especie.get("ruta_foto"))
        self._version_catalogo = version
        self._programar_orden_panel()

    def _actualizar_tarjeta(self, datos):
        datos["detalle"].configure(
            text=f"Vista {hace_cuanto(time.monotonic() - datos['visto'])} · {datos['confianza'] * 100:.0f} %"
        )

    def abrir_ficha(self, id_especie):
        especie = self.base.especie(id_especie)
        if especie is None or not especie["activo"]:
            return
        if self._ficha is not None and self._ficha.winfo_exists():
            self._ficha.cerrar()
        captura = (self._tarjetas.get(id_especie) or {}).get("miniatura") or ""
        try:
            resumen = self.base.resumen_especie(id_especie)
        except Exception:
            resumen = None
        self._ficha = FichaEspecie(self, especie, captura, resumen)

    # ------------------------------------------------------
    # Ciclos
    # ------------------------------------------------------

    def _ajustar_visor_video(self, evento):
        self._preparador_video.tamano = (evento.width, evento.height)

    def abrir_pantalla_secundaria(self, crear):
        """Crea la Pantalla 2 con el refresco del video en pausa.

        En Windows, CustomTkinter llama a update() al crear la ventana, que procesa
        eventos hasta vaciar la cola; con el video a 30 FPS la cola nunca se vacía y
        la Pantalla 2 no terminaba de abrirse. Pausar el video ~1 s lo evita.
        """
        self._video_en_pausa = True
        try:
            self.pantalla_secundaria = crear()
        finally:
            self._video_en_pausa = False
        return self.pantalla_secundaria

    def _ciclo_video(self):
        if self.cerrando or not self.winfo_exists():
            return
        if getattr(self, "_video_en_pausa", False):
            self.after(100, self._ciclo_video)
            return
        ultimo = self._preparador_video.ultimo
        if ultimo is not None:
            clave, imagen = ultimo
            if clave != self._ultimo_video and clave[1] == self._preparador_video.tamano:
                self._ultimo_video = clave
                self._ultimo_id_imagen = clave[0]
                self._imagen_tk = ImageTk.PhotoImage(imagen, master=self)
                self.etiqueta_video.configure(image=self._imagen_tk)
                if self.mensaje_video.winfo_ismapped():
                    self.mensaje_video.place_forget()
        self.after(15, self._ciclo_video)

    def _ciclo_eventos(self):
        if self.cerrando or not self.winfo_exists():
            return
        while not self.motor.eventos.empty():
            try:
                self._evento(self.motor.eventos.get_nowait())
            except sqlite3.Error as error:
                print("No se pudo actualizar el avistamiento reciente:", error)
        ahora = time.monotonic()
        vencidas = [i for i, d in self._tarjetas.items() if ahora - d["visto"] > SEGUNDOS_AUTOLIMPIEZA_PANEL]
        for id_especie in vencidas:
            self._tarjetas.pop(id_especie)["marco"].destroy()
        if vencidas:
            self._programar_orden_panel()
        self.after(200, self._ciclo_eventos)

    def _ciclo_estado(self):
        if self.cerrando or not self.winfo_exists():
            return
        self.reloj.configure(text=datetime.now().strftime("%H:%M"))
        try:
            self._refrescar_catalogo_panel()
        except sqlite3.Error as error:
            print("No se pudo actualizar el catálogo del observatorio:", error)
        for datos in self._tarjetas.values():
            self._actualizar_tarjeta(datos)

        estado = self.fuente.estado
        textos = {
            "ONLINE": ("● Cámara en línea", T.ETIQUETA_BIEN),
            "RECONECTANDO": ("● Reconectando la cámara…", T.ETIQUETA_ATENCION),
            "FAILOVER_DEMO": ("● Modo demostración", T.ETIQUETA_RIESGO),
            "SIN_SENAL": ("● Sin señal de video", T.ETIQUETA_RIESGO),
        }
        texto, color = textos.get(estado, ("", T.ETIQUETA_NEUTRA))
        if self.fuente.tipo == "video" and estado == "ONLINE":
            texto, color = "● Video de prueba", T.ETIQUETA_INFO
        self.chip_estado.configure(text=f"  {texto}  ", fg_color=color)

        if estado == "FAILOVER_DEMO":
            if not self.aviso_demo.winfo_ismapped():
                self.aviso_demo.place(relx=0, rely=0, relwidth=1)
        elif self.aviso_demo.winfo_ismapped():
            self.aviso_demo.place_forget()

        if self.motor.error:
            self.mensaje_video.configure(text=self.motor.error)
            if not self.mensaje_video.winfo_ismapped():
                self.mensaje_video.place(relx=0.5, rely=0.12, anchor="n")
        elif estado == "SIN_SENAL" and self._ultimo_id_imagen == 0:
            self.mensaje_video.configure(
                text="No hay señal de la cámara ni video de demostración.\nRevisa la conexión de la cámara."
            )

        if self.motor.modo and not self._modo_informado:
            self._modo_informado = True
            reconocibles = self.motor.especies_reconocibles
            print(f"{self.fuente.descripcion} · IA: {self.motor.modo} · {len(reconocibles)} especies reconocibles:")
            print("   " + ", ".join(reconocibles))
        self.after(1000, self._ciclo_estado)

    def cerrar(self):
        self.cerrando = True
        if self._orden_pendiente is not None:
            self.after_cancel(self._orden_pendiente)
        self._preparador_video.fin.set()
        if self.pantalla_secundaria is not None:
            try:
                self.pantalla_secundaria.cerrar_sistema()
            except Exception:
                pass
        self.motor.detener()
        self.fuente.detener()
        self.base.cerrar()
        self.destroy()
