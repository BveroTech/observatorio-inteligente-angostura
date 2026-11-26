import csv
import json
import sqlite3
import time
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from config.settings import (
    ARCHIVO_BASE_DATOS,
    ARCHIVO_CATALOGO,
    BASE_DIR,
    CARPETA_CAPTURAS,
    CARPETA_SONIDOS_SIMULADOR,
    RECURSOS_DIR,
)

FORMATO_FECHA = "%Y-%m-%d %H:%M:%S"
ROLES = ("Administrador", "Especialista")
ESTADOS_CAMARA = ("ONLINE", "RECONECTANDO", "FAILOVER_DEMO", "SIN_SENAL")
TIEMPO_ESPERA_SQLITE = 10
PERMITE_RETIRAR_ADMIN = (
    " AND (rol <> 'Administrador' OR EXISTS (SELECT 1 FROM USUARIO_ADMIN otro"
    " WHERE otro.rol = 'Administrador' AND otro.id_usuario <> USUARIO_ADMIN.id_usuario))"
)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS USUARIO_ADMIN (
    id_usuario      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre          VARCHAR(100) NOT NULL,
    correo          VARCHAR(120) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    rol             VARCHAR(30)  NOT NULL DEFAULT 'Administrador'
                    CHECK (rol IN ('Administrador', 'Especialista')),
    ultimo_login    DATETIME
);

CREATE TABLE IF NOT EXISTS ESPECIE_AVE (
    id_especie          INTEGER PRIMARY KEY,
    nombre_comun        VARCHAR(100) NOT NULL,
    nombre_cientifico   VARCHAR(120) NOT NULL UNIQUE,
    genero              VARCHAR(60),
    familia             VARCHAR(60),
    orden               VARCHAR(60),
    tamano_cm           VARCHAR(30),
    peso_g              VARCHAR(30),
    envergadura_cm      VARCHAR(30),
    habitat             TEXT,
    conservacion_uicn   VARCHAR(50),
    conservacion_rce    VARCHAR(50),
    caracteristicas     TEXT,
    distribucion        TEXT,
    migracion           TEXT,
    comportamiento      TEXT,
    alimentacion        TEXT,
    ruta_audio_canto    VARCHAR(255),
    ruta_foto           VARCHAR(255),
    activo              BOOLEAN NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    actualizado_por     INTEGER REFERENCES USUARIO_ADMIN (id_usuario) ON DELETE SET NULL,
    fecha_actualizacion DATETIME
);
CREATE INDEX IF NOT EXISTS idx_especie_nombre ON ESPECIE_AVE (nombre_comun);
CREATE INDEX IF NOT EXISTS idx_especie_familia ON ESPECIE_AVE (familia);

CREATE TABLE IF NOT EXISTS HISTORIAL_AVISTAMIENTO (
    id_avistamiento     INTEGER PRIMARY KEY AUTOINCREMENT,
    id_especie          INTEGER NOT NULL REFERENCES ESPECIE_AVE (id_especie),
    timestamp_deteccion DATETIME NOT NULL DEFAULT (datetime('now', 'localtime')),
    nivel_confianza     REAL NOT NULL CHECK (nivel_confianza BETWEEN 0.0 AND 1.0),
    ancho_bbox_px       INTEGER NOT NULL CHECK (ancho_bbox_px > 0),
    alto_bbox_px        INTEGER NOT NULL CHECK (alto_bbox_px > 0),
    area_px             INTEGER NOT NULL,
    es_simulacion       BOOLEAN NOT NULL DEFAULT 0 CHECK (es_simulacion IN (0, 1)),
    ruta_captura_thumb  VARCHAR(255)
);
CREATE INDEX IF NOT EXISTS idx_avistamiento_fecha ON HISTORIAL_AVISTAMIENTO (timestamp_deteccion);
CREATE INDEX IF NOT EXISTS idx_avistamiento_especie ON HISTORIAL_AVISTAMIENTO (id_especie);

