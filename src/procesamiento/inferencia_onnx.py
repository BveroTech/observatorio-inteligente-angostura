import ast
import csv
import json
import logging
import math
import os
import re
import time
import unicodedata
from pathlib import Path

import cv2
import numpy as np

from config.settings import (
    ARCHIVO_CATALOGO,
    ARCHIVO_CLASES_MODELO,
    CARPETA_CACHE_TENSORRT,
    HILOS_IA,
    MODELO_CLASIFICADOR,
    MODELO_DETECTOR,
    TAMANO_ENTRADA_DETECTOR,
    TAMANO_MINIMO_PX,
    UMBRAL_CONFIANZA,
    UMBRAL_DETECCION_AVE,
    UMBRAL_IOA_CONTENCION,
    UMBRAL_IOU_NMS,
    USAR_TENSORRT,
    TENSORRT_FP16,
    obtener_ruta_recurso,
)

CLASE_AVE_COCO = "bird"
registro = logging.getLogger("observatorio.ia")


def _descartar_recortes_duplicados(detecciones, umbral=UMBRAL_IOA_CONTENCION):
    """Suprime la caja menor cuando una caja fiable cubre más de su IoA."""
    estados_validos = ("identificada", "sin_ficha", "ave")
    orden = sorted(
        (i for i, d in enumerate(detecciones) if d["estado"] in estados_validos),
        key=lambda i: (detecciones[i]["confianza"], detecciones[i]["ancho"] * detecciones[i]["alto"]),
        reverse=True,
    )
    conservadas = []
    descartadas = set()
    for indice in orden:
        deteccion = detecciones[indice]
        area = deteccion["ancho"] * deteccion["alto"]
        x1, y1, x2, y2 = deteccion["caja"]
        for area_mayor, confianza, caja in conservadas:
            if area >= area_mayor or deteccion["confianza"] >= confianza:
                continue
            a1, b1, a2, b2 = caja
            interseccion = max(0, min(x2, a2) - max(x1, a1)) * max(0, min(y2, b2) - max(y1, b1))
            if interseccion > area * umbral:
                descartadas.add(indice)
                break
        else:
            conservadas.append((area, deteccion["confianza"], deteccion["caja"]))
    return [d for indice, d in enumerate(detecciones) if indice not in descartadas]


