import secrets
import sqlite3
import time

from functools import wraps
from pathlib import Path
from flask import abort, current_app, flash, g, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash
from config.settings import ARCHIVO_CLAVE_SECRETA
from src.persistencia.repositorio_sqlite import ROLES

SAL_ACCESO = "acceso-desde-catalogo"
SEGUNDOS_TOKEN_ACCESO = 60
LARGO_MINIMO_CLAVE = 8
tokens_usados = set()


def clave_secreta():
    """Lee la SECRET_KEY local o la genera. No se versiona ni se comparte."""
    archivo = Path(ARCHIVO_CLAVE_SECRETA)
    if archivo.exists():
        clave = archivo.read_text(encoding="utf-8").strip()
        if len(clave) >= 32:
            return clave
    archivo.parent.mkdir(parents=True, exist_ok=True)
    clave = secrets.token_hex(32)
    archivo.write_text(clave, encoding="utf-8")
    return clave

def crear_token_acceso(id_usuario, clave=None):
    """
    Enlace de un solo uso para entrar al portal desde la tuerca del catálogo,
    después de que el catálogo verificó correo y contraseña.
    """
    serializador = URLSafeTimedSerializer(clave or clave_secreta(), salt=SAL_ACCESO)
    return serializador.dumps({"u": int(id_usuario), "n": secrets.token_hex(8)})


class ControlIntentos:
    """Cuenta intentos fallidos por correo e IP (en memoria del proceso)."""

    def __init__(self, maximo, minutos):
        self.maximo = maximo
        self.segundos = minutos * 60
        self.fallos = {}

    def _clave(self, correo, ip):
        return f"{(correo or '').strip().lower()}|{ip}"

    def bloqueado(self, correo, ip):
        intentos = self.fallos.get(self._clave(correo, ip))
        if not intentos:
            return 0
        ahora = time.time()
        recientes = [t for t in intentos if ahora - t < self.segundos]
        self.fallos[self._clave(correo, ip)] = recientes
        if len(recientes) >= self.maximo:
            return int(self.segundos - (ahora - recientes[0])) + 1
        return 0

    def fallo(self, correo, ip):
        self.fallos.setdefault(self._clave(correo, ip), []).append(time.time())

    def limpiar(self, correo, ip):
        self.fallos.pop(self._clave(correo, ip), None)


