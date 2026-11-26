"""
Suma al dataset las aves identificadas a mano en el portal (menú «Por identificar»).

    python laboratorio_ia/scripts_entrenamiento/importar_identificadas.py
    python laboratorio_ia/scripts_entrenamiento/importar_identificadas.py --simular
    python laboratorio_ia/scripts_entrenamiento/importar_identificadas.py --incluir-simulacion

Así se cierra el ciclo de aprendizaje del kiosco:
  1. El kiosco guarda un recorte de cada ave que no reconoce (data/por_identificar/).
  2. Una persona la identifica en el portal (http://127.0.0.1:5000/por-identificar).
  3. Este script copia esas fotos al dataset:
       - Especie que el modelo ya conoce → dataset_aves/<división>/<Especie>/pi_<id>.jpg
         (1 de cada 10 a test, 1 a val, el resto a train). Son fotos de la cámara
         real: las más valiosas para que el modelo funcione en el humedal.
       - Especie nueva → laboratorio_ia/dataset_nuevas/<Nombre común>/ hasta juntar
         suficientes fotos (--minimo-nueva) para agregarla como clase. Si el dataset
         ya tiene la clase «Otra ave», también se copian ahí, para que el modelo
         aprenda a decir «no es ninguna de las especies que conozco».
       - «No es un ave» → laboratorio_ia/dataset_nuevas/_no_es_ave/ (falsos positivos
         del detector, para revisarlos).
  4. Se reentrena y evalúa con entrenar_clasificador.py / evaluar_clasificador.py
     (ver laboratorio_ia/ENTRENAMIENTO.md) y se despliega solo si mejora.

El reentrenamiento NO es automático a propósito: una etiqueta equivocada o un
modelo peor no deben llegar al kiosco sin que una persona revise la evaluación.

Por defecto solo usa registros de la cámara real; --incluir-simulacion agrega
los del video de demostración y de la captura de pantalla.
Se puede ejecutar las veces que se quiera: no repite fotos ya copiadas.
"""
import argparse
import shutil
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
LABORATORIO = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

DATASET = LABORATORIO / "dataset_aves"
NUEVAS = LABORATORIO / "dataset_nuevas"
CLASE_OTRA_AVE = "Otra ave"
DIVISIONES = ("train", "val", "test")


def division_de(id_registro):
    """Reparto fijo por id: 10 % test, 10 % val, 80 % train (no cambia entre ejecuciones)."""
    resto = id_registro % 10
    return "test" if resto == 0 else "val" if resto == 1 else "train"


def ya_copiada(nombre):
    carpetas = [DATASET / d for d in DIVISIONES] + [NUEVAS]
    return any(next(carpeta.glob(f"*/{nombre}"), None) is not None for carpeta in carpetas)


def copiar(origen, destino, simular):
    if destino.exists():
        return False
    if not simular:
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origen, destino)
    return True


def main(argumentos=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", type=Path, default=None, help="Base de datos (por defecto data/observatorio.db)")
    parser.add_argument("--incluir-simulacion", action="store_true",
                        help="También usa lo registrado con el video de demostración o la captura de pantalla")
    parser.add_argument("--minimo-nueva", type=int, default=60,
                        help="Fotos de una especie nueva para considerarla lista para agregarla como clase")
    parser.add_argument("--simular", action="store_true", help="Muestra qué haría sin copiar nada")
    args = parser.parse_args(argumentos)

    from laboratorio_ia.scripts_entrenamiento.descargar_fotos_inaturalist import ESPECIES
    from src.persistencia.repositorio_sqlite import BaseDatos, ruta_absoluta

    carpeta_de = {n.casefold(): carpeta for carpeta, nombres in ESPECIES.items() for n in nombres}
    hay_otra_ave = (DATASET / "train" / CLASE_OTRA_AVE).is_dir()
    base = BaseDatos(args.base)
    try:
        filas = base.identificadas_para_entrenar()
    finally:
        base.cerrar()

    copiadas, omitidas = Counter(), Counter()
    for fila in filas:
        if fila["es_simulacion"] and not args.incluir_simulacion:
            omitidas["simulación (usa --incluir-simulacion)"] += 1
            continue
        origen = ruta_absoluta(fila["ruta_captura"])
        if origen is None or not Path(origen).is_file():
            omitidas["falta el archivo"] += 1
            continue
        nombre = f"pi_{fila['id_registro']}.jpg"
        if ya_copiada(nombre):
            omitidas["ya estaba en el dataset"] += 1
            continue
        division = division_de(fila["id_registro"])
        if fila["estado"] == "no_es_ave":
            destinos = [NUEVAS / "_no_es_ave" / nombre]
            etiqueta = "No es un ave"
        elif (fila["nombre_cientifico"] or "").casefold() in carpeta_de:
            carpeta = carpeta_de[fila["nombre_cientifico"].casefold()]
            destinos = [DATASET / division / carpeta / nombre]
            etiqueta = carpeta
        else:
            destinos = [NUEVAS / fila["nombre_comun"] / nombre]
            if hay_otra_ave:
                destinos.append(DATASET / division / CLASE_OTRA_AVE / nombre)
            etiqueta = f"{fila['nombre_comun']} (nueva)"
        if any([copiar(origen, d, args.simular) for d in destinos]):
            copiadas[etiqueta] += 1

    verbo = "Se copiarían" if args.simular else "Copiadas"
    print(f"{verbo} {sum(copiadas.values())} fotos identificadas:")
    for etiqueta, n in sorted(copiadas.items()):
        print(f"  {etiqueta}: {n}")
    for motivo, n in omitidas.items():
        print(f"  omitidas ({motivo}): {n}")

    if NUEVAS.is_dir():
        nuevas = {p.name: sum(1 for _ in p.glob("*.jpg")) for p in NUEVAS.iterdir() if p.is_dir() and p.name != "_no_es_ave"}
        if nuevas:
            lugar = NUEVAS.relative_to(RAIZ) if NUEVAS.is_relative_to(RAIZ) else NUEVAS
            print(f"\nEspecies nuevas acumuladas en {lugar} (mínimo {args.minimo_nueva} para agregarlas):")
            for especie, n in sorted(nuevas.items(), key=lambda e: -e[1]):
                estado = "LISTA para agregar como clase" if n >= args.minimo_nueva else f"faltan {args.minimo_nueva - n}"
                print(f"  {especie}: {n} fotos · {estado}")
            print("Para agregar una especie lista: reparte sus fotos en dataset_aves/{train,val,test}/<Nombre común>/ "
                  "(mín. 20 en val y en test), completa con descargar_fotos.bat si faltan, y entrena con --forzar.")
    if copiadas and not args.simular:
        print("\nSiguiente paso: reentrenar y comparar con el modelo actual (laboratorio_ia/ENTRENAMIENTO.md, sección 7).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
