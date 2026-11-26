"""Visor del catálogo. Las tarjetas se dibujan en una sola superficie Tk."""

import sys
import tkinter as tk
from tkinter import font as tkfont

import customtkinter as ctk

from src.presentacion import tema_visual as T
from src.presentacion.cache_imagenes import MINIATURA_CATALOGO
from src.presentacion.ventana_kiosco import color_conservacion, texto_uicn


class ListaCatalogo(ctk.CTkFrame):
    def __init__(self, padre, cache, abrir_ficha, mostrar_mas):
        super().__init__(padre, fg_color=T.FONDO, corner_radius=0, width=1, height=1)
        self.cache = cache
        self.abrir_ficha = abrir_ficha
        self.mostrar_mas = mostrar_mas
        self._especies = ()
        self._filas = ()
        self._restantes = 0
        self._mensaje = ""
        self._medida = None
        self._imagenes = []
        self._rangos_filas = []
        self._inicio = None
        self._arrastrando = False
        self._pulso = None
        self._destino = 0
        self._alto_total = 1

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.lienzo = tk.Canvas(self, bg=T.FONDO, bd=0, highlightthickness=0, width=1, height=1, yscrollincrement=1)
        self.lienzo.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        barra = ctk.CTkScrollbar(self, width=25, command=self.lienzo.yview)
        barra.grid(row=0, column=1, sticky="ns", padx=(1, 1), pady=6)
        self.lienzo.configure(yscrollcommand=barra.set)

        self.lienzo.bind("<Configure>", self._ajustar)
        self.lienzo.bind("<ButtonPress-1>", self._presionar)
        self.lienzo.bind("<B1-Motion>", self._mover)
        self.lienzo.bind("<ButtonRelease-1>", self._soltar)
        self.lienzo.bind("<MouseWheel>", self._rueda)
        if sys.platform.startswith("linux"):
            self.lienzo.bind("<Button-4>", self._rueda)
            self.lienzo.bind("<Button-5>", self._rueda)
        self.lienzo.bind("<Motion>", self._cursor)

    def mostrar(self, especies, vistas_hoy, restantes, mensaje=""):
        self._especies = tuple(especies)
        filas = []
        for e in especies:
            foto = self.cache.obtener(e.get("ruta_foto"), MINIATURA_CATALOGO) or self.cache.obtener(
                e.get("ultima_captura"), MINIATURA_CATALOGO,
            )
            detalle = " · ".join(v for v in (e.get("familia"), e.get("orden")) if v)
            veces = e.get("veces") if vistas_hoy else None
            if veces:
                detalle = f"Vista {veces} vez{'es' if veces != 1 else ''} hoy · {detalle}"
            filas.append((e["id_especie"], e["nombre_comun"], e["nombre_cientifico"], detalle,
                          e.get("conservacion_uicn"), foto))
        estado = (tuple(filas), restantes, mensaje)
        if estado != (self._filas, self._restantes, self._mensaje):
            self._filas, self._restantes, self._mensaje = estado
            self._dibujar()

    def ir_arriba(self):
        self._cancelar_gesto()
        self.lienzo.yview_moveto(0)

    def _ajustar(self, evento):
        medida = (evento.width, self._get_widget_scaling())
        if medida != self._medida:
            self._medida = medida
            self._dibujar()

    def _redondeado(self, x, y, ancho, alto, radio, **estilo):
        derecha, abajo = x + ancho, y + alto
        radio = min(radio, ancho / 2, alto / 2)
        return self.lienzo.create_polygon(
            x, y + radio, x, y, x + radio, y, derecha - radio, y, derecha, y, derecha, y + radio,
            derecha, abajo - radio, derecha, abajo, derecha - radio, abajo,
            x + radio, abajo, x, abajo, x, abajo - radio, smooth=True, **estilo,
        )

    @staticmethod
    def _recortar(texto, fuente, ancho):
        if fuente.measure(texto) <= ancho:
            return texto
        while texto and fuente.measure(texto + "…") > ancho:
            texto = texto[:-1]
        return texto.rstrip() + "…"

    def _dibujar(self):
        if self._medida is None:
            return
        lienzo = self.lienzo
        ancho, escala = self._medida
        if ancho < 100:
            return
        p = self._apply_widget_scaling
        # Los elementos del canvas comparten una única ventana nativa, incluso al desplazarse.
        origen = lienzo.canvasy(0)
        lienzo.delete("all")
        self._imagenes.clear()
        self._rangos_filas.clear()
        self._margen = round(p(10))
        self._fuentes = {
            clave: tkfont.Font(root=lienzo, family=T.FAMILIA, size=-round(p(tamano)), weight=peso, slant=inclinacion)
            for clave, tamano, peso, inclinacion in (
                ("titulo", 17, "bold", "roman"), ("cientifico", 13, "normal", "italic"),
                ("detalle", 13, "normal", "roman"), ("insignia", 11, "bold", "roman"),
                ("boton", 15, "bold", "roman"), ("mensaje", 18, "normal", "roman"),
            )
        }
        ancho_tarjeta = ancho - 2 * self._margen
        margen_vertical = round(p(7))
        y = margen_vertical
        for fila in self._filas:
            alto = self._dibujar_fila(fila, self._margen, y, ancho_tarjeta, escala)
            self._rangos_filas.append((y, y + alto, fila[0]))
            y += alto + 2 * margen_vertical
        fin = y - margen_vertical
        self._fin_filas = fin
        if self._restantes:
            margen = min(p(60), ancho / 5)
            self._dibujar_boton(margen, fin + p(14), ancho - 2 * margen, p(58),
                                f"Mostrar más especies ({self._restantes} restantes)", T.CRISTAL_ACCION)
            fin += p(96)
        elif self._mensaje:
            lienzo.create_text(ancho / 2, p(73), text=self._mensaje, font=self._fuentes["mensaje"],
                               fill=T.GRIS, width=ancho - p(30))
            fin = p(110)
        self._alto_total = max(1, round(fin))
        lienzo.configure(scrollregion=(0, 0, ancho, self._alto_total))
        lienzo.yview_moveto(max(0, origen) / self._alto_total)

    def _dibujar_fila(self, fila, x, y, ancho, escala):
        _, nombre, cientifico, detalle, estado, foto = fila
        lienzo, p = self.lienzo, self._apply_widget_scaling
        x_texto, x_boton = x + p(140), x + ancho - p(116)
        espacio = max(1, x_boton - x_texto - p(12))
        fuente_titulo = self._fuentes["titulo"]
        titulo = lienzo.create_text(
            x_texto, y + p(22), text=nombre, width=espacio, font=fuente_titulo, fill=T.CRISTAL_TEXTO, anchor="nw",
        )
        _, arriba, _, abajo = lienzo.bbox(titulo)
        alto_extra = max(0, abajo - arriba - fuente_titulo.metrics("linespace"))
        alto = round(p(145)) + alto_extra
        self._redondeado(x + 1, y + 1, ancho - 2, alto - 2, p(16), fill=T.CRISTAL,
                         outline=T.CRISTAL_BORDE, width=p(2))
        lienzo.create_line(x + p(16), y + p(7), x + ancho - p(16), y + p(7), fill=T.CRISTAL_REFLEJO, width=p(3))
        lienzo.tag_raise(titulo)
        ancho_foto, alto_foto = (p(n) for n in MINIATURA_CATALOGO)
        x_foto, y_foto = x + p(20), y + (alto - alto_foto) / 2
        self._redondeado(x_foto, y_foto, ancho_foto, alto_foto, p(12), fill=T.CRISTAL_REFLEJO, outline="")
        centro_foto = (x_foto + ancho_foto / 2, y_foto + alto_foto / 2)
        if foto is not None:
            imagen_tk = foto.create_scaled_photo_image(escala, "light")
            self._imagenes.append(imagen_tk)
            lienzo.create_image(*centro_foto, image=imagen_tk)
        else:
            lienzo.create_text(*centro_foto, text="Sin foto", font=self._fuentes["detalle"], fill=T.CRISTAL_TEXTO)
        for clave, valor, dy in (("cientifico", cientifico, 61), ("detalle", detalle, 89)):
            fuente = self._fuentes[clave]
            texto = self._recortar(valor, fuente, espacio)
            lienzo.create_text(x_texto, y + p(dy) + alto_extra, text=texto, font=fuente, fill=T.GRIS, anchor="w")
        if uicn := texto_uicn(estado):
            fuente = self._fuentes["insignia"]
            texto = self._recortar(uicn, fuente, max(1, espacio - p(16)))
            relleno = T.mezclar(color_conservacion(estado), T.CRISTAL_REFLEJO, 0.35)
            self._redondeado(x_texto, y + p(106) + alto_extra, fuente.measure(texto) + p(16), p(27), p(12),
                             fill=relleno, outline=T.CRISTAL_BORDE, width=p(2))
            lienzo.create_text(x_texto + p(8), y + p(119) + alto_extra, text=texto,
                               font=fuente, fill=T.CRISTAL_TEXTO, anchor="w")
        self._dibujar_boton(x_boton, y + (alto - p(48)) / 2, p(100), p(48), "Ver ficha →", T.CRISTAL)
        return alto

    def _dibujar_boton(self, x, y, ancho, alto, texto, color):
        p = self._apply_widget_scaling
        self._redondeado(x, y, ancho, alto, p(12), fill=color, activefill=T.CRISTAL_HOVER,
                         outline=T.CRISTAL_BORDE, width=p(2))
        self.lienzo.create_text(x + ancho / 2, y + alto / 2, text=texto, fill=T.CRISTAL_TEXTO, font=self._fuentes["boton"])

    def _objetivo(self, evento):
        if self._medida is None or self._medida[0] < 100 or not self._filas:
            return None
        x, y = evento.x, self.lienzo.canvasy(evento.y)
        ancho = self._medida[0]
        if self._margen <= x < ancho - self._margen:
            for arriba, abajo, id_especie in self._rangos_filas:
                if arriba <= y < abajo:
                    return id_especie
        fin = self._fin_filas
        margen = min(self._apply_widget_scaling(60), ancho / 5)
        arriba = fin + self._apply_widget_scaling(14)
        abajo = fin + self._apply_widget_scaling(72)
        if self._restantes and margen <= x < ancho - margen and arriba <= y < abajo:
            return "mas"
        return None

    def _cursor(self, evento):
        cursor = "hand2" if self._objetivo(evento) is not None else ""
        if self.lienzo.cget("cursor") != cursor:
            self.lienzo.configure(cursor=cursor)

    def _presionar(self, evento):
        self._cancelar_gesto()
        self._inicio = (evento.x_root, evento.y_root, self.lienzo.canvasy(0), self._objetivo(evento))

    def _mover(self, evento):
        if self._inicio is None:
            return
        _, y, origen, _ = self._inicio
        distancia = y - evento.y_root
        if self._arrastrando or abs(distancia) > self._apply_widget_scaling(8):
            self._arrastrando = True
            self._destino = (origen + distancia) / self._alto_total
            if self._pulso is None:
                self._pulso = self.after(16, self._desplazar)

    def _desplazar(self):
        self._pulso = None
        self.lienzo.yview_moveto(self._destino)

    def _soltar(self, evento):
        if self._inicio is None:
            return
        x, _, _, objetivo = self._inicio
        self._mover(evento)
        arrastrando = self._arrastrando
        self._cancelar_gesto()
        if arrastrando:
            self._desplazar()
        elif (
            objetivo is not None and abs(x - evento.x_root) <= self._apply_widget_scaling(8)
            and objetivo == self._objetivo(evento)
        ):
            if objetivo == "mas":
                self.mostrar_mas()
            else:
                especie = next(e for e in self._especies if e["id_especie"] == objetivo)
                self.abrir_ficha(especie)

    def _rueda(self, evento):
        if evento.num in (4, 5):
            distancia = -48 if evento.num == 4 else 48
        else:
            distancia = -evento.delta * (1 if sys.platform == "darwin" else 0.4)
        self.lienzo.yview_scroll(round(self._apply_widget_scaling(distancia)), "units")
        self.winfo_toplevel().event_generate("<<ToqueVisitante>>")
        return "break"

    def _cancelar_gesto(self):
        if self._pulso is not None:
            self.after_cancel(self._pulso)
            self._pulso = None
        self._inicio = None
        self._arrastrando = False

    def destroy(self):
        self._cancelar_gesto()
        super().destroy()
