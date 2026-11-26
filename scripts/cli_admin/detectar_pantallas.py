"""
Detecta los monitores conectados y muestra su número en grande sobre cada uno
(como «Identificar» en la configuración de pantalla de Windows).

    python scripts/cli_admin/detectar_pantallas.py
    python scripts/cli_admin/detectar_pantallas.py --segundos 0     # solo la lista, sin mostrar números

Los números son los que usan los lanzadores de scripts/lanzadores_windows/
(MONITOR_KIOSCO, MONITOR_TACTIL, MONITOR_CAMARA).
"""
import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from config.settings import ES_LINUX  # noqa: E402
from src.aplicacion.gestor_monitores import describir_monitores, listar_monitores  # noqa: E402


def main(argumentos=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--segundos", type=float, default=4, help="Tiempo que se muestran los números (0 = no mostrar)")
    args = parser.parse_args(argumentos)

    try:
        monitores = [(principal, numero, rect, nombre) for numero, nombre, rect, principal in describir_monitores()]
        monitores.sort(key=lambda m: m[1] or 0)
    except Exception as error:
        print(f"No se pudieron leer los monitores: {error}")
        return 1
    print(f"Monitores conectados: {len(monitores)}\n")
    if not monitores:
        print("  No se detectaron monitores." + ("  En Linux se necesita la sesión gráfica (DISPLAY=:0) y xrandr." if ES_LINUX else ""))
        return 1
    for principal, numero, (x, y, ancho, alto), nombre in monitores:
        print(f"  Monitor {numero} ({nombre}): {ancho} x {alto}{'  (PRINCIPAL)' if principal else ''}   posición ({x}, {y})")
    if ES_LINUX:
        print("\nEn Linux se configuran por nombre de salida en config/pantallas.conf (SALIDA_KIOSCO, SALIDA_TACTIL).")

    principal = next((n for p, n, _, _ in monitores if p), None)
    # Misma regla que la Pantalla 2 en modo automático: el segundo de listar_monitores().
    numero_de = {rect: n for _, n, rect, _ in monitores}
    otros = [numero_de.get(rect) for rect in listar_monitores()[1:]]
    print("\nConfiguración automática de ejecutar_observatorio.bat (MONITOR_KIOSCO y MONITOR_TACTIL vacíos):")
    print(f"  Kiosco (Pantalla 1)       -> monitor {principal} (el principal)")
    print(f"  Pantalla táctil (Pantalla 2) -> monitor {otros[0] if otros else principal}"
          f"{'' if otros else ' (no hay segundo monitor: se abre sobre el principal)'}")
    if len(monitores) > 2:
        print("  Hay más de 2 monitores: conviene fijar MONITOR_KIOSCO y MONITOR_TACTIL en el .bat.")

    if args.segundos > 0:
        import tkinter as tk

        raiz = tk.Tk()
        raiz.withdraw()
        for es_principal, numero, (x, y, ancho, alto), _ in monitores:
            ventana = tk.Toplevel(raiz)
            ventana.overrideredirect(True)
            ventana.attributes("-topmost", True)
            lado = min(ancho, alto) // 2
            ventana.geometry(f"{lado}x{lado}+{x + (ancho - lado) // 2}+{y + (alto - lado) // 2}")
            marco = tk.Frame(ventana, bg="#1B4F72")
            marco.pack(fill="both", expand=True)
            tk.Label(marco, text=str(numero), fg="white", bg="#1B4F72",
                     font=("Segoe UI", max(48, lado // 3), "bold")).pack(expand=True)
            tk.Label(marco, text=f"{ancho} x {alto}" + ("  · principal" if es_principal else ""), fg="#D6EAF8",
                     bg="#1B4F72", font=("Segoe UI", max(12, lado // 20))).pack(pady=(0, lado // 10))
        raiz.after(int(args.segundos * 1000), raiz.destroy)
        raiz.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