CREATE TABLE IF NOT EXISTS METRICA_SISTEMA (
    id_metrica                INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_registro            DATETIME NOT NULL DEFAULT (datetime('now', 'localtime')),
    fps_promedio              REAL,
    inferencia_ms_promedio    REAL,
    inferencia_ms_maximo      REAL,
    estado_camara             VARCHAR(30) NOT NULL
                              CHECK (estado_camara IN ('ONLINE', 'RECONECTANDO', 'FAILOVER_DEMO', 'SIN_SENAL')),
    total_detecciones         INTEGER NOT NULL DEFAULT 0,
    total_descartes_px        INTEGER NOT NULL DEFAULT 0,
    total_descartes_confianza INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_metrica_fecha ON METRICA_SISTEMA (fecha_registro);

-- Aves que el modelo no reconoció. Una persona las identifica en el portal y
-- esas fotos (de la cámara real) se suman al próximo entrenamiento.
CREATE TABLE IF NOT EXISTS AVE_POR_IDENTIFICAR (
    id_registro         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_deteccion DATETIME NOT NULL DEFAULT (datetime('now', 'localtime')),
    ruta_captura        VARCHAR(255) NOT NULL,
    clase_sugerida      VARCHAR(100),
    confianza_sugerida  REAL CHECK (confianza_sugerida IS NULL OR confianza_sugerida BETWEEN 0.0 AND 1.0),
    motivo              VARCHAR(30) NOT NULL CHECK (motivo IN ('baja_confianza', 'sin_ficha', 'otra_ave')),
    ancho_bbox_px       INTEGER,
    alto_bbox_px        INTEGER,
    es_simulacion       BOOLEAN NOT NULL DEFAULT 0 CHECK (es_simulacion IN (0, 1)),
    estado              VARCHAR(20) NOT NULL DEFAULT 'pendiente'
                        CHECK (estado IN ('pendiente', 'identificada', 'no_es_ave', 'descartada')),
    id_especie          INTEGER REFERENCES ESPECIE_AVE (id_especie) ON DELETE SET NULL,
    revisado_por        INTEGER REFERENCES USUARIO_ADMIN (id_usuario) ON DELETE SET NULL,
    fecha_revision      DATETIME
);
CREATE INDEX IF NOT EXISTS idx_por_identificar_estado ON AVE_POR_IDENTIFICAR (estado, timestamp_deteccion);

CREATE TABLE IF NOT EXISTS FICHA_TRADUCCION (
    id_especie          INTEGER NOT NULL REFERENCES ESPECIE_AVE (id_especie) ON DELETE CASCADE,
    idioma              VARCHAR(2) NOT NULL CHECK (idioma IN ('en', 'de')),
    campo               VARCHAR(30) NOT NULL,
    texto               TEXT,
    huella_original     VARCHAR(16),
    manual              BOOLEAN NOT NULL DEFAULT 0 CHECK (manual IN (0, 1)),
    actualizado_por     INTEGER REFERENCES USUARIO_ADMIN (id_usuario) ON DELETE SET NULL,
    fecha_actualizacion DATETIME,
    PRIMARY KEY (id_especie, idioma, campo)
);
"""

ESTADOS_POR_IDENTIFICAR = ("pendiente", "identificada", "no_es_ave", "descartada")

# Columna de la planilla -> columna de ESPECIE_AVE.
COLUMNAS_PLANILLA = {
    "ID": "id_especie",
    "Nombre_Comun": "nombre_comun",
    "Nombre_Cientifico": "nombre_cientifico",
    "Genero": "genero",
    "Familia": "familia",
    "Orden": "orden",
    "Tamano_cm": "tamano_cm",
    "Peso_g": "peso_g",
    "Envergadura_cm": "envergadura_cm",
    "Habitat": "habitat",
    "Conservacion_UICN": "conservacion_uicn",
    "Conservacion_RCE": "conservacion_rce",
    "Caracteristicas_Distintivas": "caracteristicas",
    "Distribucion": "distribucion",
    "Migracion": "migracion",
    "Comportamiento": "comportamiento",
    "Alimentacion": "alimentacion",
}
CAMPOS_EDITABLES = [c for c in COLUMNAS_PLANILLA.values() if c != "id_especie"] + [
    "ruta_audio_canto",
    "ruta_foto",
    "activo",
]


# Campos de la ficha que se muestran traducidos (inglés y alemán). Las medidas,
# la taxonomía y el nombre científico son iguales en todos los idiomas.
CAMPOS_TRADUCIBLES = [
    "nombre_comun", "caracteristicas", "habitat", "distribucion", "migracion",
    "comportamiento", "alimentacion", "conservacion_uicn", "conservacion_rce",
]
IDIOMAS_TRADUCCION = ("en", "de")


class ConflictoEdicion(Exception):
    """Otra conexión modificó la ficha antes de que se guardara."""


def revision_ficha(especie):
    campos = [especie.get(campo) for campo in CAMPOS_EDITABLES]
    contenido = json.dumps(campos, ensure_ascii=False).encode("utf-8")
    return sha256(contenido).hexdigest()


def ahora_texto(momento=None):
    if momento is None:
        momento = datetime.now()
    elif not isinstance(momento, datetime):
        momento = datetime.fromtimestamp(momento)
    elif momento.tzinfo is not None:
        momento = momento.astimezone()
    return momento.strftime(FORMATO_FECHA)


def limites_dia(dia=None):
    """Devuelve el día calendario local y los límites ISO del intervalo semiabierto."""
    if dia is None:
        dia = date.today()
    elif isinstance(dia, datetime):
        dia = (dia.astimezone() if dia.tzinfo is not None else dia).date()
    elif isinstance(dia, str):
        dia = date.fromisoformat(dia)
    return dia, dia.isoformat(), (dia + timedelta(days=1)).isoformat()


def ruta_relativa(ruta):
    """Ruta relativa a la carpeta del proyecto, con barras normales."""
    if not ruta:
        return ""
    ruta = Path(ruta)
    for base in (BASE_DIR, RECURSOS_DIR):
        try:
            return ruta.resolve().relative_to(base.resolve()).as_posix()
        except ValueError:
            pass
    return ruta.as_posix()


def ruta_absoluta(ruta):
    """
    Convierte una ruta relativa almacenada en la base de datos o JSON en Path absoluto,
    con soporte para PyInstaller (`sys._MEIPASS`) y compatibilidad con rutas heredadas
    (`capturas/...` -> `data/capturas/...`).
    """
    if not ruta:
        return None
    ruta_path = Path(ruta)
    if ruta_path.is_absolute():
        return ruta_path

    texto_posix = str(ruta).replace("\\", "/")
    candidatos = [BASE_DIR / ruta_path]
    if RECURSOS_DIR != BASE_DIR:
        candidatos.append(RECURSOS_DIR / ruta_path)

    # Compatibilidad con rutas de capturas previas a la migración a data/capturas/
    if texto_posix.startswith("capturas/"):
        subruta = texto_posix[len("capturas/"):]
        candidatos.append(CARPETA_CAPTURAS / subruta)
    elif texto_posix.startswith("data/capturas/"):
        subruta = texto_posix[len("data/capturas/"):]
        candidatos.append(CARPETA_CAPTURAS / subruta)
        candidatos.append(BASE_DIR / "capturas" / subruta)

    # Compatibilidad con audios ubicados en laboratorio_ia/simulador_pantalla2/sonidos/
    if texto_posix.startswith("assets/sonidos/"):
        nombre_audio = Path(texto_posix).name
        candidatos.append(CARPETA_SONIDOS_SIMULADOR / nombre_audio)

    for candidato in candidatos:
        if candidato.exists():
            return candidato
    return candidatos[0]


class BaseDatos:
    def __init__(self, ruta=None, inicializar_esquema=False):
        self.ruta = Path(ruta) if ruta else ARCHIVO_BASE_DATOS
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.conexion = sqlite3.connect(str(self.ruta), timeout=TIEMPO_ESPERA_SQLITE, check_same_thread=False)
        try:
            self.conexion.row_factory = sqlite3.Row
            self.conexion.execute("PRAGMA foreign_keys = ON")
            self._activar_wal()
            self.conexion.execute("PRAGMA synchronous = NORMAL")

            if inicializar_esquema or not self._esquema_presente():
                self.conexion.executescript(ESQUEMA)
                self._migrar_rutas_capturas()
        except BaseException:
            self.conexion.close()
            raise

    def _activar_wal(self):
        """La transición inicial a WAL puede devolver SQLITE_BUSY sin esperar."""
        limite = time.monotonic() + TIEMPO_ESPERA_SQLITE
        while True:
            try:
                self.conexion.execute("PRAGMA journal_mode = WAL").fetchone()
                return
            except sqlite3.OperationalError as error:
                codigo = error.sqlite_errorcode & 0xFF
                if codigo not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or time.monotonic() >= limite:
                    raise
                time.sleep(0.025)

    def _esquema_presente(self):
        try:
            filas = self.conexion.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name IN ('METRICA_SISTEMA', 'AVE_POR_IDENTIFICAR', 'FICHA_TRADUCCION')"
            ).fetchone()
            return filas[0] == 3
        except sqlite3.Error:
            return False

    def _migrar_rutas_capturas(self):
        """Actualiza rutas heredadas únicamente si el archivo se movió."""
        try:
            pendientes = self._todos(
                "SELECT DISTINCT ruta_captura_thumb FROM HISTORIAL_AVISTAMIENTO "
                "WHERE ruta_captura_thumb LIKE 'capturas/%'"
            )
            movidas = []
            for fila in pendientes:
                ruta = fila["ruta_captura_thumb"]
                if not (BASE_DIR / ruta).is_file() and (CARPETA_CAPTURAS / ruta[len("capturas/"):]).is_file():
                    movidas.append(("data/" + ruta, ruta))
            if movidas:
                with self.conexion:
                    self.conexion.executemany(
                        "UPDATE HISTORIAL_AVISTAMIENTO SET ruta_captura_thumb = ? WHERE ruta_captura_thumb = ?",
                        movidas,
                    )
        except sqlite3.Error:
            pass

    def cerrar(self):
        try:
            self.conexion.close()
        except sqlite3.Error:
            pass

    def _uno(self, consulta, parametros=()):
        fila = self.conexion.execute(consulta, parametros).fetchone()
        return dict(fila) if fila else None

    def _todos(self, consulta, parametros=()):
        return [dict(fila) for fila in self.conexion.execute(consulta, parametros)]

    def version_datos(self):
        """Cambia cuando otra conexión confirma escrituras en esta base."""
        return self.conexion.execute("PRAGMA data_version").fetchone()[0]

    # ------------------------------------------------------
    # Catálogo
    # ------------------------------------------------------

    def cargar_catalogo(self, ruta_csv=None, actualizar=False, *, solo_vacio=False):
        """
        Carga las especies de la planilla. Sin `actualizar`, solo agrega las
        que faltan y no toca las que el personal ya editó.
        Devuelve (insertadas, actualizadas).
        """
        ruta_csv = Path(ruta_csv) if ruta_csv else ARCHIVO_CATALOGO
        insertadas = actualizadas = 0
        with self.conexion:
            if not self.conexion.in_transaction:
                self.conexion.execute("BEGIN IMMEDIATE")
            if solo_vacio and self.total_especies():
                return 0, 0
            with open(ruta_csv, "r", newline="", encoding="utf-8-sig") as archivo:
                for fila in csv.DictReader(archivo):
                    datos = {
                        destino: (fila.get(origen) or "").strip()
                        for origen, destino in COLUMNAS_PLANILLA.items()
                    }
                    if not datos["nombre_comun"] or not datos["nombre_cientifico"]:
                        continue
                    datos["id_especie"] = int(datos["id_especie"]) if datos["id_especie"].isdigit() else None
                    existente = self._uno(
                        "SELECT id_especie FROM ESPECIE_AVE WHERE lower(nombre_cientifico) = lower(?)",
                        (datos["nombre_cientifico"],),
                    )
                    if existente is None:
                        columnas = [c for c in datos if datos[c] not in (None, "")]
                        self.conexion.execute(
                            f"INSERT INTO ESPECIE_AVE ({', '.join(columnas)}) "
                            f"VALUES ({', '.join('?' for _ in columnas)})",
                            [datos[c] for c in columnas],
                        )
                        insertadas += 1
                    elif actualizar:
                        columnas = [c for c in datos if c not in ("id_especie", "nombre_cientifico")]
                        self.conexion.execute(
                            f"UPDATE ESPECIE_AVE SET {', '.join(f'{c} = ?' for c in columnas)} "
                            "WHERE id_especie = ?",
                            [datos[c] for c in columnas] + [existente["id_especie"]],
                        )
                        actualizadas += 1
        return insertadas, actualizadas

    def total_especies(self, solo_activas=False):
        consulta = "SELECT COUNT(*) AS n FROM ESPECIE_AVE"
        if solo_activas:
            consulta += " WHERE activo = 1"
        return self._uno(consulta)["n"]

    def especie(self, id_especie):
        return self._uno("SELECT * FROM ESPECIE_AVE WHERE id_especie = ?", (id_especie,))

    def especie_por_cientifico(self, nombre_cientifico):
        return self._uno(
            "SELECT * FROM ESPECIE_AVE WHERE lower(nombre_cientifico) = lower(?)",
            (nombre_cientifico,),
        )

    def especies(self, texto="", solo_activas=False, limite=None, desplazamiento=0):
        condiciones, parametros = [], []
        if texto:
            patron = f"%{texto.strip()}%"
            condiciones.append(
                "(nombre_comun LIKE ? OR nombre_cientifico LIKE ? OR familia LIKE ? OR orden LIKE ?)"
            )
            parametros += [patron] * 4
        if solo_activas:
            condiciones.append("activo = 1")
        consulta = "SELECT * FROM ESPECIE_AVE"
        if condiciones:
            consulta += " WHERE " + " AND ".join(condiciones)
        consulta += " ORDER BY nombre_comun COLLATE NOCASE"
        if limite:
            consulta += " LIMIT ? OFFSET ?"
            parametros += [int(limite), int(desplazamiento)]
        return self._todos(consulta, parametros)

    def contar_especies(self, texto="", solo_activas=False):
        condiciones, parametros = [], []
        if texto:
            patron = f"%{texto.strip()}%"
            condiciones.append(
                "(nombre_comun LIKE ? OR nombre_cientifico LIKE ? OR familia LIKE ? OR orden LIKE ?)"
            )
            parametros += [patron] * 4
        if solo_activas:
            condiciones.append("activo = 1")
        consulta = "SELECT COUNT(*) AS n FROM ESPECIE_AVE"
        if condiciones:
            consulta += " WHERE " + " AND ".join(condiciones)
        return self._uno(consulta, parametros)["n"]

    def guardar_especie(self, datos, id_usuario=None, id_especie=None, *, revision=None):
        """Crea o actualiza una especie. Devuelve su id."""
        datos = {c: datos.get(c) for c in CAMPOS_EDITABLES if c in datos}
        datos["actualizado_por"] = id_usuario
        datos["fecha_actualizacion"] = ahora_texto()
        with self.conexion:
            if not self.conexion.in_transaction:
                self.conexion.execute("BEGIN IMMEDIATE")
            if id_especie is not None and revision is not None:
                actual = self.especie(id_especie)
                if actual is None:
                    raise LookupError(id_especie)
                if revision_ficha(actual) != revision:
                    raise ConflictoEdicion(id_especie)
            nombre = datos.get("nombre_cientifico")
            if nombre:
                otra = self._uno(
                    "SELECT id_especie FROM ESPECIE_AVE WHERE lower(nombre_cientifico) = lower(?) "
                    "AND id_especie IS NOT ?",
                    (nombre, id_especie),
                )
                if otra:
                    raise sqlite3.IntegrityError("El nombre científico ya existe")
            if id_especie is None:
                columnas = list(datos)
                cursor = self.conexion.execute(
                    f"INSERT INTO ESPECIE_AVE ({', '.join(columnas)}) "
                    f"VALUES ({', '.join('?' for _ in columnas)})",
                    [datos[c] for c in columnas],
                )
                return cursor.lastrowid
            cursor = self.conexion.execute(
                f"UPDATE ESPECIE_AVE SET {', '.join(f'{c} = ?' for c in datos)} WHERE id_especie = ?",
                list(datos.values()) + [id_especie],
            )
            if not cursor.rowcount:
                raise LookupError(id_especie)
        return id_especie

    # ------------------------------------------------------------------
    # Traducciones de la ficha (inglés y alemán)
    # ------------------------------------------------------------------

    def traducciones(self, id_especie, idioma):
        """{campo: fila} de la traducción de una especie a un idioma."""
        filas = self._todos(
            "SELECT * FROM FICHA_TRADUCCION WHERE id_especie = ? AND idioma = ?", (id_especie, idioma))
        return {fila["campo"]: fila for fila in filas}

    def guardar_traduccion(self, id_especie, idioma, campo, texto, huella_original, manual=False, id_usuario=None):
        if idioma not in IDIOMAS_TRADUCCION or campo not in CAMPOS_TRADUCIBLES:
            raise ValueError(f"Traducción no válida: {idioma}/{campo}")
        with self.conexion:
            self.conexion.execute(
                "INSERT INTO FICHA_TRADUCCION (id_especie, idioma, campo, texto, huella_original, manual, "
                "actualizado_por, fecha_actualizacion) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (id_especie, idioma, campo) DO UPDATE SET texto = excluded.texto, "
                "huella_original = excluded.huella_original, manual = excluded.manual, "
                "actualizado_por = excluded.actualizado_por, fecha_actualizacion = excluded.fecha_actualizacion",
                (id_especie, idioma, campo, texto, huella_original, 1 if manual else 0, id_usuario, ahora_texto()),
            )

    def especie_en_idioma(self, id_especie, idioma):
        """La ficha con los campos traducidos; lo que falte queda en español."""
        especie = self.especie(id_especie)
        if especie is None or idioma not in IDIOMAS_TRADUCCION:
            return especie
        return aplicar_traduccion(especie, self.traducciones(id_especie, idioma))

    def mapa_traducciones(self, idioma):
        """{id_especie: {campo: texto}} de todo el catálogo en un idioma (una sola consulta)."""
        resultado = {}
        if idioma not in IDIOMAS_TRADUCCION:
            return resultado
        for fila in self._todos("SELECT id_especie, campo, texto FROM FICHA_TRADUCCION WHERE idioma = ?", (idioma,)):
            if fila["texto"]:
                resultado.setdefault(fila["id_especie"], {})[fila["campo"]] = fila["texto"]
        return resultado

    def resumen_traducciones(self):
        """{idioma: especies con al menos un campo traducido}."""
        return {fila["idioma"]: fila["total"] for fila in self._todos(
            "SELECT idioma, COUNT(DISTINCT id_especie) AS total FROM FICHA_TRADUCCION GROUP BY idioma")}

    def eliminar_especie(self, id_especie):
        """Elimina una especie sin avistamientos. Si tiene historial, la base
        lo impide (llave foránea) y se lanza sqlite3.IntegrityError: en ese
        caso corresponde desactivarla."""
        with self.conexion:
            cursor = self.conexion.execute("DELETE FROM ESPECIE_AVE WHERE id_especie = ?", (id_especie,))
        return bool(cursor.rowcount)

    def cambiar_activo(self, id_especie, activo, id_usuario=None):
        """Establece el estado o lo alterna atómicamente si activo es None."""
        with self.conexion:
            fila = self._uno(
                "UPDATE ESPECIE_AVE SET activo = COALESCE(?, 1 - activo), "
                "actualizado_por = ?, fecha_actualizacion = ? WHERE id_especie = ? "
                "RETURNING activo, nombre_comun",
                (int(bool(activo)) if activo is not None else None, id_usuario, ahora_texto(), id_especie),
            )
        return fila

    def familias(self):
        return [f["familia"] for f in self._todos(
            "SELECT DISTINCT familia FROM ESPECIE_AVE WHERE familia <> '' ORDER BY familia")]

    def distractores(self, id_especie, cantidad=2, excluir=()):
        """Especies activas para las alternativas incorrectas de la trivia,
        primero de la misma familia, luego del mismo orden y luego cualquiera."""
        base = self.especie(id_especie)
        if base is None:
            return []
        elegidas, vistos = [], {id_especie, *excluir}
        for campo in ("familia", "orden", None):
            if len(elegidas) >= cantidad:
                break
            consulta = "SELECT * FROM ESPECIE_AVE WHERE activo = 1"
            parametros = []
            if campo:
                consulta += f" AND {campo} = ?"
                parametros.append(base[campo])
            consulta += " ORDER BY random() LIMIT 20"
            for fila in self._todos(consulta, parametros):
                if fila["id_especie"] not in vistos:
                    elegidas.append(fila)
                    vistos.add(fila["id_especie"])
                if len(elegidas) >= cantidad:
                    break
        return elegidas

    # ------------------------------------------------------
    # Avistamientos
    # ------------------------------------------------------

    # ------------------------------------------------------
    # Aves por identificar
    # ------------------------------------------------------

    def registrar_por_identificar(self, ruta_captura, motivo, clase_sugerida=None, confianza=None,
                                  ancho=None, alto=None, es_simulacion=False, momento=None):
        with self.conexion:
            cursor = self.conexion.execute(
                "INSERT INTO AVE_POR_IDENTIFICAR (timestamp_deteccion, ruta_captura, clase_sugerida, "
                "confianza_sugerida, motivo, ancho_bbox_px, alto_bbox_px, es_simulacion) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ahora_texto(momento), ruta_relativa(ruta_captura), clase_sugerida,
                    None if confianza is None else round(min(max(float(confianza), 0.0), 1.0), 4),
                    motivo, ancho, alto, 1 if es_simulacion else 0,
                ),
            )
        return cursor.lastrowid

    def contar_por_identificar(self, estado="pendiente", desde=None):
        consulta, valores = "SELECT COUNT(*) AS n FROM AVE_POR_IDENTIFICAR WHERE 1 = 1", []
        if estado:
            consulta += " AND estado = ?"
            valores.append(estado)
        if desde:
            consulta += " AND timestamp_deteccion >= ?"
            valores.append(desde)
        return self._uno(consulta, valores)["n"]

    def por_identificar(self, estado="pendiente", limite=50, desplazamiento=0):
        consulta = (
            "SELECT p.*, e.nombre_comun, e.nombre_cientifico, u.nombre AS revisor "
            "FROM AVE_POR_IDENTIFICAR p "
            "LEFT JOIN ESPECIE_AVE e ON e.id_especie = p.id_especie "
            "LEFT JOIN USUARIO_ADMIN u ON u.id_usuario = p.revisado_por "
        )
        valores = []
        if estado:
            consulta += "WHERE p.estado = ? "
            valores.append(estado)
        orden = "ASC" if estado == "pendiente" else "DESC"
        consulta += f"ORDER BY p.timestamp_deteccion {orden}, p.id_registro {orden} LIMIT ? OFFSET ?"
        return self._todos(consulta, valores + [int(limite), int(desplazamiento)])

    def resolver_por_identificar(self, id_registro, estado, id_especie=None, id_usuario=None):
        """Marca un registro como identificado (con su especie), no_es_ave, descartado o pendiente."""
        if estado not in ESTADOS_POR_IDENTIFICAR:
            raise ValueError(f"Estado no válido: {estado}")
        if estado == "identificada" and id_especie is None:
            raise ValueError("Falta la especie.")
        especie = id_especie if estado == "identificada" else None
        with self.conexion:
            cursor = self.conexion.execute(
                "UPDATE AVE_POR_IDENTIFICAR SET estado = ?, id_especie = ?, revisado_por = ?, fecha_revision = ? "
                "WHERE id_registro = ? AND (? IS NULL OR EXISTS (SELECT 1 FROM ESPECIE_AVE WHERE id_especie = ?))",
                (
                    estado, especie,
                    None if estado == "pendiente" else id_usuario,
                    None if estado == "pendiente" else ahora_texto(),
                    id_registro, especie, especie,
                ),
            )
        return cursor.rowcount == 1

    def identificadas_para_entrenar(self):
        return self._todos(
            "SELECT p.id_registro, p.ruta_captura, p.estado, p.es_simulacion, e.id_especie, e.nombre_comun, "
            "e.nombre_cientifico FROM AVE_POR_IDENTIFICAR p LEFT JOIN ESPECIE_AVE e ON e.id_especie = p.id_especie "
            "WHERE p.estado IN ('identificada', 'no_es_ave') ORDER BY p.id_registro"
        )

    def especies_para_identificar(self):
        """Todo el catálogo (activas o no), para elegir la especie de un ave desconocida."""
        return self._todos(
            "SELECT id_especie, nombre_comun, nombre_cientifico, activo FROM ESPECIE_AVE "
            "ORDER BY nombre_comun COLLATE NOCASE"
        )

    def registrar_avistamiento(
        self, id_especie, confianza, ancho, alto, es_simulacion=False, ruta_thumb="", momento=None,
        *, nombre_cientifico=None,
    ):
        """Registra solo especies activas, incluso si otro proceso modifica el catálogo."""
        with self.conexion:
            cursor = self.conexion.execute(
                "INSERT INTO HISTORIAL_AVISTAMIENTO (id_especie, timestamp_deteccion, nivel_confianza, "
                "ancho_bbox_px, alto_bbox_px, area_px, es_simulacion, ruta_captura_thumb) "
                "SELECT id_especie, ?, ?, ?, ?, ?, ?, ? FROM ESPECIE_AVE WHERE id_especie = ? AND activo = 1 "
                "AND (? IS NULL OR lower(nombre_cientifico) = lower(?))",
                (
                    ahora_texto(momento),
                    round(min(max(float(confianza), 0.0), 1.0), 4),
                    int(ancho),
                    int(alto),
                    int(ancho) * int(alto),
                    1 if es_simulacion else 0,
                    ruta_relativa(ruta_thumb),
                    id_especie,
                    nombre_cientifico,
                    nombre_cientifico,
                ),
            )
        return cursor.lastrowid if cursor.rowcount else None

    def ids_avistamientos_existentes(self, ids):
        """Identifica los avistamientos de una lista acotada que siguen en el historial."""
        ids = tuple(ids)
        if not ids:
            return set()
        marcas = ", ".join("?" for _ in ids)
        return {f["id_avistamiento"] for f in self._todos(
            f"SELECT id_avistamiento FROM HISTORIAL_AVISTAMIENTO WHERE id_avistamiento IN ({marcas})", ids,
        )}

    def _filtro_avistamientos(self, id_especie=None, desde=None, hasta=None, incluir_simulacion=True):
        condiciones, parametros = [], []
        if id_especie:
            condiciones.append("h.id_especie = ?")
            parametros.append(int(id_especie))
        if desde:
            condiciones.append("h.timestamp_deteccion >= ?")
            parametros.append(desde)
        if hasta:
            condiciones.append("h.timestamp_deteccion < ?")
            parametros.append(hasta)
        if not incluir_simulacion:
            condiciones.append("h.es_simulacion = 0")
        where = (" WHERE " + " AND ".join(condiciones)) if condiciones else ""
        return where, parametros

    def avistamientos(self, limite=100, desplazamiento=0, **filtros):
        where, parametros = self._filtro_avistamientos(**filtros)
        consulta = (
            "SELECT h.*, e.nombre_comun, e.nombre_cientifico FROM HISTORIAL_AVISTAMIENTO h "
            "JOIN ESPECIE_AVE e ON e.id_especie = h.id_especie"
            + where
            + " ORDER BY h.timestamp_deteccion DESC, h.id_avistamiento DESC"
        )
        if limite:
            consulta += " LIMIT ? OFFSET ?"
            parametros += [int(limite), int(desplazamiento)]
        return self._todos(consulta, parametros)

    def contar_avistamientos(self, **filtros):
        where, parametros = self._filtro_avistamientos(**filtros)
        return self._uno("SELECT COUNT(*) AS n FROM HISTORIAL_AVISTAMIENTO h" + where, parametros)["n"]

    def avistamientos_por_especie(self, limite=10, **filtros):
        where, parametros = self._filtro_avistamientos(**filtros)
        return self._todos(
            "SELECT e.id_especie, e.nombre_comun, COUNT(*) AS cantidad, "
            "AVG(h.nivel_confianza) AS confianza_media FROM HISTORIAL_AVISTAMIENTO h "
            "JOIN ESPECIE_AVE e ON e.id_especie = h.id_especie"
            + where
            + " GROUP BY e.id_especie ORDER BY cantidad DESC, e.nombre_comun LIMIT ?",
            parametros + [int(limite)],
        )

    def avistamientos_por_hora(self, **filtros):
        where, parametros = self._filtro_avistamientos(**filtros)
        filas = self._todos(
            "SELECT CAST(strftime('%H', h.timestamp_deteccion) AS INTEGER) AS hora, COUNT(*) AS cantidad "
            "FROM HISTORIAL_AVISTAMIENTO h" + where + " GROUP BY hora",
            parametros,
        )
        por_hora = {fila["hora"]: fila["cantidad"] for fila in filas}
        return [(hora, por_hora.get(hora, 0)) for hora in range(24)]

    def avistamientos_por_dia(self, dias=14, hoy=None, incluir_simulacion=True):
        hoy, _, hasta = limites_dia(hoy)
        primero = hoy - timedelta(days=dias - 1)
        where, parametros = self._filtro_avistamientos(
            desde=primero.isoformat(), hasta=hasta, incluir_simulacion=incluir_simulacion,
        )
        filas = self._todos(
            "SELECT substr(h.timestamp_deteccion, 1, 10) AS dia, COUNT(*) AS cantidad "
            "FROM HISTORIAL_AVISTAMIENTO h" + where + " GROUP BY dia",
            parametros,
        )
        por_dia = {fila["dia"]: fila["cantidad"] for fila in filas}
        return [
            ((primero + timedelta(days=i)).isoformat(), por_dia.get((primero + timedelta(days=i)).isoformat(), 0))
            for i in range(dias)
        ]

    def especies_del_dia(self, dia=None):
        """Especies activas avistadas en el día, con su último avistamiento."""
        _, desde, hasta = limites_dia(dia)
        return self._todos(
            "WITH diario AS ("
            " SELECT h.id_especie, h.id_avistamiento, h.timestamp_deteccion, h.ruta_captura_thumb,"
            " COUNT(*) OVER (PARTITION BY h.id_especie) AS veces,"
            " ROW_NUMBER() OVER (PARTITION BY h.id_especie"
            " ORDER BY h.timestamp_deteccion DESC, h.id_avistamiento DESC) AS posicion"
            " FROM HISTORIAL_AVISTAMIENTO h"
            " WHERE h.timestamp_deteccion >= ? AND h.timestamp_deteccion < ?"
            ") SELECT e.*, d.timestamp_deteccion AS ultimo_avistamiento, d.veces,"
            " d.ruta_captura_thumb AS ultima_captura, d.id_avistamiento AS ultimo_id"
            " FROM diario d JOIN ESPECIE_AVE e ON e.id_especie = d.id_especie"
            " WHERE d.posicion = 1 AND e.activo = 1"
            " ORDER BY d.timestamp_deteccion DESC, d.id_avistamiento DESC",
            (desde, hasta),
        )

    def resumen_del_dia(self, dia=None):
        """Instantánea del día para visitantes, incluidas detecciones de demostración."""
        dia, _, _ = limites_dia(dia)
        especies = self.especies_del_dia(dia)
        return {"dia": dia, "especies": especies, "total": sum(e["veces"] for e in especies)}

    def resumen_especie(self, id_especie):
        """Totales de avistamientos de una especie (cámara real y demostración por separado)."""
        _, desde, hasta = limites_dia()
        return self._uno(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN es_simulacion = 0 THEN 1 ELSE 0 END) AS reales, "
            "SUM(CASE WHEN h.timestamp_deteccion >= ? AND h.timestamp_deteccion < ? AND e.activo = 1"
            " THEN 1 ELSE 0 END) AS hoy, "
            "MIN(timestamp_deteccion) AS primero, MAX(timestamp_deteccion) AS ultimo, "
            "MAX(nivel_confianza) AS confianza_max, AVG(nivel_confianza) AS confianza_media, "
            "COUNT(DISTINCT substr(timestamp_deteccion, 1, 10)) AS dias "
            "FROM HISTORIAL_AVISTAMIENTO h JOIN ESPECIE_AVE e ON e.id_especie = h.id_especie "
            "WHERE h.id_especie = ?",
            (desde, hasta, id_especie),
        )

    def especies_por_cientifico(self, nombres):
        """Especies activas en el mismo orden que la lista de nombres científicos."""
        resultado = []
        for nombre in nombres:
            fila = self.especie_por_cientifico(nombre)
            if fila and fila["activo"]:
                resultado.append(fila)
        return resultado

    def ultima_captura(self, id_especie):
        fila = self._uno(
            "SELECT ruta_captura_thumb FROM HISTORIAL_AVISTAMIENTO WHERE id_especie = ? "
            "AND ruta_captura_thumb <> '' ORDER BY timestamp_deteccion DESC, id_avistamiento DESC LIMIT 1",
            (id_especie,),
        )
        return fila["ruta_captura_thumb"] if fila else ""

    def catalogo_visitantes(self):
        """Fichas activas y su última captura disponible, en una sola consulta."""
        return self._todos(
            "SELECT e.*, (SELECT h.ruta_captura_thumb FROM HISTORIAL_AVISTAMIENTO h "
            "WHERE h.id_especie = e.id_especie AND h.ruta_captura_thumb <> '' "
            "ORDER BY h.timestamp_deteccion DESC, h.id_avistamiento DESC LIMIT 1) AS ultima_captura "
            "FROM ESPECIE_AVE e WHERE e.activo = 1"
        )

    # ------------------------------------------------------
    # Métricas
    # ------------------------------------------------------

    def registrar_metrica(
        self,
        estado_camara,
        fps_promedio=None,
        inferencia_ms_promedio=None,
        inferencia_ms_maximo=None,
        total_detecciones=0,
        total_descartes_px=0,
        total_descartes_confianza=0,
    ):
        if estado_camara not in ESTADOS_CAMARA:
            estado_camara = "SIN_SENAL"
        with self.conexion:
            self.conexion.execute(
                "INSERT INTO METRICA_SISTEMA (fecha_registro, fps_promedio, inferencia_ms_promedio, "
                "inferencia_ms_maximo, estado_camara, total_detecciones, total_descartes_px, "
                "total_descartes_confianza) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ahora_texto(),
                    fps_promedio,
                    inferencia_ms_promedio,
                    inferencia_ms_maximo,
                    estado_camara,
                    int(total_detecciones),
                    int(total_descartes_px),
                    int(total_descartes_confianza),
                ),
            )

    def resumen_metricas(self, desde=None, hasta=None):
        consulta = (
            "SELECT COUNT(*) AS registros, AVG(fps_promedio) AS fps, "
            "AVG(inferencia_ms_promedio) AS inferencia_ms, MAX(inferencia_ms_maximo) AS inferencia_ms_max, "
            "SUM(total_detecciones) AS detecciones, SUM(total_descartes_px) AS descartes_px, "
            "SUM(total_descartes_confianza) AS descartes_confianza, "
            "SUM(CASE WHEN estado_camara = 'FAILOVER_DEMO' THEN 1 ELSE 0 END) AS registros_demo "
            "FROM METRICA_SISTEMA"
        )
        condiciones, parametros = [], []
        if desde:
            condiciones.append("fecha_registro >= ?")
            parametros.append(desde)
        if hasta:
            condiciones.append("fecha_registro < ?")
            parametros.append(hasta)
        if condiciones:
            consulta += " WHERE " + " AND ".join(condiciones)
        resumen = self._uno(consulta, parametros)
        ultima = self._uno("SELECT * FROM METRICA_SISTEMA ORDER BY fecha_registro DESC, id_metrica DESC LIMIT 1")
        resumen["ultima"] = ultima
        return resumen

    def metricas(self, limite=60):
        return self._todos(
            "SELECT * FROM METRICA_SISTEMA ORDER BY fecha_registro DESC, id_metrica DESC LIMIT ?",
            (int(limite),),
        )

    # ------------------------------------------------------
    # Usuarios
    # ------------------------------------------------------

    def usuarios(self):
        return self._todos(
            "SELECT id_usuario, nombre, correo, rol, ultimo_login FROM USUARIO_ADMIN ORDER BY nombre"
        )

    def usuario_por_correo(self, correo):
        return self._uno(
            "SELECT * FROM USUARIO_ADMIN WHERE lower(correo) = lower(?)", ((correo or "").strip(),)
        )

    def usuario(self, id_usuario):
        return self._uno("SELECT * FROM USUARIO_ADMIN WHERE id_usuario = ?", (id_usuario,))

    def crear_usuario(self, nombre, correo, password_hash, rol="Administrador"):
        if rol not in ROLES:
            raise ValueError(f"Rol no válido: {rol}")
        with self.conexion:
            cursor = self.conexion.execute(
                "INSERT INTO USUARIO_ADMIN (nombre, correo, password_hash, rol) VALUES (?, ?, ?, ?)",
                (nombre.strip(), correo.strip().lower(), password_hash, rol),
            )
        return cursor.lastrowid

    def actualizar_usuario(self, id_usuario, nombre=None, rol=None, password_hash=None):
        cambios = {}
        if nombre:
            cambios["nombre"] = nombre.strip()
        if rol:
            if rol not in ROLES:
                raise ValueError(f"Rol no válido: {rol}")
            cambios["rol"] = rol
        if password_hash:
            cambios["password_hash"] = password_hash
        if not cambios:
            return False
        condicion = PERMITE_RETIRAR_ADMIN if rol is not None and rol != "Administrador" else ""
        with self.conexion:
            cursor = self.conexion.execute(
                f"UPDATE USUARIO_ADMIN SET {', '.join(f'{c} = ?' for c in cambios)} WHERE id_usuario = ?" + condicion,
                list(cambios.values()) + [id_usuario],
            )
        return bool(cursor.rowcount)

    def eliminar_usuario(self, id_usuario):
        with self.conexion:
            cursor = self.conexion.execute(
                "DELETE FROM USUARIO_ADMIN WHERE id_usuario = ?" + PERMITE_RETIRAR_ADMIN, (id_usuario,),
            )
        return bool(cursor.rowcount)

    def marcar_login(self, id_usuario):
        with self.conexion:
            self.conexion.execute(
                "UPDATE USUARIO_ADMIN SET ultimo_login = ? WHERE id_usuario = ?", (ahora_texto(), id_usuario)
            )

    def total_administradores(self):
        return self._uno("SELECT COUNT(*) AS n FROM USUARIO_ADMIN WHERE rol = 'Administrador'")["n"]

    def total_usuarios(self):
        return self._uno("SELECT COUNT(*) AS n FROM USUARIO_ADMIN")["n"]


def aplicar_traduccion(especie, traducciones):
    """Copia de la ficha con los textos traducidos ({campo: texto o fila}) sobre los en español."""
    if not especie:
        return especie
    resultado = dict(especie)
    for campo, valor in (traducciones or {}).items():
        texto = valor["texto"] if isinstance(valor, (dict, sqlite3.Row)) else valor
        if texto and campo in CAMPOS_TRADUCIBLES:
            resultado[campo] = texto
    return resultado


def preparar_base(ruta=None):
    """Crea la base si no existe y carga el catálogo si está vacío."""
    base = BaseDatos(ruta, inicializar_esquema=True)
    if base.total_especies() == 0 and ARCHIVO_CATALOGO.exists():
        base.cargar_catalogo(solo_vacio=True)
    return base
