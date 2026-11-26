"""
Crea data/observatorio.db (las 4 tablas de la Guía 2.3) y carga el catálogo.

    python scripts/cli_admin/crear_base_datos.py               crea y agrega las especies que falten
    python scripts/cli_admin/crear_base_datos.py --actualizar  además sobrescribe las fichas con el CSV
    python scripts/cli_admin/crear_base_datos.py --esquema     solo muestra el script SQL

Sin --actualizar no se tocan las especies que el personal ya editó en el portal.
"""
import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from config.settings import ARCHIVO_BASE_DATOS, ARCHIVO_CATALOGO  # noqa: E402
from src.persistencia.repositorio_sqlite import ESQUEMA, BaseDatos  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--actualizar", action="store_true", help="Sobrescribe las fichas existentes con el CSV")
    parser.add_argument("--csv", type=Path, default=ARCHIVO_CATALOGO)
    parser.add_argument("--esquema", action="store_true", help="Muestra el DDL y termina")
    args = parser.parse_args()

    if args.esquema:
        print(ESQUEMA.strip())
        return 0

    base = BaseDatos()
    insertadas, actualizadas = base.cargar_catalogo(args.csv, actualizar=args.actualizar)
    print(f"Base de datos: {ARCHIVO_BASE_DATOS}")
    print(f"Especies nuevas: {insertadas} · actualizadas: {actualizadas} · total: {base.total_especies()}")
    print(f"Usuarios del portal: {base.total_usuarios()}")
    if base.total_usuarios() == 0:
        print("Crea el primer usuario con scripts\\lanzadores_windows\\crear_usuario.bat")
    base.cerrar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
