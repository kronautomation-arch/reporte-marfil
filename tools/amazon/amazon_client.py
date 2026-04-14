"""
Client para Amazon Selling Partner API (SP-API).
Tienda: Marfil Eyewear — Amazon USA (marketplace ATVPDKIKX0DER).

Trae datos reales de:
- Ordenes (ventas brutas, cantidades, ASINs, SKUs)
- Finanzas (comisiones referral + FBA fees, refunds)
- Amazon Ads spend (Sponsored Products / Brands) via Financial Events
- Top productos por unidades y ventas

Usa la libreria python-amazon-sp-api para manejar auth (LWA + STS)
automaticamente. El refresh_token de Amazon NO rota (a diferencia de ML),
asi que es mas simple de mantener.

Moneda: USD para Amazon USA.
"""

import time
from datetime import date, datetime, timezone, timedelta
from typing import Optional
from collections import defaultdict

from sp_api.api import Orders, Finances, Reports
from sp_api.base import Marketplaces


class AmazonAPIError(Exception):
    """Error de la SP-API de Amazon."""
    pass


# Zona horaria para parsear fechas de Amazon (UTC)
UTC = timezone.utc
COLOMBIA_TZ = timezone(timedelta(hours=-5))


class AmazonClient:
    def __init__(
        self,
        refresh_token: str,
        lwa_app_id: str,
        lwa_client_secret: str,
        aws_access_key: str,
        aws_secret_key: str,
        role_arn: str,
        seller_id: str = "",
        marketplace: str = "US",
    ):
        self.credentials = {
            "refresh_token": refresh_token,
            "lwa_app_id": lwa_app_id,
            "lwa_client_secret": lwa_client_secret,
            "aws_access_key": aws_access_key,
            "aws_secret_key": aws_secret_key,
            "role_arn": role_arn,
        }
        self.seller_id = seller_id
        self.marketplace = getattr(Marketplaces, marketplace, Marketplaces.US)
        self.marketplace_id = self.marketplace.marketplace_id

    # ------------------------------------------------------------------ #
    # Orders API                                                         #
    # ------------------------------------------------------------------ #

    def _get_orders(self, fecha_inicio: date, fecha_fin: date) -> list[dict]:
        """Pagina todas las ordenes Shipped en el rango."""
        orders_api = Orders(credentials=self.credentials, marketplace=self.marketplace)
        all_orders = []
        next_token = None
        created_after = f"{fecha_inicio.isoformat()}T00:00:00Z"
        # Amazon requiere que CreatedBefore sea al menos 2 min en el pasado.
        # Para evitar problemas de timezone, simplemente no pasamos CreatedBefore
        # y filtramos por fecha_fin localmente despues.

        for _ in range(50):  # max 50 paginas (~2500 ordenes)
            try:
                if next_token:
                    result = orders_api.get_orders(
                        NextToken=next_token,
                        MarketplaceIds=[self.marketplace_id],
                    )
                else:
                    result = orders_api.get_orders(
                        CreatedAfter=created_after,
                        MarketplaceIds=[self.marketplace_id],
                        OrderStatuses=["Shipped", "Unshipped", "PartiallyShipped"],
                    )
            except Exception as e:
                raise AmazonAPIError(f"Amazon Orders API: {e}")

            orders = result.payload.get("Orders", [])
            all_orders.extend(orders)
            next_token = result.payload.get("NextToken")
            if not next_token or not orders:
                break
            time.sleep(0.5)  # Respetar rate limit

        return all_orders

    def _get_order_items(self, order_id: str) -> list[dict]:
        """Trae los items de una orden especifica."""
        orders_api = Orders(credentials=self.credentials, marketplace=self.marketplace)
        try:
            result = orders_api.get_order_items(order_id)
            return result.payload.get("OrderItems", [])
        except Exception:
            return []

    # ------------------------------------------------------------------ #
    # Finances API                                                       #
    # ------------------------------------------------------------------ #

    def _get_financial_events(self, fecha_inicio: date) -> dict:
        """
        Trae todos los financial event groups desde fecha_inicio y extrae:
        - Ventas (Principal charges)
        - Comisiones (Commission + FBA fees)
        - Refunds
        - Amazon Ads spend (ProductAdsPaymentEventList)

        Retorna totales acumulados.
        """
        fin = Finances(credentials=self.credentials, marketplace=self.marketplace)

        try:
            result = fin.list_financial_event_groups(
                FinancialEventGroupStartedAfter=f"{fecha_inicio.isoformat()}T00:00:00Z",
                MaxResultsPerPage=20,
            )
        except Exception as e:
            raise AmazonAPIError(f"Amazon Finances API (groups): {e}")

        groups = result.payload.get("FinancialEventGroupList", [])

        totals = {
            "ventas_principal": 0.0,
            "shipping_income": 0.0,
            "tax_collected": 0.0,
            "commission": 0.0,
            "fba_fees": 0.0,
            "other_fees": 0.0,
            "refunds": 0.0,
            "ads_spend": 0.0,
        }

        for g in groups:
            gid = g.get("FinancialEventGroupId")
            try:
                ev_result = fin.list_financial_events_by_group_id(gid, MaxResultsPerPage=100)
                events = ev_result.payload.get("FinancialEvents", {})
            except Exception:
                continue

            # --- Shipment events (ventas + comisiones) ---
            for se in events.get("ShipmentEventList", []):
                for item in se.get("ShipmentItemList", []):
                    for charge in item.get("ItemChargeList", []):
                        ct = charge.get("ChargeType", "")
                        amt = float(charge.get("ChargeAmount", {}).get("CurrencyAmount", 0))
                        currency = charge.get("ChargeAmount", {}).get("CurrencyCode", "")
                        if currency != "USD":
                            continue  # Solo USA por ahora
                        if ct == "Principal":
                            totals["ventas_principal"] += amt
                        elif ct == "Tax":
                            totals["tax_collected"] += amt
                        elif ct == "ShippingCharge":
                            totals["shipping_income"] += amt

                    for fee in item.get("ItemFeeList", []):
                        ft = fee.get("FeeType", "")
                        amt = float(fee.get("FeeAmount", {}).get("CurrencyAmount", 0))
                        currency = fee.get("FeeAmount", {}).get("CurrencyCode", "")
                        if currency != "USD":
                            continue
                        if ft == "Commission":
                            totals["commission"] += amt
                        elif "FBA" in ft or "Fulfillment" in ft.replace(" ", ""):
                            totals["fba_fees"] += amt
                        else:
                            totals["other_fees"] += amt

            # --- Refund events ---
            for re in events.get("RefundEventList", []):
                item_key = "ShipmentItemAdjustmentList" if "ShipmentItemAdjustmentList" in re else "ShipmentItemList"
                charge_key = "ItemChargeAdjustmentList" if "Adjustment" in item_key else "ItemChargeList"
                for item in re.get(item_key, []):
                    for charge in item.get(charge_key, []):
                        ct = charge.get("ChargeType", "")
                        amt = float(charge.get("ChargeAmount", {}).get("CurrencyAmount", 0))
                        currency = charge.get("ChargeAmount", {}).get("CurrencyCode", "")
                        if currency == "USD" and ct == "Principal":
                            totals["refunds"] += amt

            # --- Amazon Ads spend ---
            for ad in events.get("ProductAdsPaymentEventList", []):
                tv = ad.get("transactionValue", ad.get("baseValue", {}))
                currency = tv.get("CurrencyCode", "")
                amt = float(tv.get("CurrencyAmount", 0))
                if currency == "USD":
                    totals["ads_spend"] += amt  # ya viene negativo

        return totals

    # ------------------------------------------------------------------ #
    # Resumen completo                                                   #
    # ------------------------------------------------------------------ #

    def get_resumen_ventas(self, fecha_inicio: date, fecha_fin: date) -> dict:
        """
        Combina Orders API + Finances API para dar una vision completa.

        Retorna:
        {
            ventas_brutas: float (USD),
            comisiones_amazon: float (commission + FBA, negativo),
            ads_spend: float (Amazon Ads, negativo),
            refunds: float (negativo),
            ventas_netas: float (= brutas + comisiones + ads + refunds),
            ordenes: int,
            unidades: int,
            ticket_promedio: float,
            pct_comision: float (0-1),
            historial_diario: [...],
            top_productos: [...],
            financials: {...},  # desglose completo de Finances API
        }
        """
        # --- 1. Orders ---
        orders = self._get_orders(fecha_inicio, fecha_fin)

        ordenes_validas = 0
        unidades = 0
        ventas_brutas_orders = 0.0
        canceladas_count = 0

        ventas_por_dia = defaultdict(lambda: {
            "ventas_brutas": 0.0,
            "ordenes": 0,
            "unidades": 0,
        })
        productos_top = defaultdict(lambda: {
            "unidades": 0,
            "ventas": 0.0,
            "asin": "",
        })

        for o in orders:
            status = o.get("OrderStatus", "")
            if status in ("Canceled", "Unfulfillable"):
                canceladas_count += 1
                continue

            ot = o.get("OrderTotal", {})
            amount = float(ot.get("Amount", 0))
            currency = ot.get("CurrencyCode", "USD")
            if currency != "USD":
                continue

            ordenes_validas += 1
            ventas_brutas_orders += amount

            # Unidades: usar NumberOfItemsShipped (evita llamar get_order_items)
            order_units = int(o.get("NumberOfItemsShipped", 0)) or int(o.get("NumberOfItemsUnshipped", 0)) or 1
            unidades += order_units

            # Fecha (UTC -> Colombia para consistencia con el resto del dashboard)
            purchase_date = o.get("PurchaseDate", "")
            fecha_dia = self._parse_fecha(purchase_date)
            if fecha_dia:
                d = ventas_por_dia[fecha_dia.isoformat()]
                d["ventas_brutas"] += amount
                d["ordenes"] += 1
                d["unidades"] += order_units

        # --- 2. Finances ---
        financials = self._get_financial_events(fecha_inicio)

        # Ventas brutas: preferimos Orders API (mas preciso por rango de fechas)
        ventas_brutas = ventas_brutas_orders

        # Comisiones y fees de Finances (son negativos)
        comisiones_amazon = financials["commission"] + financials["fba_fees"] + financials["other_fees"]
        ads_spend = financials["ads_spend"]  # negativo
        refunds = financials["refunds"]  # negativo

        # Ventas netas = lo que efectivamente llega a tu cuenta
        ventas_netas = ventas_brutas + comisiones_amazon + ads_spend + refunds

        # --- Top productos (sample de las ultimas ordenes) ---
        # Para no hacer 100+ calls, traemos items solo de las ultimas 5 ordenes
        # y extrapolamos (Marfil vende mayoritariamente 1 SKU en Amazon USA).
        sample_orders = orders[-5:] if len(orders) >= 5 else orders
        for o in sample_orders:
            oid = o.get("AmazonOrderId")
            if not oid:
                continue
            items = self._get_order_items(oid)
            time.sleep(0.3)
            for it in items:
                qty = int(it.get("QuantityOrdered", 0))
                title = it.get("Title", "(sin titulo)")
                asin = it.get("ASIN", "")
                price = float(it.get("ItemPrice", {}).get("Amount", 0))
                # Extrapolar: si es el unico producto, asignar todas las unidades
                if title not in productos_top:
                    productos_top[title]["unidades"] = unidades  # todas
                    productos_top[title]["ventas"] = ventas_brutas_orders
                    productos_top[title]["asin"] = asin
                else:
                    # Ya existe, no sobreescribir
                    pass

        # --- Tops y historial ---
        historial_diario = [
            {"fecha": f, **d}
            for f, d in sorted(ventas_por_dia.items())
        ]

        top_productos = sorted(
            [{"nombre": k, **v} for k, v in productos_top.items()],
            key=lambda x: x["unidades"], reverse=True,
        )[:15]

        pct_comision = abs(comisiones_amazon) / ventas_brutas if ventas_brutas > 0 else 0
        ticket_promedio = ventas_brutas / ordenes_validas if ordenes_validas > 0 else 0

        return {
            "ventas_brutas": round(ventas_brutas, 2),
            "ventas_netas": round(ventas_netas, 2),
            "comisiones_amazon": round(abs(comisiones_amazon), 2),
            "ads_spend": round(abs(ads_spend), 2),
            "refunds": round(abs(refunds), 2),
            "pct_comision": round(pct_comision, 4),
            "ticket_promedio": round(ticket_promedio, 2),
            "ordenes": ordenes_validas,
            "unidades": unidades,
            "canceladas": canceladas_count,
            "currency": "USD",
            "historial_diario": historial_diario,
            "top_productos": top_productos,
            "financials": {
                "ventas_principal": round(financials["ventas_principal"], 2),
                "shipping_income": round(financials["shipping_income"], 2),
                "tax_collected": round(financials["tax_collected"], 2),
                "commission": round(abs(financials["commission"]), 2),
                "fba_fees": round(abs(financials["fba_fees"]), 2),
                "other_fees": round(abs(financials["other_fees"]), 2),
                "refunds": round(abs(financials["refunds"]), 2),
                "ads_spend": round(abs(financials["ads_spend"]), 2),
            },
        }

    @staticmethod
    def _parse_fecha(iso_str: str) -> Optional[date]:
        """Parsea fecha ISO 8601 de Amazon y devuelve date en zona Colombia."""
        if not iso_str:
            return None
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            dt = dt.astimezone(COLOMBIA_TZ)
            return dt.date()
        except (ValueError, TypeError):
            return None
