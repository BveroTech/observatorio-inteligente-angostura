"""
Portal > Fuente de video: elegir si el kiosco analiza la cámara IP del humedal o una
captura de pantalla (también cámara USB o el video de demostración). El cambio se
aplica en vivo: el kiosco revisa la configuración cada 2 segundos.
"""
from flask import flash, redirect, render_template, request, url_for

from src.aplicacion import configuracion_fuente as cf
from web.auth import requiere_admin


def _monitores():
    try:
        from src.aplicacion.gestor_monitores import describir_monitores

        return [{"numero": n, "nombre": nombre, "ancho": r[2], "alto": r[3], "principal": p}
                for n, nombre, r, p in describir_monitores()]
    except Exception:
        return []


def _ventanas():
    try:
        from src.adquisicion.captura_ventana import listar_ventanas

        return listar_ventanas()
    except Exception:
        return []


def registrar_rutas_fuente_video(app, obtener_bd):

    @app.route("/fuente-video", methods=["GET", "POST"])
    @requiere_admin
    def fuente_video():
        if request.method == "POST":
            tipo = request.form.get("tipo", "")
            try:
                monitor = int(request.form.get("monitor") or 1)
                indice = int(request.form.get("indice") or 0)
            except ValueError:
                flash("Número de monitor o de cámara no válido.", "error")
                return redirect(url_for("fuente_video"))
            url = request.form.get("url_rtsp", "").strip()
            programa, titulo = None, None
            if tipo == "ventana":
                elegida = request.form.get("ventana", "")
                if elegida and elegida != "_manual":
                    programa, _, titulo_ventana = elegida.partition("|")
                    titulo = request.form.get("titulo_filtro", "").strip()
                    if request.form.get("usar_titulo") == "1":
                        titulo = titulo or titulo_ventana
                else:
                    programa = request.form.get("programa_manual", "").strip()
                    titulo = request.form.get("titulo_filtro", "").strip()
            try:
                # La dirección solo se reemplaza si se escribió una nueva (el campo se muestra vacío).
                cf.guardar_fuente(tipo, monitor=monitor, indice=indice, url_rtsp=url or None,
                                  programa=programa, titulo=titulo)
            except (ValueError, OSError) as error:
                flash(f"No se pudo guardar: {error}", "error")
                return redirect(url_for("fuente_video"))
            if tipo == "rtsp" and not (url or cf.url_rtsp_enmascarada()):
                flash("Falta la dirección de la cámara IP: mientras tanto el kiosco muestra el video de demostración.",
                      "error")
            flash(f"Fuente guardada: {cf.TIPOS[tipo]}. Si el kiosco está abierto, cambia en unos segundos.", "ok")
            return redirect(url_for("fuente_video"))
        return render_template(
            "fuente_video.html", tipos=cf.TIPOS, actual=cf.leer_fuente(), monitores=_monitores(),
            url_enmascarada=cf.url_rtsp_enmascarada(), estado=cf.leer_estado_kiosco(), ventanas=_ventanas(),
        )
