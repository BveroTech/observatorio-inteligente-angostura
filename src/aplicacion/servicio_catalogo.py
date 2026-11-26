import argparse
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import unicodedata
import webbrowser
from datetime import datetime

import customtkinter as ctk
from PIL import Image, ImageDraw

from config.settings import (
    ADMIN_HOST,
    ADMIN_PUERTO,
    BASE_DIR,
    ES_EMPAQUETADO,
    ESPECIES_FOCO,
    INTENTOS_LOGIN_MAXIMOS,
    MINUTOS_BLOQUEO_LOGIN,
)
from src.aplicacion.gestor_monitores import listar_monitores
from src.persistencia.repositorio_sqlite import BaseDatos, preparar_base
from src.presentacion import tema_visual as T
from src.presentacion.ventana_kiosco import (
    ALTO_BOTON,
    abrir_imagen,
    barra_degradado,
    color_conservacion,
    llenar_ficha,
    texto_uicn,
)

POR_PAGINA = 25
TAMANO_MINIATURA = (96, 72)
SEGUNDOS_REINICIO = 180          # sin toques: vuelve a la lista inicial
SEGUNDOS_CIERRE_ACCESO = 60      # sin toques: se cierra «Acceso restringido»
FILTROS = ("Todas", "Especies del embalse", "Vistas hoy")


def clave(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "").lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip()


def icono_tuerca(tamano=30, color=T.GRIS):
    """Engranaje dibujado con Pillow (no depende de que la fuente tenga el símbolo)."""
    escala = 4
    lado = tamano * escala
    imagen = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(imagen)
    centro = lado / 2
    radio_ext, radio_int, dientes = lado * 0.46, lado * 0.34, 8
    import math

    puntos = []
    for i in range(dientes * 4):
        angulo = 2 * math.pi * i / (dientes * 4) - math.pi / (dientes * 4)
        r = radio_ext if (i % 4) in (1, 2) else radio_int
        puntos.append((centro + r * math.cos(angulo), centro + r * math.sin(angulo)))
    dibujo.polygon(puntos, fill=color)
    hueco = lado * 0.14
    dibujo.ellipse((centro - hueco, centro - hueco, centro + hueco, centro + hueco), fill=(0, 0, 0, 0))
    imagen = imagen.resize((tamano, tamano), Image.LANCZOS)
    return ctk.CTkImage(light_image=imagen, dark_image=imagen, size=(tamano, tamano))


# ----------------------------------------------------------------------
# Acceso al portal de administración
# ----------------------------------------------------------------------

def portal_activo():
    try:
        with socket.create_connection(("127.0.0.1", ADMIN_PUERTO), timeout=0.5):
            return True
    except OSError:
        return False


def _iniciar_portal_embebido():
    try:
        from web import crear_app
        app = crear_app()
        app.run(host=ADMIN_HOST, port=ADMIN_PUERTO, debug=False, threaded=True, use_reloader=False)
    except Exception as error:
        print(f"No se pudo iniciar el servidor web embebido: {error}")


