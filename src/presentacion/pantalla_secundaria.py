"""
Interfaces de la Segunda Pantalla (Pantalla 2 · Monitor Táctil de Autoatención)
del Observatorio Inteligente de Aves - Parque Angostura.

Incluye:
1. Menú de Inicio interactivo («Catálogo de Aves» y «Trivia de Cantos»).
2. Catálogo Público 100 % de Solo Lectura (Read-Only) conectado a `observatorio.db`,
   con buscador + Teclado Virtual Táctil integrado + invocación de `tabtip`.
3. Trivia Educativa de Cantos con especies activas y avistamientos de SQLite.
4. Optimización Touch UX:
   - Regla «Fat Finger»: todos los botones e ítems táctiles >= 48x48 px con márgenes amplios.
   - `CTkScrollableFrame` con barra de desplazamiento ancha (`scrollbar_width=25`).
   - Timeout global de inactividad de 60 segundos que limpia búsquedas/fichas y
     regresa automáticamente al Menú de Inicio.
   - Modo Kiosco Estricto (Anti-Escape): `overrideredirect(True)` / `-fullscreen`,
     ocultando barra de tareas y bloqueando el cierre accidental por visitantes.
"""
import os
import random
import re
import sqlite3
import textwrap
import threading
import time
import tkinter as tk
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from itertools import islice

import customtkinter as ctk

from config.settings import (
    CARPETA_ASSETS,
    ESPECIES_FOCO,
    IDIOMA_ORIGINAL,
    IDIOMAS,
    MONITOR_PANTALLA_2,
    PANTALLA_2,
    SEGUNDOS_INACTIVIDAD_PANTALLA2,
)
from src.aplicacion.gestor_audio import Reproductor, buscar_audio_especie
from src.aplicacion.lector_voz import LectorFicha, precargar, voz_disponible
from src.aplicacion.gestor_monitores import listar_monitores, rect_monitor
from src.persistencia.repositorio_sqlite import BaseDatos
from src.presentacion import tema_visual as T
from src.presentacion.cache_imagenes import (
    FOTO_FICHA,
    FOTO_TRIVIA,
    MINIATURA_HOY,
    CacheImagenes,
    EtiquetaFoto,
    clave_imagen,
    preparar_imagenes,
)
from src.presentacion.idioma_kiosco import TraduccionesCatalogo, parrafos_ficha, tx
from src.presentacion.lista_catalogo import ListaCatalogo
from src.presentacion.ventana_kiosco import (
    abrir_imagen,
    barra_degradado,
    llenar_ficha,
)

# Regla "Fat Finger": dimensiones mínimas de controles táctiles (>= 48x48 px)
ALTO_MINIMO_TACTIL = 54
ANCHO_SCROLLBAR_TACTIL = 25
POR_PAGINA_CATALOGO = 24
FILTRO_ANGOSTURA = "Especies de Angostura"
FILTRO_VISTAS_HOY = "Vistas hoy"
FILTROS_CATALOGO = (FILTRO_ANGOSTURA, FILTRO_VISTAS_HOY)
SEGUNDOS_ENTRE_PREGUNTAS = 4
INTERVALO_AVISTAMIENTOS_MS = 3000


def boton_cristal(padre, texto, accion, **opciones):
    estilo = {
        "height": ALTO_MINIMO_TACTIL, "width": 100, "corner_radius": 12,
        "font": T.fuente_ctk(15, "bold"), "border_width": 2,
        "fg_color": T.CRISTAL_ACCION, "border_color": T.CRISTAL_BORDE,
        "hover_color": T.CRISTAL_HOVER, "text_color": T.CRISTAL_TEXTO,
    }
    estilo.update(opciones)
    return ctk.CTkButton(padre, text=texto, command=accion, **estilo)


def boton_ver_ficha(padre, accion):
    return boton_cristal(padre, "Ver ficha →", accion, height=48, fg_color=T.CRISTAL)


def tarjeta_cristal(padre, al_tocar=None):
    tarjeta = ctk.CTkFrame(padre, **T.ESTILO_TARJETA_CRISTAL)
    reflejo = ctk.CTkFrame(tarjeta, fg_color=T.CRISTAL_REFLEJO, height=3, corner_radius=2)
    reflejo.pack(fill="x", padx=15, pady=(6, 0))
    if al_tocar is not None:
        tarjeta.configure(cursor="hand2")
        for widget in (tarjeta, reflejo):
            widget.bind("<Button-1>", lambda _evento: al_tocar(), add="+")
    return tarjeta


def controles_canto(padre, reproductor, especie, ficha, idioma="es", barra=None):
    audio = buscar_audio_especie(especie, ficha)
    if audio is None or not reproductor.puede_reproducir(audio):
        return
    separacion = (10, 0) if barra is not None else 0
    if barra is None:
        barra = ctk.CTkFrame(padre, fg_color="transparent")
        barra.pack(fill="x", padx=16, pady=(4, 0))
    tarea = None

    def cancelar(_evento=None):
        nonlocal tarea
        if tarea is not None:
            boton.after_cancel(tarea)
            tarea = None

    def actualizar(_evento=None):
        nonlocal tarea
        activo = reproductor.reproduciendo(audio)
        texto = ("■ " + tx("detener", idioma)) if activo else ("▶ " + tx("escuchar", idioma))
        if texto != boton.cget("text"):
            boton.configure(text=texto)
        if activo and tarea is None:
            tarea = boton.after(120, revisar)
        elif not activo:
            cancelar()

    def revisar():
        nonlocal tarea
        tarea = None
        actualizar()

    def alternar():
        if reproductor.reproduciendo(audio):
            reproductor.detener()
        else:
            reproductor.reproducir(audio)
        actualizar()

    boton = boton_cristal(barra, "▶ " + tx("escuchar", idioma), alternar, width=152)
    boton.pack(side="left", padx=separacion)
    tk.Misc.bind(boton, "<Map>", actualizar, add="+")
    tk.Misc.bind(boton, "<Destroy>", cancelar, add="+")


def barra_workspace(padre, titulo, volver=None):
    barra = ctk.CTkFrame(padre, fg_color=T.CRISTAL, corner_radius=0)
    barra.pack(fill="x")
    if volver is not None:
        boton_cristal(barra, "← Volver", volver, height=48, fg_color=T.CRISTAL_REFLEJO).pack(
            side="left", padx=(12, 0), pady=8,
        )
    ctk.CTkLabel(
        barra, text=titulo, font=T.fuente_ctk(19, "bold"), text_color=T.CRISTAL_TEXTO,
        anchor="w", height=48,
    ).pack(side="left", padx=12, pady=8)
    ctk.CTkFrame(padre, fg_color=T.DIVISOR, height=1, corner_radius=0).pack(fill="x")
    return barra


def ajustar_ancho_texto(contenedor, *etiquetas, margen=0):
    def ajustar(evento):
        ancho = max(1, round(contenedor._reverse_widget_scaling(evento.width)) - margen)
        for etiqueta in etiquetas:
            etiqueta.configure(wraplength=ancho)

    tk.Misc.bind(contenedor, "<Configure>", ajustar, add="+")


def _leer_datos_visitantes(ruta, rutas_cargadas):
    """Toma una instantánea WAL y prepara las fotos nuevas fuera del hilo Tk."""
    base = BaseDatos(ruta)
    try:
        base.conexion.execute("BEGIN")
        hoy = base.resumen_del_dia()
        catalogo = base.catalogo_visitantes()
    finally:
        base.cerrar()
    catalogo.sort(key=lambda e: _normalizar_busqueda(e["nombre_comun"]))
    rutas = {
        ruta_foto for grupo in (catalogo, hoy["especies"]) for fila in grupo
        for campo in ("ruta_foto", "ultima_captura")
        if (ruta_foto := clave_imagen(fila.get(campo)))
    }
    datos = (hoy, catalogo)
    return datos, rutas, preparar_imagenes(rutas - rutas_cargadas)


def _normalizar_busqueda(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "").lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip()


def invocar_teclado_tactil_windows():
    """
    Invoca el teclado táctil de Windows (`tabtip`) en un hilo secundario para no
    bloquear el bucle de eventos de la interfaz gráfica.
    """
    if os.name != "nt":
        return

    def _lanzar():
        try:
            os.system("cmd /c start \"\" tabtip >nul 2>nul")
        except OSError:
            pass

    threading.Thread(target=_lanzar, daemon=True, name="teclado_tabtip").start()


