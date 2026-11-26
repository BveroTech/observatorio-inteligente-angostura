import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, abort, flash, g, render_template, request, send_from_directory, session, url_for
from werkzeug.utils import safe_join

from config.settings import (
    CARPETA_CAPTURAS,
    CARPETA_FUENTES,
    CARPETA_SONIDOS_SIMULADOR,
    CARPETA_WEB,
    INTENTOS_LOGIN_MAXIMOS,
    MAX_MB_ARCHIVO_SUBIDO,
    MINUTOS_BLOQUEO_LOGIN,
    MINUTOS_SESION_ADMIN,
    RECURSOS_DIR,
    obtener_ruta_datos,
)
from src.persistencia.repositorio_sqlite import BaseDatos
from src.presentacion import tema_visual as T
from web.admin_crud import registrar_rutas_crud
from web.auth import (
    ControlIntentos,
    clave_secreta,
    crear_token_acceso,
    registrar_rutas_auth,
    requiere_sesion,
)
from web.dashboard_metricas import registrar_rutas_metricas
from web.fuente_video import registrar_rutas_fuente_video
from web.por_identificar import registrar_rutas_por_identificar

__all__ = ["crear_app", "crear_token_acceso", "clave_secreta"]

ESTADOS_CAMARA_TEXTO = {
    "ONLINE": "Cámara en línea",
    "RECONECTANDO": "Reconectando",
    "FAILOVER_DEMO": "Modo demostración",
    "SIN_SENAL": "Sin señal",
}


