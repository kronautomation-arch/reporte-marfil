"""
REPORTE MARFIL — Orquestador principal.
Jala datos de 3 fuentes (Sheets, envia.com, Meta Ads), calcula métricas
y genera dashboard.json para el frontend.
"""

import json
import sys
from datetime import date, timedelta, datetime
from pathlib import Path

# Agregar raíz del proyecto al path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools.core.env_loader import load_env, get_env
from tools.core.logger import setup_logger
from tools.sheets.sheets_client import SheetsClient
from tools.envia.envia_client import EnviaClient
from tools.meta.meta_client import MetaAdsClient

logger = setup_logger()


def calcular_periodo(periodo: str) -> tuple[date, date]:
    """Calcula fecha_inicio y fecha_fin para un periodo dado."""
    hoy = date.today()

    if periodo == "ayer":
        ayer = hoy - timedelta(days=1)
        return ayer, ayer
    elif periodo == "7d":
        return hoy - timedelta(days=6), hoy
    elif periodo == "14d":
        return hoy - timedelta(days=13), hoy
    elif periodo == "30d":
        return hoy - timedelta(days=29), hoy
    elif periodo == "esta_semana":
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        return inicio_semana, hoy
    elif periodo == "este_mes":
        return hoy.replace(day=1), hoy
    elif periodo == "todo":
        return date(2024, 1, 1), hoy
    else:
        return hoy - timedelta(days=29), hoy


def procesar_pos(sheets_data: dict, config: dict, periodo: str) -> dict:
    """Procesa datos de puntos de venta desde Sheets."""
    fecha_inicio, fecha_fin = calcular_periodo(periodo)
    costo_unitario = config.get("costo_unitario_gafa", 0)

    puntos = {}
    nombres = {
        "caracoli": ("Caracolí", "Bucaramanga"),
        "titan_plaza": ("Titan Plaza", "Bogotá"),
        "fundadores": ("Fundadores", "Manizales"),
    }

    for key, (nombre, ciudad) in nombres.items():
        pos_data = sheets_data.get("pos", {}).get(key, {})
        ventas_list = pos_data.get("ventas", [])
        gastos_list = pos_data.get("gastos", [])
        costos_fijos = pos_data.get("costos_fijos", {})

        # Filtrar por periodo
        ventas_filtradas = [
            v for v in ventas_list
            if fecha_inicio.isoformat() <= v["fecha"] <= fecha_fin.isoformat()
        ]
        gastos_filtrados = [
            g for g in gastos_list
            if fecha_inicio.isoformat() <= g["fecha"] <= fecha_fin.isoformat()
        ]

        total_ventas = sum(v["total"] for v in ventas_filtradas)
        total_unidades = sum(v["unidades"] for v in ventas_filtradas)
        total_gastos_diarios = sum(g["monto"] for g in gastos_filtrados)
        costo_mercancia = total_unidades * costo_unitario

        # Prorratear costos fijos al periodo
        dias_periodo = max((fecha_fin - fecha_inicio).days + 1, 1)
        dias_mes = 30
        factor_prorrateo = dias_periodo / dias_mes
        total_costos_fijos = sum(costos_fijos.values()) * factor_prorrateo

        gastos_totales = total_costos_fijos + total_gastos_diarios + costo_mercancia
        utilidad = total_ventas - gastos_totales
        margen = (utilidad / total_ventas * 100) if total_ventas > 0 else 0

        # Desglose
        arriendo = costos_fijos.get("Arriendo", 0) * factor_prorrateo
        salarios = sum(v for k, v in costos_fijos.items() if "salario" in k.lower()) * factor_prorrateo

        puntos[key] = {
            "nombre": nombre,
            "ciudad": ciudad,
            "ventas": total_ventas,
            "unidades": total_unidades,
            "gastos": {
                "arriendo": round(arriendo),
                "salarios": round(salarios),
                "costo_gafas": round(costo_mercancia),
                "otros": round(total_gastos_diarios),
                "total": round(gastos_totales),
            },
            "utilidad": round(utilidad),
            "margen": round(margen, 1),
        }

    return puntos


