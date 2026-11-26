"""
Aves por identificar: recortes de aves que el modelo no reconoció (confianza
bajo el umbral o especie sin ficha). Una persona indica qué especie es, o la
descarta; lo identificado se suma al entrenamiento con
laboratorio_ia/scripts_entrenamiento/importar_identificadas.py.
"""
from pathlib import Path

from flask import abort, flash, g, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import safe_join

from config.settings import CARPETA_POR_IDENTIFICAR
from src.persistencia.repositorio_sqlite import ESTADOS_POR_IDENTIFICAR
from web.auth import requiere_sesion

POR_PAGINA = 24
ESTADOS_TEXTO = {
    "pendiente": "Pendientes",
    "identificada": "Identificadas",
    "no_es_ave": "No es un ave",
    "descartada": "Descartadas",
}
MOTIVOS_TEXTO = {
    "baja_confianza": "Confianza baja",
    "sin_ficha": "Especie sin ficha",
    "otra_ave": "Ave fuera de las especies del modelo",
}


def _entero(valor, defecto=None):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return defecto


def registrar_rutas_por_identificar(app, obtener_bd):

    @app.context_processor
    def pendientes_por_identificar():
        if g.get("usuario") is None:
            return {}
        try:
            return {"pendientes_identificar": obtener_bd().contar_por_identificar()}
        except Exception:
            return {"pendientes_identificar": 0}

    @app.route("/por-identificar")
    @requiere_sesion
    def por_identificar():
        bd = obtener_bd()
        estado = request.args.get("estado", "pendiente")
        if estado not in ESTADOS_POR_IDENTIFICAR:
            estado = "pendiente"
        pagina = max(_entero(request.args.get("pagina"), 1), 1)
        total = bd.contar_por_identificar(estado)
        paginas = max((total + POR_PAGINA - 1) // POR_PAGINA, 1)
        pagina = min(pagina, paginas)
        filas = bd.por_identificar(estado, POR_PAGINA, (pagina - 1) * POR_PAGINA)
        conteos = {e: bd.contar_por_identificar(e) for e in ESTADOS_POR_IDENTIFICAR}
        return render_template(
            "por_identificar.html", filas=filas, estado=estado, conteos=conteos, estados=ESTADOS_TEXTO,
            motivos=MOTIVOS_TEXTO, especies=bd.especies_para_identificar(), pagina=pagina, paginas=paginas,
            argumentos={"estado": estado},
        )

    @app.route("/por-identificar/<int:id_registro>", methods=["POST"])
    @requiere_sesion
    def resolver_por_identificar(id_registro):
        bd = obtener_bd()
        accion = request.form.get("accion", "")
        estado_lista = request.form.get("volver", "pendiente")
        id_especie = None
        if accion == "identificar":
            id_especie = _entero(request.form.get("id_especie"))
            if id_especie is None:
                flash("Elige la especie antes de guardar.", "error")
                return redirect(url_for("por_identificar", estado=estado_lista))
            nuevo = "identificada"
        elif accion in ("no_es_ave", "descartada", "pendiente"):
            nuevo = accion
        else:
            abort(400)
        if not bd.resolver_por_identificar(id_registro, nuevo, id_especie, g.usuario["id_usuario"]):
            abort(404)
        mensajes = {
            "identificada": "Ave identificada. Se usará en el próximo entrenamiento.",
            "no_es_ave": "Marcada como «no es un ave».",
            "descartada": "Registro descartado.",
            "pendiente": "Registro devuelto a pendientes.",
        }
        flash(mensajes[nuevo], "ok")
        return redirect(url_for("por_identificar", estado=estado_lista, pagina=request.form.get("pagina", 1)))

    @app.route("/por-identificar/imagen/<path:ruta>")
    @requiere_sesion
    def imagen_por_identificar(ruta):
        candidato = safe_join(CARPETA_POR_IDENTIFICAR, ruta)
        if not candidato or not Path(candidato).is_file():
            abort(404)
        return send_from_directory(CARPETA_POR_IDENTIFICAR, ruta)
