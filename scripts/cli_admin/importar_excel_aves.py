"""
Convierte la planilla de aves de Chile en data/semillas/catalogo_aves_chile.csv y
actualiza las fichas en la base de datos (data/observatorio.db).

Uso (desde la carpeta del proyecto):

    .venv\\Scripts\\python.exe scripts\\cli_admin\\importar_excel_aves.py
    .venv\\Scripts\\python.exe scripts\\cli_admin\\importar_excel_aves.py RUTA\\planilla.xlsx

Excel convierte algunos rangos en fechas: "10-12" se guarda como 10 de
diciembre y "12-14" como diciembre de 2014. Este script los recupera según
el formato de la celda. Para que no vuelva a pasar, da formato Texto a las
columnas Tamano_cm, Peso_g y Envergadura_cm antes de escribir en ellas.
"""
import csv
import datetime
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from config.settings import ARCHIVO_CATALOGO, CARPETA_SEMILLAS  # noqa: E402
from src.persistencia.repositorio_sqlite import BaseDatos  # noqa: E402

ENTRADA = CARPETA_SEMILLAS / "base_datos_aves_chile.xlsx"
SALIDA = ARCHIVO_CATALOGO

COLUMNAS = [
    "ID", "Nombre_Comun", "Nombre_Cientifico", "Genero", "Familia", "Orden",
    "Tamano_cm", "Peso_g", "Envergadura_cm", "Habitat", "Conservacion_UICN",
    "Conservacion_RCE", "Caracteristicas_Distintivas", "Distribucion",
    "Migracion", "Comportamiento", "Alimentacion",
]


def texto_celda(celda):
    valor = celda.value
    if valor is None:
        return "", False
    if isinstance(valor, (datetime.datetime, datetime.date)):
        formato = (celda.number_format or "").lower()
        if formato.startswith("d"):
            # "10-12" leído como día 10 del mes 12.
            return f"{valor.day}-{valor.month}", True
        # "12-14" leído como mes 12 del año 2014.
        return f"{valor.month}-{valor.year % 100}", True
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip(), False


def main():
    try:
        import openpyxl
    except ImportError:
        sys.exit(
            "Falta openpyxl. Instálalo con:\n"
            "    .venv\\Scripts\\python.exe -m pip install openpyxl"
        )

    entrada = Path(sys.argv[1]) if len(sys.argv) > 1 else ENTRADA
    hoja = openpyxl.load_workbook(entrada).worksheets[0]

    encabezado = [str(c.value).strip() if c.value is not None else "" for c in hoja[1]]
    faltan = [c for c in COLUMNAS if c not in encabezado]
    if faltan:
        sys.exit(f"Faltan columnas en la planilla: {', '.join(faltan)}")
    posicion = {nombre: encabezado.index(nombre) for nombre in COLUMNAS}

    filas, recuperadas, vistos = [], [], set()
    for fila in hoja.iter_rows(min_row=2):
        valores = {}
        for nombre, indice in posicion.items():
            texto, era_fecha = texto_celda(fila[indice])
            valores[nombre] = texto
            if era_fecha:
                recuperadas.append((valores.get("Nombre_Comun") or f"fila {fila[0].row}", nombre, texto))
        if not valores["Nombre_Comun"]:
            continue
        cientifico = valores["Nombre_Cientifico"].lower()
        if cientifico in vistos:
            print(f"AVISO - nombre científico repetido, se omite: {valores['Nombre_Cientifico']}")
            continue
        vistos.add(cientifico)
        filas.append(valores)

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(SALIDA, "w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS)
        escritor.writeheader()
        escritor.writerows(filas)

    print(f"{len(filas)} especies guardadas en {SALIDA}")

    base = BaseDatos()
    insertadas, actualizadas = base.cargar_catalogo(SALIDA, actualizar=True)
    base.cerrar()
    print(f"Base de datos: {insertadas} especies nuevas, {actualizadas} fichas actualizadas")
    if recuperadas:
        print(f"{len(recuperadas)} medidas que Excel había convertido en fecha:")
        for nombre, columna, texto in recuperadas:
            print(f"  {nombre}: {columna} = {texto}")


if __name__ == "__main__":
    main()
