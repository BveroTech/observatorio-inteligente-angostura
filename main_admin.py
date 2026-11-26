import argparse
import ipaddress
import socket
import sys
import threading
import traceback
import webbrowser

from pathlib import Path
from threading import Timer

from config.settings import ADMIN_HOST, ADMIN_PUERTO, ES_EMPAQUETADO
from src.persistencia.repositorio_sqlite import preparar_base
from web import crear_app


def _manejar_excepcion_hilo(args):
    if issubclass(args.exc_type, SystemExit):
        return
    nombre = args.thread.name if args.thread else "desconocido"
    print(f"[AVISO] Excepción controlada en hilo web '{nombre}': {args.exc_value}")
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)


def enlaces_red(puerto):
    """Direcciones con que otros equipos de la red local abren el portal."""
    nombre = socket.gethostname()
    enlaces = [f"http://{nombre}:{puerto}"]
    try:
        ips = socket.gethostbyname_ex(nombre)[2]
    except OSError:
        ips = []
    for ip in ips:
        try:
            privada = ipaddress.ip_address(ip).is_private and not ip.startswith("127.")
        except ValueError:
            privada = False
        if privada:
            enlaces.append(f"http://{ip}:{puerto}")
    return enlaces


def puerto_ocupado(puerto):
    """True si ya hay un portal (u otro programa) escuchando en ese puerto de este equipo."""
    try:
        with socket.create_connection(("127.0.0.1", puerto), timeout=0.5):
            return True
    except OSError:
        return False


def herramienta(nombre, argumentos=None):
    """Ejecuta una herramienta de scripts/cli_admin (también dentro de Admin.exe)."""
    carpeta = Path(__file__).resolve().parent / "scripts" / "cli_admin"
    if carpeta.is_dir() and str(carpeta) not in sys.path:
        sys.path.insert(0, str(carpeta))
    modulo = __import__(nombre)
    resultado = modulo.main(argumentos) if argumentos is not None else modulo.main()
    if ES_EMPAQUETADO:
        input("\nPresiona Enter para cerrar...")
    return resultado


def servir(app, host, puerto):
    """waitress si está instalado (servidor para uso real); si no, el de Flask."""
    try:
        from waitress import serve
    except ImportError:
        app.run(host=host, port=puerto, debug=False, threaded=True, use_reloader=False)
        return
    serve(app, host=host, port=puerto, threads=8, ident="Observatorio")


def main(argumentos=None):
    threading.excepthook = _manejar_excepcion_hilo

    parser = argparse.ArgumentParser(description="Portal de administración del Observatorio")
    parser.add_argument("--host", default=ADMIN_HOST, help="127.0.0.1 = solo este equipo; 0.0.0.0 = red local")
    parser.add_argument("--puerto", type=int, default=ADMIN_PUERTO)
    parser.add_argument("--sin-navegador", action="store_true", help="No abrir el navegador al iniciar")
    parser.add_argument("--mostrar-enlace", action="store_true",
                        help="Solo muestra el enlace para abrir el portal desde otro equipo de la red")
    parser.add_argument("--crear-usuario", action="store_true",
                        help="Crea un usuario del portal o restablece su contraseña")
    parser.add_argument("--traducir-fichas", action="store_true",
                        help="Traduce al inglés y al alemán las fichas que falten o hayan cambiado")
    parser.add_argument("--detectar-pantallas", action="store_true",
                        help="Muestra los monitores y su número (para config/observatorio.ini)")
    args = parser.parse_args(argumentos)
    if args.crear_usuario:
        return herramienta("crear_usuario")
    if args.detectar_pantallas:
        return herramienta("detectar_pantallas", [])
    if args.traducir_fichas:
        return herramienta("traducir_fichas", [])
    if args.mostrar_enlace:
        print("Desde otro computador de la misma red, abre en el navegador:")
        for enlace in enlaces_red(args.puerto):
            print("   ", enlace)
        return

    direccion = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.puerto}"
    if puerto_ocupado(args.puerto):
        # El portal ya está abierto (por ejemplo, lo abrió el kiosco): solo se muestra en el navegador.
        print(f"El portal ya está abierto en {direccion}")
        if not args.sin_navegador:
            webbrowser.open(direccion)
        return

    base = preparar_base()
    try:
        ruta_base = base.ruta
        sin_usuarios = base.total_usuarios() == 0
    finally:
        base.cerrar()

    app = crear_app(ruta_base=ruta_base)
    print(f"Portal de administración en {direccion}  (Ctrl+C para detener)")
    if args.host == "0.0.0.0":
        print("El portal queda abierto a la red local. Desde otro computador, abre en el navegador:")
        for enlace in enlaces_red(args.puerto):
            print("   ", enlace)
    if sin_usuarios:
        print("Aún no hay usuarios: crea el primero con " + ("el acceso directo «Crear usuario del portal»" if ES_EMPAQUETADO else "scripts\\lanzadores_windows\\crear_usuario.bat"))
    temporizador = None
    if not args.sin_navegador:
        temporizador = Timer(1.2, lambda: webbrowser.open(direccion))
        temporizador.daemon = True
        temporizador.start()
    try:
        servir(app, args.host, args.puerto)
    except KeyboardInterrupt:
        pass
    finally:
        if temporizador is not None:
            temporizador.cancel()


if __name__ == "__main__":
    main()
