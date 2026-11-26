import sqlite3
from pathlib import Path
from uuid import uuid4

from flask import abort, flash, g, redirect, render_template, request, url_for
from PIL import Image
from werkzeug.utils import secure_filename

from config.settings import IDIOMAS, TRADUCIR_AL_GUARDAR, obtener_ruta_datos
from src.aplicacion import lector_fichas
from src.aplicacion.servicio_traduccion import (
    a_espanol,
    estado_traducciones,
    huella,
    traduciendo,
    traducir_en_segundo_plano,
)
from src.persistencia.repositorio_sqlite import (
    CAMPOS_EDITABLES,
    CAMPOS_TRADUCIBLES,
    IDIOMAS_TRADUCCION,
    ConflictoEdicion,
    revision_ficha,
    ruta_relativa,
)
from web.auth import requiere_sesion

CARPETA_FOTOS = obtener_ruta_datos("assets/fotos")
CARPETA_SONIDOS = obtener_ruta_datos("assets/sonidos")
EXTENSIONES_FOTO = {".jpg", ".jpeg", ".png", ".webp"}
EXTENSIONES_AUDIO = {".wav", ".ogg", ".mp3"}
FORMATOS_FOTO = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
POR_PAGINA = 25

SECCIONES_FICHA = [
    ("Identificación", [
        ("nombre_comun", "Nombre común", "texto", True),
        ("nombre_cientifico", "Nombre científico", "texto", True),
        ("genero", "Género", "texto", False),
        ("familia", "Familia", "texto", False),
        ("orden", "Orden", "texto", False),
    ]),
    ("Medidas", [
        ("tamano_cm", "Tamaño (cm)", "texto", False),
        ("peso_g", "Peso (g)", "texto", False),
        ("envergadura_cm", "Envergadura (cm)", "texto", False),
    ]),
    ("Conservación", [
        ("conservacion_uicn", "Estado UICN", "texto", False),
        ("conservacion_rce", "Estado RCE (Chile)", "texto", False),
    ]),
    ("Ficha", [
        ("caracteristicas", "Características distintivas", "area", False),
        ("habitat", "Hábitat", "area", False),
        ("distribucion", "Distribución", "area", False),
        ("migracion", "Migración", "area", False),
        ("comportamiento", "Comportamiento", "area", False),
        ("alimentacion", "Alimentación", "area", False),
    ]),
]

LARGOS_MAXIMOS = {
    "nombre_comun": 100, "nombre_cientifico": 120, "genero": 60, "familia": 60, "orden": 60,
    "tamano_cm": 30, "peso_g": 30, "envergadura_cm": 30, "conservacion_uicn": 50, "conservacion_rce": 50,
}


def _entero_positivo(valor, defecto=1):
    try:
        return max(int(valor), 1)
    except (TypeError, ValueError):
        return defecto


def validar_archivo(campo, extensiones):
    archivo = request.files.get(campo)
    if archivo is None or not archivo.filename:
        return None, "", None
    extension = Path(archivo.filename).suffix.lower()
    if extension not in extensiones:
        return None, "", f"Formato no permitido ({extension or 'sin extensión'}). Usa: {', '.join(sorted(extensiones))}."
    if campo == "foto":
        try:
            with Image.open(archivo.stream) as imagen:
                if imagen.format != FORMATOS_FOTO[extension]:
                    return None, "", "La extensión no corresponde al formato de la imagen."
                imagen.verify()
        except (Image.DecompressionBombError, OSError, SyntaxError, ValueError):
            return None, "", "La imagen está dañada o tiene un formato inválido."
        finally:
            archivo.stream.seek(0)
    return archivo, extension, None


def leer_formulario():
    datos, errores = {}, []
    for _titulo, campos in SECCIONES_FICHA:
        for nombre, etiqueta, _tipo, obligatorio in campos:
            valor = request.form.get(nombre, "").strip()
            if obligatorio and not valor:
                errores.append(f"«{etiqueta}» es obligatorio.")
            largo = LARGOS_MAXIMOS.get(nombre)
            if largo and len(valor) > largo:
                errores.append(f"«{etiqueta}» admite hasta {largo} caracteres.")
            datos[nombre] = valor
    datos["activo"] = 1 if request.form.get("activo") == "1" else 0
    return datos, errores