def crear_app(ruta_base=None, pruebas=False):
    app = Flask(
        __name__,
        template_folder=str(CARPETA_WEB / "plantillas"),
        static_folder=str(CARPETA_WEB / "estaticos"),
        static_url_path="/estaticos",
    )
    app.config.update(
        SECRET_KEY=secrets.token_hex(32) if pruebas else clave_secreta(),
        SESSION_COOKIE_NAME="observatorio_sesion",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=MINUTOS_SESION_ADMIN),
        MAX_CONTENT_LENGTH=MAX_MB_ARCHIVO_SUBIDO * 1024 * 1024,
        RUTA_BASE=ruta_base,
        TESTING=pruebas,
    )
    app.extensions["control_intentos"] = ControlIntentos(INTENTOS_LOGIN_MAXIMOS, MINUTOS_BLOQUEO_LOGIN)

    def base():
        if "base" not in g:
            g.base = BaseDatos(app.config["RUTA_BASE"])
        return g.base

    @app.teardown_appcontext
    def cerrar_base(_error):
        conexion = g.pop("base", None)
        if conexion is not None:
            conexion.cerrar()

    @app.before_request
    def cargar_usuario():
        g.usuario = None
        id_usuario = session.get("id_usuario")
        if id_usuario is None:
            return
        ultimo = session.get("ultimo_acceso", 0)
        if time.time() - ultimo > MINUTOS_SESION_ADMIN * 60:
            csrf_previo = session.get("csrf_token")
            session.clear()
            if csrf_previo:
                session["csrf_token"] = csrf_previo
            flash("La sesión se cerró por inactividad. Vuelve a ingresar.", "aviso")
            return
        usuario = base().usuario(id_usuario)
        if usuario is None:
            csrf_previo = session.get("csrf_token")
            session.clear()
            if csrf_previo:
                session["csrf_token"] = csrf_previo
            return
        session["ultimo_acceso"] = time.time()
        session.permanent = True
        g.usuario = usuario

    @app.before_request
    def revisar_csrf():
        if request.method != "POST":
            return
        enviado = request.form.get("csrf_token", "")
        esperado = session.get("csrf_token", "")
        if not esperado or not secrets.compare_digest(enviado, esperado):
            abort(400, description="El formulario venció. Recarga la página e inténtalo de nuevo.")

    def token_csrf():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    @app.after_request
    def cabeceras(respuesta):
        respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
        respuesta.headers.setdefault("X-Frame-Options", "DENY")
        respuesta.headers.setdefault("Referrer-Policy", "same-origin")
        if request.endpoint not in ("static", "fuente", "medio", "captura", "imagen_por_identificar"):
            respuesta.headers.setdefault("Cache-Control", "no-store")
        return respuesta

    @app.context_processor
    def variables_globales():
        return {
            "T": T,
            "usuario": g.get("usuario"),
            "csrf_token": token_csrf,
            "es_admin": bool(g.get("usuario") and g.usuario["rol"] == "Administrador"),
            "texto_estado": ESTADOS_CAMARA_TEXTO,
            "ahora": datetime.now(),
        }

    @app.template_filter("porcentaje")
    def porcentaje(valor):
        if valor is None:
            return "—"
        return f"{float(valor) * 100:.0f} %"

    @app.template_filter("numero")
    def numero(valor, decimales=0):
        if valor is None:
            return "—"
        texto = f"{float(valor):,.{decimales}f}"
        return texto.replace(",", "X").replace(".", ",").replace("X", ".")

    # Servidor de archivos locales y capturas
    @app.route("/fuentes/<nombre>")
    def fuente(nombre):
        return send_from_directory(CARPETA_FUENTES, nombre, max_age=86400)

    @app.route("/medios/<path:ruta>")
    @requiere_sesion
    def medio(ruta):
        local = obtener_ruta_datos("assets")
        empaquetada = RECURSOS_DIR / "assets"
        for carpeta in (local, empaquetada):
            candidato = safe_join(carpeta, ruta)
            if candidato and Path(candidato).is_file():
                return send_from_directory(carpeta, ruta)
        if ruta.startswith("sonidos/"):
            alternativo = CARPETA_SONIDOS_SIMULADOR / Path(ruta).name
            if alternativo.is_file():
                return send_from_directory(CARPETA_SONIDOS_SIMULADOR, Path(ruta).name)
        abort(404)

    @app.route("/capturas/<path:ruta>")
    @requiere_sesion
    def captura(ruta):
        heredadas = obtener_ruta_datos("capturas")
        carpetas = (heredadas, CARPETA_CAPTURAS) if request.args.get("heredada") == "1" else (CARPETA_CAPTURAS, heredadas)
        for carpeta in carpetas:
            candidato = safe_join(carpeta, ruta)
            if candidato and Path(candidato).is_file():
                return send_from_directory(carpeta, ruta)
        abort(404)

    @app.template_global()
    def url_archivo(ruta):
        if not ruta:
            return ""
        ruta = ruta.replace("\\", "/")
        if ruta.startswith("assets/"):
            return url_for("medio", ruta=ruta[len("assets/"):])
        if ruta.startswith("laboratorio_ia/simulador_pantalla2/sonidos/"):
            nombre = ruta[len("laboratorio_ia/simulador_pantalla2/sonidos/"):]
            return url_for("medio", ruta=f"sonidos/{nombre}")
        if ruta.startswith("data/por_identificar/"):
            return url_for("imagen_por_identificar", ruta=ruta[len("data/por_identificar/"):])
        if ruta.startswith("capturas/") or ruta.startswith("data/capturas/"):
            prefijo = "data/capturas/" if ruta.startswith("data/capturas/") else "capturas/"
            return url_for("captura", ruta=ruta[len(prefijo):], heredada=1 if prefijo == "capturas/" else None)
        return ""

    # Registro de los 3 submódulos (Alineados con BPMN 3)
    registrar_rutas_auth(app, base)
    registrar_rutas_crud(app, base)
    registrar_rutas_metricas(app, base)
    registrar_rutas_por_identificar(app, base)
    registrar_rutas_fuente_video(app, base)

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(413)
    def error(e):
        mensajes = {
            403: "Tu rol no tiene acceso a esta sección.",
            404: "La página o el registro no existe.",
            413: f"El archivo supera el máximo de {MAX_MB_ARCHIVO_SUBIDO} MB.",
        }
        texto = mensajes.get(e.code) or getattr(e, "description", "") or "Solicitud no válida."
        return render_template("error.html", codigo=e.code, texto=texto), e.code

    return app