def requiere_sesion(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if g.get("usuario") is None:
            return redirect(url_for("ingresar", siguiente=request.path))
        return vista(*args, **kwargs)
    return envoltura

def requiere_admin(vista):
    @wraps(vista)
    @requiere_sesion
    def envoltura(*args, **kwargs):
        if g.usuario["rol"] != "Administrador":
            abort(403)
        return vista(*args, **kwargs)
    return envoltura

def registrar_rutas_auth(app, obtener_bd):
    """Registra las rutas de inicio de sesión, cuenta y gestión de usuarios."""

    @app.route("/")
    def inicio():
        if g.usuario is None:
            return redirect(url_for("ingresar"))
        if g.usuario["rol"] == "Administrador":
            return redirect(url_for("panel"))
        return redirect(url_for("especies"))

    @app.route("/ingresar", methods=["GET", "POST"])
    def ingresar():
        if g.usuario is not None:
            return redirect(url_for("inicio"))
        bd = obtener_bd()
        intentos = current_app.extensions["control_intentos"]
        sin_usuarios = bd.total_usuarios() == 0
        correo = ""
        if request.method == "POST":
            correo = request.form.get("correo", "").strip()
            clave = request.form.get("clave", "")
            ip = request.remote_addr or "local"
            espera = intentos.bloqueado(correo, ip)
            if espera:
                flash(f"Demasiados intentos fallidos. Espera {espera // 60 + 1} min antes de reintentar.", "error")
            else:
                usuario = bd.usuario_por_correo(correo)
                if usuario and check_password_hash(usuario["password_hash"], clave):
                    intentos.limpiar(correo, ip)
                    siguiente = request.args.get("siguiente", "")
                    session.clear()
                    session["id_usuario"] = usuario["id_usuario"]
                    session["ultimo_acceso"] = time.time()
                    session["csrf_token"] = secrets.token_urlsafe(32)
                    session.permanent = True
                    bd.marcar_login(usuario["id_usuario"])
                    if siguiente.startswith("/") and not siguiente.startswith("//"):
                        return redirect(siguiente)
                    return redirect(url_for("inicio"))
                intentos.fallo(correo, ip)
                flash("Correo o contraseña incorrectos.", "error")
        return render_template("ingresar.html", correo=correo, sin_usuarios=sin_usuarios)

    @app.route("/acceso/<token>")
    def acceso_directo(token):
        bd = obtener_bd()
        serializador = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=SAL_ACCESO)
        try:
            datos = serializador.loads(token, max_age=SEGUNDOS_TOKEN_ACCESO)
        except (BadSignature, ValueError, TypeError):
            datos = None
        usuario = bd.usuario(datos.get("u")) if isinstance(datos, dict) and datos.get("u") is not None else None
        nonce = datos.get("n") if isinstance(datos, dict) else None
        if usuario is None or not nonce or nonce in tokens_usados:
            flash("El enlace de acceso venció o ya se usó. Ingresa con tu correo y contraseña.", "error")
            return redirect(url_for("ingresar"))
        if len(tokens_usados) > 500:
            tokens_usados.clear()
        tokens_usados.add(nonce)
        session.clear()
        session["id_usuario"] = usuario["id_usuario"]
        session["ultimo_acceso"] = time.time()
        session["csrf_token"] = secrets.token_urlsafe(32)
        session.permanent = True
        bd.marcar_login(usuario["id_usuario"])
        return redirect(url_for("inicio"))

    @app.route("/salir", methods=["POST"])
    def salir():
        session.clear()
        flash("Sesión cerrada.", "ok")
        return redirect(url_for("ingresar"))

    @app.route("/cuenta", methods=["GET", "POST"])
    @requiere_sesion
    def cuenta():
        bd = obtener_bd()
        if request.method == "POST":
            actual = request.form.get("actual", "")
            nueva = request.form.get("nueva", "")
            repetida = request.form.get("repetida", "")
            if not check_password_hash(g.usuario["password_hash"], actual):
                flash("La contraseña actual no es correcta.", "error")
            elif len(nueva) < LARGO_MINIMO_CLAVE:
                flash(f"La nueva contraseña debe tener al menos {LARGO_MINIMO_CLAVE} caracteres.", "error")
            elif nueva != repetida:
                flash("Las contraseñas nuevas no coinciden.", "error")
            else:
                if not bd.actualizar_usuario(g.usuario["id_usuario"], password_hash=generate_password_hash(nueva)):
                    abort(404)
                flash("Contraseña actualizada.", "ok")
                return redirect(url_for("cuenta"))
        return render_template("cuenta.html")

    @app.route("/usuarios", methods=["GET", "POST"])
    @requiere_admin
    def usuarios():
        bd = obtener_bd()
        if request.method == "POST":
            nombre = request.form.get("nombre", "").strip()
            correo = request.form.get("correo", "").strip().lower()
            rol = request.form.get("rol", "")
            clave = request.form.get("clave", "")
            if not nombre or "@" not in correo or rol not in ROLES:
                flash("Completa nombre, un correo válido y el rol.", "error")
            elif len(clave) < LARGO_MINIMO_CLAVE:
                flash(f"La contraseña debe tener al menos {LARGO_MINIMO_CLAVE} caracteres.", "error")
            elif bd.usuario_por_correo(correo):
                flash("Ya existe un usuario con ese correo.", "error")
            else:
                try:
                    bd.crear_usuario(nombre, correo, generate_password_hash(clave), rol)
                except sqlite3.IntegrityError:
                    flash("Ya existe un usuario con ese correo.", "error")
                else:
                    flash(f"Usuario {correo} creado como {rol}.", "ok")
                    return redirect(url_for("usuarios"))
        return render_template("usuarios.html", filas=bd.usuarios(), roles=ROLES)

    @app.route("/usuarios/<int:id_usuario>", methods=["POST"])
    @requiere_admin
    def editar_usuario(id_usuario):
        bd = obtener_bd()
        objetivo = bd.usuario(id_usuario)
        if objetivo is None:
            abort(404)
        accion = request.form.get("accion")
        if accion == "eliminar":
            if id_usuario == g.usuario["id_usuario"]:
                flash("No puedes eliminar tu propia cuenta.", "error")
            elif bd.eliminar_usuario(id_usuario):
                flash(f"Usuario {objetivo['correo']} eliminado.", "ok")
            elif bd.usuario(id_usuario) is None:
                abort(404)
            else:
                flash("Debe quedar al menos un Administrador.", "error")
        elif accion == "rol":
            rol = request.form.get("rol", "")
            if rol not in ROLES:
                flash("Rol no válido.", "error")
            elif bd.actualizar_usuario(id_usuario, rol=rol):
                flash(f"{objetivo['correo']} ahora es {rol}.", "ok")
            elif bd.usuario(id_usuario) is None:
                abort(404)
            else:
                flash("Debe quedar al menos un Administrador.", "error")
        elif accion == "clave":
            clave = request.form.get("clave", "")
            if len(clave) < LARGO_MINIMO_CLAVE:
                flash(f"La contraseña debe tener al menos {LARGO_MINIMO_CLAVE} caracteres.", "error")
            else:
                if not bd.actualizar_usuario(id_usuario, password_hash=generate_password_hash(clave)):
                    abort(404)
                flash(f"Contraseña de {objetivo['correo']} restablecida.", "ok")
        return redirect(url_for("usuarios"))
