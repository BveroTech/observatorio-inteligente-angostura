import argparse
import logging
import platform
import threading
import traceback

from config import settings as config
from src.adquisicion.captura_pantalla import interpretar_region
from src.adquisicion.captura_rtsp import FuenteVideo
from src.aplicacion.configuracion_fuente import vigilar as vigilar_fuente
from src.aplicacion.gestor_monitores import leer_configuracion_pantallas
from src.persistencia.repositorio_sqlite import preparar_base
from src.presentacion.pantalla_secundaria import PantallaSecundaria
from src.presentacion.ventana_kiosco import Kiosco
from src.procesamiento.inferencia_onnx import Identificador
from src.procesamiento.motor_vision import Motor

registro = logging.getLogger("observatorio")


def _manejar_excepcion_hilo(args):
    if issubclass(args.exc_type, SystemExit):
        return
    nombre = args.thread.name if args.thread else "desconocido"
    print(f"[AVISO] Excepción controlada en hilo '{nombre}': {args.exc_value}")
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)


def crear_fuente(tipo, camara=None, video=None, monitor=None, region=None, ventana=None):
    if tipo == "pantalla":
        origen = {"monitor": config.MONITOR_CAPTURA if monitor is None else monitor, "region": region}
        return FuenteVideo("pantalla", origen, video_demo=config.VIDEO_DEMOSTRACION)
    if tipo == "ventana":
        programa, _, titulo = (ventana or f"{config.VENTANA_PROGRAMA}|{config.VENTANA_TITULO}").partition("|")
        origen = {"programa": programa.strip(), "titulo": titulo.strip()}
        return FuenteVideo("ventana", origen, video_demo=config.VIDEO_DEMOSTRACION)
    if tipo == "rtsp":
        return FuenteVideo("rtsp", config.url_rtsp(), video_demo=config.VIDEO_DEMOSTRACION)
    if tipo == "camara":
        indice = config.INDICE_CAMARA if camara is None else camara
        return FuenteVideo("camara", indice, video_demo=config.VIDEO_DEMOSTRACION)
    return FuenteVideo("video", video or config.VIDEO_DESARROLLO, video_demo=config.VIDEO_DEMOSTRACION)


def monitores_por_defecto():
    """(kiosco, táctil): en Linux salen de config/pantallas.conf; en Windows, de settings.py."""
    if config.ES_LINUX:
        conf = leer_configuracion_pantallas()
        return (conf.get("SALIDA_KIOSCO") or config.MONITOR_KIOSCO,
                conf.get("SALIDA_TACTIL") or config.MONITOR_PANTALLA_2)
    return config.MONITOR_KIOSCO, config.MONITOR_PANTALLA_2


def _registro_a_archivo():
    """Observatorio.exe no tiene consola: los mensajes y errores van a data/kiosco.log."""
    ruta = config.CARPETA_DATOS / "kiosco.log"
    try:
        modo = "w" if ruta.exists() and ruta.stat().st_size > 5 * 2**20 else "a"
        archivo = open(ruta, modo, encoding="utf-8", buffering=1)
    except OSError:
        return
    import sys

    sys.stdout = sys.stderr = archivo


def main(argumentos=None):
    threading.excepthook = _manejar_excepcion_hilo
    if config.ES_EMPAQUETADO:
        _registro_a_archivo()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    kiosco_defecto, tactil_defecto = monitores_por_defecto()
    parser = argparse.ArgumentParser(description="Observatorio Inteligente de Aves")
    parser.add_argument("--fuente", choices=("rtsp", "camara", "video", "pantalla", "ventana"),
                        default=config.FUENTE_VIDEO)
    parser.add_argument("--ventana", default=None,
                        help='con --fuente ventana: "programa.exe" o "programa.exe|texto del título" (p. ej. "chrome.exe|YouTube")')
    parser.add_argument("--monitor", type=int, default=None,
                        help="monitor a capturar con --fuente pantalla (1, 2, 3…; 0 = todos)")
    parser.add_argument("--region", type=interpretar_region, default=None,
                        help="zona del escritorio a capturar con --fuente pantalla: x,y,ancho,alto")
    parser.add_argument("--camara", type=int, default=None, help="índice de la cámara USB")
    parser.add_argument("--video", default=None, help="video para --fuente video")
    parser.add_argument(
        "--sin-pantalla2",
        "--sin-trivia",
        dest="sin_pantalla2",
        action="store_true",
        help="no abrir la Segunda Pantalla interactiva (Catálogo Público + Trivia)",
    )
    parser.add_argument("--pantalla-completa", action="store_true")
    parser.add_argument("--monitor-kiosco", default=kiosco_defecto,
                        help="monitor del kiosco: número (Windows: Configuración > Pantalla > Identificar; "
                             "Linux: orden de xrandr) o, en Linux, nombre de salida (p. ej. DP-1-1)")
    parser.add_argument("--monitor-tactil", default=tactil_defecto,
                        help="monitor de la Pantalla 2 interactiva (catálogo y trivia), igual que --monitor-kiosco")
    opciones = parser.parse_args(argumentos)
    registro.info("Plataforma: %s %s · Python %s · Jetson: %s", platform.system(), platform.machine(),
                  platform.python_version(), "sí" if config.ES_JETSON else "no")
    if opciones.fuente == "pantalla" and opciones.region is None:
        capturado = config.MONITOR_CAPTURA if opciones.monitor is None else opciones.monitor
        if str(capturado) in (str(opciones.monitor_kiosco), str(opciones.monitor_tactil)):
            print(f"[AVISO] Se captura el monitor {capturado}, donde también está una pantalla del sistema: "
                  "el kiosco se analizaría a sí mismo. Pon el video de aves en otro monitor.")

    preparar_base().cerrar()

    if config.INICIAR_PORTAL_CON_KIOSCO:
        # Versión instalada: el portal (Admin.exe) se abre en segundo plano si no está abierto.
        from src.aplicacion.servicio_catalogo import asegurar_portal

        threading.Thread(target=asegurar_portal, daemon=True, name="abrir_portal").start()

    fuente = crear_fuente(opciones.fuente, opciones.camara, opciones.video, opciones.monitor, opciones.region,
                          opciones.ventana)
    motor = Motor(fuente, lambda buscar: Identificador(buscar))
    fuente.start()
    motor.start()
    # Cambios de fuente hechos en el portal (Fuente de video) se aplican en vivo.
    fin_vigilancia = threading.Event()
    threading.Thread(target=vigilar_fuente, args=(fuente, fin_vigilancia), daemon=True,
                     name="vigilar_fuente").start()

    kiosco = None
    try:
        kiosco = Kiosco(
            motor,
            fuente,
            pantalla_completa=opciones.pantalla_completa or config.KIOSCO_PANTALLA_COMPLETA,
            monitor=opciones.monitor_kiosco,
        )
        if not opciones.sin_pantalla2 and config.PANTALLA_2 != "no":
            kiosco.after(
                800,
                lambda: kiosco.abrir_pantalla_secundaria(
                    lambda: PantallaSecundaria(kiosco, monitor=opciones.monitor_tactil)
                ),
            )
        kiosco.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        fin_vigilancia.set()
        motor.detener()
        fuente.detener()
        if kiosco is not None and not kiosco.cerrando:
            kiosco.cerrar()
        motor.join(timeout=2)
        fuente.join(timeout=2)


if __name__ == "__main__":
    main()