def procesar_digital(envia_data: dict, meta_data: dict, sheets_data: dict, config: dict, periodo: str) -> dict:
    """Procesa datos digitales: ventas (envia), ads (meta), costos fijos (sheets)."""
    fecha_inicio, fecha_fin = calcular_periodo(periodo)
    costo_unitario = config.get("costo_unitario_gafa", 0)
    pct_devoluciones = config.get("pct_devoluciones", 0.15)

    # Ventas de envia.com
    ventas_brutas = envia_data.get("ventas_brutas", 0)
    ordenes = envia_data.get("ordenes", 0)
    unidades = envia_data.get("unidades", 0)

    # Devoluciones estimadas
    devoluciones = ventas_brutas * pct_devoluciones
    ventas_netas = ventas_brutas - devoluciones

    # Costo mercancía
    costo_producto = unidades * costo_unitario

    # Costo envío — estimado como dato del Sheets o un % (ajustar según API real)
    # Por ahora estimamos costo de envío como dato disponible en envia.com
    costo_envio = ventas_brutas * 0.08  # Placeholder: 8% del total como envío

    # Ads
    gasto_ads = meta_data.get("gasto_total", 0)
    cuentas_ads = meta_data.get("cuentas", [])
    purchases = meta_data.get("purchases_total", 0)
    cpa = meta_data.get("cpa", 0)

    # ROAS
    roas = ventas_netas / gasto_ads if gasto_ads > 0 else 0

    # Costos fijos digitales del Sheets
    digital_sheets = sheets_data.get("digital", {})
    costos_fijos = digital_sheets.get("costos_fijos", {})
    gastos_variables = digital_sheets.get("gastos", [])

    # Prorratear costos fijos
    dias_periodo = max((fecha_fin - fecha_inicio).days + 1, 1)
    factor_prorrateo = dias_periodo / 30
    total_costos_fijos = sum(costos_fijos.values()) * factor_prorrateo
    total_gastos_variables = sum(g["monto"] for g in gastos_variables)

    # Costo operaciones = costos fijos + gastos variables
    costo_operaciones = total_costos_fijos + total_gastos_variables

    # Utilidad
    utilidad = ventas_netas - costo_producto - costo_envio - gasto_ads - costo_operaciones - devoluciones

    # Último día
    historial = envia_data.get("historial_diario", [])
    meta_daily = meta_data.get("historial_diario", [])
    ultimo_dia_ventas = historial[-1]["ventas"] if historial else 0
    ultimo_dia_ordenes = historial[-1]["ordenes"] if historial else 0
    ultimo_dia_gasto = meta_daily[-1]["gasto"] if meta_daily else 0
    ultimo_dia_roas = ultimo_dia_ventas / ultimo_dia_gasto if ultimo_dia_gasto > 0 else 0
    ultimo_dia_cpa = ultimo_dia_gasto / ultimo_dia_ordenes if ultimo_dia_ordenes > 0 else 0

    return {
        "ventas_brutas": round(ventas_brutas),
        "devoluciones": round(devoluciones),
        "ventas_netas": round(ventas_netas),
        "ordenes": ordenes,
        "unidades": unidades,
        "costo_producto": round(costo_producto),
        "costo_envio": round(costo_envio),
        "costo_operaciones": round(costo_operaciones),
        "costos_fijos": {k: round(v) for k, v in costos_fijos.items()},
        "ads": {
            "gasto_total": round(gasto_ads),
            "cuentas": [
                {"nombre": c["nombre"], "gasto": round(c["gasto"])}
                for c in cuentas_ads
            ],
            "roas": round(roas, 1),
            "cpa": round(cpa),
        },
        "utilidad": round(utilidad),
        "ultimo_dia": {
            "ventas": round(ultimo_dia_ventas),
            "utilidad": 0,
            "ordenes": ultimo_dia_ordenes,
            "roas": round(ultimo_dia_roas, 1),
            "cpa": round(ultimo_dia_cpa),
            "gasto_ads": round(ultimo_dia_gasto),
        },
        "historial_diario": [
            {"fecha": h["fecha"], "ventas": round(h["ventas"]), "utilidad": 0}
            for h in historial
        ],
    }