class MarcoDesplazableTactil(ctk.CTkScrollableFrame):
    """
    Extensión de `CTkScrollableFrame` optimizada para pantallas táctiles de
    autoatención con barra de desplazamiento ancha (`scrollbar_width=25`).
    """

    def __init__(self, master, scrollbar_width=ANCHO_SCROLLBAR_TACTIL, *, barra_automatica=False,
                 arrastre=False, **kwargs):
        super().__init__(master, **kwargs)
        self.scrollbar_width = max(25, int(scrollbar_width))
        try:
            self._scrollbar.configure(width=self.scrollbar_width)
        except (AttributeError, tk.TclError):
            pass
        self._gesto = None
        self._arrastrando = False
        self._pulso = None
        self._ajuste_altura = None
        self._bindings_gesto = {}
        if barra_automatica:
            self._parent_canvas.configure(yscrollcommand=self._actualizar_barra)
            self._scrollbar.grid_remove()
        if arrastre:
            self._tag_gesto = f"DesplazamientoTactil:{self}"
            for evento, accion in (
                ("<ButtonPress-1>", self._presionar), ("<B1-Motion>", self._mover),
                ("<ButtonRelease-1>", self._soltar),
            ):
                self._bindings_gesto[evento] = self.bind_class(self._tag_gesto, evento, accion)
            self.registrar_gesto(self._parent_canvas)

    def _actualizar_barra(self, inicio, fin):
        self._scrollbar.set(inicio, fin)
        hay_desplazamiento = float(inicio) > 0 or float(fin) < 1
        visible = bool(self._scrollbar.winfo_manager())
        if hay_desplazamiento and not visible:
            self._scrollbar.grid()
        elif visible and not hay_desplazamiento:
            self._scrollbar.grid_remove()

    def programar_altura(self, _evento=None):
        if self._ajuste_altura is None:
            self._ajuste_altura = self.after_idle(self._sincronizar_altura)

    def _sincronizar_altura(self):
        self._ajuste_altura = None
        # Una lista que se encoge estando desplazada puede conservar la altura anterior en Tk.
        lienzo = self._parent_canvas
        altura = self.winfo_reqheight()
        if int(lienzo.itemcget(self._create_window_id, "height")) != altura:
            lienzo.itemconfigure(self._create_window_id, height=altura)
            lienzo.configure(scrollregion=(0, 0, lienzo.winfo_width(), altura))
            if altura <= lienzo.winfo_height():
                lienzo.yview_moveto(0)

    @property
    def gesto_activo(self):
        return self._gesto is not None

    def registrar_gesto(self, widget, boton=None):
        # El bindtag recibe el toque antes de los bindings propios de CTkButton.
        if isinstance(widget, ctk.CTkButton):
            boton = widget
        widget._boton_gesto = boton
        tags = widget.bindtags()
        if self._tag_gesto not in tags:
            widget.bindtags((self._tag_gesto, *tags))
        for hijo in widget.winfo_children():
            self.registrar_gesto(hijo, boton)

    def _presionar(self, evento):
        self.cancelar_gesto()
        caja = self._parent_canvas.bbox("all")
        altura = max(1, caja[3] - caja[1]) if caja else 1
        self._gesto = (evento.x_root, evento.y_root, self._parent_canvas.yview()[0],
                       altura, evento.widget._boton_gesto)
        self.winfo_toplevel().event_generate("<<ToqueVisitante>>")
        return "break"

    def _mover(self, evento):
        if self._gesto is None:
            return
        _, y, origen, altura, _ = self._gesto
        distancia = y - evento.y_root
        if self._arrastrando or abs(distancia) > self._apply_widget_scaling(8):
            self._arrastrando = True
            self._destino = origen + distancia / altura
            if self._pulso is None:
                self._pulso = self.after(16, self._desplazar)

    def _desplazar(self):
        self._pulso = None
        self._parent_canvas.yview_moveto(self._destino)

    def _soltar(self, evento):
        if self._gesto is None:
            return "break"
        x, _, _, _, boton = self._gesto
        self._mover(evento)
        arrastrando = self._arrastrando
        self.cancelar_gesto()
        if arrastrando:
            self._desplazar()
        elif boton is not None and boton.winfo_exists() and abs(x - evento.x_root) <= self._apply_widget_scaling(8):
            boton.invoke()
        return "break"

    def cancelar_gesto(self):
        if self._pulso is not None:
            self.after_cancel(self._pulso)
            self._pulso = None
        self._gesto = None
        self._arrastrando = False

    def destroy(self):
        self.cancelar_gesto()
        if self._ajuste_altura is not None:
            self.after_cancel(self._ajuste_altura)
        for evento, comando in self._bindings_gesto.items():
            self.unbind_class(self._tag_gesto, evento)
            self._root().deletecommand(comando)
        super().destroy()


class TarjetaAvistamiento(ctk.CTkFrame):
    def __init__(self, padre, abrir_ficha, cache):
        super().__init__(padre, fg_color=T.FONDO, border_width=1, border_color=T.DIVISOR, corner_radius=12)
        self.especie = None
        self._imagen = None
        self.cache = cache
        abrir = lambda: abrir_ficha(self.especie)

        cuerpo = ctk.CTkFrame(self, fg_color="transparent", cursor="hand2")
        cuerpo.pack(fill="x", padx=8, pady=(8, 0))
        self.foto = EtiquetaFoto(
            cuerpo, text="Sin foto", width=66, height=50, corner_radius=8, fg_color=T.CRISTAL,
            font=T.fuente_ctk(11), text_color=T.CRISTAL_TEXTO,
        )
        self.foto.pack(side="left", anchor="n", padx=(0, 8))
        textos = ctk.CTkFrame(cuerpo, fg_color="transparent", cursor="hand2")
        textos.pack(side="left", fill="both", expand=True)
        self.nombre = ctk.CTkLabel(textos, font=T.fuente_ctk(15, "bold"), text_color=T.CRISTAL_TEXTO)
        self.cientifico = ctk.CTkLabel(textos, font=T.fuente_ctk(12, inclinada=True), text_color=T.TEXTO)
        self.detalle = ctk.CTkLabel(textos, font=T.fuente_ctk(12), text_color=T.GRIS)
        for etiqueta in (self.nombre, self.cientifico, self.detalle):
            etiqueta.configure(text="", anchor="w", justify="left", height=16, wraplength=120)
            etiqueta.pack(fill="x")
        ajustar_ancho_texto(textos, self.nombre, self.cientifico, self.detalle)

        for widget in (self, cuerpo, self.foto, textos, self.nombre, self.cientifico, self.detalle):
            widget.bind("<Button-1>", lambda _evento: abrir(), add="+")
        boton_ver_ficha(self, abrir).pack(anchor="e", padx=8, pady=(4, 8))

    def actualizar(self, especie):
        if especie != self.especie:
            self.especie = especie
            self.nombre.configure(text=especie["nombre_comun"])
            self.cientifico.configure(text=especie["nombre_cientifico"])
            hora = (especie.get("ultimo_avistamiento") or "")[11:16]
            veces = especie["veces"]
            visitas = f"{veces} {'vez' if veces == 1 else 'veces'}"
            self.detalle.configure(text=f"{visitas} · Última {hora}" if hora else visitas)

        imagen = self.cache.obtener(especie.get("ruta_foto"), MINIATURA_HOY) or self.cache.obtener(
            especie.get("ultima_captura"), MINIATURA_HOY,
        )
        if imagen is not self._imagen:
            self._imagen = imagen
            self.foto.configure(text="" if imagen else "Sin foto", image=imagen or "")


