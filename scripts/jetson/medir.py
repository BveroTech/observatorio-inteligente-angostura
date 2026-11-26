"""
Mide el rendimiento del Observatorio durante N minutos y lo guarda en CSV (KPI-02 y KPI-03).

    .venv/bin/python scripts/jetson/medir.py --minutos 10 --fuente video
    .venv/bin/python scripts/jetson/medir.py --minutos 10 --fuente rtsp
    .venv/bin/python scripts/jetson/medir.py --minutos 2 --fuente video --video assets/videos/demo.mp4

Usa la MISMA fuente de video (FuenteVideo, con GStreamer/NVDEC en el Jetson) y la
MISMA IA (Identificador: detector + clasificador, mismos umbrales) que el kiosco,
pero sin la interfaz gráfica, para medir solo el procesamiento. Cada --intervalo
segundos agrega una fila con:

    cuadros procesados y FPS · ms de inferencia por cuadro (promedio, p95, máximo) ·
    proveedor de ONNX Runtime (TensorRT / CUDA / CPU) · RAM usada/total ·
    temperaturas (CPU, GPU, SoC… según tegrastats) · aves detectadas · estado de la fuente

RAM y temperaturas salen de `tegrastats` (Jetson); si no está, de /proc/meminfo y
/sys/class/thermal (Linux) o quedan vacías (Windows). Al terminar escribe un
resumen .md junto al CSV y compara con las metas del informe:
    KPI-02: >= 15 FPS      KPI-03: inferencia <= 90 ms por cuadro
Todo lo que se reporta es lo medido en esta ejecución.
"""
import argparse
import csv
import platform
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

META_FPS = 15.0
META_MS = 90.0


class Tegrastats(threading.Thread):
    """Lee tegrastats en segundo plano y guarda la última muestra."""

    def __init__(self):
        super().__init__(daemon=True, name="tegrastats")
        self.ultima = ""
        self.proceso = None

    def run(self):
        try:
            self.proceso = subprocess.Popen(["tegrastats", "--interval", "1000"], stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, text=True)
            for linea in self.proceso.stdout:
                self.ultima = linea.strip()
        except OSError:
            pass

    def detener(self):
        if self.proceso is not None:
            self.proceso.terminate()


def leer_sistema(tegra):
    """(ram_usada_mb, ram_total_mb, {sensor: °C}, origen)."""
    if tegra is not None and tegra.ultima:
        ram = re.search(r"RAM (\d+)/(\d+)MB", tegra.ultima)
        temperaturas = {k.lower(): float(v) for k, v in re.findall(r"([A-Za-z0-9_]+)@(-?\d+(?:\.\d+)?)C", tegra.ultima)}
        return (int(ram.group(1)) if ram else None, int(ram.group(2)) if ram else None, temperaturas, "tegrastats")
    if platform.system() == "Linux":
        datos = {}
        try:
            for linea in Path("/proc/meminfo").read_text().splitlines():
                clave, _, valor = linea.partition(":")
                datos[clave] = int(valor.split()[0])
        except OSError:
            pass
        total, disponible = datos.get("MemTotal"), datos.get("MemAvailable")
        temperaturas = {}
        for zona in Path("/sys/class/thermal").glob("thermal_zone*"):
            try:
                tipo = (zona / "type").read_text().strip().lower()
                temperaturas[tipo] = int((zona / "temp").read_text().strip()) / 1000
            except (OSError, ValueError):
                continue
        usada = (total - disponible) // 1024 if total and disponible else None
        return usada, total // 1024 if total else None, temperaturas, "/proc y /sys"
    try:
        import psutil

        memoria = psutil.virtual_memory()
        return (memoria.total - memoria.available) // 2**20, memoria.total // 2**20, {}, "psutil"
    except ImportError:
        return None, None, {}, "sin datos"


