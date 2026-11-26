import csv
import io

from datetime import datetime, timedelta
from flask import Response, render_template, request
from src.persistencia.repositorio_sqlite import limites_dia
from web.auth import requiere_admin, requiere_sesion

POR_PAGINA = 25


def _entero_positivo(valor, defecto=1):
    try:
        return max(int(valor), 1)
    except (TypeError, ValueError):
        return defecto

def filtros_bitacora():
    filtros = {"incluir_simulacion": request.args.get("simulacion", "1") == "1"}
    id_especie = request.args.get("especie", "").strip()
    if id_especie.isdigit():
        filtros["id_especie"] = int(id_especie)
    for campo in ("desde", "hasta"):
        valor = request.args.get(campo, "").strip()
        try:
            fecha = datetime.strptime(valor, "%Y-%m-%d")
        except ValueError:
            continue
        if campo == "hasta":
            fecha += timedelta(days=1)  # hasta inclusive
        filtros[campo] = fecha.strftime("%Y-%m-%d")
    return filtros

def registrar_rutas_metricas(app, obtener_bd):
    """Registra las rutas del dashboard analítico, bitácora y exportación CSV."""

    @app.route("/panel")
    @requiere_admin
    def panel():
        bd = obtener_bd()
        hoy, _, manana = limites_dia()
        dias = _entero_positivo(request.args.get("dias", 7), 7)
        dias = dias if dias in (1, 7, 30) else 7
        desde = (hoy - timedelta(days=dias - 1)).isoformat()
        incluir_simulacion = request.args.get("simulacion") == "1"
        filtros = {"desde": desde, "hasta": manana, "incluir_simulacion": incluir_simulacion}

        bd.conexion.execute("BEGIN")
        resumen_hoy = bd.resumen_del_dia(hoy)
        metricas = bd.resumen_metricas(desde=desde, hasta=manana)
        descartes_px = metricas.get("descartes_px") or 0
        descartes_conf = metricas.get("descartes_confianza") or 0
        candidatas = metricas.get("detecciones") or 0
        tasas = {
            "px": descartes_px / candidatas if candidatas else None,
            "confianza": descartes_conf / candidatas if candidatas else None,
        }
        por_hora = bd.avistamientos_por_hora(**filtros)
        por_dia = bd.avistamientos_por_dia(dias=dias, hoy=hoy, incluir_simulacion=incluir_simulacion)
        por_especie = bd.avistamientos_por_especie(limite=10, **filtros)
        periodo_total = bd.contar_avistamientos(**filtros)
        simulados = bd.contar_avistamientos(desde=desde, hasta=manana) - bd.contar_avistamientos(
            desde=desde, hasta=manana, incluir_simulacion=False,
        )
        return render_template(
            "panel.html",
            dias=dias,
            incluir_simulacion=incluir_simulacion,
            hoy_total=resumen_hoy["total"],
            hoy_especies=len(resumen_hoy["especies"]),
            periodo_total=periodo_total,
            simulados=simulados,
            metricas=metricas,
            candidatas=candidatas,
            tasas=tasas,
            por_hora=por_hora,
            max_hora=max([c for _, c in por_hora] + [1]),
            por_dia=por_dia,
            max_dia=max([c for _, c in por_dia] + [1]),
            por_especie=por_especie,
            max_especie=max([e["cantidad"] for e in por_especie] + [1]),
            ultimas_metricas=bd.metricas(limite=15),
            especies_activas=bd.total_especies(solo_activas=True),
            especies_total=bd.total_especies(),
        )

    @app.route("/bitacora")
    @requiere_sesion
    def bitacora():
        bd = obtener_bd()
        bd.conexion.execute("BEGIN")
        filtros = filtros_bitacora()
        pagina = _entero_positivo(request.args.get("pagina", 1), 1)
        total = bd.contar_avistamientos(**filtros)
        paginas = max((total + POR_PAGINA - 1) // POR_PAGINA, 1)
        pagina = min(pagina, paginas)
        filas = bd.avistamientos(limite=POR_PAGINA, desplazamiento=(pagina - 1) * POR_PAGINA, **filtros)
        argumentos = {k: v for k, v in request.args.items() if k != "pagina"}
        return render_template(
            "bitacora.html", filas=filas, total=total, pagina=pagina, paginas=paginas,
            argumentos=argumentos, opciones_especie=bd.especies(),
        )

    @app.route("/bitacora.csv")
    @requiere_sesion
    def bitacora_csv():
        bd = obtener_bd()
        filas = bd.avistamientos(limite=None, **filtros_bitacora())
        salida = io.StringIO()
        salida.write("\ufeff")  # BOM UTF-8 para que Excel reconozca los acentos
        escritor = csv.writer(salida, delimiter=";")
        escritor.writerow([
            "id_avistamiento", "fecha_hora", "id_especie", "nombre_comun", "nombre_cientifico",
            "nivel_confianza", "ancho_bbox_px", "alto_bbox_px", "area_px", "es_simulacion", "ruta_captura_thumb",
        ])
        for f in filas:
            escritor.writerow([
                f["id_avistamiento"], f["timestamp_deteccion"], f["id_especie"], f["nombre_comun"],
                f["nombre_cientifico"], f"{f['nivel_confianza']:.4f}".replace(".", ","), f["ancho_bbox_px"],
                f["alto_bbox_px"], f["area_px"], f["es_simulacion"], f["ruta_captura_thumb"] or "",
            ])
        nombre = f"avistamientos_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        return Response(
            salida.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
        )