class PanelAvistamientosHoy(ctk.CTkFrame):
    def __init__(self, padre, ruta, abrir_ficha, cache, al_cargar_datos):
        super().__init__(padre, fg_color=T.FONDO_SUAVE, corner_radius=0)
        self.ruta = ruta
        self.abrir_ficha = abrir_ficha
        self.cache = cache
        self.al_cargar_datos = al_cargar_datos
        self._lector = ThreadPoolExecutor(max_workers=1, thread_name_prefix="datos_visitantes")
        self._consulta = None
        self._revision = None
        self._tarjetas = {}
        self._firma = None
        self._error = False

        barra_workspace(self, "Avistamientos de Hoy")
        resumen = ctk.CTkFrame(self, fg_color="transparent")
        resumen.pack(fill="x", padx=10, pady=10)
        resumen.grid_columnconfigure((0, 1), weight=1, uniform="cifras")
        self.cifra_especies = self._cifra(resumen, 0, "especies hoy")
        self.cifra_avistamientos = self._cifra(resumen, 1, "avistamientos hoy")

        self.estado = ctk.CTkLabel(
            self, text="Consultando registros…", font=T.fuente_ctk(12, "bold"),
            text_color=T.CRISTAL_TEXTO, anchor="w", height=20,
        )
        self.estado.pack(fill="x", padx=12, pady=(0, 4))
        self.lista = MarcoDesplazableTactil(
            self, fg_color=T.FONDO_SUAVE, corner_radius=0, width=1, height=1, barra_automatica=True,
        )
        self.lista.pack(fill="both", expand=True, padx=(8, 4), pady=(0, 8))
        self.lista._parent_canvas.bind("<Configure>", self.lista.programar_altura, add="+")
        self.lista.grid_columnconfigure(0, weight=1)
        self.vacio = ctk.CTkLabel(
            self.lista, text="Todavía no se han identificado\naves hoy.", font=T.fuente_ctk(14),
            text_color=T.GRIS, anchor="w", justify="left",
        )
        self._revision = self.after(0, self._solicitar)

    @staticmethod
    def _cifra(padre, columna, texto):
        caja = ctk.CTkFrame(padre, fg_color=T.CRISTAL, border_color=T.DIVISOR, border_width=1, corner_radius=12)
        caja.grid(row=0, column=columna, sticky="ew", padx=(0, 4) if columna == 0 else (4, 0))
        valor = ctk.CTkLabel(caja, text="—", font=T.fuente_ctk(25, "bold"), text_color=T.CRISTAL_TEXTO, anchor="w")
        valor.pack(fill="x", padx=8, pady=(6, 0))
        ctk.CTkLabel(
            caja, text=texto, font=T.fuente_ctk(11, "bold"), text_color=T.CRISTAL_TEXTO, anchor="w",
        ).pack(fill="x", padx=8, pady=(0, 5))
        return valor

    def _solicitar(self):
        self._consulta = self._lector.submit(_leer_datos_visitantes, self.ruta, self.cache.rutas_cargadas())
        self._revision = self.after(80, self._recibir)

    def _recibir(self):
        if not self._consulta.done():
            self._revision = self.after(80, self._recibir)
            return
        try:
            datos, rutas, nuevas = self._consulta.result()
        except (sqlite3.Error, OSError):
            if not self._error:
                self.estado.configure(text="Actualización pendiente · Reintentando")
                self._error = True
            self._revision = self.after(INTERVALO_AVISTAMIENTOS_MS, self._solicitar)
        else:
            self._integrar(iter(nuevas.items()), datos, rutas)
        self._consulta = None

    def _integrar(self, pendientes, datos, rutas):
        lote = list(islice(pendientes, 16))
        if lote:
            for ruta, variantes in lote:
                self.cache.guardar(ruta, variantes)
            self._revision = self.after(1, self._integrar, pendientes, datos, rutas)
            return
        hoy, catalogo = datos
        if hoy["dia"] != date.today():
            self._revision = self.after(0, self._solicitar)
            return
        self._revision = self.after(INTERVALO_AVISTAMIENTOS_MS, self._solicitar)
        self.cache.conservar(rutas)
        self._actualizar(hoy["dia"], hoy["especies"], hoy["total"])
        self.al_cargar_datos(catalogo, hoy["especies"])

    def _actualizar(self, dia, especies, total):
        firma = (
            dia, total, tuple(especies),
            tuple(tuple(self.cache.obtener(e.get(campo), MINIATURA_HOY) for campo in ("ultima_captura", "ruta_foto"))
                  for e in especies),
        )
        anterior = self._firma
        if firma == anterior and not self._error:
            return
        self._firma = firma
        if anterior is None or dia != anterior[0] or self._error:
            self.estado.configure(text=f"{dia:%d-%m-%Y}  ·  Últimas detecciones primero")
            self._error = False
        if anterior is None or len(especies) != len(anterior[2]):
            self.cifra_especies.configure(text=str(len(especies)))
        if anterior is None or total != anterior[1]:
            self.cifra_avistamientos.configure(text=str(total))
        if especies:
            if self.vacio.winfo_manager():
                self.vacio.grid_remove()
        elif not self.vacio.winfo_manager():
            self.vacio.grid(row=0, column=0, sticky="ew", padx=8, pady=12)

        anteriores = self._tarjetas
        actuales = {}
        for indice, especie in enumerate(especies):
            id_especie = especie["id_especie"]
            tarjeta = anteriores.get(id_especie) or TarjetaAvistamiento(self.lista, self.abrir_ficha, self.cache)
            tarjeta.actualizar(especie)
            if tarjeta.grid_info().get("row") != indice:
                tarjeta.grid(row=indice, column=0, sticky="ew", padx=(0, 4), pady=(0, 8))
            actuales[id_especie] = tarjeta
        for id_especie in anteriores.keys() - actuales.keys():
            anteriores[id_especie].destroy()
        self._tarjetas = actuales
        self.lista.programar_altura()

    def destroy(self):
        if self._revision is not None:
            self.after_cancel(self._revision)
        self._lector.shutdown(wait=False, cancel_futures=True)
        super().destroy()


class TecladoVirtualTactil(ctk.CTkFrame):
    """
    Teclado virtual QWERTY en español integrado en CustomTkinter para garantizar
    la escritura táctil en modo Kiosco Estricto. Cada tecla cumple >= 48x48 px.
    """

    FILAS = (
        ("Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"),
        ("A", "S", "D", "F", "G", "H", "J", "K", "L", "Ñ"),
        ("Z", "X", "C", "V", "B", "N", "M"),
    )

    def __init__(self, padre, entrada_objetivo, al_cambiar, al_ocultar):
        super().__init__(padre, **T.ESTILO_TARJETA_CRISTAL)
        self.entrada = entrada_objetivo
        self.al_cambiar = al_cambiar
        self.al_ocultar = al_ocultar
        self._construir()

    def _construir(self):
        contenedor = ctk.CTkFrame(self, fg_color="transparent")
        contenedor.pack(fill="x", padx=6, pady=8)

        for letras in self.FILAS:
            fila = ctk.CTkFrame(contenedor, fg_color="transparent")
            fila.pack(pady=4)
            for letra in letras:
                boton_cristal(
                    fila, letra, lambda ch=letra.lower(): self._insertar(ch), width=48, height=50,
                    font=T.fuente_ctk(18, "bold"), fg_color=T.CRISTAL_REFLEJO,
                ).pack(side="left", padx=2)

        fila_acciones = ctk.CTkFrame(contenedor, fg_color="transparent")
        fila_acciones.pack(pady=(6, 2))

        for texto, ancho, comando in (
            ("Limpiar", 86, self._limpiar),
            ("Espacio", 136, lambda: self._insertar(" ")),
            ("⌫ Borrar", 94, self._borrar),
            ("Ocultar teclado", 142, self.al_ocultar),
        ):
            boton_cristal(fila_acciones, texto, comando, width=ancho, height=50).pack(side="left", padx=3)

    def _insertar(self, caracter):
        self.entrada.insert("end", caracter)
        self.al_cambiar()

    def _borrar(self):
        actual = self.entrada.get()
        if actual:
            self.entrada.delete(len(actual) - 1, "end")
            self.al_cambiar()

    def _limpiar(self):
        self.entrada.delete(0, "end")
        self.al_cambiar()


# ==========================================================
# 1. MENÚ DE INICIO
# ==========================================================


