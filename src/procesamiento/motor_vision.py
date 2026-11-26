import queue
import threading
import time
from datetime import datetime
from itertools import product
from uuid import uuid4

import cv2
import numpy as np
from PIL import Image, ImageDraw

from config.settings import (
    CARPETA_CAPTURAS,
    CARPETA_POR_IDENTIFICAR,
    CUADROS_PARA_CONFIRMAR,
    GUARDAR_AVES_DESCONOCIDAS,
    MAXIMO_DESCONOCIDAS_DIA,
    SEGUNDOS_ENTRE_AVISTAMIENTOS,
    SEGUNDOS_ENTRE_DESCONOCIDAS,
    SEGUNDOS_ENTRE_METRICAS,
    SEGUNDOS_SIN_VER_TRACK,
    VENTANA_CONFIRMACION,
)
from src.aplicacion.puente_json import publicar_aves_hoy
from src.persistencia.repositorio_sqlite import BaseDatos, ruta_relativa
from src.presentacion import tema_visual as tema
from src.procesamiento.seguimiento import Seguidor

SEGUNDOS_REVISION_DATOS = 1


class CatalogoEnMemoria:
    def __init__(self, base):
        self.base = base
        self._por_cientifico = {}
        self._version = None
        self.actualizar()

    def actualizar(self):
        version = self.base.version_datos()
        if version == self._version:
            return False
        self._por_cientifico = {
            fila["nombre_cientifico"].casefold(): fila for fila in self.base.especies(solo_activas=True)
        }
        self._version = version
        return True

    def buscar(self, nombre_cientifico):
        return self._por_cientifico.get((nombre_cientifico or "").casefold())