def calcular_consolidado(digital: dict, pos: dict) -> dict:
    """Calcula vista 360 consolidada."""
    ingresos_digital = digital.get("ventas_netas", 0)
    ingresos_pos = sum(p.get("ventas", 0) for p in pos.values())
    ingresos_totales = ingresos_digital + ingresos_pos

    costos_digital = (
        digital.get("costo_producto", 0) +
        digital.get("costo_envio", 0) +
        digital.get("costo_operaciones", 0) +
        digital.get("ads", {}).get("gasto_total", 0) +
        digital.get("devoluciones", 0)
    )
    costos_pos = sum(p.get("gastos", {}).get("total", 0) for p in pos.values())
    costos_totales = costos_digital + costos_pos

    utilidad_neta = ingresos_totales - costos_totales
    margen = (utilidad_neta / ingresos_totales * 100) if ingresos_totales > 0 else 0

    distribucion = {}
    if ingresos_totales > 0:
        distribucion["digital"] = round(ingresos_digital / ingresos_totales * 100, 1)
        for key, punto in pos.items():
            distribucion[key] = round(punto.get("ventas", 0) / ingresos_totales * 100, 1)

    return {
        "ingresos_totales": round(ingresos_totales),
        "costos_totales": round(costos_totales),
        "utilidad_neta": round(utilidad_neta),
        "margen": round(margen, 1),
        "distribucion": distribucion,
    }


def generar_dashboard_json(periodos: list[str] = None) -> dict:
    """Genera el JSON completo del dashboard."""
    if periodos is None:
        periodos = ["ayer", "7d", "14d", "30d", "esta_semana", "este_mes", "todo"]

    load_env()

    # Inicializar clients
    sheets_client = SheetsClient(
        credentials_path=get_env("GOOGLE_SHEETS_CREDENTIALS_PATH"),
        spreadsheet_id=get_env("SPREADSHEET_ID"),
    )
    envia_client = EnviaClient(api_token=get_env("ENVIA_API_KEY"))
    meta_client = MetaAdsClient(
        access_token=get_env("META_ACCESS_TOKEN"),
        account_ids=[get_env("META_ACCOUNT_ID_1"), get_env("META_ACCOUNT_ID_2")],
    )

    dashboard = {
        "updated_at": datetime.now().isoformat(),
        "periodos": {},
    }

    for periodo in periodos:
        logger.info(f"Procesando periodo: {periodo}")
        fecha_inicio, fecha_fin = calcular_periodo(periodo)

        # Obtener datos
        sheets_data = sheets_client.get_data(fecha_inicio, fecha_fin)
        config = sheets_data.get("config", {})

        envia_data = envia_client.get_ventas_digitales(fecha_inicio, fecha_fin)
        meta_data = meta_client.get_all_accounts_data(fecha_inicio, fecha_fin)

        # Procesar
        pos = procesar_pos(sheets_data, config, periodo)
        digital = procesar_digital(envia_data, meta_data, sheets_data, config, periodo)
        consolidado = calcular_consolidado(digital, pos)

        dashboard["periodos"][periodo] = {
            "fecha_inicio": fecha_inicio.isoformat(),
            "fecha_fin": fecha_fin.isoformat(),
            "config": config,
            "digital": digital,
            "pos": pos,
            "consolidado": consolidado,
        }

    return dashboard


def main():
    logger.info("=== REPORTE MARFIL — Inicio de actualización ===")

    try:
        dashboard = generar_dashboard_json()

        output_path = Path(__file__).resolve().parent / "dashboard.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(dashboard, f, ensure_ascii=False, indent=2)

        logger.info(f"dashboard.json generado exitosamente ({output_path})")
        logger.info(f"Periodos procesados: {list(dashboard['periodos'].keys())}")

    except Exception as e:
        logger.error(f"Error generando dashboard: {e}", exc_info=True)
        raise

    logger.info("=== REPORTE MARFIL — Actualización completada ===")


if __name__ == "__main__":
    main()