class VistaMenuInicio(ctk.CTkFrame):
    """Actividades disponibles en el área de trabajo del Centro Interactivo."""

    def __init__(self, padre, ir_catalogo, ir_trivia):
        super().__init__(padre, fg_color=T.FONDO, corner_radius=0)
        barra_workspace(self, "Actividades")
        cuerpo = ctk.CTkFrame(self, fg_color="transparent")
        cuerpo.pack(fill="both", expand=True, padx=12, pady=12)
        cuerpo.grid_columnconfigure(0, weight=1)
        cuerpo.grid_rowconfigure((0, 1), weight=1, uniform="actividades")

        self._crear_tarjeta(
            cuerpo, 0, "Catálogo de Aves",
            "Consulta fichas con fotos, cantos, hábitat y estado de conservación.",
            "Abrir catálogo →", ir_catalogo,
        )
        self._crear_tarjeta(
            cuerpo, 1, "Trivia de Cantos",
            "Escucha un canto o mira una foto e identifica el ave entre tres opciones.",
            "Iniciar trivia →", ir_trivia,
        )

    @staticmethod
    def _crear_tarjeta(padre, fila, titulo, descripcion, accion, comando):
        tarjeta = tarjeta_cristal(padre, al_tocar=comando)
        tarjeta.grid(row=fila, column=0, sticky="nsew", pady=(0, 6) if fila == 0 else (6, 0))

        cuerpo = ctk.CTkFrame(tarjeta, fg_color="transparent", cursor="hand2")
        cuerpo.place(relx=0.5, rely=0.5, relwidth=0.94, anchor="center")
        cuerpo.grid_columnconfigure(0, weight=1)
        nombre = ctk.CTkLabel(
            cuerpo, text=titulo, font=T.fuente_ctk(30, "bold"), text_color=T.CRISTAL_TEXTO,
            anchor="center", justify="center", wraplength=300,
        )
        nombre.grid(row=0, column=0, sticky="ew")
        descripcion = ctk.CTkLabel(
            cuerpo, text=descripcion, font=T.fuente_ctk(17), text_color=T.CRISTAL_TEXTO,
            anchor="center", justify="center", wraplength=300,
        )
        descripcion.grid(row=1, column=0, sticky="ew", pady=(8, 24))
        boton_cristal(cuerpo, accion, comando, width=260, height=56, font=T.fuente_ctk(18, "bold")).grid(
            row=2, column=0,
        )
        ajustar_ancho_texto(cuerpo, nombre, descripcion)
        for widget in (cuerpo, nombre, descripcion):
            widget.bind("<Button-1>", lambda _evento: comando(), add="+")


# ==========================================================
# 2. CATÁLOGO PÚBLICO (100 % SOLO LECTURA / READ-ONLY)
# ==========================================================


class VistaCatalogoPublico(ctk.CTkFrame):
    """
    Catálogo público interactivo y estrictamente de solo lectura (Read-Only)
    para los visitantes del parque. No expone ninguna operación CRUD ni acceso
    administrativo.
    """

    def __init__(self, padre, reproductor, volver_menu, cache, abrir_ficha):
        super().__init__(padre, fg_color=T.FONDO, corner_radius=0)
        self.abrir_ficha = abrir_ficha
        self.reproductor = reproductor
        self.volver_menu = volver_menu
        self.cache = cache

        self._filtro = FILTRO_ANGOSTURA
        self._catalogo = None
        self._por_id = {}
        self._foco_trivia = self._hoy = ()
        self._revision_fotos = cache.revision
        self._resultados = []
        self._mostradas = 0
        self._busqueda_pendiente = None
        self._teclado_visible = False

        self._construir()

    def _construir(self):
        barra_workspace(self, "Catálogo de Aves", self._salir_a_menu)
        cuerpo = ctk.CTkFrame(self, fg_color=T.FONDO)
        cuerpo.pack(fill="both", expand=True, padx=10, pady=8)
        cuerpo.grid_columnconfigure(0, weight=1)
        cuerpo.grid_rowconfigure(3, weight=1)

        filtros = ctk.CTkFrame(cuerpo, fg_color="transparent", border_width=0)
        filtros.grid(row=0, column=0, sticky="ew")
        self._botones_filtro = {}
        fuente_filtros = T.fuente_ctk(14, "bold")
        for columna, filtro in enumerate(FILTROS_CATALOGO):
            filtros.grid_columnconfigure(columna, weight=1, uniform="filtros")
            boton = boton_cristal(filtros, filtro, lambda f=filtro: self._cambiar_filtro(f), font=fuente_filtros)
            boton.grid(row=0, column=columna, sticky="ew", padx=6)
            self._botones_filtro[filtro] = boton
        self._actualizar_estilo_filtros()

        # Barra de búsqueda táctil + botones de apoyo (>= 54 px de alto)
        controles_busqueda = ctk.CTkFrame(cuerpo, fg_color=T.FONDO)
        controles_busqueda.grid(row=1, column=0, sticky="ew", pady=6)

        self.buscador = ctk.CTkEntry(
            controles_busqueda,
            placeholder_text="Buscar nombre o familia…",
            height=ALTO_MINIMO_TACTIL,
            font=T.fuente_ctk(17),
            corner_radius=12,
            border_width=2,
            border_color=T.CRISTAL_BORDE,
            fg_color=T.CRISTAL,
            text_color=T.CRISTAL_TEXTO,
            placeholder_text_color=T.CRISTAL_TEXTO,
        )
        self.buscador.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.buscador.bind("<KeyRelease>", self._buscar_luego)
        self.buscador.bind("<FocusIn>", self._al_enfocar_buscador, add="+")
        self.buscador.bind("<Button-1>", self._al_enfocar_buscador, add="+")

        self.boton_teclado = boton_cristal(
            controles_busqueda, "⌨  Teclado", self._alternar_teclado, width=110, fg_color=T.CRISTAL_REFLEJO,
        )
        self.boton_teclado.pack(side="left", padx=(0, 10))

        self.boton_limpiar = boton_cristal(
            controles_busqueda, "✕  Limpiar", self._limpiar_busqueda, fg_color=T.CRISTAL_REFLEJO,
        )
        self.boton_limpiar.pack(side="left")

        self.resumen = ctk.CTkLabel(
            cuerpo,
            text="",
            font=T.fuente_ctk(14, "bold"),
            text_color=T.ACENTO,
            anchor="w", justify="left", wraplength=380,
        )
        self.resumen.grid(row=2, column=0, sticky="ew", padx=6, pady=4)
        ajustar_ancho_texto(cuerpo, self.resumen, margen=12)

        # Contenedor del teclado virtual táctil (se despliega al tocar el buscador)
        self.panel_teclado = TecladoVirtualTactil(
            cuerpo,
            entrada_objetivo=self.buscador,
            al_cambiar=self._buscar_luego,
            al_ocultar=self.ocultar_teclado,
        )

        self.lista = ListaCatalogo(cuerpo, self.cache, self.abrir_ficha, self._mostrar_mas)
        self.lista.grid(row=3, column=0, sticky="nsew")

    def destroy(self):
        if self._busqueda_pendiente is not None:
            self.after_cancel(self._busqueda_pendiente)
        super().destroy()

    def _salir_a_menu(self):
        self.reproductor.detener()
        self.ocultar_teclado()
        self.volver_menu()

    def _al_enfocar_buscador(self, _evento=None):
        invocar_teclado_tactil_windows()
        self.mostrar_teclado()

    def _alternar_teclado(self):
        if self._teclado_visible:
            self.ocultar_teclado()
        else:
            invocar_teclado_tactil_windows()
            self.mostrar_teclado()

    def mostrar_teclado(self):
        if not self._teclado_visible:
            self._teclado_visible = True
            self.panel_teclado.grid(row=4, column=0, sticky="ew", pady=(4, 0))
            self.boton_teclado.configure(fg_color=T.CRISTAL_ACCION)

    def ocultar_teclado(self):
        if self._teclado_visible:
            self._teclado_visible = False
            self.panel_teclado.grid_remove()
            self.boton_teclado.configure(fg_color=T.CRISTAL_REFLEJO)

    def _limpiar_busqueda(self):
        self.buscador.delete(0, "end")
        self._actualizar()

    def reiniciar_estado(self):
        """Restaura la búsqueda y el filtro inicial del catálogo."""
        if self._busqueda_pendiente is not None:
            try:
                self.after_cancel(self._busqueda_pendiente)
            except tk.TclError:
                pass
            self._busqueda_pendiente = None
        self.reproductor.detener()
        self.ocultar_teclado()
        self.buscador.delete(0, "end")
        self._filtro = FILTRO_ANGOSTURA
        self._actualizar_estilo_filtros()
        self._actualizar()

    def _actualizar_estilo_filtros(self):
        for filtro, boton in self._botones_filtro.items():
            activo = filtro == self._filtro
            boton.configure(
                fg_color=T.CRISTAL_ACCION if activo else T.CRISTAL_REFLEJO,
                hover_color=T.CRISTAL_HOVER if activo else T.CRISTAL,
            )

    def _cambiar_filtro(self, filtro):
        if filtro == self._filtro:
            return
        self._filtro = filtro
        self._actualizar_estilo_filtros()
        self._actualizar()

    def _buscar_luego(self, _evento=None):
        if self._busqueda_pendiente is not None:
            try:
                self.after_cancel(self._busqueda_pendiente)
            except tk.TclError:
                pass
        self._busqueda_pendiente = self.after(250, self._actualizar)

    def cargar_datos(self, catalogo, hoy):
        cambio_catalogo = catalogo != self._catalogo
        if cambio_catalogo:
            self._por_id = {e["id_especie"]: e for e in catalogo}
        cambio_hoy = hoy != self._hoy
        cambio_fotos = self.cache.revision != self._revision_fotos
        if not (cambio_catalogo or cambio_hoy or cambio_fotos):
            return
        inicial = self._catalogo is None
        if cambio_catalogo:
            self._catalogo = catalogo
            por_cientifico = {e["nombre_cientifico"].lower(): e for e in catalogo}
            self._foco_trivia = [por_cientifico[n.lower()] for n in ESPECIES_FOCO if n.lower() in por_cientifico]
        self._hoy = hoy
        self._revision_fotos = self.cache.revision
        cambio_visible = (cambio_hoy if self._filtro == FILTRO_VISTAS_HOY else cambio_catalogo) or cambio_fotos
        if cambio_visible and self.winfo_ismapped() and self._busqueda_pendiente is None:
            self._actualizar(conservar_posicion=not inicial)

    def _consultar(self):
        especies = self._hoy if self._filtro == FILTRO_VISTAS_HOY else self._catalogo
        texto = _normalizar_busqueda(self.buscador.get())
        if not texto:
            return especies
        return [
            e for e in especies if any(
                texto in _normalizar_busqueda(e.get(campo))
                for campo in ("nombre_comun", "nombre_cientifico", "familia", "orden")
            )
        ]

    def _actualizar(self, conservar_posicion=False):
        self._busqueda_pendiente = None
        if not self.winfo_exists():
            return
        if self._catalogo is None:
            self.resumen.configure(text="Cargando catálogo…")
            return
        self._resultados = self._consultar()

        n = len(self._resultados)
        buscado = self.buscador.get().strip()
        vistas_hoy = self._filtro == FILTRO_VISTAS_HOY
        plural = "s" if n != 1 else ""
        if buscado:
            ambito = "entre las aves vistas hoy" if vistas_hoy else "entre las especies de Angostura"
            texto = f"{n} resultado{plural} para «{buscado}» {ambito}"
        elif vistas_hoy:
            texto = f"{n} especie{plural} identificada{plural} hoy por la cámara"
        else:
            texto = f"{n} especie{plural} de Angostura disponible{plural} para explorar"
        if texto != self.resumen.cget("text"):
            self.resumen.configure(text=texto)

        cantidad = max(POR_PAGINA_CATALOGO, self._mostradas) if conservar_posicion else POR_PAGINA_CATALOGO
        self._mostrar_filas(min(n, cantidad))
        if not conservar_posicion:
            self.lista.ir_arriba()

    def _mostrar_mas(self):
        self._mostrar_filas(min(len(self._resultados), self._mostradas + POR_PAGINA_CATALOGO))

    def _mostrar_filas(self, cantidad):
        self._mostradas = cantidad
        vistas_hoy = self._filtro == FILTRO_VISTAS_HOY
        mensaje = ""
        if not cantidad:
            mensaje = (
                "Todavía no se han identificado aves hoy."
                if vistas_hoy else "No hay especies que coincidan con la búsqueda."
            )
        self.lista.mostrar(self._resultados[:cantidad], vistas_hoy, len(self._resultados) - cantidad, mensaje)


