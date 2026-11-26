"""
Traduce al inglés y al alemán las fichas del catálogo (sin internet).

    python scripts/cli_admin/traducir_fichas.py               traduce lo que falta o cambió (activas primero)
    python scripts/cli_admin/traducir_fichas.py --todas       también las especies inactivas
    python scripts/cli_admin/traducir_fichas.py --forzar      vuelve a traducir todo, incluso lo corregido a mano

En la versión instalada:  Admin.exe --traducir-fichas
Lo corregido a mano en el portal no se toca (salvo --forzar).
"""
import argparse
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src.aplicacion.servicio_traduccion import traducir_especie  # noqa: E402
from src.aplicacion import traductor  # noqa: E402
from src.persistencia.repositorio_sqlite import preparar_base  # noqa: E402


def main(argumentos=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--todas", action="store_true", help="incluye las especies inactivas")
    parser.add_argument("--forzar", action="store_true", help="vuelve a traducir también lo corregido a mano")
    args = parser.parse_args(argumentos)

    if not traductor.traductor_disponible():
        print(f"No se puede traducir: {traductor.ultimo_error}")
        print("Si faltan los modelos: python scripts/cli_admin/descargar_modelos_idiomas.py")
        return 1
    base = preparar_base()
    try:
        especies = base.especies(solo_activas=not args.todas)
        especies.sort(key=lambda e: (not e.get("activo"), e["nombre_comun"]))
        inicio, total = time.monotonic(), 0
        for numero, especie in enumerate(especies, 1):
            cantidad = traducir_especie(base, especie["id_especie"], forzar=args.forzar)
            total += cantidad
            print(f"[{numero}/{len(especies)}] {especie['nombre_comun']}: {cantidad} campos traducidos", flush=True)
        print(f"\nListo: {total} campos en {time.monotonic() - inicio:.0f} s. Resumen por idioma: {base.resumen_traducciones()}")
    finally:
        base.cerrar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
