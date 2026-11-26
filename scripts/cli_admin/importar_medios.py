"""
Asigna fotos y cantos a las especies del catálogo de una sola vez.

1. Copia las fotos en  assets/fotos/   y los cantos en  assets/sonidos/
2. Nombra cada archivo con el nombre científico o el nombre común de la especie:
       Fulica armillata.jpg      Tagua común.jpg      tagua_comun.png
       Cygnus melancoryphus.mp3  Cisne de cuello negro.wav
   (no importan mayúsculas, tildes, espacios ni guiones bajos)
3. Ejecuta  scripts\\lanzadores_windows\\importar_medios.bat

Fotos: .jpg .jpeg .png .webp  ·  Cantos: .wav .ogg .mp3
Sin Pygame, el kiosco solo reproduce .wav.

Opciones:
    --reemplazar   también cambia especies que ya tenían foto o canto
    --simular      muestra qué haría, sin guardar nada
"""
import argparse
import re
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from config.settings import CARPETA_FOTOS, CARPETA_SONIDOS  # noqa: E402
from src.persistencia.repositorio_sqlite import ahora_texto, preparar_base, ruta_relativa  # noqa: E402

FOTOS = CARPETA_FOTOS
SONIDOS = CARPETA_SONIDOS
EXT_FOTO = {".jpg", ".jpeg", ".png", ".webp"}
EXT_AUDIO = {".wav", ".ogg", ".mp3"}


def clave(texto):
    texto = unicodedata.normalize("NFKD", str(texto).lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", texto)


def main():
    parser = argparse.ArgumentParser(description="Asigna fotos y cantos al catálogo")
    parser.add_argument("--reemplazar", action="store_true")
    parser.add_argument("--simular", action="store_true")
    args = parser.parse_args()

    base = preparar_base()
    indice = {}
    for e in base.especies():
        indice[clave(e["nombre_cientifico"])] = e
        indice.setdefault(clave(e["nombre_comun"]), e)

    resumen = {"foto": 0, "audio": 0, "omitidos": 0}
    sin_especie = []
    for carpeta, extensiones, campo, tipo in (
        (FOTOS, EXT_FOTO, "ruta_foto", "foto"),
        (SONIDOS, EXT_AUDIO, "ruta_audio_canto", "audio"),
    ):
        carpeta.mkdir(parents=True, exist_ok=True)
        for archivo in sorted(carpeta.iterdir()):
            if archivo.suffix.lower() not in extensiones:
                continue
            especie = indice.get(clave(archivo.stem))
            if especie is None:
                try:
                    sin_especie.append(archivo.relative_to(RAIZ).as_posix())
                except ValueError:
                    sin_especie.append(archivo.as_posix())
                continue
            ruta = ruta_relativa(archivo)
            if especie.get(campo) == ruta:
                continue
            if especie.get(campo) and not args.reemplazar:
                print(f"  ya tiene {tipo}: {especie['nombre_comun']} ({especie[campo]}) — usa --reemplazar")
                resumen["omitidos"] += 1
                continue
            print(f"  {tipo:5} {especie['nombre_comun']:30} <- {ruta}")
            if not args.simular:
                with base.conexion:
                    base.conexion.execute(
                        f"UPDATE ESPECIE_AVE SET {campo} = ?, fecha_actualizacion = ? WHERE id_especie = ?",
                        (ruta, ahora_texto(), especie["id_especie"]),
                    )
                especie[campo] = ruta
            resumen[tipo] += 1

    print(f"\nFotos asignadas: {resumen['foto']} · Cantos asignados: {resumen['audio']} · "
          f"Omitidos (ya tenían): {resumen['omitidos']}")
    if sin_especie:
        print("\nEstos archivos no coinciden con ninguna especie (revisa el nombre):")
        for ruta in sin_especie:
            print("  -", ruta)
    total = base.total_especies()
    con_foto = base._uno("SELECT COUNT(*) AS n FROM ESPECIE_AVE WHERE ruta_foto <> ''")["n"]
    con_audio = base._uno("SELECT COUNT(*) AS n FROM ESPECIE_AVE WHERE ruta_audio_canto <> ''")["n"]
    print(f"\nCatálogo: {con_foto} de {total} con foto · {con_audio} de {total} con canto")
    if args.simular:
        print("(simulación: no se guardó nada)")
    base.cerrar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