def etiquetas_campos():
    return {nombre: etiqueta for _t, campos in SECCIONES_FICHA for nombre, etiqueta, _tipo, _o in campos}


def leer_ficha_tecnica(actual):
    """
    Lee la ficha técnica subida (foto, escaneo o PDF) en el idioma elegido.
    Devuelve (datos para el formulario en español, info de la lectura) o lanza ValueError.
    """
    idioma = request.form.get("idioma_documento", "es")
    if idioma not in IDIOMAS:
        raise ValueError("Idioma no válido.")
    archivo = request.files.get("documento")
    if archivo is None or not archivo.filename:
        raise ValueError("Elige el archivo de la ficha técnica (foto, escaneo o PDF).")
    if Path(archivo.filename).suffix.lower() not in lector_fichas.EXTENSIONES:
        raise ValueError("Formato no admitido. Usa una foto (JPG, PNG, TIFF) o un PDF.")
    try:
        texto = lector_fichas.leer_documento(archivo.read(), archivo.filename, idioma)
    except (OSError, Image.DecompressionBombError, SyntaxError) as error:
        raise ValueError("No se pudo abrir el archivo: está dañado o no es una imagen/PDF válido.") from error
    leidos = lector_fichas.extraer_campos(texto)
    espanol = {}
    for campo, valor in leidos.items():
        if campo == "nombre_comun" and idioma != "es" and actual and actual.get("nombre_comun"):
            continue  # el nombre común en español no se reemplaza por una traducción automática
        espanol[campo] = a_espanol(campo, valor, idioma) if campo in CAMPOS_TRADUCIBLES else valor
        largo = LARGOS_MAXIMOS.get(campo)
        if largo:
            espanol[campo] = espanol[campo][:largo]
    datos = {**(actual or {c: "" for c in CAMPOS_EDITABLES}), **{c: v for c, v in espanol.items() if v}}
    if actual is None:
        datos["activo"] = 1
    lectura = {
        "idioma": idioma,
        "nombre_idioma": IDIOMAS[idioma],
        "texto": texto.strip(),
        "reconocidos": [etiquetas_campos().get(c, c) for c in leidos],
        "originales": {c: v for c, v in leidos.items() if c in CAMPOS_TRADUCIBLES} if idioma != "es" else {},
    }
    return datos, lectura


