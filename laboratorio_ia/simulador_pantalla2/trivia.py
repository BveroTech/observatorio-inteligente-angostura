import random
import customtkinter as ctk

from config.settings import PANTALLA_2
from src.aplicacion.gestor_audio import Reproductor, buscar_audio_especie
from src.aplicacion.gestor_monitores import listar_monitores
from src.aplicacion.puente_json import LectorAvesHoy
from src.persistencia.repositorio_sqlite import BaseDatos
from src.presentacion import tema_visual as T
from src.presentacion.ventana_kiosco import ALTO_BOTON, abrir_imagen, barra_degradado

SEGUNDOS_ENTRE_PREGUNTAS = 4
SEGUNDOS_REVISION_JSON = 3


class Trivia(ctk.CTkToplevel):
    def __init__(self, maestro, modo=PANTALLA_2):
        super().__init__(maestro, fg_color=T.FONDO_SUAVE)
        self.title("Trivia de cantos · " + T.TITULO)
        self.base = BaseDatos()
        self.lector = LectorAvesHoy()
        self.reproductor = Reproductor()
        self.protocol("WM_DELETE_WINDOW", self.cerrar)

        self.aciertos = 0
        self.intentos = 0
        self.pregunta = None
        self._ultima_especie = None
        self._esperando = False

        self._ubicar(modo)
        self._construir()
        self.after(300, self._revisar)

    def _ubicar(self, modo):
        monitores = listar_monitores(self)
        if modo == "auto" and len(monitores) >= 2:
            x, y, ancho, alto = monitores[1]
            self.geometry(f"{ancho}x{alto}+{x}+{y}")
            self.overrideredirect(True)
        else:
            self.geometry("1100x700+60+40")

    def _construir(self):
        barra_degradado(self, alto=6).pack(fill="x")
        encabezado = ctk.CTkFrame(self, fg_color=T.FONDO, corner_radius=0, height=96)
        encabezado.pack(fill="x")
        encabezado.pack_propagate(False)
        ctk.CTkLabel(
            encabezado, text="¿Qué ave es?", font=T.fuente_ctk(34, "bold"), text_color=T.TEXTO
        ).pack(side="left", padx=36)
        self.marcador = ctk.CTkLabel(
            encabezado, text="", font=T.fuente_ctk(20, "bold"), text_color=T.TEXTO,
            fg_color=T.ETIQUETA_INFO, corner_radius=20, height=44,
        )
        self.marcador.pack(side="right", padx=36)

        self.tarjeta = ctk.CTkFrame(self, fg_color=T.FONDO, corner_radius=24)
        self.tarjeta.pack(fill="both", expand=True, padx=48, pady=28)

        self.enunciado = ctk.CTkLabel(
            self.tarjeta, text="", font=T.fuente_ctk(26, "bold"), text_color=T.TEXTO, wraplength=900
        )
        self.enunciado.pack(pady=(36, 16))
        self.medio = ctk.CTkFrame(self.tarjeta, fg_color=T.FONDO)
        self.medio.pack(pady=8)

        self.opciones = ctk.CTkFrame(self.tarjeta, fg_color=T.FONDO)
        self.opciones.pack(pady=18)
        self.botones = []
        for indice in range(3):
            boton = ctk.CTkButton(
                self.opciones, text="", height=ALTO_BOTON + 16, width=300, corner_radius=30,
                font=T.fuente_ctk(20, "bold"), fg_color=T.ACENTO, hover_color=T.ACENTO_HOVER,
                text_color="#FFFFFF", command=lambda i=indice: self._responder(i),
            )
            boton.grid(row=0, column=indice, padx=12)
            self.botones.append(boton)

        self.retro = ctk.CTkLabel(self.tarjeta, text="", font=T.fuente_ctk(22, "bold"), text_color=T.TEXTO)
        self.retro.pack(pady=(6, 20))

        ctk.CTkLabel(
            self, text="Las preguntas salen de las aves que la cámara vio hoy en el embalse.",
            font=T.fuente_ctk(15), text_color=T.GRIS,
        ).pack(pady=(0, 18))
        self._actualizar_marcador()

    def _actualizar_marcador(self):
        self.marcador.configure(text=f"  Aciertos: {self.aciertos} de {self.intentos}  ")

    def _limpiar_medio(self):
        for widget in self.medio.winfo_children():
            widget.destroy()

    def _revisar(self):
        if not self.winfo_exists():
            return
        if self.pregunta is None and not self._esperando:
            self._nueva_pregunta()
        self.after(SEGUNDOS_REVISION_JSON * 1000, self._revisar)

    def _nueva_pregunta(self):
        self._esperando = False
        self.retro.configure(text="")
        especies = self.lector.leer().get("especies", [])
        if not especies:
            self.pregunta = None
            self._limpiar_medio()
            self.enunciado.configure(
                text="Todavía no se han avistado aves hoy.\nVuelve en un rato: apenas la cámara vea una, comenzará la trivia."
            )
            for boton in self.botones:
                boton.grid_remove()
            return

        candidatas = [e for e in especies if e["id_especie"] != self._ultima_especie] or especies
        correcta = random.choice(candidatas)
        self._ultima_especie = correcta["id_especie"]

        distractores = [e for e in especies if e["id_especie"] != correcta["id_especie"]]
        random.shuffle(distractores)
        distractores = [{"id_especie": e["id_especie"], "nombre_comun": e["nombre_comun"]} for e in distractores[:2]]
        if len(distractores) < 2:
            excluir = [d["id_especie"] for d in distractores]
            distractores += self.base.distractores(correcta["id_especie"], 2 - len(distractores), excluir=excluir)
        if len(distractores) < 2:
            self.pregunta = None
            return

        opciones = [correcta] + distractores[:2]
        random.shuffle(opciones)
        self.pregunta = {"correcta": correcta, "opciones": opciones, "respondida": False}

        ficha = self.base.especie(correcta["id_especie"]) or {}
        audio = buscar_audio_especie(correcta, ficha)
        self._limpiar_medio()
        if audio is not None and self.reproductor.puede_reproducir(audio):
            self.enunciado.configure(text="Escucha el canto: ¿qué ave es?")
            ctk.CTkButton(
                self.medio, text="▶  Escuchar el canto", height=ALTO_BOTON + 10, width=320, corner_radius=30,
                font=T.fuente_ctk(20, "bold"), fg_color=T.VERDE, hover_color=T.AZUL, text_color=T.TEXTO,
                command=lambda: self.reproductor.reproducir(audio),
            ).pack(pady=10)
            self.reproductor.reproducir(audio)
        else:
            imagen = abrir_imagen(correcta.get("ruta_foto") or ficha.get("ruta_foto"), (520, 300)) or abrir_imagen(
                correcta.get("ruta_captura"), (520, 300)
            )
            if imagen is not None:
                self.enunciado.configure(text="¿Qué ave es esta?")
                ctk.CTkLabel(self.medio, text="", image=imagen).pack()
            else:
                self.enunciado.configure(text="Lee la pista: ¿de qué ave se trata?")
                ctk.CTkLabel(
                    self.medio, text=ficha.get("caracteristicas") or ficha.get("habitat") or "",
                    font=T.fuente_ctk(22), text_color=T.TEXTO, wraplength=860, justify="center",
                ).pack(pady=10)

        for boton, opcion in zip(self.botones, opciones):
            boton.configure(text=opcion["nombre_comun"], fg_color=T.ACENTO, state="normal")
            boton.grid()

    def _responder(self, indice):
        if not self.pregunta or self.pregunta["respondida"]:
            return
        self.pregunta["respondida"] = True
        elegida = self.pregunta["opciones"][indice]
        correcta = self.pregunta["correcta"]
        self.intentos += 1
        if elegida["id_especie"] == correcta["id_especie"]:
            self.aciertos += 1
            self.retro.configure(text="¡Correcto!")
        else:
            self.retro.configure(text=f"Era {correcta['nombre_comun']}.")
        for boton, opcion in zip(self.botones, self.pregunta["opciones"]):
            if opcion["id_especie"] == correcta["id_especie"]:
                boton.configure(fg_color=T.VERDE, text_color_disabled=T.TEXTO)
            elif opcion is elegida:
                boton.configure(fg_color=T.NARANJA, text_color_disabled=T.TEXTO)
            boton.configure(state="disabled")
        self._actualizar_marcador()
        self.reproductor.detener()
        self._esperando = True
        self.after(SEGUNDOS_ENTRE_PREGUNTAS * 1000, self._siguiente)

    def _siguiente(self):
        if not self.winfo_exists():
            return
        self.pregunta = None
        self._nueva_pregunta()

    def cerrar(self):
        self.reproductor.detener()
        self.base.cerrar()
        self.destroy()