def main(argumentos=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--minutos", type=float, default=10)
    parser.add_argument("--fuente", choices=("video", "rtsp", "camara", "pantalla"), default="video")
    parser.add_argument("--video", default=None, help="video para --fuente video (por defecto, el de demostración)")
    parser.add_argument("--monitor", type=int, default=None, help="monitor para --fuente pantalla")
    parser.add_argument("--intervalo", type=float, default=5, help="segundos entre filas del CSV")
    parser.add_argument("--salida", type=Path, default=None, help="archivo CSV (por defecto data/mediciones/)")
    args = parser.parse_args(argumentos)

    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from config import settings
    from config.settings import ES_JETSON
    from main_kiosco import crear_fuente
    from src.procesamiento.inferencia_onnx import Identificador

    salida = args.salida or settings.obtener_ruta_datos("data/mediciones") / f"medicion_{datetime.now():%Y%m%d_%H%M}.csv"
    salida.parent.mkdir(parents=True, exist_ok=True)

    print("Cargando modelos (con TensorRT, la primera vez puede tardar varios minutos en compilar)...")
    identificador = Identificador(lambda cientifico: {"id_especie": cientifico, "nombre_comun": cientifico, "activo": 1})
    proveedor_det = identificador.detector.proveedor
    proveedor_cls = identificador.clasificador.proveedor if identificador.clasificador else "-"
    fuente = crear_fuente(args.fuente, video=args.video, monitor=args.monitor)
    fuente.start()

    tegra = None
    if shutil.which("tegrastats"):
        tegra = Tegrastats()
        tegra.start()

    columnas = ["hora", "segundos", "cuadros", "fps", "ms_promedio", "ms_p95", "ms_maximo", "proveedor_detector",
                "proveedor_clasificador", "ram_usada_mb", "ram_total_mb", "temperaturas_c", "aves_detectadas",
                "estado_fuente", "origen_datos_sistema"]
    todos_ms, filas = [], []
    inicio = time.monotonic()
    fin = inicio + args.minutos * 60
    print(f"Midiendo {args.minutos:g} min · fuente {args.fuente} · plataforma {platform.machine()}"
          f"{' (Jetson)' if ES_JETSON else ''} · detector {proveedor_det} · clasificador {proveedor_cls}")
    print(f"CSV: {salida}")
    with open(salida, "w", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(columnas)
        ultimo_id, ms, aves, marca = 0, [], 0, inicio
        try:
            while time.monotonic() < fin:
                id_cuadro, cuadro, _, _ = fuente.ultimo_cuadro(despues_de=ultimo_id)
                if cuadro is None or id_cuadro == ultimo_id:
                    time.sleep(0.002)
                else:
                    ultimo_id = id_cuadro
                    detecciones, estadisticas = identificador.procesar(cuadro)
                    ms.append(estadisticas["ms"])
                    aves += sum(1 for d in detecciones if d["estado"] != "pequena")
                ahora = time.monotonic()
                if ahora - marca >= args.intervalo:
                    usada, total, temperaturas, origen = leer_sistema(tegra)
                    fila = [
                        datetime.now().strftime("%H:%M:%S"), round(ahora - inicio, 1), len(ms),
                        round(len(ms) / (ahora - marca), 2),
                        round(statistics.fmean(ms), 1) if ms else "",
                        round(sorted(ms)[int(0.95 * (len(ms) - 1))], 1) if ms else "",
                        round(max(ms), 1) if ms else "",
                        proveedor_det, proveedor_cls, usada if usada is not None else "",
                        total if total is not None else "",
                        " ".join(f"{k}={v:.1f}" for k, v in sorted(temperaturas.items())), aves, fuente.estado, origen,
                    ]
                    escritor.writerow(fila)
                    archivo.flush()
                    filas.append(dict(zip(columnas, fila)))
                    todos_ms.extend(ms)
                    print(f"  {fila[1]:>6}s  {fila[3]:>6} FPS  {fila[4]} ms prom  {fila[6]} ms máx  RAM {fila[9]}/{fila[10]} MB"
                          f"  {fila[11]}  [{fila[13]}]")
                    ms, aves, marca = [], 0, ahora
        except KeyboardInterrupt:
            print("Interrumpido: se guarda lo medido hasta ahora.")
        finally:
            fuente.detener()
            if tegra is not None:
                tegra.detener()

    escribir_resumen(salida, args, filas, todos_ms, proveedor_det, proveedor_cls)
    return 0


def escribir_resumen(salida, args, filas, todos_ms, proveedor_det, proveedor_cls):
    if not filas or not todos_ms:
        print("No se procesó ningún cuadro: revise la fuente de video (estado en el CSV).")
        return
    duracion = float(filas[-1]["segundos"])
    fps = len(todos_ms) / duracion if duracion else 0
    ms_prom = statistics.fmean(todos_ms)
    ms_p95 = sorted(todos_ms)[int(0.95 * (len(todos_ms) - 1))]
    ms_max = max(todos_ms)
    rams = [f["ram_usada_mb"] for f in filas if f["ram_usada_mb"] != ""]
    total = next((f["ram_total_mb"] for f in filas if f["ram_total_mb"] != ""), "")
    cumple = lambda ok: "CUMPLE" if ok else "NO CUMPLE"  # noqa: E731
    lineas = [
        f"# Medición de rendimiento · {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"- Equipo: {platform.node()} · {platform.system()} {platform.machine()} · Python {platform.python_version()}",
        f"- Fuente: {args.fuente} · duración medida {duracion / 60:.1f} min · {len(todos_ms)} cuadros procesados",
        f"- ONNX Runtime: detector en **{proveedor_det}**, clasificador en **{proveedor_cls}**",
        f"- Datos: `{salida.name}`",
        "",
        "| Indicador | Medido | Meta | Resultado |",
        "|---|---:|---:|---|",
        f"| KPI-02 · FPS de procesamiento | {fps:.1f} | ≥ {META_FPS:g} | {cumple(fps >= META_FPS)} |",
        f"| KPI-03 · Inferencia promedio por cuadro | {ms_prom:.1f} ms | ≤ {META_MS:g} ms | {cumple(ms_prom <= META_MS)} |",
        f"| Inferencia p95 | {ms_p95:.1f} ms | — | — |",
        f"| Inferencia máxima | {ms_max:.1f} ms | — | — |",
        (f"| RAM usada (promedio / máximo) | {statistics.fmean(rams):.0f} / {max(rams)} MB de {total} MB | — | — |"
         if rams else "| RAM usada | sin datos en este equipo | — | — |"),
        "",
        "Medición sin la interfaz gráfica (solo captura + IA). El FPS del video en pantalla se mide aparte.",
    ]
    resumen = salida.with_suffix(".md")
    resumen.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print("\n".join(lineas[7:13]))
    print(f"Resumen: {resumen}")


if __name__ == "__main__":
    sys.exit(main())