def registrar_rutas_crud(app, obtener_bd):
    """Registra las rutas del mantenedor CRUD de especies del catálogo."""

    @app.route("/especies")
    @requiere_sesion
    def especies():
        bd = obtener_bd()
        texto = request.args.get("q", "").strip()
        solo_activas = request.args.get("activas") == "1"
        pagina = _entero_positivo(request.args.get("pagina", 1), 1)
        total = bd.contar_especies(texto=texto, solo_activas=solo_activas)
        paginas = max((total + POR_PAGINA - 1) // POR_PAGINA, 1)
        pagina = min(pagina, paginas)
        filas = bd.especies(
            texto=texto, solo_activas=solo_activas, limite=POR_PAGINA, desplazamiento=(pagina - 1) * POR_PAGINA
        )
        return render_template(
            "especies.html", filas=filas, texto=texto, solo_activas=solo_activas,
            pagina=pagina, paginas=paginas, total=total,
        )

    @app.route("/especies/nueva", methods=["GET", "POST"])
    @app.route("/especies/<int:id_especie>", methods=["GET", "POST"])
    @requiere_sesion
    def especie(id_especie=None):
        bd = obtener_bd()
        actual = bd.especie(id_especie) if id_especie else None
        if id_especie and actual is None:
            abort(404)

        def mostrar_ficha(datos, estado=200, lectura=None):
            editor = bd.usuario(actual["actualizado_por"]) if actual and actual.get("actualizado_por") else None
            return render_template(
                "especie.html",
                especie=datos,
                secciones=SECCIONES_FICHA,
                nueva=id_especie is None,
                editor=editor,
                lectura=lectura,
                lector=lector_fichas.estado(),
                idiomas=IDIOMAS,
                idiomas_traduccion=IDIOMAS_TRADUCCION,
                campos_traducibles=CAMPOS_TRADUCIBLES,
                etiquetas=etiquetas_campos(),
                traducciones=estado_traducciones(bd, actual) if actual else None,
                traduciendo=traduciendo(id_especie) if id_especie else False,
                revision=revision_ficha(actual) if actual else "",
                avistamientos=bd.contar_avistamientos(id_especie=id_especie) if id_especie else 0,
                ultima_captura=bd.ultima_captura(id_especie) if id_especie else "",
            ), estado

        if request.method == "POST" and request.form.get("accion") == "leer_ficha":
            vacia = {**{c: "" for c in CAMPOS_EDITABLES}, "activo": 1}
            try:
                datos, lectura = leer_ficha_tecnica(actual)
            except lector_fichas.LectorNoDisponible as error:
                flash(f"El lector de fichas no está disponible: {error}", "error")
                return mostrar_ficha(actual or vacia, 503)
            except ValueError as error:
                flash(str(error), "error")
                return mostrar_ficha(actual or vacia, 400)
            if lectura["reconocidos"]:
                flash(f"Ficha técnica leída ({lectura['nombre_idioma']}): se rellenaron "
                      f"{len(lectura['reconocidos'])} campos. Revísalos y guarda.", "ok")
            else:
                flash("Se leyó el documento, pero no se reconocieron secciones de la ficha. "
                      "Abajo está el texto leído para copiarlo a mano.", "error")
            return mostrar_ficha(datos, lectura=lectura)

        if request.method == "POST":
            revision = revision_ficha(actual) if actual else None
            if revision is not None and request.form.get("revision", revision) != revision:
                abort(409, description="Otra edición cambió la ficha. Recarga la página antes de guardar.")
            datos, errores = leer_formulario()
            otra = bd.especie_por_cientifico(datos["nombre_cientifico"]) if datos["nombre_cientifico"] else None
            if otra and otra["id_especie"] != id_especie:
                errores.append(f"Ya existe una especie con ese nombre científico (n.º {otra['id_especie']}).")
            medios = []
            for campo, etiqueta, carpeta, extensiones, columna in (
                ("foto", "Foto", CARPETA_FOTOS, EXTENSIONES_FOTO, "ruta_foto"),
                ("audio", "Canto", CARPETA_SONIDOS, EXTENSIONES_AUDIO, "ruta_audio_canto"),
            ):
                archivo, extension, error = validar_archivo(campo, extensiones)
                if error:
                    errores.append(f"{etiqueta}: {error}")
                elif archivo is not None:
                    medios.append((archivo, carpeta, extension, columna))
                elif request.form.get(f"quitar_{campo}") == "1":
                    datos[columna] = ""
            datos_formulario = {**(actual or {}), **datos}
            if errores:
                for error in errores:
                    flash(error, "error")
                return mostrar_ficha(datos_formulario, 400)
            nombre = secure_filename(datos["nombre_cientifico"])[:100] or "especie"
            guardados = []
            confirmado = False
            try:
                for archivo, carpeta, extension, columna in medios:
                    carpeta.mkdir(parents=True, exist_ok=True)
                    # Una ruta nueva invalida las cachés y no sobrescribe archivos en uso.
                    destino = carpeta / f"{nombre}_{uuid4().hex}{extension}"
                    guardados.append(destino)
                    archivo.save(destino)
                    datos[columna] = ruta_relativa(destino)
                nuevo_id = bd.guardar_especie(
                    datos, id_usuario=g.usuario["id_usuario"], id_especie=id_especie, revision=revision,
                )
                confirmado = True
            except LookupError:
                abort(404)
            except ConflictoEdicion:
                abort(409, description="Otra edición cambió la ficha. Recarga la página antes de guardar.")
            except sqlite3.IntegrityError:
                abort(400, description="El catálogo cambió mientras editabas esta ficha. Recarga la página.")
            except OSError:
                app.logger.exception("No se pudo guardar el medio de la especie")
                flash("No se pudo guardar el archivo. Comprueba el almacenamiento e inténtalo de nuevo.", "error")
                return mostrar_ficha(datos_formulario, 503)
            finally:
                if not confirmado:
                    for destino in guardados:
                        try:
                            destino.unlink(missing_ok=True)
                        except OSError:
                            app.logger.warning("No se pudo retirar un archivo de la edición fallida", exc_info=True)
            # Texto original de una ficha técnica en inglés/alemán: queda como traducción revisada.
            idioma_lectura = request.form.get("lectura_idioma", "")
            if idioma_lectura in IDIOMAS_TRADUCCION:
                for campo in CAMPOS_TRADUCIBLES:
                    original = request.form.get(f"lectura_{campo}", "").strip()
                    if original and datos.get(campo):
                        bd.guardar_traduccion(nuevo_id, idioma_lectura, campo, original, huella(datos[campo]),
                                              manual=True, id_usuario=g.usuario["id_usuario"])
            mensaje = "Especie guardada." if id_especie else "Especie creada."
            if TRADUCIR_AL_GUARDAR and traducir_en_segundo_plano(bd.ruta, nuevo_id):
                mensaje += " Las traducciones al inglés y al alemán se actualizan en segundo plano."
            flash(mensaje, "ok")
            return redirect(url_for("especie", id_especie=nuevo_id))
        vacia = {c: "" for c in CAMPOS_EDITABLES}
        vacia["activo"] = 1
        return mostrar_ficha(actual or vacia)

    @app.route("/especies/<int:id_especie>/traducciones", methods=["POST"])
    @requiere_sesion
    def traducciones_especie(id_especie):
        bd = obtener_bd()
        actual = bd.especie(id_especie)
        if actual is None:
            abort(404)
        accion = request.form.get("accion", "guardar")
        if accion == "guardar":
            cambios = 0
            for idioma in IDIOMAS_TRADUCCION:
                existentes = bd.traducciones(id_especie, idioma)
                for campo in CAMPOS_TRADUCIBLES:
                    clave = f"{idioma}__{campo}"
                    if clave not in request.form:
                        continue
                    nuevo = request.form.get(clave, "").strip()
                    previo = ((existentes.get(campo) or {}).get("texto") or "").strip()
                    if nuevo != previo:
                        bd.guardar_traduccion(id_especie, idioma, campo, nuevo, huella(actual.get(campo) or ""),
                                              manual=True, id_usuario=g.usuario["id_usuario"])
                        cambios += 1
            if cambios:
                flash(f"Traducciones guardadas: {cambios} campo(s) corregido(s) a mano.", "ok")
            else:
                flash("No había cambios en las traducciones.", "ok")
        elif accion in ("actualizar", "rehacer"):
            if traducir_en_segundo_plano(bd.ruta, id_especie, forzar=accion == "rehacer"):
                flash("Traduciendo en segundo plano. Recarga la página en unos segundos.", "ok")
            else:
                flash("Faltan los modelos de traducción (scripts/cli_admin/descargar_modelos_idiomas.py).", "error")
        else:
            abort(400)
        return redirect(url_for("especie", id_especie=id_especie) + "#traducciones")

    @app.route("/especies/<int:id_especie>/activo", methods=["POST"])
    @requiere_sesion
    def cambiar_activo(id_especie):
        bd = obtener_bd()
        solicitado = request.form.get("activo")
        if solicitado not in (None, "0", "1"):
            abort(400)
        activo = solicitado == "1" if solicitado is not None else None
        actual = bd.cambiar_activo(id_especie, activo, g.usuario["id_usuario"])
        if actual is None:
            abort(404)
        flash(f"«{actual['nombre_comun']}» {'activada' if actual['activo'] else 'desactivada'}.", "ok")
        volver = request.form.get("volver") or ""
        if volver.startswith("/") and not volver.startswith("//"):
            return redirect(volver)
        return redirect(url_for("especies"))

    @app.route("/especies/<int:id_especie>/eliminar", methods=["POST"])
    @requiere_sesion
    def eliminar_especie(id_especie):
        bd = obtener_bd()
        actual = bd.especie(id_especie)
        if actual is None:
            abort(404)
        try:
            if not bd.eliminar_especie(id_especie):
                abort(404)
        except sqlite3.IntegrityError:
            flash("No se puede eliminar: la especie tiene avistamientos registrados. Desactívala en su lugar.", "error")
            return redirect(url_for("especie", id_especie=id_especie))
        flash(f"«{actual['nombre_comun']}» eliminada del catálogo.", "ok")
        return redirect(url_for("especies"))