# ==========================================================
# 3. TRIVIA DE CANTOS INTEGRADA
# ==========================================================


class VistaTriviaCantos(ctk.CTkFrame):
    """
    Vista interactiva de la Trivia de Cantos enlazada a la Segunda Pantalla,
    con botón táctil para volver al Menú Principal y controles >= 48x48 px.
    """

    def __init__(self, padre, reproductor, volver_menu, cache):
        super().__init__(padre, fg_color=T.FONDO, corner_radius=0)
        self.reproductor = reproductor
        self.volver_menu = volver_menu
        self.cache = cache
        self._candidatas = None
        self._preferidas = []
        self._revision_fotos = cache.revision

        self.aciertos = 0
        self.intentos = 0
        self.pregunta = None
        self._preguntadas = set()
        self._partida_completa = False
        self._activa = False
        self._avance = None
        self._foto = None
        self._alto_trivia = 0

        self._construir()

    def _construir(self):
        barra = barra_workspace(self, "Trivia de Cantos", self.volver_menu)
        self.marcador = ctk.CTkLabel(
            barra, text="", font=T.fuente_ctk(14, "bold"), text_color=T.CRISTAL_TEXTO,
            fg_color=T.CRISTAL_ACCION, corner_radius=10, height=32,
        )
        self.marcador.pack(side="right", padx=12)
        boton_cristal(barra, "Reiniciar", self.reiniciar, height=48).pack(side="right", padx=(0, 4))
        self._actualizar_marcador()

        area = MarcoDesplazableTactil(self, fg_color=T.FONDO, width=1, height=1, barra_automatica=True)
        area.pack(fill="both", expand=True, padx=12, pady=12)
        area.grid_columnconfigure(0, weight=1)
        cuerpo = ctk.CTkFrame(area, fg_color="transparent")
        cuerpo.grid(row=0, column=0, sticky="ew", padx=6, pady=8)
        cuerpo.grid_columnconfigure((0, 1), weight=1, uniform="trivia")

        def ajustar_area(evento):
            area.grid_rowconfigure(0, minsize=evento.height)
            self._alto_trivia = self._reverse_widget_scaling(evento.height)
            self._ajustar_foto()

        area._parent_canvas.bind("<Configure>", ajustar_area, add="+")
        self.enunciado = ctk.CTkLabel(
            cuerpo, text="", font=T.fuente_ctk(28, "bold"), text_color=T.CRISTAL_TEXTO,
            anchor="center", justify="center", wraplength=400,
        )
        self.enunciado.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=(0, 20))

        visor = ctk.CTkFrame(
            cuerpo, fg_color=T.CRISTAL, border_color=T.CRISTAL_BORDE, border_width=2, corner_radius=14,
        )
        visor.grid(row=1, column=0, sticky="nsew", padx=(4, 6))
        ctk.CTkLabel(
            visor, text="PISTA", font=T.fuente_ctk(16, "bold"), text_color=T.ACENTO,
        ).pack(fill="x", padx=12, pady=(10, 6))
        self.medio = ctk.CTkFrame(
            visor, fg_color=T.CRISTAL_REFLEJO, border_color=T.DIVISOR, border_width=1, corner_radius=10,
        )
        self.medio.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        tk.Misc.bind(self.medio, "<Configure>", self._ajustar_foto, add="+")
        self._etiqueta_foto = EtiquetaFoto(self.medio, text="")
        self._etiqueta_pista = ctk.CTkLabel(
            self.medio, text="", font=T.fuente_ctk(19), text_color=T.CRISTAL_TEXTO,
            wraplength=200, justify="center",
        )
        ajustar_ancho_texto(self._etiqueta_pista, self._etiqueta_pista)
        self._boton_canto = boton_cristal(
            self.medio, "▶  Repetir canto", None, height=70, width=220, font=T.fuente_ctk(19, "bold"),
        )

        opciones = ctk.CTkFrame(cuerpo, fg_color=T.FONDO_SUAVE, corner_radius=14)
        opciones.grid(row=1, column=1, sticky="nsew", padx=(6, 4))
        ctk.CTkLabel(
            opciones, text="ELIGE UNA RESPUESTA", font=T.fuente_ctk(16, "bold"), text_color=T.ACENTO,
        ).pack(fill="x", padx=12, pady=(10, 6))
        respuestas = ctk.CTkFrame(opciones, fg_color="transparent")
        respuestas.pack(fill="x", expand=True, padx=10, pady=(0, 8))
        self.botones = []
        for indice in range(3):
            boton = boton_cristal(
                respuestas, "", lambda i=indice: self._responder(i), height=80, width=1,
                font=T.fuente_ctk(20, "bold"),
            )
            self.botones.append(boton)

        self.retro = ctk.CTkLabel(
            cuerpo, text="", font=T.fuente_ctk(20, "bold"), text_color=T.CRISTAL_TEXTO,
            fg_color=T.CRISTAL, corner_radius=10, height=50, justify="center", wraplength=400,
        )
        self.retro.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4, pady=(16, 4))
        ajustar_ancho_texto(cuerpo, self.enunciado, self.retro, margen=16)

    def _ajustar_foto(self, _evento=None):
        if self._foto is None:
            return
        imagen, (ancho, alto) = self._foto
        disponible = self._reverse_widget_scaling(self.medio.winfo_width()) - 24
        if disponible < 1:
            return
        alto_maximo = max(160, self._alto_trivia * 0.55)
        escala = min(1, disponible / ancho, alto_maximo / alto)
        tamano = (max(1, round(ancho * escala)), max(1, round(alto * escala)))
        if imagen.cget("size") != tamano:
            original = imagen.cget("light_image")
            imagen.configure(size=tamano, light_image=original, dark_image=original)

    def activar(self):
        self._activa = True
        self.reiniciar()

    def _cancelar_avance(self):
        if self._avance is not None:
            self.after_cancel(self._avance)
            self._avance = None

    def reiniciar(self):
        if not self._activa:
            return
        self._cancelar_avance()
        self.reproductor.detener()
        self.pregunta = None
        self.aciertos = self.intentos = 0
        self._preguntadas.clear()
        self._partida_completa = False
        self._actualizar_marcador()
        self._nueva_pregunta()

    def desactivar(self):
        self._activa = False
        self.pregunta = None
        self._cancelar_avance()
        self.reproductor.detener()

    def _actualizar_marcador(self):
        self.marcador.configure(text=f"   Aciertos: {self.aciertos} de {self.intentos}   ")

    def _limpiar_medio(self):
        self._foto = None
        self._etiqueta_foto.pack_forget()
        self._etiqueta_foto.configure(image="")
        self._etiqueta_pista.pack_forget()
        self._boton_canto.pack_forget()

    def cargar_datos(self, hoy, foco, fichas):
        # Prioriza las vistas hoy y las de foco. Las demás activas amplían la partida.
        por_id = {e["id_especie"]: e for e in hoy}
        candidatas = []
        nombres = set()
        ids = set()
        for especie in (*hoy, *foco, *fichas.values()):
            id_especie = especie["id_especie"]
            nombre = _normalizar_busqueda(especie["nombre_comun"])
            if id_especie in fichas and id_especie not in ids and nombre and nombre not in nombres:
                candidatas.append(por_id.get(id_especie, fichas[id_especie]))
                nombres.add(nombre)
                ids.add(id_especie)
        ids_preferidos = {e["id_especie"] for e in (*hoy, *foco)}
        self._preferidas = [e for e in candidatas if e["id_especie"] in ids_preferidos]
        cambio = candidatas != self._candidatas or self.cache.revision != self._revision_fotos
        self._candidatas = candidatas
        self._revision_fotos = self.cache.revision
        if not self._activa or not cambio or self._partida_completa:
            return
        if self.pregunta is not None:
            if self.pregunta["respondida"]:
                return
            correcta = self.pregunta["correcta"]
            actual = fichas.get(correcta["id_especie"], {})
            campos = ("ruta_audio_canto", "ruta_foto", "caracteristicas", "habitat")
            opciones_vigentes = all(
                fichas.get(opcion["id_especie"], {}).get("nombre_comun") == opcion["nombre_comun"]
                for opcion in self.pregunta["opciones"]
            )
            if opciones_vigentes and all(correcta.get(campo) == actual.get(campo) for campo in campos):
                return
            self._preguntadas.discard(correcta["id_especie"])
            self.reproductor.detener()
            self.pregunta = None
        self._nueva_pregunta()

    def _nueva_pregunta(self):
        if not self._activa or not self.winfo_exists():
            return
        self.pregunta = None
        self._limpiar_medio()
        for boton in self.botones:
            boton.pack_forget()
        if self._candidatas is None:
            self.enunciado.configure(text="Cargando recursos de la trivia…")
            self.retro.configure(text="")
            return
        if len(self._candidatas) < 3:
            self.enunciado.configure(text="La trivia necesita tres especies distintas")
            self.retro.configure(text="  Podrás jugar cuando haya al menos tres fichas activas con nombres diferentes.")
            return

        preferidas = list(self._preferidas)
        ids_preferidos = {e["id_especie"] for e in preferidas}
        adicionales = [e for e in self._candidatas if e["id_especie"] not in ids_preferidos]
        random.shuffle(preferidas)
        random.shuffle(adicionales)
        for correcta in (*preferidas, *adicionales):
            if correcta["id_especie"] not in self._preguntadas and self._mostrar_pista(correcta):
                break
        else:
            if self.intentos:
                self._partida_completa = True
                self.enunciado.configure(text="Fin de la partida")
                self.retro.configure(text=f"  {self.aciertos} de {self.intentos} aciertos. Pulsa Reiniciar para jugar otra vez.")
            else:
                self.enunciado.configure(text="No hay pistas disponibles")
                self.retro.configure(text="  La trivia necesita al menos un canto, una foto o una descripción.")
            return

        self._preguntadas.add(correcta["id_especie"])
        distractores = [e for e in self._candidatas if e["id_especie"] != correcta["id_especie"]]
        opciones = [correcta, *random.sample(distractores, 2)]
        random.shuffle(opciones)
        self.pregunta = {"correcta": correcta, "opciones": opciones, "respondida": False}
        self.retro.configure(text="  Selecciona A, B o C para responder.")

        for letra, boton, opcion in zip("ABC", self.botones, opciones):
            texto = textwrap.fill(f"{letra}   ·   {opcion['nombre_comun']}", width=24)
            boton.configure(
                text=texto, fg_color=T.CRISTAL_ACCION, border_color=T.CRISTAL_BORDE,
                text_color_disabled=T.CRISTAL_TEXTO, state="normal",
            )
            boton.pack(fill="x", padx=8, pady=(0, 8))

    def _mostrar_pista(self, especie):
        audio = buscar_audio_especie(especie)
        if audio is not None and self.reproductor.reproducir(audio):
            self.enunciado.configure(text="Escucha el canto: ¿qué ave es?")
            self._boton_canto.configure(command=lambda: self.reproductor.reproducir(audio))
            self._boton_canto.pack(expand=True, padx=10, pady=10)
            return True

        imagen = self.cache.obtener(especie.get("ruta_foto"), FOTO_TRIVIA) or self.cache.obtener(
            especie.get("ultima_captura"), FOTO_TRIVIA,
        )
        if imagen is not None:
            self.enunciado.configure(text="Observa la fotografía: ¿qué ave es esta?")
            self._foto = (imagen, imagen.cget("light_image").size)
            self._etiqueta_foto.configure(image=imagen)
            self._etiqueta_foto.pack(expand=True, padx=8, pady=8)
            self._ajustar_foto()
            return True

        pista = next((texto.strip() for texto in (especie.get("caracteristicas"), especie.get("habitat"))
                      if texto and texto.strip()), "")
        if pista:
            self.enunciado.configure(text="Lee la pista: ¿de qué ave se trata?")
            self._etiqueta_pista.configure(text=pista)
            self._etiqueta_pista.pack(fill="x", expand=True, padx=10, pady=10)
        return bool(pista)

    def _responder(self, indice):
        if not self._activa or not self.pregunta or self.pregunta["respondida"]:
            return
        self.pregunta["respondida"] = True
        elegida = self.pregunta["opciones"][indice]
        correcta = self.pregunta["correcta"]
        self.intentos += 1
        if elegida["id_especie"] == correcta["id_especie"]:
            self.aciertos += 1
            self.retro.configure(text="  ✓  ¡Correcto! Siguiente pregunta en unos segundos…")
        else:
            self.retro.configure(text=f"  Respuesta correcta: {correcta['nombre_comun']}. Siguiente pregunta en unos segundos…")

        for boton, opcion in zip(self.botones, self.pregunta["opciones"]):
            if opcion["id_especie"] == correcta["id_especie"]:
                boton.configure(fg_color=T.ETIQUETA_BIEN, border_color=T.VERDE)
            elif opcion is elegida:
                boton.configure(fg_color=T.ETIQUETA_RIESGO, border_color=T.NARANJA)
            boton.configure(state="disabled")

        self._actualizar_marcador()
        self.reproductor.detener()
        self._boton_canto.pack_forget()
        self._avance = self.after(SEGUNDOS_ENTRE_PREGUNTAS * 1000, self._siguiente)

    def _siguiente(self):
        self._avance = None
        if not self._activa or not self.winfo_exists():
            return
        self.pregunta = None
        self._nueva_pregunta()


