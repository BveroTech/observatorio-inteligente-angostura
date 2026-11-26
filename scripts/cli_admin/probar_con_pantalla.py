"""
Prueba el reconocimiento de aves capturando la pantalla (sin cámara).

    python scripts/cli_admin/probar_con_pantalla.py                 # pregunta qué monitor capturar
    python scripts/cli_admin/probar_con_pantalla.py --monitor 2
    python scripts/cli_admin/probar_con_pantalla.py --region 0,0,1920,1080
    python scripts/cli_admin/probar_con_pantalla.py --listar-monitores

Cómo usarla:
  1. Reproduce un video de aves en un monitor (YouTube, eBird, Macaulay Library…),
     idealmente a pantalla completa.
  2. Ejecuta esta prueba indicando ese monitor. La ventana de resultados se abre
     en OTRO monitor (si se capturara a sí misma, analizaría su propia imagen).
  3. Cada ave detectada muestra sus 3 especies más probables:
       verde   = el kiosco la identificaría (confianza ≥ UMBRAL_CONFIANZA)
       naranjo = duda: el kiosco no la nombraría
       gris    = muy pequeña (< TAMANO_MINIMO_PX): no se clasifica
     El panel derecho agrupa las 10 especies por parecido y cuenta las aves vistas.
  4. Cierra con Q o Esc. Queda un informe en laboratorio_ia/reportes/prueba_pantalla_<fecha>.md
     con cada ave (seguida entre cuadros), su especie, su segunda opción y el
     resumen por grupo, más un CSV con todas las detecciones.

Usa el mismo detector, clasificador y umbrales que el kiosco (src/procesamiento/inferencia_onnx.py).
Ojo: el modelo solo conoce 10 especies; un ave de otra especie siempre se parecerá
a alguna, y la confianza baja (naranjo) es la forma correcta de "no sé".
"""
import argparse
import csv
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from config.settings import TAMANO_MINIMO_PX, UMBRAL_CONFIANZA  # noqa: E402
from src.adquisicion.captura_pantalla import CapturaPantalla, interpretar_region, listar_monitores  # noqa: E402
from src.procesamiento.inferencia_onnx import Identificador  # noqa: E402
from src.procesamiento.seguimiento import Seguidor  # noqa: E402

# Las 10 especies agrupadas por parecido. Los grupos salen de cuánto se confunde
# el modelo entre ellas en val+test (probabilidad media cruzada y errores) y de su
# aspecto: el par más confundido es Tagua común ↔ Yeco.
GRUPOS = [
    ("Negras de agua", ["Tagua común", "Yeco"],
     "cuerpo oscuro nadando; la tagua tiene pico y escudete blancos, el yeco (cormorán) pico ganchudo"),
    ("Patos", ["Pato cuchara", "Pato jergon grande", "Pato anteojillo", "Pato rana de pico delgado"],
     "misma silueta; se distinguen por el pico y el diseño de la cabeza"),
    ("Blancas con negro", ["Cisne de cuello negro", "Gaviota de Franklin"],
     "cuerpo blanco con cabeza/cuello negro; el modelo las cruza a veces"),
    ("Inconfundibles", ["Huala", "Martin pescador"],
     "silueta propia (zambullidor de cuello largo / martín pescador posado)"),
]
GRUPO_DE = {especie: nombre for nombre, especies, _ in GRUPOS for especie in especies}

VERDE, NARANJO, GRIS, BLANCO = (60, 200, 60), (0, 150, 255), (150, 150, 150), (235, 235, 235)
ANCHO_PANEL = 380
MINIMO_CUADROS_AVE = 3  # un ave cuenta en el informe si se siguió al menos estos cuadros


def sin_tildes(texto):
    """cv2.putText no dibuja tildes ni ñ."""
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def elegir_monitor():
    monitores = listar_monitores()
    print("Monitores disponibles:")
    for numero, x, y, ancho, alto in monitores[1:]:
        print(f"  {numero}: {ancho}x{alto} en ({x}, {y})")
    while True:
        texto = input("¿Qué monitor muestra el video de aves? Número: ").strip()
        if texto.isdigit() and 1 <= int(texto) < len(monitores):
            return int(texto)


def monitor_para_ventana(zona):
    """Un monitor distinto del capturado, para que la ventana no se capture a sí misma."""
    cx, cy = zona["left"] + zona["width"] // 2, zona["top"] + zona["height"] // 2
    for _, x, y, ancho, alto in listar_monitores()[1:]:
        if not (x <= cx < x + ancho and y <= cy < y + alto):
            return x, y, ancho, alto
    return None