class Motor(threading.Thread):
    def __init__(self, fuente, crear_identificador, ruta_base=None):
        super().__init__(daemon=True, name="inferencia")
        self.fuente = fuente
        self._crear_identificador = crear_identificador
        self._ruta_base = ruta_base
        self._detener = threading.Event()
        self._candado = threading.Lock()

        self.eventos = queue.Queue()
        self.error = None
        self.listo = threading.Event()
        self.modo = ""
        self.especies_reconocibles = []

        # Recuadros y etiquetas del último análisis. El video se dibuja aparte
        # (PreparadorVideo) a la velocidad de la fuente, con estas capas encima,
        # para que la imagen no quede limitada a la velocidad de la IA.
        self._capas = []
        self._tamano_capas = None
        self._id_imagen = 0
        self._estado = {"fps": 0.0, "ms": 0.0, "aves": 0, "es_simulacion": False}

        self._fuentes = {}

    def detener(self):
        self._detener.set()

    def capas_actuales(self):
        """(id, (alto, ancho) del cuadro analizado, capas a dibujar, estado)."""
        with self._candado:
            return self._id_imagen, self._tamano_capas, self._capas, dict(self._estado)

    def run(self):
        base = None
        try:
            base = BaseDatos(self._ruta_base)
            try:
                catalogo = CatalogoEnMemoria(base)
                self.identificador = self._crear_identificador(catalogo.buscar)
                self.modo = self.identificador.modo
                self.especies_reconocibles = self.identificador.especies_reconocibles()
            except Exception as error:
                self.error = str(error)
                self.listo.set()
                self._bucle_sin_modelo(base)
                return
            self.listo.set()

            seguidor = Seguidor(
                segundos_sin_ver=SEGUNDOS_SIN_VER_TRACK,
                ventana=VENTANA_CONFIRMACION, confirmaciones=CUADROS_PARA_CONFIRMAR,
            )
            registros = {}
            ultimo_visto_evento = {}
            ultimo_id = 0
            generacion_anterior = None
            dia = None
            revisar_datos = 0.0
            metricas = self._metricas_vacias()
            inicio_ventana = time.monotonic()
            fps_suave = 0.0
            ultimo_cuadro = None

            while not self._detener.is_set():
                ahora = time.monotonic()
                if ahora - inicio_ventana >= SEGUNDOS_ENTRE_METRICAS:
                    self._guardar_metricas(base, metricas, ahora - inicio_ventana)
                    metricas = self._metricas_vacias()
                    inicio_ventana = ahora

                if ahora >= revisar_datos:
                    revisar_datos = ahora + SEGUNDOS_REVISION_DATOS
                    dia_actual = datetime.now().date()
                    cambio_catalogo = catalogo.actualizar()
                    if dia_actual != dia:
                        dia = dia_actual
                        seguidor.pistas.clear()
                        registros.clear()
                        ultimo_visto_evento.clear()
                        self._publicar_hoy(base)
                    elif cambio_catalogo:
                        self._depurar_registros(base, seguidor, registros)
                        self._publicar_hoy(base)
                    if cambio_catalogo:
                        self.especies_reconocibles = self.identificador.especies_reconocibles()

                id_cuadro, cuadro, es_simulacion, generacion = self.fuente.ultimo_cuadro(despues_de=ultimo_id)
                if cuadro is None or id_cuadro == ultimo_id:
                    time.sleep(0.005)
                    continue
                ultimo_id = id_cuadro
                if generacion != generacion_anterior:
                    # Un corte no puede aportar votos a las pistas del tramo anterior.
                    seguidor.pistas.clear()
                    ultimo_cuadro = None
                    fps_suave = 0.0
                    generacion_anterior = generacion

                try:
                    detecciones, estadisticas = self.identificador.procesar(cuadro)
                except Exception as error:
                    seguidor.actualizar((), time.monotonic())
                    self.error = f"Error de inferencia: {error}"
                    time.sleep(0.5)
                    continue
                self.error = None

                metricas["cuadros"] += 1
                metricas["ms"].append(estadisticas["ms"])
                metricas["detecciones"] += estadisticas["candidatas"]
                metricas["descartes_px"] += estadisticas["descartes_px"]
                metricas["descartes_confianza"] += estadisticas["descartes_confianza"]

                self._procesar_detecciones(
                    base, seguidor, cuadro, detecciones, es_simulacion, registros, ultimo_visto_evento,
                )

                capas = self._capas_de(detecciones)
                duracion = time.monotonic() - (ultimo_cuadro or time.monotonic())
                ultimo_cuadro = time.monotonic()
                if duracion > 0:
                    fps_suave = 0.9 * fps_suave + 0.1 * (1.0 / duracion) if fps_suave else 1.0 / duracion
                with self._candado:
                    self._capas = capas
                    self._tamano_capas = cuadro.shape[:2]
                    self._id_imagen += 1
                    self._estado = {
                        "fps": fps_suave,
                        "ms": estadisticas["ms"],
                        "aves": sum(1 for d in detecciones if d["estado"] != "pequena"),
                        "es_simulacion": es_simulacion,
                    }

            self._guardar_metricas(base, metricas, time.monotonic() - inicio_ventana)
        except Exception as error:
            self.error = f"Error inesperado en motor de visión: {error}"
        finally:
            self.listo.set()
            if base is not None:
                base.cerrar()

    def _bucle_sin_modelo(self, base):
        ultimo_id = 0
        inicio = time.monotonic()
        metricas = self._metricas_vacias()
        ultimo_estado = None
        revisar_datos = 0.0
        while not self._detener.is_set():
            ahora = time.monotonic()
            if ahora - inicio >= SEGUNDOS_ENTRE_METRICAS:
                self._guardar_metricas(base, metricas, ahora - inicio)
                metricas, inicio = self._metricas_vacias(), ahora
            if ahora >= revisar_datos:
                revisar_datos = ahora + SEGUNDOS_REVISION_DATOS
                estado = (datetime.now().date(), base.version_datos())
                if estado != ultimo_estado:
                    ultimo_estado = estado
                    self._publicar_hoy(base)
            id_cuadro, cuadro, es_simulacion, _ = self.fuente.ultimo_cuadro(despues_de=ultimo_id)
            if cuadro is None or id_cuadro == ultimo_id:
                time.sleep(0.01)
                continue
            ultimo_id = id_cuadro
            metricas["cuadros"] += 1
            with self._candado:
                self._capas = []
                self._tamano_capas = cuadro.shape[:2]
                self._id_imagen += 1
                self._estado["es_simulacion"] = es_simulacion

    # ------------------------------------------------------

    @staticmethod
    def _metricas_vacias():
        return {"cuadros": 0, "ms": [], "detecciones": 0, "descartes_px": 0, "descartes_confianza": 0}

    def _guardar_metricas(self, base, metricas, segundos):
        try:
            base.registrar_metrica(
                self.fuente.estado,
                fps_promedio=round(metricas["cuadros"] / segundos, 2) if segundos > 0 else 0.0,
                inferencia_ms_promedio=round(float(np.mean(metricas["ms"])), 2) if metricas["ms"] else None,
                inferencia_ms_maximo=round(float(np.max(metricas["ms"])), 2) if metricas["ms"] else None,
                total_detecciones=metricas["detecciones"],
                total_descartes_px=metricas["descartes_px"],
                total_descartes_confianza=metricas["descartes_confianza"],
            )
        except Exception as error:
            print("No se pudieron guardar las métricas:", error)

    @staticmethod
    def _depurar_registros(base, seguidor, registros):
        ids = {id_avistamiento for _, id_avistamiento in registros.values()}
        ids.update(p["id_avistamiento"] for p in seguidor.pistas.values() if p["id_avistamiento"] is not None)
        vigentes = base.ids_avistamientos_existentes(ids)
        for clave in [clave for clave, (_, id_) in registros.items() if id_ not in vigentes]:
            del registros[clave]
        for pista in seguidor.pistas.values():
            if pista["id_avistamiento"] not in vigentes:
                pista["id_avistamiento"] = None
                pista.pop("miniatura", None)

    def _procesar_detecciones(self, base, seguidor, cuadro, detecciones, es_simulacion, registros, ultimo_visto):
        ahora = time.monotonic()
        observadas = [d for d in detecciones if d["estado"] != "pequena"]
        ids = seguidor.actualizar([d["caja"] for d in observadas], ahora)
        for deteccion, id_pista in zip(observadas, ids):
            pista = seguidor.pistas[id_pista]
            deteccion["pista"] = pista
            especie = deteccion["especie"] if deteccion["estado"] == "identificada" else None
            id_especie = especie["id_especie"] if especie is not None else None
            if not seguidor.observar(id_pista, id_especie):
                self._revisar_desconocida(base, cuadro, deteccion, pista, es_simulacion, ahora)
                continue
            clave = (id_especie, es_simulacion)
            ultimo_registro, _ = registros.get(clave, (-float("inf"), None))
            if pista["especie_registrada"] is None and ahora - ultimo_registro >= SEGUNDOS_ENTRE_AVISTAMIENTOS:
                if ahora - pista.get("ultimo_intento", -float("inf")) < 1.0:
                    continue
                pista["ultimo_intento"] = ahora
                registro = self._registrar(base, cuadro, deteccion, especie, es_simulacion, id_pista)
                if registro is not None:
                    pista["especie_registrada"] = id_especie
                    pista["id_avistamiento"] = registro["id_avistamiento"]
                    pista["miniatura"] = registro["miniatura"]
                    registros[clave] = (ahora, registro["id_avistamiento"])
                    ultimo_visto[clave] = ahora
                    self.eventos.put(registro)
                    self._publicar_hoy(base)
                continue
            if pista["especie_registrada"] is not None and pista["id_avistamiento"] is None:
                # La eliminación administrativa no vuelve a publicar la misma pista.
                continue
            if ahora - ultimo_visto.get(clave, -float("inf")) >= 1.0:
                ultimo_visto[clave] = ahora
                evento = {
                    "tipo": "visto", "id_especie": id_especie, "id_pista": id_pista,
                    "confianza": deteccion["confianza"], "nombre_cientifico": especie["nombre_cientifico"],
                }
                if pista["id_avistamiento"] is not None:
                    evento["id_avistamiento"] = pista["id_avistamiento"]
                    evento["miniatura"] = pista["miniatura"]
                self.eventos.put(evento)

    # ------------------------------------------------------
    # Aves por identificar
    # ------------------------------------------------------

    def _revisar_desconocida(self, base, cuadro, deteccion, pista, es_simulacion, ahora):
        """Guarda una vez por pista el mejor recorte de un ave que el modelo no reconoce.

        Cuenta como desconocida si en la ventana de confirmación la mayoría de los
        cuadros no reconoció especie (confianza bajo el umbral o especie sin ficha).
        Se guarda el recorte más grande visto, para que se pueda identificar a ojo
        y sirva como foto de entrenamiento.
        """
        if not GUARDAR_AVES_DESCONOCIDAS or deteccion["estado"] not in ("baja_confianza", "sin_ficha"):
            return
        if pista.get("por_identificar") or pista["especie_registrada"] is not None:
            return
        pista["desconocida"] = pista.get("desconocida", 0) + 1
        x1, y1, x2, y2 = deteccion["caja"]
        area = (x2 - x1) * (y2 - y1)
        if area > pista.get("mejor_area", 0):
            alto, ancho = cuadro.shape[:2]
            margen_x, margen_y = round((x2 - x1) * 0.15), round((y2 - y1) * 0.15)
            recorte = cuadro[max(0, y1 - margen_y):min(alto, y2 + margen_y), max(0, x1 - margen_x):min(ancho, x2 + margen_x)]
            pista["mejor_area"] = area
            pista["mejor_recorte"] = recorte.copy()
            pista["mejor_datos"] = {
                "motivo": "sin_ficha" if deteccion["estado"] == "sin_ficha" else "baja_confianza",
                "clase": deteccion.get("clase"), "confianza": deteccion["confianza"],
                "ancho": x2 - x1, "alto": y2 - y1,
            }
        if pista["desconocida"] < CUADROS_PARA_CONFIRMAR or pista["votos"].count(None) < CUADROS_PARA_CONFIRMAR:
            return
        if ahora - getattr(self, "_ultima_desconocida", -float("inf")) < SEGUNDOS_ENTRE_DESCONOCIDAS:
            return
        hoy = datetime.now().strftime("%Y-%m-%d")
        if getattr(self, "_desconocidas_hoy", (None, 0))[0] != hoy:
            try:
                self._desconocidas_hoy = (hoy, base.contar_por_identificar(estado=None, desde=hoy))
            except Exception:
                self._desconocidas_hoy = (hoy, 0)
        if self._desconocidas_hoy[1] >= MAXIMO_DESCONOCIDAS_DIA:
            return
        self._ultima_desconocida = ahora
        pista["por_identificar"] = True
        datos = pista.pop("mejor_datos")
        recorte = pista.pop("mejor_recorte")
        momento = datetime.now()
        archivo = None
        try:
            carpeta = CARPETA_POR_IDENTIFICAR / momento.strftime("%Y-%m-%d")
            carpeta.mkdir(parents=True, exist_ok=True)
            lado = max(recorte.shape[:2])
            if lado > 800:
                escala = 800 / lado
                recorte = cv2.resize(recorte, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
            correcto, codificado = cv2.imencode(".jpg", recorte, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not correcto:
                return
            archivo = carpeta / f"desc_{momento:%H%M%S}_{uuid4().hex[:8]}.jpg"
            archivo.write_bytes(codificado.tobytes())
            base.registrar_por_identificar(
                archivo, datos["motivo"], datos["clase"], datos["confianza"], datos["ancho"], datos["alto"],
                es_simulacion=es_simulacion, momento=momento,
            )
            self._desconocidas_hoy = (hoy, self._desconocidas_hoy[1] + 1)
        except Exception as error:
            print("No se pudo guardar el ave por identificar:", error)
            if archivo is not None:
                archivo.unlink(missing_ok=True)

    @staticmethod
    def _publicar_hoy(base):
        # Puente de compatibilidad para el simulador. SQLite es la fuente principal.
        try:
            publicar_aves_hoy(base.especies_del_dia())
        except Exception as error:
            print("No se pudo actualizar el puente de avistamientos:", error)

    def _registrar(self, base, cuadro, deteccion, especie, es_simulacion, id_pista):
        momento = datetime.now()
        id_especie = especie["id_especie"]
        archivo = self._guardar_miniatura(cuadro, deteccion["caja"], id_especie, momento)
        ruta = ruta_relativa(archivo)
        id_avistamiento = None
        try:
            id_avistamiento = base.registrar_avistamiento(
                id_especie, deteccion["confianza"], deteccion["ancho"], deteccion["alto"],
                es_simulacion=es_simulacion, ruta_thumb=ruta, momento=momento,
                nombre_cientifico=especie["nombre_cientifico"],
            )
        except Exception as error:
            print("No se pudo registrar el avistamiento:", error)
        if id_avistamiento is None:
            if archivo is not None:
                try:
                    archivo.unlink(missing_ok=True)
                except OSError as error:
                    print("No se pudo retirar el recorte sin registro:", error)
            return None
        return {
            "tipo": "nuevo", "id_especie": id_especie, "id_avistamiento": id_avistamiento, "id_pista": id_pista,
            "nombre": especie["nombre_comun"], "confianza": deteccion["confianza"], "miniatura": ruta,
            "nombre_cientifico": especie["nombre_cientifico"],
            "hora": momento.strftime("%H:%M"),
        }

    @staticmethod
    def _guardar_miniatura(cuadro, caja, id_especie, momento):
        ruta = None
        try:
            x1, y1, x2, y2 = caja
            recorte = cuadro[y1:y2, x1:x2]
            if recorte.size == 0:
                return None
            escala = min(1.0, 320 / recorte.shape[1])
            if escala < 1.0:
                tamano = (320, max(1, round(recorte.shape[0] * escala)))
                recorte = cv2.resize(recorte, tamano, interpolation=cv2.INTER_AREA)
            correcto, datos = cv2.imencode(".jpg", recorte, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not correcto:
                return None
            carpeta = CARPETA_CAPTURAS / momento.strftime("%Y-%m-%d")
            carpeta.mkdir(parents=True, exist_ok=True)
            ruta = carpeta / f"sp{id_especie:03d}_{momento:%H%M%S}_{uuid4().hex}.jpg"
            datos.tofile(str(ruta))
            return ruta
        except (OSError, cv2.error) as error:
            print("No se pudo guardar el recorte del ave:", error)
            if ruta is not None:
                try:
                    ruta.unlink(missing_ok=True)
                except OSError:
                    pass
            return None

    @staticmethod
    def _capas_de(detecciones):
        """Recuadros y etiquetas a dibujar, en píxeles del cuadro analizado."""
        capas = []
        for deteccion in detecciones:
            estado = deteccion["estado"]
            if estado in ("pequena", "baja_confianza"):
                capas.append({"caja": deteccion["caja"], "color": tema.CAJA_DESCARTADA, "grosor": 1, "texto": None})
                continue
            if estado == "identificada" and deteccion["pista"]["confirmada"] == deteccion["especie"]["id_especie"]:
                color = tema.CAJA_IDENTIFICADA
                texto = f"{deteccion['especie']['nombre_comun']} {deteccion['confianza'] * 100:.0f} %"
            elif estado == "identificada":
                color, texto = tema.CAJA_IDENTIFICANDO, "Identificando…"
            elif estado == "sin_ficha":
                color, texto = tema.CAJA_SIN_FICHA, "Ave sin ficha"
            else:
                color, texto = tema.CAJA_IDENTIFICANDO, "Ave"
            capas.append({"caja": deteccion["caja"], "color": color, "grosor": 3, "texto": texto})
        return capas

    def _fuente(self, tamano):
        if tamano not in self._fuentes:
            self._fuentes[tamano] = tema.fuente_pil(tamano)
        return self._fuentes[tamano]

    def dibujar_capas(self, imagen, capas, escala=1.0, desplazamiento=(0, 0), clave=None):
        """Dibuja las capas sobre una imagen PIL ya escalada (y recortada en desplazamiento).

        Ubicar y dibujar etiquetas cuesta ~20 ms con varias aves; como las capas solo
        cambian cuando la IA termina un análisis, el plan (recuadros + etiquetas ya
        dibujadas) se calcula una vez por `clave` y en cada cuadro de video solo se pega.
        """
        if not capas:
            return imagen
        llave = (clave, imagen.size, round(escala, 4), tuple(desplazamiento))
        if clave is None or getattr(self, "_plan", (None,))[0] != llave:
            self._plan = (llave, self._planificar(capas, imagen.size, escala, desplazamiento))
        cajas, etiquetas = self._plan[1]
        dibujo = ImageDraw.Draw(imagen)
        for caja, color, grosor in cajas:
            dibujo.rectangle(caja, outline=color, width=grosor)
        for etiqueta, posicion in etiquetas:
            imagen.paste(etiqueta, posicion)
        return imagen

    def _planificar(self, capas, tamano, escala, desplazamiento):
        dx, dy = desplazamiento
        ancho, alto = tamano
        fuente = self._fuente(max(10, round(18 * escala)))
        dibujo = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        cajas, pendientes = [], []
        for capa in capas:
            x1, y1, x2, y2 = capa["caja"]
            caja = (round(x1 * escala) - dx, round(y1 * escala) - dy, round(x2 * escala) - dx, round(y2 * escala) - dy)
            grosor = max(1, round(capa["grosor"] * max(escala, 0.67)))
            cajas.append(((caja[0], caja[1], caja[2] - 1, caja[3] - 1), capa["color"], grosor))
            if capa["texto"]:
                pendientes.append((caja, capa["color"], capa["texto"], capa["color"] == tema.CAJA_IDENTIFICADA))

        etiquetas, ocupadas = [], []
        relleno_x, relleno_y = max(4, round(7 * escala)), max(3, round(5 * escala))
        for caja, color, texto, _ in sorted(pendientes, key=lambda e: e[3], reverse=True):
            izquierda, arriba, derecha, abajo = dibujo.textbbox((0, 0), texto, font=fuente)
            if derecha - izquierda + 2 * relleno_x > ancho:
                texto = self._recortar_texto(dibujo, texto, ancho - 2 * relleno_x, fuente)
                if not texto:
                    continue
                izquierda, arriba, derecha, abajo = dibujo.textbbox((0, 0), texto, font=fuente)
            medida = (derecha - izquierda + 2 * relleno_x, abajo - arriba + 2 * relleno_y)
            posicion = self._ubicar_etiqueta(caja, medida, (ancho, alto), ocupadas)
            if posicion is None:
                continue
            ocupadas.append(posicion)
            etiqueta = Image.new("RGB", medida, color)
            ImageDraw.Draw(etiqueta).text((relleno_x - izquierda, relleno_y - arriba), texto,
                                          fill=tema.TEXTO_ETIQUETA, font=fuente)
            etiquetas.append((etiqueta, (posicion[0], posicion[1])))
        return cajas, etiquetas

    def _recortar_texto(self, dibujo, texto, ancho_maximo, fuente):
        while texto:
            texto = texto[:-1].rstrip()
            candidata = texto + "…"
            x1, _, x2, _ = dibujo.textbbox((0, 0), candidata, font=fuente)
            if x2 - x1 <= ancho_maximo:
                return candidata
        return ""

    @staticmethod
    def _ubicar_etiqueta(caja, medida, tamano_imagen, ocupadas):
        ancho, alto = medida
        limite_x, limite_y = tamano_imagen[0] - ancho, tamano_imagen[1] - alto
        if limite_x < 0 or limite_y < 0:
            return None
        x1, y1, x2, y2 = caja
        preferido = (x1, y1 - alto) if y1 >= alto else (x1, y1)
        xs = {0, x1, x2 - ancho, limite_x}
        ys = {0, y1, y1 - alto, y2, limite_y}
        for izquierda, arriba, derecha, abajo in ocupadas:
            xs.update((izquierda - ancho, derecha))
            ys.update((arriba - alto, abajo))
        xs = {min(limite_x, max(0, x)) for x in xs}
        ys = {min(limite_y, max(0, y)) for y in ys}
        candidatos = sorted(product(xs, ys), key=lambda xy: (
            abs(xy[0] - preferido[0]) + abs(xy[1] - preferido[1]), xy[1], xy[0],
        ))
        for x, y in candidatos:
            if all(x + ancho <= a or x >= c or y + alto <= b or y >= d for a, b, c, d in ocupadas):
                return x, y, x + ancho, y + alto
        return None