def clave_clase(nombre):
    """'Pato jergón-grande' -> 'patojergongrande'."""
    texto = unicodedata.normalize("NFKD", str(nombre).lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", texto)


def proveedores_disponibles():
    """Proveedores de ONNX Runtime en orden de preferencia, con sus opciones.

    Jetson (onnxruntime-gpu): TensorRT -> CUDA -> CPU. Windows: CUDA o DirectML si
    están instalados -> CPU. TensorRT guarda el motor compilado en
    CARPETA_CACHE_TENSORRT para no recompilarlo en cada arranque.
    """
    import onnxruntime as ort

    disponibles = ort.get_available_providers()
    lista = []
    if USAR_TENSORRT and "TensorrtExecutionProvider" in disponibles:
        CARPETA_CACHE_TENSORRT.mkdir(parents=True, exist_ok=True)
        lista.append(("TensorrtExecutionProvider", {
            "trt_engine_cache_enable": True,
            "trt_engine_cache_path": str(CARPETA_CACHE_TENSORRT),
            "trt_fp16_enable": bool(TENSORRT_FP16),
        }))
    for nombre in ("CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"):
        if nombre in disponibles:
            lista.append(nombre)
    return lista or disponibles


def _nombre_proveedor(proveedor):
    return proveedor[0] if isinstance(proveedor, tuple) else proveedor


def crear_sesion(ruta, opciones):
    """Sesión ONNX con el mejor proveedor que funcione; si uno falla al iniciar, prueba el siguiente."""
    import onnxruntime as ort

    proveedores = proveedores_disponibles()
    ultimo_error = None
    for inicio in range(len(proveedores)):
        candidatos = proveedores[inicio:]
        try:
            sesion = ort.InferenceSession(ruta, sess_options=opciones, providers=candidatos)
        except Exception as error:  # p. ej. TensorRT sin sus bibliotecas
            ultimo_error = error
            registro.warning("No se pudo usar %s (%s); se prueba el siguiente proveedor.",
                             _nombre_proveedor(candidatos[0]), error)
            continue
        registro.info("Modelo %s · proveedor en uso: %s (disponibles: %s)", Path(ruta).name,
                      sesion.get_providers()[0], ", ".join(_nombre_proveedor(p) for p in proveedores))
        return sesion
    raise RuntimeError(f"No se pudo abrir {ruta} con ningún proveedor de ONNX Runtime: {ultimo_error}")


def _nombres_de_metadatos(sesion):
    metadatos = sesion.get_modelmeta().custom_metadata_map
    texto = metadatos.get("names")
    if not texto:
        return {}
    try:
        nombres = ast.literal_eval(texto)
    except (ValueError, SyntaxError):
        return {}
    if isinstance(nombres, list):
        nombres = dict(enumerate(nombres))
    return {int(k): str(v) for k, v in nombres.items()} if isinstance(nombres, dict) else {}


def _tensor_rgb(imagen):
    rgb = cv2.cvtColor(imagen, cv2.COLOR_BGR2RGB)
    return np.ascontiguousarray(rgb.transpose(2, 0, 1)[None], dtype=np.float32) / np.float32(255)


class ModeloONNX:
    def __init__(self, ruta):
        import onnxruntime as ort

        self.ruta = str(obtener_ruta_recurso(ruta))
        opciones = ort.SessionOptions()
        hilos = int(os.environ.get("OBSERVATORIO_HILOS_IA") or HILOS_IA or 0)
        if hilos > 0:
            # Deja núcleos libres para mostrar el video a FPS_VIDEO mientras la IA analiza.
            opciones.intra_op_num_threads = hilos
        self.sesion = crear_sesion(self.ruta, opciones)
        entrada = self.sesion.get_inputs()[0]
        self.nombre_entrada = entrada.name
        forma = entrada.shape
        self.alto_entrada = forma[2] if isinstance(forma[2], int) else None
        self.ancho_entrada = forma[3] if isinstance(forma[3], int) else None
        self.nombres = _nombres_de_metadatos(self.sesion)
        self.proveedor = self.sesion.get_providers()[0]

    def ejecutar(self, tensor):
        return self.sesion.run(None, {self.nombre_entrada: tensor})[0]


class Detector(ModeloONNX):
    def __init__(self, ruta, tamano=TAMANO_ENTRADA_DETECTOR):
        super().__init__(ruta)
        self.alto = self.alto_entrada or tamano
        self.ancho = self.ancho_entrada or tamano

    def _letterbox(self, imagen):
        alto, ancho = imagen.shape[:2]
        escala = min(self.alto / alto, self.ancho / ancho)
        nuevo_ancho, nuevo_alto = max(1, round(ancho * escala)), max(1, round(alto * escala))
        redimensionada = cv2.resize(imagen, (nuevo_ancho, nuevo_alto), interpolation=cv2.INTER_LINEAR)
        izquierda = (self.ancho - nuevo_ancho) // 2
        arriba = (self.alto - nuevo_alto) // 2
        lienzo = np.full((self.alto, self.ancho, 3), 114, dtype=np.uint8)
        lienzo[arriba:arriba + nuevo_alto, izquierda:izquierda + nuevo_ancho] = redimensionada
        return lienzo, (nuevo_ancho / ancho, nuevo_alto / alto), izquierda, arriba

    def detectar(self, imagen_bgr, umbral=UMBRAL_DETECCION_AVE, iou=UMBRAL_IOU_NMS, clases=None):
        """Lista de (x1, y1, x2, y2, confianza, id_clase) en píxeles de la imagen original."""
        alto, ancho = imagen_bgr.shape[:2]
        lienzo, (escala_x, escala_y), izquierda, arriba = self._letterbox(imagen_bgr)
        salida = self.ejecutar(_tensor_rgb(lienzo))[0]  # (4 + clases, candidatos) o su transpuesta
        atributos = 4 + len(self.nombres)
        if self.nombres and salida.shape[0] != atributos and salida.shape[1] != atributos:
            raise ValueError(f"Salida YOLO inesperada: {salida.shape}; se esperaban {atributos} atributos.")
        if (self.nombres and salida.shape[0] != atributos) or (not self.nombres and salida.shape[0] > salida.shape[1]):
            salida = salida.T
        cajas = salida[:4].T
        puntajes = salida[4:].T
        if clases is not None:
            mascara = np.zeros(puntajes.shape[1], dtype=bool)
            mascara[list(clases)] = True
            puntajes = np.where(mascara[None, :], puntajes, 0.0)

        ids = puntajes.argmax(axis=1)
        confianzas = puntajes[np.arange(len(ids)), ids]
        elegidas = (confianzas >= umbral) & np.isfinite(confianzas) & np.isfinite(cajas).all(axis=1)
        if not np.any(elegidas):
            return []
        cajas, confianzas, ids = cajas[elegidas], confianzas[elegidas], ids[elegidas]

        # Invierte la escala real (incluido el redondeo del letterbox) y recorta antes de NMS.
        cx, cy, w, h = cajas.T
        x1 = np.clip((cx - w / 2 - izquierda) / escala_x, 0, ancho)
        y1 = np.clip((cy - h / 2 - arriba) / escala_y, 0, alto)
        x2 = np.clip((cx + w / 2 - izquierda) / escala_x, 0, ancho)
        y2 = np.clip((cy + h / 2 - arriba) / escala_y, 0, alto)
        validas = (x2 - x1 >= 1) & (y2 - y1 >= 1)
        if not np.any(validas):
            return []
        xywh = np.stack((x1, y1, x2 - x1, y2 - y1), axis=1)[validas]
        confianzas, ids = confianzas[validas], ids[validas]
        # Todas las clases compiten por la misma caja. El umbral ya se aplicó arriba.
        indices = cv2.dnn.NMSBoxes(xywh.tolist(), confianzas.tolist(), 0.0, iou)
        indices = np.array(indices).reshape(-1) if len(indices) else []

        resultado = []
        for i in indices:
            x, y, w, h = xywh[i]
            resultado.append((
                math.floor(x), math.floor(y), min(ancho, math.ceil(x + w)), min(alto, math.ceil(y + h)),
                float(confianzas[i]), int(ids[i]),
            ))
        return resultado


class Clasificador(ModeloONNX):
    def __init__(self, ruta, tamano=224):
        super().__init__(ruta)
        self.tamano = self.alto_entrada or tamano

    def clasificar(self, recorte_bgr, grupos_clase=None):
        """(id_clase, probabilidad)."""
        probabilidades = self.probabilidades(recorte_bgr, grupos_clase)
        if probabilidades is None:
            return -1, 0.0
        indice = int(probabilidades.argmax())
        return indice, float(probabilidades[indice])

    def probabilidades(self, recorte_bgr, grupos_clase=None):
        """Probabilidad de cada clase (suma 1), o None si la salida no es válida."""
        alto, ancho = recorte_bgr.shape[:2]
        escala = self.tamano / min(alto, ancho)
        nuevo = (max(self.tamano, round(ancho * escala)), max(self.tamano, round(alto * escala)))
        imagen = cv2.resize(recorte_bgr, nuevo, interpolation=cv2.INTER_LINEAR)
        x = (imagen.shape[1] - self.tamano) // 2
        y = (imagen.shape[0] - self.tamano) // 2
        imagen = imagen[y:y + self.tamano, x:x + self.tamano]
        probabilidades = self.ejecutar(_tensor_rgb(imagen))[0].astype(np.float64)
        if not np.isfinite(probabilidades).all():
            return None
        if abs(probabilidades.sum() - 1.0) > 0.01 or probabilidades.min() < 0:
            probabilidades = np.exp(probabilidades - probabilidades.max())
            probabilidades /= probabilidades.sum()
        for grupo in grupos_clase or ():
            principal, *alias = grupo
            probabilidades[principal] += probabilidades[alias].sum()
            probabilidades[alias] = 0.0
        return probabilidades


def cargar_clases_modelo(ruta=ARCHIVO_CLASES_MODELO, ruta_catalogo=None):
    resultado = {}
    catalogo_resuelto = obtener_ruta_recurso(ruta_catalogo) if ruta_catalogo else ARCHIVO_CATALOGO
    try:
        with open(catalogo_resuelto, "r", encoding="utf-8-sig", newline="") as archivo:
            for fila in csv.DictReader(archivo):
                cientifico = (fila.get("Nombre_Cientifico") or "").strip()
                if not cientifico:
                    continue
                resultado[clave_clase(cientifico)] = cientifico
                comun = (fila.get("Nombre_Comun") or "").strip()
                if comun:
                    resultado.setdefault(clave_clase(comun), cientifico)
    except FileNotFoundError:
        pass
    clases_resuelto = obtener_ruta_recurso(ruta) if ruta else ARCHIVO_CLASES_MODELO
    try:
        with open(clases_resuelto, "r", encoding="utf-8") as archivo:
            clases = json.load(archivo).get("clases", {})
    except (FileNotFoundError, json.JSONDecodeError):
        clases = {}
    resultado.update({clave_clase(k): v for k, v in clases.items()})
    return resultado


class Identificador:
    def __init__(
        self,
        buscar_especie,
        ruta_detector=MODELO_DETECTOR,
        ruta_clasificador=MODELO_CLASIFICADOR,
        clases_modelo=None,
        umbral_confianza=UMBRAL_CONFIANZA,
        umbral_deteccion=UMBRAL_DETECCION_AVE,
        tamano_minimo=TAMANO_MINIMO_PX,
    ):
        ruta_det = obtener_ruta_recurso(ruta_detector) if ruta_detector else None
        if not ruta_det or not Path(ruta_det).is_file() or Path(ruta_det).stat().st_size == 0:
            raise FileNotFoundError(
                f"No existe el modelo {ruta_detector}. Ejecuta exportar_modelos.bat para generarlo."
            )
        self.detector = Detector(ruta_det)
        self.clasificador = None
        if ruta_clasificador:
            ruta_cls = obtener_ruta_recurso(ruta_clasificador)
            if Path(ruta_cls).is_file() and Path(ruta_cls).stat().st_size > 0:
                self.clasificador = Clasificador(ruta_cls)

        self.umbral_confianza = umbral_confianza
        self.umbral_deteccion = umbral_deteccion
        self.tamano_minimo = tamano_minimo
        self.clases_modelo = clases_modelo if clases_modelo is not None else cargar_clases_modelo()
        self._buscar = buscar_especie
        grupos = {}
        if self.clasificador is not None:
            for indice, nombre in self.clasificador.nombres.items():
                cientifico = self.clases_modelo.get(clave_clase(nombre))
                if cientifico:
                    grupos.setdefault(cientifico.casefold(), []).append(indice)
        self._alias_clasificador = [ids for ids in grupos.values() if len(ids) > 1]

        ids_ave = [i for i, n in self.detector.nombres.items() if clave_clase(n) == CLASE_AVE_COCO]
        if ids_ave:
            self.ids_ave = set(ids_ave)
            self.modo = "dos etapas" if self.clasificador is not None else "solo ave"
        else:
            self.ids_ave = None
            self.modo = "una etapa"

    # ------------------------------------------------------

    def especie_de_clase(self, nombre_clase):
        cientifico = self.clases_modelo.get(clave_clase(nombre_clase))
        especie = self._buscar(cientifico) if cientifico else None
        if especie is None or not especie.get("activo", 1):
            return None
        return especie

    def especies_reconocibles(self):
        if self.modo == "una etapa":
            nombres = self.detector.nombres.values()
        elif self.modo == "dos etapas":
            nombres = self.clasificador.nombres.values()
        else:
            return []
        especies = {}
        for nombre in nombres:
            especie = self.especie_de_clase(nombre)
            if especie is not None:
                especies[especie["id_especie"]] = especie["nombre_comun"]
        return sorted(especies.values())

    def procesar(self, cuadro_bgr):
        inicio = time.perf_counter()
        clases = self.ids_ave if self.ids_ave else None
        candidatas = self.detector.detectar(cuadro_bgr, umbral=self.umbral_deteccion, clases=clases)

        detecciones = []
        descartes_px = descartes_confianza = 0
        for x1, y1, x2, y2, conf_det, id_clase in candidatas:
            deteccion = {
                "caja": (x1, y1, x2, y2),
                "ancho": x2 - x1,
                "alto": y2 - y1,
                "confianza": conf_det,
                "especie": None,
                "clase": None,
            }
            if deteccion["ancho"] < self.tamano_minimo or deteccion["alto"] < self.tamano_minimo:
                deteccion["estado"] = "pequena"
                descartes_px += 1
                detecciones.append(deteccion)
                continue

            if self.modo == "solo ave":
                deteccion["estado"] = "ave"
                detecciones.append(deteccion)
                continue

            if self.modo == "dos etapas":
                recorte = cuadro_bgr[y1:y2, x1:x2]
                id_especie_modelo, confianza = self.clasificador.clasificar(recorte, self._alias_clasificador)
                nombre_clase = self.clasificador.nombres.get(id_especie_modelo, str(id_especie_modelo))
            else:
                confianza = conf_det
                nombre_clase = self.detector.nombres.get(id_clase, str(id_clase))

            deteccion["confianza"] = confianza
            deteccion["clase"] = nombre_clase
            if confianza < self.umbral_confianza:
                deteccion["estado"] = "baja_confianza"
                descartes_confianza += 1
            else:
                especie = self.especie_de_clase(nombre_clase)
                deteccion["especie"] = especie
                deteccion["estado"] = "identificada" if especie is not None else "sin_ficha"
            detecciones.append(deteccion)

        detecciones_filtradas = _descartar_recortes_duplicados(detecciones)
        estadisticas = {
            "ms": (time.perf_counter() - inicio) * 1000.0,
            "candidatas": len(candidatas),
            "descartes_px": descartes_px,
            "descartes_confianza": descartes_confianza,
            "descartes_contencion": len(detecciones) - len(detecciones_filtradas),
        }
        return detecciones_filtradas, estadisticas