class Ave:
    """Una pista del seguidor: acumula probabilidades de todos sus cuadros."""

    def __init__(self, n_clases):
        self.suma = np.zeros(n_clases)
        self.cuadros = 0
        self.inicio = time.monotonic()

    def agregar(self, probabilidades):
        self.suma += probabilidades
        self.cuadros += 1

    @property
    def media(self):
        return self.suma / max(1, self.cuadros)


class Prueba:
    def __init__(self, captura):
        self.captura = captura
        self.identificador = Identificador(lambda cientifico: {"id_especie": cientifico, "nombre_comun": cientifico,
                                                               "activo": 1})
        if self.identificador.modo != "dos etapas":
            raise SystemExit(f"Se necesita el modo dos etapas (detector + clasificador); está en: {self.identificador.modo}")
        self.clasificador = self.identificador.clasificador
        self.nombres = self.clasificador.nombres
        self.seguidor = Seguidor()
        self.aves = {}
        self.terminadas = []
        self.filas_csv = []
        self.cuadros = 0
        self.ms = []

    # ------------------------------------------------------------------

    def analizar(self, cuadro):
        inicio = time.perf_counter()
        detecciones, _ = self.identificador.procesar(cuadro)
        clasificables = [d for d in detecciones if d["estado"] != "pequena"]
        ahora = time.monotonic()
        pistas = self.seguidor.actualizar([d["caja"] for d in clasificables], ahora)
        resultados = []
        for deteccion, id_pista in zip(clasificables, pistas):
            x1, y1, x2, y2 = deteccion["caja"]
            probabilidades = self.clasificador.probabilidades(cuadro[y1:y2, x1:x2],
                                                              self.identificador._alias_clasificador)
            if probabilidades is None:
                continue
            ave = self.aves.setdefault(id_pista, Ave(len(probabilidades)))
            ave.agregar(probabilidades)
            orden = np.argsort(probabilidades)[::-1][:3]
            top = [(self.nombres[int(i)], float(probabilidades[i])) for i in orden]
            resultados.append((deteccion["caja"], top, id_pista))
            self.filas_csv.append([f"{datetime.now():%H:%M:%S.%f}"[:-3], id_pista, x1, y1, x2 - x1, y2 - y1,
                                   *[v for par in top for v in (par[0], f"{par[1]:.3f}")]])
        pequenas = [d["caja"] for d in detecciones if d["estado"] == "pequena"]
        for id_pista in [i for i in self.aves if i not in self.seguidor.pistas]:
            self.terminadas.append(self.aves.pop(id_pista))
        self.cuadros += 1
        self.ms.append((time.perf_counter() - inicio) * 1000)
        return resultados, pequenas

    def todas_las_aves(self):
        return [a for a in self.terminadas + list(self.aves.values()) if a.cuadros >= MINIMO_CUADROS_AVE]

    # ------------------------------------------------------------------

    def dibujar(self, cuadro, resultados, pequenas, alto_ventana):
        escala = min(1.0, alto_ventana / cuadro.shape[0], 1500 / cuadro.shape[1])
        vista = cv2.resize(cuadro, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA) if escala < 1 else cuadro.copy()
        grosor = 2
        for x1, y1, x2, y2 in pequenas:
            cv2.rectangle(vista, (int(x1 * escala), int(y1 * escala)), (int(x2 * escala), int(y2 * escala)), GRIS, 1)
        for (x1, y1, x2, y2), top, _ in resultados:
            color = VERDE if top[0][1] >= UMBRAL_CONFIANZA else NARANJO
            p1, p2 = (int(x1 * escala), int(y1 * escala)), (int(x2 * escala), int(y2 * escala))
            cv2.rectangle(vista, p1, p2, color, grosor)
            lineas = [f"{sin_tildes(n)} {p * 100:.0f}%" for n, p in top if p >= 0.01]
            y = max(18, p1[1] - 6 - 18 * (len(lineas) - 1))
            for i, linea in enumerate(lineas):
                tam = 0.55 if i == 0 else 0.45
                (ancho, alto), _ = cv2.getTextSize(linea, cv2.FONT_HERSHEY_SIMPLEX, tam, 1)
                cv2.rectangle(vista, (p1[0], y - alto - 4), (p1[0] + ancho + 6, y + 4), (0, 0, 0), -1)
                cv2.putText(vista, linea, (p1[0] + 3, y), cv2.FONT_HERSHEY_SIMPLEX, tam,
                            color if i == 0 else BLANCO, 1, cv2.LINE_AA)
                y += 18
        panel = self.panel(vista.shape[0], {top[0][0] for _, top, _ in resultados if top[0][1] >= UMBRAL_CONFIANZA})
        return np.hstack([vista, panel])

    def panel(self, alto, vistas_ahora):
        panel = np.full((max(alto, 560), ANCHO_PANEL, 3), 30, np.uint8)
        conteo = Counter(self.nombres[int(a.media.argmax())] for a in self.todas_las_aves()
                         if a.media.max() >= UMBRAL_CONFIANZA)
        y = 28
        ms = np.median(self.ms[-30:]) if self.ms else 0
        cv2.putText(panel, f"{ms:.0f} ms/cuadro  umbral {UMBRAL_CONFIANZA:.2f}", (12, y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, BLANCO, 1, cv2.LINE_AA)
        y += 22
        cv2.putText(panel, "Aves vistas por especie (Q = salir)", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, GRIS, 1,
                    cv2.LINE_AA)
        for nombre, especies, _ in GRUPOS:
            y += 32
            cv2.putText(panel, sin_tildes(nombre).upper(), (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 180, 90), 1,
                        cv2.LINE_AA)
            for especie in especies:
                y += 22
                color = VERDE if especie in vistas_ahora else BLANCO
                cv2.putText(panel, f"  {sin_tildes(especie)}", (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
                            cv2.LINE_AA)
                cv2.putText(panel, str(conteo.get(especie, 0)), (ANCHO_PANEL - 40, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                            color, 1, cv2.LINE_AA)
        return panel[:alto] if panel.shape[0] > alto else panel

    # ------------------------------------------------------------------

    def informe(self, carpeta, descripcion, minutos):
        carpeta.mkdir(parents=True, exist_ok=True)
        marca = f"{datetime.now():%Y%m%d_%H%M}"
        ruta_csv = carpeta / f"prueba_pantalla_{marca}.csv"
        with open(ruta_csv, "w", newline="", encoding="utf-8-sig") as archivo:
            escritor = csv.writer(archivo, delimiter=";")
            escritor.writerow(["hora", "ave", "x", "y", "ancho", "alto", "especie_1", "prob_1", "especie_2", "prob_2",
                               "especie_3", "prob_3"])
            escritor.writerows(self.filas_csv)

        aves = self.todas_las_aves()
        pct = lambda v: f"{v * 100:.0f} %"  # noqa: E731
        lineas = [
            f"# Prueba con captura de pantalla · {datetime.now():%Y-%m-%d %H:%M}",
            "",
            f"- Fuente: {descripcion} · {minutos:.1f} min · {self.cuadros} cuadros · "
            f"mediana {np.median(self.ms) if self.ms else 0:.0f} ms por cuadro",
            f"- Aves seguidas (≥ {MINIMO_CUADROS_AVE} cuadros): {len(aves)} · "
            f"identificadas con confianza ≥ {UMBRAL_CONFIANZA:.2f}: "
            f"{sum(a.media.max() >= UMBRAL_CONFIANZA for a in aves)}",
            f"- Detalle de cada detección: `{ruta_csv.name}`",
            "",
            "La confianza de cada ave es el promedio de todos los cuadros en que se la siguió.",
            "Esta prueba no sabe qué especie era en realidad: compara la columna «Especie»",
            "con lo que muestra el video.",
            "",
            "## Por grupo de especies parecidas",
            "",
            "| Grupo | Especie | Aves | Identificadas | Confianza media | Segunda opción más común |",
            "|---|---|---:|---:|---:|---|",
        ]
        por_especie = defaultdict(list)
        for ave in aves:
            por_especie[self.nombres[int(ave.media.argmax())]].append(ave)
        for nombre, especies, _ in GRUPOS:
            for especie in especies:
                grupo = por_especie.get(especie, [])
                dudosas = [a for a in grupo if np.sort(a.media)[-2] >= 0.01]
                segundas = Counter(self.nombres[int(np.argsort(a.media)[-2])] for a in dudosas)
                segunda = "sin dudas (< 1 %)" if grupo and not dudosas else ""
                if segundas:
                    s, veces = segundas.most_common(1)[0]
                    misma = " (mismo grupo)" if GRUPO_DE.get(s) == nombre else ""
                    segunda = f"{s}{misma} · {veces} de {len(grupo)}"
                identificadas = sum(a.media.max() >= UMBRAL_CONFIANZA for a in grupo)
                confianza = pct(np.mean([a.media.max() for a in grupo])) if grupo else "—"
                lineas.append(f"| {nombre} | {especie} | {len(grupo)} | {identificadas} | {confianza} | {segunda} |")

        lineas += ["", "## Cada ave", "",
                   "| # | Especie | Confianza | 2.ª opción | 3.ª opción | Cuadros | ¿El kiosco la nombra? |",
                   "|---:|---|---:|---|---|---:|---|"]
        for i, ave in enumerate(sorted(aves, key=lambda a: a.inicio), 1):
            orden = np.argsort(ave.media)[::-1]
            p = ave.media
            opcion = lambda k: f"{self.nombres[int(orden[k])]} {pct(p[orden[k]])}" if p[orden[k]] >= 0.01 else "—"  # noqa: E731
            lineas.append(f"| {i} | {self.nombres[int(orden[0])]} | {pct(p[orden[0]])} | {opcion(1)} | "
                          f"{opcion(2)} | {ave.cuadros} | "
                          f"{'sí' if p[orden[0]] >= UMBRAL_CONFIANZA else 'no (duda)'} |")

        lineas += ["", "## Grupos usados", ""]
        for nombre, especies, nota in GRUPOS:
            lineas.append(f"- **{nombre}**: {', '.join(especies)} — {nota}.")
        ruta_md = carpeta / f"prueba_pantalla_{marca}.md"
        ruta_md.write_text("\n".join(lineas) + "\n", encoding="utf-8")
        return ruta_md


def main(argumentos=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--monitor", type=int, default=None, help="monitor a capturar (1, 2, 3…)")
    parser.add_argument("--region", type=interpretar_region, default=None, help="zona a capturar: x,y,ancho,alto")
    parser.add_argument("--listar-monitores", action="store_true")
    parser.add_argument("--segundos", type=float, default=0, help="termina sola tras estos segundos (0 = hasta Q)")
    parser.add_argument("--salida", type=Path, default=RAIZ / "laboratorio_ia" / "reportes")
    args = parser.parse_args(argumentos)

    if args.listar_monitores:
        for numero, x, y, ancho, alto in listar_monitores()[1:]:
            print(f"{numero}: {ancho}x{alto} en ({x}, {y})")
        return 0
    monitor = args.monitor if args.monitor is not None or args.region else elegir_monitor()
    captura = CapturaPantalla(monitor or 1, args.region, fps_maximo=0)
    descripcion = f"región {args.region}" if args.region else f"monitor {monitor}"
    print(f"Capturando {descripcion} ({captura.zona['width']}x{captura.zona['height']}). Q o Esc para terminar.")
    print("Grupos de especies parecidas:")
    for nombre, especies, nota in GRUPOS:
        print(f"  {nombre}: {', '.join(especies)}  ({nota})")

    prueba = Prueba(captura)
    ventana = "Prueba de reconocimiento (Q = salir)"
    cv2.namedWindow(ventana, cv2.WINDOW_NORMAL)
    otro = monitor_para_ventana(captura.zona)
    alto_ventana = 900
    if otro:
        x, y, ancho, alto = otro
        alto_ventana = min(alto - 120, 900)
        cv2.moveWindow(ventana, x + 30, y + 30)
    else:
        print("AVISO: hay un solo monitor. Usa --region para capturar solo la zona del video y deja esta "
              "ventana fuera de ella.")
    inicio = time.monotonic()
    try:
        while True:
            correcto, cuadro = captura.read()
            if not correcto:
                time.sleep(0.05)
                continue
            resultados, pequenas = prueba.analizar(cuadro)
            cv2.imshow(ventana, prueba.dibujar(cuadro, resultados, pequenas, alto_ventana))
            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), ord("Q"), 27) or cv2.getWindowProperty(ventana, cv2.WND_PROP_VISIBLE) < 1:
                break
            if args.segundos and time.monotonic() - inicio >= args.segundos:
                break
    except KeyboardInterrupt:
        pass
    finally:
        captura.release()
        cv2.destroyAllWindows()
    ruta = prueba.informe(args.salida, descripcion, (time.monotonic() - inicio) / 60)
    print(f"Informe: {ruta.relative_to(RAIZ) if ruta.is_relative_to(RAIZ) else ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
