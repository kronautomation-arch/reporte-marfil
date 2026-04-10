"""
REPORTE MARFIL — Orquestador principal.
Jala datos de 4 fuentes (Sheets, Shopify, envia.com, Meta Ads) y genera
dashboard.json con datos DIARIOS para que el frontend agregue
por cualquier rango de fechas.

Jerarquia de fuentes para ventas digitales:
- SHOPIFY: fuente primaria (unidades reales, descuentos, top productos, canales)
- ENVIA: fuente secundaria (costos de envio, cross-check)
- META ADS: gasto publicitario
- SHEETS: POS fisicos, costos fijos, configuracion
"""

import json
import sys
from datetime import date, timedelta, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools.core.env_loader import load_env, get_env
from tools.core.logger import setup_logger
from tools.sheets.sheets_client import SheetsClient
from tools.envia.envia_client import EnviaClient
from tools.meta.meta_client import MetaAdsClient, MetaAPIError
from tools.shopify.shopify_client import ShopifyClient, ShopifyAPIError

logger = setup_logger()


def main():
    logger.info("=== REPORTE MARFIL — Inicio de actualización ===")

    load_env()

    # Rango: desde 1 de enero del año hasta hoy
    hoy = date.today()
    inicio_ano = date(hoy.year, 1, 1)

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
    shopify_client = ShopifyClient(
        shop=get_env("SHOPIFY_STORE"),
        access_token=get_env("SHOPIFY_ACCESS_TOKEN"),
    )

    # === 1. Sheets: todo el año ===
    logger.info("Leyendo Google Sheets...")
    sheets_data = sheets_client.get_data(inicio_ano, hoy)
    config = sheets_data.get("config", {})
    costo_unitario = config.get("costo_unitario_gafa", 0)

    # === 2. Envia.com: ventas digitales (fuente de verdad para "se despacho") ===
    # Envia es el SOURCE OF TRUTH de "que se envio fisicamente". Una orden de
    # Shopify que NO esta en envia significa que el cliente nunca confirmo /
    # nunca se le envio el producto -> NO es venta real.
    logger.info("Consultando envia.com...")
    envia_data = envia_client.get_ventas_digitales(inicio_ano, hoy)

    # Tasa real de devolucion calculada desde status de envia
    devoluciones_info = envia_data.get("devoluciones", {})
    pct_devoluciones = devoluciones_info.get("tasa_por_monto", 0)
    logger.info(
        f"Devoluciones (rechazos en destino): {devoluciones_info.get('ordenes', 0)} ordenes / "
        f"${devoluciones_info.get('monto', 0):,.0f} ({pct_devoluciones*100:.2f}%)"
    )

    # Set de IDs de Shopify que SI tienen envio confirmado en envia (no rechazados)
    shipped_shopify_ids = {
        od.get("shopify_order_id")
        for od in envia_data.get("ordenes_detalle", [])
        if od.get("shopify_order_id")
    }
    logger.info(f"Ordenes despachadas via envia: {len(shipped_shopify_ids)}")

    # === 2.5 Shopify: ventas digitales (detalle, filtrado por despachadas) ===
    # Shopify nos da unidades reales, descuentos, top productos, canales.
    # Pero SOLO contamos como venta las ordenes que ya se despacharon (cross-ref con envia).
    logger.info("Consultando Shopify...")
    shopify_error = None
    try:
        shopify_data = shopify_client.get_resumen_ventas(
            inicio_ano, hoy, shipped_order_ids=shipped_shopify_ids
        )
        nd = shopify_data["no_despachadas"]
        logger.info(
            f"Shopify (despachadas): {shopify_data['ordenes']} ordenes / "
            f"{shopify_data['unidades']} unidades / ${shopify_data['ventas_brutas']:,} brutas"
        )
        logger.warning(
            f"NO DESPACHADAS (cliente no confirmo): {nd['ordenes']} ordenes / "
            f"${nd['monto']:,} ({nd['tasa']*100:.2f}% del total vivo)"
        )
    except (ShopifyAPIError, Exception) as e:
        shopify_error = str(e)
        logger.error(f"Shopify fallo, fallback a envia: {shopify_error}")
        shopify_data = None

    # === 3. Meta Ads: por cuenta y diario ===
    # Si Meta falla (token expirado, permisos, etc.) seguimos generando el dashboard
    # con el resto de datos para que no se quede congelado por completo.
    logger.info("Consultando Meta Ads...")
    meta_error = None
    try:
        meta_data = meta_client.get_all_accounts_data(inicio_ano, hoy)
    except (MetaAPIError, Exception) as e:
        meta_error = str(e)
        logger.error(f"Meta Ads falló, continuando sin datos publicitarios: {meta_error}")
        meta_data = {
            "gasto_total": 0,
            "cuentas": [
                {"nombre": f"Cuenta {str(i + 1).zfill(2)}", "gasto": 0, "purchases": 0}
                for i in range(len(meta_client.account_ids))
            ],
            "cpa": 0,
            "purchases_total": 0,
            "historial_diario": [],
        }

    # === 4. Construir datos diarios DIGITALES ===
    # Fuente PRIMARIA: Shopify (unidades reales, ventas brutas, descuentos)
    # Fuente SECUNDARIA: envia.com (costo de envio real)
    shopify_diario = {}
    if shopify_data:
        for h in shopify_data.get("historial_diario", []):
            shopify_diario[h["fecha"]] = {
                "ventas_brutas": h["ventas_brutas"],
                "ventas_netas": h["ventas_netas"],
                "descuentos": h["descuentos"],
                "unidades": h["unidades"],
                "ordenes": h["ordenes"],
            }

    # Envia: solo costo de envio (los demas datos de envia los usamos como fallback
    # si Shopify fallo, o como cross-check)
    envia_diario = {}
    for h in envia_data.get("historial_diario", []):
        envia_diario[h["fecha"]] = {"ventas": h["ventas"], "ordenes": h["ordenes"]}

    costo_envio_por_dia = {}
    for od in envia_data.get("ordenes_detalle", []):
        f = od["fecha"]
        costo_envio_por_dia[f] = costo_envio_por_dia.get(f, 0) + od.get("costo_envio", 0)

    # === 5. Construir datos diarios para meta (por cuenta) ===
    meta_diario_total = {}
    for h in meta_data.get("historial_diario", []):
        meta_diario_total[h["fecha"]] = h["gasto"]

    # === 6. POS diario desde Sheets ===
    pos_nombres = {
        "caracoli": {"nombre": "Caracolí", "ciudad": "Bucaramanga"},
        "titan_plaza": {"nombre": "Titan Plaza", "ciudad": "Bogotá"},
        "fundadores": {"nombre": "Fundadores", "ciudad": "Manizales"},
    }

    pos_data = {}
    for key, info in pos_nombres.items():
        pd = sheets_data.get("pos", {}).get(key, {})
        costos_fijos = pd.get("costos_fijos", {})

        # Ventas diarias
        ventas_diarias = {}
        for v in pd.get("ventas", []):
            ventas_diarias[v["fecha"]] = {"unidades": v["unidades"], "total": v["total"]}

        # Gastos diarios
        gastos_diarios = {}
        for g in pd.get("gastos", []):
            gastos_diarios[g["fecha"]] = gastos_diarios.get(g["fecha"], 0) + g["monto"]

        pos_data[key] = {
            "nombre": info["nombre"],
            "ciudad": info["ciudad"],
            "costos_fijos": costos_fijos,
            "costos_fijos_total_mensual": sum(costos_fijos.values()),
            "ventas_diarias": ventas_diarias,
            "gastos_diarios": gastos_diarios,
        }

    # === 7. Digital costos fijos desde Sheets ===
    digital_sheets = sheets_data.get("digital", {})
    digital_costos_fijos = digital_sheets.get("costos_fijos", {})
    digital_gastos_var = {}
    for g in digital_sheets.get("gastos", []):
        digital_gastos_var[g["fecha"]] = digital_gastos_var.get(g["fecha"], 0) + g["monto"]

    # === 8. Generar JSON ===
    # Recopilar todas las fechas
    all_dates = set()
    all_dates.update(shopify_diario.keys())
    all_dates.update(envia_diario.keys())
    all_dates.update(meta_diario_total.keys())
    for pd in pos_data.values():
        all_dates.update(pd["ventas_diarias"].keys())
        all_dates.update(pd["gastos_diarios"].keys())
    all_dates.update(digital_gastos_var.keys())

    # Datos diarios combinados
    daily = {}
    for fecha in sorted(all_dates):
        sp = shopify_diario.get(fecha, {})
        ev = envia_diario.get(fecha, {})

        # Si tenemos Shopify, esa es la fuente primaria de ventas digitales.
        # Si no (fallback), caemos a envia.
        if sp:
            digital_ventas = sp.get("ventas_brutas", 0)
            digital_ventas_netas = sp.get("ventas_netas", 0)
            digital_descuentos = sp.get("descuentos", 0)
            digital_unidades = sp.get("unidades", 0)
            digital_ordenes = sp.get("ordenes", 0)
        else:
            digital_ventas = ev.get("ventas", 0)
            digital_ventas_netas = ev.get("ventas", 0)
            digital_descuentos = 0
            digital_unidades = ev.get("ordenes", 0)  # aproximacion
            digital_ordenes = ev.get("ordenes", 0)

        daily[fecha] = {
            # Ventas digitales (Shopify primario, envia fallback)
            "envia_ventas": digital_ventas,           # nombre legacy mantenido para frontend
            "envia_ordenes": digital_ordenes,
            "envia_unidades": digital_unidades,
            "envia_costo_envio": costo_envio_por_dia.get(fecha, 0),
            "digital_ventas_netas": digital_ventas_netas,
            "digital_descuentos": digital_descuentos,
            # Cross-check info (envia paralelo cuando Shopify es fuente)
            "envia_ventas_raw": ev.get("ventas", 0),
            "envia_ordenes_raw": ev.get("ordenes", 0),
            # Meta Ads
            "meta_gasto": meta_diario_total.get(fecha, 0),
        }
        # POS por punto
        for key in pos_nombres:
            pd = pos_data[key]
            vd = pd["ventas_diarias"].get(fecha, {})
            daily[fecha][f"pos_{key}_ventas"] = vd.get("total", 0) if isinstance(vd, dict) else 0
            daily[fecha][f"pos_{key}_unidades"] = vd.get("unidades", 0) if isinstance(vd, dict) else 0
            daily[fecha][f"pos_{key}_gastos"] = pd["gastos_diarios"].get(fecha, 0)
        # Digital gastos variables
        daily[fecha]["digital_gastos_var"] = digital_gastos_var.get(fecha, 0)

    errors = {}
    if meta_error:
        errors["meta"] = meta_error
    if shopify_error:
        errors["shopify"] = shopify_error

    dashboard = {
        "updated_at": datetime.now().isoformat(),
        "errors": errors,
        "config": {
            "costo_unitario_gafa": costo_unitario,
            "pct_devoluciones": pct_devoluciones,
            "ventas_fuente_primaria": "shopify" if shopify_data else "envia",
        },
        "devoluciones": {
            "monto_ytd": round(devoluciones_info.get("monto", 0)),
            "ordenes_ytd": devoluciones_info.get("ordenes", 0),
            "tasa_por_monto": round(devoluciones_info.get("tasa_por_monto", 0), 4),
            "tasa_por_ordenes": round(devoluciones_info.get("tasa_por_ordenes", 0), 4),
        },
        "shopify": {
            "ventas_brutas_ytd": shopify_data["ventas_brutas"] if shopify_data else 0,
            "ventas_netas_ytd": shopify_data["ventas_netas"] if shopify_data else 0,
            "descuentos_ytd": shopify_data["descuentos_total"] if shopify_data else 0,
            "unidades_ytd": shopify_data["unidades"] if shopify_data else 0,
            "ordenes_ytd": shopify_data["ordenes"] if shopify_data else 0,
            "canceladas": shopify_data["canceladas"] if shopify_data else {"ordenes": 0, "monto": 0},
            "reembolsadas": shopify_data["reembolsadas"] if shopify_data else {"ordenes": 0, "monto": 0},
            "no_despachadas": shopify_data["no_despachadas"] if shopify_data else {"ordenes": 0, "monto": 0, "tasa": 0, "por_canal": []},
            "top_productos": shopify_data["top_productos"] if shopify_data else [],
            "top_skus": shopify_data["top_skus"] if shopify_data else [],
            "canales": shopify_data["canales"] if shopify_data else [],
            "codigos_descuento": shopify_data["codigos_descuento"] if shopify_data else [],
        },
        "ads_cuentas": [
            {"nombre": c["nombre"], "gasto": round(c["gasto"]), "purchases": c.get("purchases", 0)}
            for c in meta_data.get("cuentas", [])
        ],
        "ads_gasto_total": round(meta_data.get("gasto_total", 0)),
        "pos_info": {
            key: {
                "nombre": info["nombre"],
                "ciudad": info["ciudad"],
                "costos_fijos": pos_data[key]["costos_fijos"],
                "costos_fijos_total_mensual": pos_data[key]["costos_fijos_total_mensual"],
            }
            for key, info in pos_nombres.items()
        },
        "digital_costos_fijos": digital_costos_fijos,
        "digital_costos_fijos_total_mensual": sum(digital_costos_fijos.values()),
        "daily": daily,
    }

    output_path = Path(__file__).resolve().parent / "dashboard.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)

    logger.info(f"dashboard.json generado: {len(daily)} días de datos")
    logger.info("=== REPORTE MARFIL — Actualización completada ===")


if __name__ == "__main__":
    main()
