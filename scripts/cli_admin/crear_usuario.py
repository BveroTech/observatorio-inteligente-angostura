"""
Crea un usuario del portal de administración (o restablece su contraseña).

    python scripts/cli_admin/crear_usuario.py

La contraseña se pide sin mostrarse en pantalla y se guarda solo como hash
(werkzeug.security.generate_password_hash).
"""
import getpass
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from werkzeug.security import generate_password_hash  # noqa: E402

from src.persistencia.repositorio_sqlite import ROLES, preparar_base  # noqa: E402

LARGO_MINIMO = 8


def preguntar(texto, defecto=""):
    respuesta = input(f"{texto}{f' [{defecto}]' if defecto else ''}: ").strip()
    return respuesta or defecto


def main():
    base = preparar_base()
    print("=== Usuario del portal de administración ===")
    correo = preguntar("Correo").lower()
    if "@" not in correo:
        print("Correo no válido.")
        return 1
    existente = base.usuario_por_correo(correo)
    if existente:
        print(f"Ya existe ({existente['nombre']}, {existente['rol']}). Se restablecerá su contraseña.")
    else:
        nombre = preguntar("Nombre")
        primero = base.total_usuarios() == 0
        rol = preguntar("Rol (Administrador / Especialista)", "Administrador" if primero else "Especialista")
        rol = rol.capitalize()
        if rol not in ROLES:
            print("Rol no válido.")
            return 1

    while True:
        clave = getpass.getpass(f"Contraseña (mínimo {LARGO_MINIMO} caracteres, no se muestra): ")
        if len(clave) < LARGO_MINIMO:
            print("Muy corta.")
            continue
        if getpass.getpass("Repite la contraseña: ") != clave:
            print("No coinciden.")
            continue
        break

    if existente:
        base.actualizar_usuario(existente["id_usuario"], password_hash=generate_password_hash(clave))
        print("Contraseña actualizada.")
    else:
        base.crear_usuario(nombre or correo, correo, generate_password_hash(clave), rol)
        print(f"Usuario {correo} creado como {rol}.")
    base.cerrar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