def asegurar_portal(espera=12):
    if portal_activo():
        return True
    exe_admin = BASE_DIR / "Admin.exe"
    script_admin = BASE_DIR / "main_admin.py"
    opciones = {"cwd": str(BASE_DIR)}
    if sys.platform.startswith("win"):
        opciones["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

    if ES_EMPAQUETADO and exe_admin.is_file():
        try:
            subprocess.Popen([str(exe_admin), "--sin-navegador"], **opciones)
        except Exception:
            threading.Thread(target=_iniciar_portal_embebido, daemon=True, name="portal_web").start()
    elif not ES_EMPAQUETADO and script_admin.is_file():
        try:
            subprocess.Popen([sys.executable, str(script_admin), "--sin-navegador"], **opciones)
        except Exception:
            threading.Thread(target=_iniciar_portal_embebido, daemon=True, name="portal_web").start()
    else:
        threading.Thread(target=_iniciar_portal_embebido, daemon=True, name="portal_web").start()

    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        if portal_activo():
            return True
        time.sleep(0.4)
    return False


class AccesoRestringido(ctk.CTkToplevel):
    _fallos = []  # momentos de intentos fallidos (compartido mientras el programa esté abierto)

    def __init__(self, maestro):
        super().__init__(maestro, fg_color=T.FONDO)
        self.maestro = maestro
        self.title("Acceso restringido")
        ancho, alto = 560, 520
        x = maestro.winfo_rootx() + (maestro.winfo_width() - ancho) // 2
        y = maestro.winfo_rooty() + (maestro.winfo_height() - alto) // 2
        self.geometry(f"{ancho}x{alto}+{max(0, x)}+{max(0, y)}")
        self.resizable(False, False)
        self.transient(maestro)
        self.protocol("WM_DELETE_WINDOW", self.volver)

        barra = ctk.CTkFrame(self, fg_color=T.NARANJA, corner_radius=0, height=8)
        barra.pack(fill="x")
        cuerpo = ctk.CTkFrame(self, fg_color=T.FONDO)
        cuerpo.pack(fill="both", expand=True, padx=36, pady=(24, 24))

        ctk.CTkLabel(cuerpo, text="Acceso restringido", font=T.fuente_ctk(28, "bold"), text_color=T.TEXTO,
                     anchor="w").pack(fill="x")
        ctk.CTkLabel(
            cuerpo, text="Esta sección es solo para el personal autorizado del observatorio.\n"
                         "Si llegaste aquí por error, presiona «Volver».",
            font=T.fuente_ctk(15), text_color=T.GRIS, anchor="w", justify="left",
        ).pack(fill="x", pady=(6, 18))

        ctk.CTkLabel(cuerpo, text="Correo", font=T.fuente_ctk(14, "bold"), text_color=T.TEXTO, anchor="w").pack(fill="x")
        self.correo = ctk.CTkEntry(cuerpo, height=44, font=T.fuente_ctk(16), corner_radius=10,
                                   border_color=T.BORDE, fg_color=T.FONDO_SUAVE, text_color=T.TEXTO)
        self.correo.pack(fill="x", pady=(4, 12))
        ctk.CTkLabel(cuerpo, text="Contraseña", font=T.fuente_ctk(14, "bold"), text_color=T.TEXTO, anchor="w").pack(fill="x")
        self.clave = ctk.CTkEntry(cuerpo, height=44, font=T.fuente_ctk(16), corner_radius=10, show="•",
                                  border_color=T.BORDE, fg_color=T.FONDO_SUAVE, text_color=T.TEXTO)
        self.clave.pack(fill="x", pady=(4, 8))
        self.mensaje = ctk.CTkLabel(cuerpo, text="", font=T.fuente_ctk(14), text_color="#B4471A", anchor="w",
                                    justify="left", wraplength=480)
        self.mensaje.pack(fill="x", pady=(0, 8))

        botones = ctk.CTkFrame(cuerpo, fg_color=T.FONDO)
        botones.pack(fill="x", side="bottom")
        self.boton_volver = ctk.CTkButton(
            botones, text="Volver", command=self.volver, height=ALTO_BOTON, corner_radius=26,
            font=T.fuente_ctk(18, "bold"), fg_color=T.FONDO, hover_color=T.ACENTO_CLARO,
            text_color=T.ACENTO, border_color=T.ACENTO, border_width=2,
        )
        self.boton_volver.pack(side="left", expand=True, fill="x", padx=(0, 8))
        self.boton_ingresar = ctk.CTkButton(
            botones, text="Ingresar", command=self.ingresar, height=ALTO_BOTON, corner_radius=26,
            font=T.fuente_ctk(18, "bold"), fg_color=T.ACENTO, hover_color=T.ACENTO_HOVER, text_color="#FFFFFF",
        )
        self.boton_ingresar.pack(side="left", expand=True, fill="x", padx=(8, 0))

        self.bind("<Return>", lambda _e: self.ingresar())
        self.bind("<Escape>", lambda _e: self.volver())
        self._ultimo_toque = time.monotonic()
        for evento in ("<Button-1>", "<Key>", "<Motion>"):
            self.bind(evento, self._toque, add="+")
        self.after(1000, self._vigilar)
        self.after(60, self._tomar_foco)
        self._revisar_bloqueo()

    def _tomar_foco(self):
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
            self.correo.focus_set()
        except tk.TclError:
            pass

    def _toque(self, _evento=None):
        self._ultimo_toque = time.monotonic()

    def _vigilar(self):
        if not self.winfo_exists():
            return
        if time.monotonic() - self._ultimo_toque > SEGUNDOS_CIERRE_ACCESO:
            self.volver()
            return
        self._revisar_bloqueo()
        self.after(1000, self._vigilar)

    @classmethod
    def _espera_bloqueo(cls):
        ahora = time.monotonic()
        cls._fallos = [t for t in cls._fallos if ahora - t < MINUTOS_BLOQUEO_LOGIN * 60]
        if len(cls._fallos) >= INTENTOS_LOGIN_MAXIMOS:
            return int(MINUTOS_BLOQUEO_LOGIN * 60 - (ahora - cls._fallos[0])) + 1
        return 0

    def _revisar_bloqueo(self):
        espera = self._espera_bloqueo()
        estado = "disabled" if espera else "normal"
        self.boton_ingresar.configure(state=estado)
        if espera:
            self.mensaje.configure(text=f"Demasiados intentos fallidos. Espera {espera // 60 + 1} min.")

    def ingresar(self):
        if self._espera_bloqueo():
            self._revisar_bloqueo()
            return
        correo, clave_texto = self.correo.get().strip(), self.clave.get()
        if not correo or not clave_texto:
            self.mensaje.configure(text="Escribe tu correo y tu contraseña.")
            return
        from werkzeug.security import check_password_hash

        base = BaseDatos()
        try:
            usuario = base.usuario_por_correo(correo)
            valido = bool(usuario and check_password_hash(usuario["password_hash"], clave_texto))
        finally:
            base.cerrar()
        self.clave.delete(0, "end")
        if not valido:
            AccesoRestringido._fallos.append(time.monotonic())
            self.mensaje.configure(text="Correo o contraseña incorrectos.")
            self._revisar_bloqueo()
            return
        AccesoRestringido._fallos.clear()
        self.mensaje.configure(text="Abriendo el panel de administración…", text_color=T.ACENTO)
        self.boton_ingresar.configure(state="disabled")
        self.update_idletasks()
        threading.Thread(target=self._abrir_portal, args=(usuario["id_usuario"],), daemon=True).start()

    def _abrir_portal(self, id_usuario):
        from web import crear_token_acceso

        listo = asegurar_portal()
        if not listo:
            self.after(0, lambda: self.mensaje.configure(
                text="No se pudo iniciar el portal. Ejecuta main_admin.py o ejecutar_observatorio.bat.",
                text_color="#B4471A",
            ))
            return
        url = f"http://127.0.0.1:{ADMIN_PUERTO}/acceso/{crear_token_acceso(id_usuario)}"
        webbrowser.open(url)
        self.after(0, self._terminar)

    def _terminar(self):
        self.volver()
        self.maestro.dejar_paso_al_navegador()

    def volver(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


# ----------------------------------------------------------------------
# Ventana principal del catálogo
# ----------------------------------------------------------------------

class Catalogo(ctk.CTk):
    def __init__(self, pantalla_completa=False, monitor=None):
        ctk.set_appearance_mode("light")
        super().__init__(fg_color=T.FONDO_SUAVE)
        T.configurar_fuente(self)
        self.base = BaseDatos()
        self.title("Catálogo de aves · " + T.TITULO)
        self._ubicar(monitor)
        self.minsize(900, 640)
        self.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.bind("<F11>", lambda _e: self.attributes("-fullscreen", not self.attributes("-fullscreen")))
        self.bind("<Escape>", lambda _e: self.attributes("-fullscreen", False))
        if pantalla_completa:
            self.after(200, lambda: self.attributes("-fullscreen", True))

        self._filtro = FILTROS[0]
        self._resultados = []
        self._mostradas = 0
        self._abierta = None          # (id_especie, marco_detalle, etiqueta_flecha)
        self._busqueda_pendiente = None
        self._ultimo_toque = time.monotonic()
        self._acceso = None

        self._crear_encabezado()
        self._crear_pie()
        self._crear_cuerpo()
        for evento in ("<Button-1>", "<Key>", "<MouseWheel>"):
            self.bind_all(evento, self._toque, add="+")
        self.after(100, self._actualizar)
        self.after(1000, self._ciclo)

    def _ubicar(self, monitor):
        monitores = listar_monitores(self)
        if monitor and 1 <= monitor <= len(monitores):
            x, y, ancho, alto = monitores[monitor - 1]
            self.geometry(f"{ancho}x{alto}+{x}+{y}")
        else:
            ancho = min(1280, self.winfo_screenwidth())
            alto = min(800, self.winfo_screenheight() - 80)
            self.geometry(f"{ancho}x{alto}+0+0")

    # ------------------------------------------------------
    # Construcción
    # ------------------------------------------------------

    def _crear_encabezado(self):
        barra_degradado(self, alto=5).pack(fill="x", side="top")
        encabezado = ctk.CTkFrame(self, fg_color=T.FONDO, corner_radius=0, height=86)
        encabezado.pack(fill="x", side="top")
        encabezado.pack_propagate(False)
        marca = ctk.CTkFrame(encabezado, fg_color=T.FONDO)
        marca.pack(side="left", padx=28)
        barra_degradado(marca, alto=50, ancho=8, vertical=True).pack(side="left", padx=(0, 14))
        textos = ctk.CTkFrame(marca, fg_color=T.FONDO)
        textos.pack(side="left")
        ctk.CTkLabel(textos, text="Catálogo de aves", font=T.fuente_ctk(24, "bold"), text_color=T.TEXTO,
                     anchor="w").pack(fill="x")
        self.subtitulo = ctk.CTkLabel(textos, text=T.SUBTITULO, font=T.fuente_ctk(14), text_color=T.GRIS, anchor="w")
        self.subtitulo.pack(fill="x")
        self.reloj = ctk.CTkLabel(encabezado, text="", font=T.fuente_ctk(22, "bold"), text_color=T.TEXTO)
        self.reloj.pack(side="right", padx=28)

    def _crear_pie(self):
        pie = ctk.CTkFrame(self, fg_color=T.FONDO_SUAVE, corner_radius=0, height=52)
        pie.pack(fill="x", side="bottom")
        pie.pack_propagate(False)
        ctk.CTkLabel(pie, text="Toca un ave para desplegar su ficha completa", font=T.fuente_ctk(13),
                     text_color=T.GRIS_CLARO).pack(side="left", padx=28)
        self.boton_tuerca = ctk.CTkButton(
            pie, text="", image=icono_tuerca(26, T.GRIS_CLARO), width=44, height=44, corner_radius=22,
            fg_color=T.FONDO_SUAVE, hover_color=T.BORDE, command=self.abrir_acceso,
        )
        self.boton_tuerca.pack(side="right", padx=20)

    def _crear_cuerpo(self):
        cuerpo = ctk.CTkFrame(self, fg_color=T.FONDO, corner_radius=18)
        cuerpo.pack(fill="both", expand=True, padx=20, pady=(16, 4))

        controles = ctk.CTkFrame(cuerpo, fg_color=T.FONDO)
        controles.pack(fill="x", padx=20, pady=(18, 6))
        self.buscador = ctk.CTkEntry(
            controles, placeholder_text="Buscar por nombre común, científico o familia…", height=46,
            font=T.fuente_ctk(16), corner_radius=23, border_color=T.BORDE, fg_color=T.FONDO_SUAVE, text_color=T.TEXTO,
        )
        self.buscador.pack(side="left", fill="x", expand=True, padx=(0, 14))
        self.buscador.bind("<KeyRelease>", self._buscar_luego)
        self.selector = ctk.CTkSegmentedButton(
            controles, values=list(FILTROS), command=self._cambiar_filtro, height=46,
            font=T.fuente_ctk(15, "bold"), corner_radius=23, fg_color=T.FONDO_SUAVE,
            selected_color=T.ACENTO, selected_hover_color=T.ACENTO_HOVER,
            unselected_color=T.FONDO_SUAVE, unselected_hover_color=T.ACENTO_CLARO,
        )
        self.selector.pack(side="right")
        self.selector.set(FILTROS[0])
        self._colorear_selector()

        self.resumen = ctk.CTkLabel(cuerpo, text="", font=T.fuente_ctk(14, "bold"), text_color=T.ACENTO, anchor="w")
        self.resumen.pack(fill="x", padx=24, pady=(4, 4))
        self.lista = ctk.CTkScrollableFrame(cuerpo, fg_color=T.FONDO)
        self.lista.pack(fill="both", expand=True, padx=10, pady=(0, 12))

    def _colorear_selector(self):
        for nombre, boton in self.selector._buttons_dict.items():
            boton.configure(text_color="#FFFFFF" if nombre == self._filtro else T.TEXTO)

    # ------------------------------------------------------
    # Búsqueda y lista
    # ------------------------------------------------------

    def _cambiar_filtro(self, filtro):
        self._filtro = filtro
        self._colorear_selector()
        self._actualizar()

    def _buscar_luego(self, _evento=None):
        if self._busqueda_pendiente is not None:
            self.after_cancel(self._busqueda_pendiente)
        self._busqueda_pendiente = self.after(300, self._actualizar)

    def _consultar(self):
        if self._filtro == "Especies del embalse":
            especies = self.base.especies_por_cientifico(ESPECIES_FOCO)
        elif self._filtro == "Vistas hoy":
            especies = [e for e in self.base.especies_del_dia()]
        else:
            especies = sorted(self.base.especies(solo_activas=True), key=lambda e: clave(e["nombre_comun"]))
        texto = clave(self.buscador.get())
        if texto:
            especies = [
                e for e in especies
                if texto in clave(e["nombre_comun"]) or texto in clave(e["nombre_cientifico"])
                or texto in clave(e.get("familia")) or texto in clave(e.get("orden"))
            ]
        return especies

    def _actualizar(self):
        self._busqueda_pendiente = None
        try:
            self._resultados = self._consultar()
        except Exception as error:
            self.resumen.configure(text=f"No se pudo leer el catálogo: {error}")
            return
        total_catalogo = self.base.total_especies(solo_activas=True)
        self.subtitulo.configure(text=f"{total_catalogo} especies · {T.SUBTITULO}")
        n = len(self._resultados)
        buscado = self.buscador.get().strip()
        if buscado:
            ambito = {"Todas": "en el catálogo", "Especies del embalse": "entre las especies del embalse",
                      "Vistas hoy": "entre las aves vistas hoy"}[self._filtro]
            texto = f"{n} resultado{'s' if n != 1 else ''} para «{buscado}» {ambito}"
        else:
            texto = {
                "Todas": f"{n} especie{'s' if n != 1 else ''}",
                "Especies del embalse": f"{n} especies más vistas en el embalse Angostura",
                "Vistas hoy": f"{n} especie{'s' if n != 1 else ''} identificada{'s' if n != 1 else ''} hoy por la cámara",
            }[self._filtro]
        self.resumen.configure(text=texto)
        self._abierta = None
        for widget in self.lista.winfo_children():
            widget.destroy()
        self._mostradas = 0
        self._boton_mas = None
        if not self._resultados:
            mensaje = ("Todavía no se han identificado aves hoy." if self._filtro == "Vistas hoy"
                       else "No hay especies que coincidan con la búsqueda.")
            ctk.CTkLabel(self.lista, text=mensaje, font=T.fuente_ctk(16), text_color=T.GRIS_CLARO).pack(pady=50)
        else:
            self._mostrar_mas()
        self._ir_arriba()

    def _mostrar_mas(self):
        if self._boton_mas is not None:
            self._boton_mas.destroy()
            self._boton_mas = None
        siguiente = self._resultados[self._mostradas:self._mostradas + POR_PAGINA]
        for especie in siguiente:
            self._fila(especie)
        self._mostradas += len(siguiente)
        restantes = len(self._resultados) - self._mostradas
        if restantes > 0:
            self._boton_mas = ctk.CTkButton(
                self.lista, text=f"Mostrar más especies ({restantes} restantes)", command=self._mostrar_mas,
                height=ALTO_BOTON, corner_radius=26, font=T.fuente_ctk(16, "bold"),
                fg_color=T.FONDO_SUAVE, hover_color=T.ACENTO_CLARO, text_color=T.ACENTO,
            )
            self._boton_mas.pack(fill="x", padx=60, pady=(10, 20))

    def _fila(self, especie):
        contenedor = ctk.CTkFrame(self.lista, fg_color=T.FONDO, border_color=T.BORDE, border_width=1, corner_radius=14)
        contenedor.pack(fill="x", padx=8, pady=5)
        cabecera = ctk.CTkFrame(contenedor, fg_color=T.FONDO, cursor="hand2")
        cabecera.pack(fill="x", padx=2, pady=2)

        id_especie = especie["id_especie"]
        ruta = especie.get("ruta_foto") or especie.get("ultima_captura") or self.base.ultima_captura(id_especie)
        imagen = abrir_imagen(ruta, TAMANO_MINIATURA)
        ctk.CTkLabel(
            cabecera, text="" if imagen else "Sin foto", image=imagen, width=TAMANO_MINIATURA[0],
            height=TAMANO_MINIATURA[1], fg_color=T.FONDO_SUAVE, corner_radius=10, text_color=T.GRIS_CLARO,
            font=T.fuente_ctk(12),
        ).pack(side="left", padx=10, pady=8)

        textos = ctk.CTkFrame(cabecera, fg_color=T.FONDO)
        textos.pack(side="left", fill="both", expand=True, pady=8)
        ctk.CTkLabel(textos, text=especie["nombre_comun"], font=T.fuente_ctk(19, "bold"), text_color=T.TEXTO,
                     anchor="w").pack(fill="x")
        ctk.CTkLabel(textos, text=especie["nombre_cientifico"], font=T.fuente_ctk(14, inclinada=True),
                     text_color=T.GRIS, anchor="w").pack(fill="x")
        detalle = " · ".join(v for v in (especie.get("familia"), especie.get("orden")) if v)
        if self._filtro == "Vistas hoy" and especie.get("veces"):
            detalle = f"Vista {especie['veces']} vez{'es' if especie['veces'] != 1 else ''} hoy · {detalle}"
        ctk.CTkLabel(textos, text=detalle, font=T.fuente_ctk(13), text_color=T.GRIS_CLARO, anchor="w").pack(fill="x")

        uicn = texto_uicn(especie.get("conservacion_uicn"))
        if uicn:
            ctk.CTkLabel(
                cabecera, text=f"  {uicn}  ", font=T.fuente_ctk(13, "bold"), text_color=T.TEXTO,
                fg_color=color_conservacion(especie.get("conservacion_uicn")), corner_radius=12, height=28,
            ).pack(side="left", padx=10)
        flecha = ctk.CTkLabel(cabecera, text="Ver ficha", font=T.fuente_ctk(14, "bold"), text_color=T.ACENTO)
        flecha.pack(side="right", padx=18)

        def alternar(_evento=None, e=especie, c=contenedor, f=flecha):
            self._alternar(e, c, f)

        contenedor.alternar = alternar
        contenedor.nombre = especie["nombre_comun"]
        pendientes = [cabecera]
        while pendientes:
            widget = pendientes.pop()
            widget.bind("<Button-1>", alternar, add="+")
            pendientes.extend(widget.winfo_children())

    def _alternar(self, especie, contenedor, flecha):
        id_especie = especie["id_especie"]
        abierta = self._abierta
        if abierta is not None:
            abierta[1].destroy()
            try:
                abierta[2].configure(text="Ver ficha")
            except tk.TclError:
                pass
            self._abierta = None
            if abierta[0] == id_especie:
                return
        ficha = self.base.especie(id_especie)
        if ficha is None:
            return
        detalle = ctk.CTkFrame(contenedor, fg_color=T.FONDO)
        detalle.pack(fill="x", padx=6, pady=(0, 10))
        ctk.CTkFrame(detalle, fg_color=T.BORDE, height=1).pack(fill="x", padx=12, pady=(0, 4))
        ancho = max(700, self.lista.winfo_width() - 40)
        try:
            resumen = self.base.resumen_especie(id_especie)
        except Exception:
            resumen = None
        llenar_ficha(detalle, ficha, self.base.ultima_captura(id_especie), ancho, resumen)
        flecha.configure(text="Cerrar ficha")
        self._abierta = (id_especie, detalle, flecha)
        self.after(50, lambda: self._llevar_a(contenedor))

    def _llevar_a(self, widget):
        try:
            self.update_idletasks()
            lienzo = self.lista._parent_canvas
            alto_total = self.lista.winfo_reqheight() or 1
            lienzo.yview_moveto(max(0.0, (widget.winfo_y() - 6) / alto_total))
        except (AttributeError, tk.TclError):
            pass

    def _ir_arriba(self):
        try:
            self.lista._parent_canvas.yview_moveto(0)
        except (AttributeError, tk.TclError):
            pass

    # ------------------------------------------------------
    # Tuerca, inactividad y cierre
    # ------------------------------------------------------

    def abrir_acceso(self):
        if self._acceso is not None and self._acceso.winfo_exists():
            self._acceso.lift()
            return
        self._acceso = AccesoRestringido(self)

    def dejar_paso_al_navegador(self):
        try:
            self.attributes("-fullscreen", False)
            self.iconify()
        except tk.TclError:
            pass

    def _toque(self, _evento=None):
        self._ultimo_toque = time.monotonic()

    def _ciclo(self):
        if not self.winfo_exists():
            return
        self.reloj.configure(text=datetime.now().strftime("%H:%M"))
        inactivo = time.monotonic() - self._ultimo_toque > SEGUNDOS_REINICIO
        acceso_abierto = self._acceso is not None and self._acceso.winfo_exists()
        if inactivo and not acceso_abierto and (self._abierta or self.buscador.get() or self._filtro != FILTROS[0]):
            self.buscador.delete(0, "end")
            self.selector.set(FILTROS[0])
            self._filtro = FILTROS[0]
            self._colorear_selector()
            self._actualizar()
        self.after(1000, self._ciclo)

    def cerrar(self):
        self.base.cerrar()
        self.destroy()


def main(argumentos=None):
    parser = argparse.ArgumentParser(description="Catálogo de aves del Observatorio")
    parser.add_argument("--pantalla-completa", action="store_true")
    parser.add_argument("--monitor", type=int, default=None, help="Número de monitor (1 = principal)")
    opciones = parser.parse_args(argumentos)
    preparar_base().cerrar()
    Catalogo(pantalla_completa=opciones.pantalla_completa, monitor=opciones.monitor).mainloop()


if __name__ == "__main__":
    main()