# ==========================================================
# VENTANA PRINCIPAL DE LA SEGUNDA PANTALLA (CTkToplevel)
# ==========================================================


class PantallaSecundaria(ctk.CTkToplevel):
    """
    Ventana `CTkToplevel` para el segundo monitor (Pantalla 2 · Kiosco Táctil).

    Integra:
    - Menú de Inicio («Catálogo de Aves» y «Trivia de Cantos»).
    - Catálogo Público (100 % Read-Only) y Trivia de Cantos.
    - Bloqueo de Sistema (Anti-Escape): pantalla completa sin bordes ni botones de cierre.
    - Timeout por inactividad de 60 segundos para volver automáticamente al Menú de Inicio.
    """

    def __init__(self, maestro, modo=PANTALLA_2, monitor=MONITOR_PANTALLA_2):
        super().__init__(maestro, fg_color=T.ESCRITORIO)
        self.title("Centro Interactivo de Visitantes")
        self.base = BaseDatos()
        self.reproductor = Reproductor()
        self.cache_imagenes = CacheImagenes()
        # Lectura en voz alta de la ficha en el idioma elegido (voces Piper, sin internet).
        self.lector = LectorFicha(self, self.reproductor, al_cambiar=self._estado_lectura)
        self._boton_leer = None
        precargar(IDIOMA_ORIGINAL)

        self._vista_actual = None
        self._vista_previa_ficha = "menu"
        self._detalle_ficha = None
        self._origen_ficha = None
        self._estado_ficha = None
        self._ultimo_toque = time.monotonic()
        self.idioma = IDIOMA_ORIGINAL
        self.traducciones = TraduccionesCatalogo(self.base)
        self._datos_crudos = None

        self._configurar_kiosco_estricto(modo, monitor)
        self._crear_encabezado()
        self._crear_vistas()
        self._registrar_eventos_tactiles()

        self.mostrar_menu()
        self._reloj_pendiente = self.after(1000, self._vigilar_inactividad)

    def _configurar_kiosco_estricto(self, modo, monitor=None):
        """
        Posiciona la ventana en el segundo monitor (si existe) y fuerza el
        modo Kiosco Anti-Escape (`overrideredirect(True)` / `-fullscreen`),
        ocultando la barra de tareas y deshabilitando el cierre por el visitante.
        """
        monitores = listar_monitores(self)
        elegido = rect_monitor(monitor)
        if monitor is not None and elegido is None:
            print(f"[AVISO] No existe el monitor {monitor}; la Pantalla 2 usa la ubicación automática.")
        if elegido is not None:
            x, y, ancho, alto = elegido
            self.geometry(f"{ancho}x{alto}+{x}+{y}")
            self.overrideredirect(True)
        elif modo == "auto" and len(monitores) >= 2:
            x, y, ancho, alto = monitores[1]
            self.geometry(f"{ancho}x{alto}+{x}+{y}")
            self.overrideredirect(True)
        elif len(monitores) >= 1:
            x, y, ancho, alto = monitores[0]
            self.geometry(f"{ancho}x{alto}+{x}+{y}")
            self.overrideredirect(True)
            try:
                self.attributes("-fullscreen", True)
            except tk.TclError:
                pass
        else:
            self.geometry("1280x800+0+0")
            self.overrideredirect(True)

        # Anti-Escape: impedir que el visitante cierre la ventana con Alt+F4 o Escape
        self.protocol("WM_DELETE_WINDOW", self._bloquear_cierre)
        self.bind("<Alt-F4>", lambda _e: "break")
        self.bind("<Escape>", lambda _e: "break")

    def _bloquear_cierre(self):
        """Ignora intentos de cierre directo sobre la Segunda Pantalla."""
        return None

    def _crear_encabezado(self):
        barra_degradado(self, alto=6).pack(fill="x", side="top")
        encabezado = ctk.CTkFrame(self, fg_color=T.FONDO, corner_radius=0, height=58)
        encabezado.pack(fill="x", side="top")
        encabezado.pack_propagate(False)

        marca = ctk.CTkFrame(encabezado, fg_color=T.FONDO)
        marca.pack(side="left", padx=16)
        logo = CARPETA_ASSETS / T.ARCHIVO_LOGO
        imagen = abrir_imagen(logo, (260, 36)) if logo.exists() else None
        if imagen is not None:
            ctk.CTkLabel(marca, text="", image=imagen).pack(side="left", padx=(0, 14))
        else:
            barra_degradado(marca, alto=42, ancho=7, vertical=True).pack(side="left", padx=(0, 12))

        textos = ctk.CTkFrame(marca, fg_color=T.FONDO)
        textos.pack(side="left")
        ctk.CTkLabel(
            textos,
            text="Centro Interactivo de Visitantes",
            font=T.fuente_ctk(18, "bold"),
            text_color=T.TEXTO,
            anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(
            textos,
            text=T.SUBTITULO,
            font=T.fuente_ctk(12),
            text_color=T.GRIS,
            anchor="w",
        ).pack(fill="x")

        derecha = ctk.CTkFrame(encabezado, fg_color=T.FONDO)
        derecha.pack(side="right", padx=16)
        self.reloj = ctk.CTkLabel(
            derecha,
            text=datetime.now().strftime("%H:%M"),
            font=T.fuente_ctk(22, "bold"),
            text_color=T.TEXTO,
        )
        self.reloj.pack(side="right")
        # Idioma de las fichas: lo elige el visitante (vuelve al español tras la inactividad).
        self._nombres_idioma = {nombre: codigo for codigo, nombre in IDIOMAS.items()}
        self.selector_idioma = ctk.CTkSegmentedButton(
            derecha, values=list(IDIOMAS.values()), command=self._elegir_idioma,
            font=T.fuente_ctk(15, "bold"), height=42, corner_radius=21,
            selected_color=T.ACENTO, selected_hover_color=T.ACENTO, unselected_color=T.GRIS,
            unselected_hover_color=T.ACENTO_HOVER, text_color="#FFFFFF", fg_color=T.GRIS,
        )
        self.selector_idioma.set(IDIOMAS[IDIOMA_ORIGINAL])
        self.selector_idioma.pack(side="right", padx=(0, 18))

    def _crear_vistas(self):
        escritorio = ctk.CTkFrame(self, fg_color="transparent")
        escritorio.pack(fill="both", expand=True, padx=8, pady=8)
        escritorio.grid_columnconfigure(0, weight=32, uniform="paneles")
        escritorio.grid_columnconfigure(1, weight=68, uniform="paneles")
        escritorio.grid_rowconfigure(0, weight=1)

        self.workspace = ctk.CTkFrame(escritorio, fg_color=T.FONDO, corner_radius=0)
        self.workspace.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self.workspace.grid_propagate(False)
        self.workspace.grid_rowconfigure(0, weight=1)
        self.workspace.grid_columnconfigure(0, weight=1)

        self.vista_menu = VistaMenuInicio(
            self.workspace,
            ir_catalogo=self.mostrar_catalogo,
            ir_trivia=self.mostrar_trivia,
        )
        self.vista_catalogo = VistaCatalogoPublico(
            self.workspace,
            abrir_ficha=self.mostrar_ficha,
            reproductor=self.reproductor,
            volver_menu=self.mostrar_menu,
            cache=self.cache_imagenes,
        )
        self.vista_trivia = VistaTriviaCantos(
            self.workspace,
            reproductor=self.reproductor,
            volver_menu=self.mostrar_menu,
            cache=self.cache_imagenes,
        )
        self.vista_ficha = ctk.CTkFrame(self.workspace, fg_color=T.FONDO, corner_radius=0)
        self._barra_ficha = barra_workspace(self.vista_ficha, tx("ficha_educativa"), self._volver_de_ficha)
        self.ficha = MarcoDesplazableTactil(self.vista_ficha, fg_color=T.FONDO_SUAVE, width=1, height=1, arrastre=True)
        self.ficha.pack(fill="both", expand=True, padx=(8, 4), pady=8)
        self._vistas = {
            "menu": self.vista_menu, "catalogo": self.vista_catalogo,
            "trivia": self.vista_trivia, "ficha": self.vista_ficha,
        }
        self.panel_hoy = PanelAvistamientosHoy(
            escritorio, self.base.ruta, self.mostrar_ficha, self.cache_imagenes, self._cargar_datos,
        )
        self.panel_hoy.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.panel_hoy.pack_propagate(False)

    def _elegir_idioma(self, nombre, *, forzar=False):
        idioma = self._nombres_idioma.get(nombre, IDIOMA_ORIGINAL)
        if idioma == self.idioma and not forzar:
            return
        self.idioma = idioma
        self.lector.detener()
        precargar(idioma)
        if self.selector_idioma.get() != IDIOMAS[idioma]:
            self.selector_idioma.set(IDIOMAS[idioma])
        for hijo in self._barra_ficha.winfo_children():
            if isinstance(hijo, ctk.CTkButton):
                hijo.configure(text="← " + tx("volver", idioma))
            elif isinstance(hijo, ctk.CTkLabel):
                hijo.configure(text=tx("ficha_educativa", idioma))
        self._estado_ficha = None
        if self._datos_crudos is not None:
            self._cargar_datos(*self._datos_crudos)

    def _cargar_datos(self, catalogo, especies):
        self._datos_crudos = (catalogo, especies)
        catalogo = self.traducciones.lista(catalogo, self.idioma)
        especies = self.traducciones.lista(especies, self.idioma)
        self.vista_catalogo.cargar_datos(catalogo, especies)
        self.vista_trivia.cargar_datos(especies, self.vista_catalogo._foco_trivia, self.vista_catalogo._por_id)
        if self._vista_actual == "ficha" and self._origen_ficha is not None:
            id_especie, desde_hoy = self._origen_ficha
            especie = self.vista_catalogo._por_id.get(id_especie)
            if especie is None:
                self._volver_de_ficha()
                return
            if self.ficha.gesto_activo:
                return
            origen = next((e for e in especies if e["id_especie"] == id_especie), {}) if desde_hoy else especie
            self._actualizar_ficha(especie, origen.get("ultima_captura"))

    def _registrar_eventos_tactiles(self):
        for secuencia in ("<Button-1>", "<B1-Motion>", "<Key>", "<MouseWheel>", "<<ToqueVisitante>>"):
            self.bind(secuencia, self._registrar_toque, add="+")

    def _registrar_toque(self, _evento=None):
        self._ultimo_toque = time.monotonic()

    # ------------------------------------------------------
    # Navegación entre vistas
    # ------------------------------------------------------

    def mostrar_menu(self):
        self._mostrar_vista("menu")

    def mostrar_catalogo(self):
        self.vista_catalogo.reiniciar_estado()
        self._mostrar_vista("catalogo")

    def mostrar_trivia(self):
        self._mostrar_vista("trivia")

    def _mostrar_vista(self, nombre):
        if nombre != "ficha" and hasattr(self, "lector"):
            self.lector.detener()
        self._registrar_toque()
        if nombre == self._vista_actual:
            return
        if self._vista_actual == "trivia":
            self.vista_trivia.desactivar()
        else:
            self.reproductor.detener()
        if self._vista_actual == "ficha":
            self.ficha.cancelar_gesto()
        self.vista_catalogo.ocultar_teclado()
        if self._vista_actual is not None:
            self._vistas[self._vista_actual].grid_remove()
        self._vistas[nombre].grid(row=0, column=0, sticky="nsew")
        self._vista_actual = nombre
        self.update_idletasks()
        if nombre == "trivia":
            self.vista_trivia.activar()
        elif nombre == "catalogo":
            self.vista_catalogo._actualizar(conservar_posicion=True)

    def mostrar_ficha(self, avistamiento):
        id_especie = avistamiento["id_especie"]
        especie = self.vista_catalogo._por_id.get(id_especie)
        if especie is None:
            return
        if self._vista_actual == "ficha":
            self.ficha.cancelar_gesto()
            self.lector.detener()
            self.reproductor.detener()
        else:
            self._vista_previa_ficha = self._vista_actual
            self._mostrar_vista("ficha")
        self._origen_ficha = (id_especie, "ultimo_id" in avistamiento)
        self._actualizar_ficha(especie, avistamiento.get("ultima_captura"))
        self.ficha._parent_canvas.yview_moveto(0)

    def _actualizar_ficha(self, especie, captura):
        ancho = round(self.ficha._reverse_widget_scaling(self.ficha.winfo_width()))
        imagen = self.cache_imagenes.obtener(especie.get("ruta_foto"), FOTO_FICHA) or self.cache_imagenes.obtener(
            captura, FOTO_FICHA,
        )
        resumen = None
        try:
            estado = (especie, ancho, imagen, self.base.version_datos(), date.today(), self.idioma)
            if estado == self._estado_ficha:
                return
            resumen = self.base.resumen_especie(especie["id_especie"])
            self._estado_ficha = estado
        except sqlite3.Error:
            # Conserva una ficha ya visible mientras una escritura concurrente termina.
            if self._detalle_ficha is not None and self._detalle_ficha[0][0] == especie:
                return
        clave = (especie, ancho, resumen, imagen, self.idioma)
        if self._detalle_ficha is None or clave != self._detalle_ficha[0]:
            if self._detalle_ficha is not None:
                anterior = self._detalle_ficha[0][0]
                if anterior.get("ruta_audio_canto") != especie.get("ruta_audio_canto"):
                    self.reproductor.detener()
                self._detalle_ficha[1].destroy()
            detalle = ctk.CTkFrame(self.ficha, fg_color="transparent")
            detalle.pack(fill="x")
            botones = ctk.CTkFrame(detalle, fg_color="transparent")
            botones.pack(fill="x", padx=16, pady=(4, 0))
            self._boton_leer = None
            if voz_disponible(self.idioma):
                self._boton_leer = boton_cristal(
                    botones, "▶ " + tx("leer_ficha", self.idioma), lambda e=especie: self._alternar_lectura(e),
                    width=170,
                )
                self._boton_leer.pack(side="left")
            controles_canto(detalle, self.reproductor, especie, especie, self.idioma, barra=botones)
            llenar_ficha(
                detalle, especie, captura, ancho, resumen, compacta=True, cristal=True,
                obtener_imagen=self.cache_imagenes.obtener, idioma=self.idioma,
            )
            self.ficha.registrar_gesto(detalle)
            self._detalle_ficha = (clave, detalle)

    def _alternar_lectura(self, especie):
        if self.lector.leyendo:
            self.lector.detener()
        else:
            self.lector.leer(parrafos_ficha(especie, self.idioma), self.idioma)

    def _estado_lectura(self, leyendo):
        boton = self._boton_leer
        try:
            if boton is not None and boton.winfo_exists():
                texto = ("■ " + tx("detener_lectura", self.idioma)) if leyendo else ("▶ " + tx("leer_ficha", self.idioma))
                boton.configure(text=texto)
        except tk.TclError:
            pass

    def _volver_de_ficha(self):
        self.lector.detener()
        self._mostrar_vista(self._vista_previa_ficha)

    # ------------------------------------------------------
    # Vigilancia de inactividad (60 segundos) y cierre
    # ------------------------------------------------------

    def _vigilar_inactividad(self):
        if not self.winfo_exists():
            return
        self.reloj.configure(text=datetime.now().strftime("%H:%M"))
        inactivo = (time.monotonic() - self._ultimo_toque) >= SEGUNDOS_INACTIVIDAD_PANTALLA2
        if inactivo and self.lector.leyendo:
            inactivo = False  # mientras lee la ficha, el visitante está escuchando
        if inactivo and self._vista_actual != "menu":
            self.lector.detener()
            self.vista_catalogo.reiniciar_estado()
            self.mostrar_menu()
        if inactivo and self.idioma != IDIOMA_ORIGINAL:
            self._elegir_idioma(IDIOMAS[IDIOMA_ORIGINAL])  # el próximo visitante empieza en español
        self._reloj_pendiente = self.after(1000, self._vigilar_inactividad)

    def cerrar_sistema(self):
        """Cierre controlado invocado únicamente al apagar el Kiosco principal."""
        self.after_cancel(self._reloj_pendiente)
        try:
            self.vista_trivia.desactivar()
            self.reproductor.detener()
            self.base.cerrar()
        except Exception:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass
