"""
Client para la API REST Admin de Shopify (tienda Marfil Oficial).

Trae las ordenes con datos REALES de:
- Unidades vendidas (sum de line_items.quantity)
- Precio de venta (subtotal_price + total_discounts = "precio bruto")
- Descuentos aplicados
- Canal de venta (source_name)
- Top productos / SKUs / variantes
- Estado financiero y fulfillment

Base URL: https://{shop}.myshopify.com/admin/api/{version}/
Auth: header X-Shopify-Access-Token
Docs: https://shopify.dev/docs/api/admin-rest/latest/resources/order

Notas de implementacion:
- La API tiene rate limit de ~2 req/seg en plan Basic. Se respeta el header
  X-Shopify-Shop-Api-Call-Limit y se hace backoff si nos acercamos al limite.
- Paginacion: cursor-based via header Link (rel="next").
- Las apps custom heredadas (creadas antes de 2024) tienen acceso al
  historico completo de ordenes sin necesitar el scope read_all_orders.
"""

import re
import time
import requests
from datetime import date, datetime, timezone
from typing import Optional, Iterator
from collections import defaultdict


class ShopifyAPIError(Exception):
    """Error de la API de Shopify (no-200 que no es rate limit recuperable)."""
    pass


# Status financieros que cuentan como venta confirmada (la venta ocurrio).
# pending = COD esperando entrega, paid = prepago, partially_paid = anticipo
PAID_STATUSES = {"paid", "partially_paid", "pending", "authorized"}

# Status financieros que NO son venta (devuelta o anulada)
REFUNDED_STATUSES = {"refunded", "voided"}


class ShopifyClient:
    def __init__(self, shop: str, access_token: str, api_version: str = "2025-07"):
        """
        shop: subdominio (ej: "marfil-oficial" para marfil-oficial.myshopify.com)
        access_token: token Admin API (shpat_... o shppa_...)
        """
        self.shop = shop
        self.api_version = api_version
        self.base_url = f"https://{shop}.myshopify.com/admin/api/{api_version}"
        self.session = requests.Session()
        self.session.headers.update({
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _request(self, method: str, url: str, params: Optional[dict] = None) -> requests.Response:
        """
        Hace request con manejo de:
        - Rate limit (429): respeta Retry-After y reintenta hasta 3 veces.
        - Bucket cercano al limite: pequeno sleep preventivo.
        - Errores 4xx/5xx: levanta ShopifyAPIError con detalle.
        """
        for attempt in range(3):
            response = self.session.request(method, url, params=params, timeout=30)

            # Bucket call limit: "X-Shopify-Shop-Api-Call-Limit: 39/40" -> sleep
            limit_header = response.headers.get("X-Shopify-Shop-Api-Call-Limit", "")
            if "/" in limit_header:
                used, total = (int(x) for x in limit_header.split("/"))
                if used >= total - 2:
                    time.sleep(1.0)

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "2"))
                time.sleep(retry_after)
                continue

            if not response.ok:
                detail = response.text[:500]
                raise ShopifyAPIError(
                    f"Shopify API {response.status_code} en {url} — {detail}"
                )

            return response

        raise ShopifyAPIError(f"Shopify API rate limit no recuperado tras 3 intentos en {url}")

    def _paginate_orders(self, params: dict) -> Iterator[dict]:
        """Pagina ordenes usando cursor-based pagination via header Link."""
        url = f"{self.base_url}/orders.json"
        current_params = dict(params)

        while True:
            response = self._request("GET", url, params=current_params)
            data = response.json()
            orders = data.get("orders", [])
            for o in orders:
                yield o

            # Buscar link next en el header
            link = response.headers.get("Link", "")
            next_url = self._parse_next_link(link)
            if not next_url:
                break

            # En requests siguientes, NO se reenvian los query params
            # (vienen en el cursor del next_url). Solo cambiamos url.
            url = next_url
            current_params = None

    @staticmethod
    def _parse_next_link(link_header: str) -> Optional[str]:
        """Extrae la URL de rel='next' del header Link de Shopify."""
        if not link_header:
            return None
        # Formato: <https://...page_info=xxx>; rel="next", <https://...>; rel="previous"
        match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
        return match.group(1) if match else None

    def get_orders(self, fecha_inicio: date, fecha_fin: date) -> list[dict]:
        """
        Trae todas las ordenes creadas entre fecha_inicio y fecha_fin (inclusive).
        Usa la zona horaria de Colombia (UTC-5) para el filtro de fechas.
        """
        # Formato ISO 8601 con offset Colombia
        start_iso = f"{fecha_inicio.isoformat()}T00:00:00-05:00"
        # +1 dia exclusivo para incluir todo el ultimo dia
        end_iso = f"{fecha_fin.isoformat()}T23:59:59-05:00"

        params = {
            "status": "any",
            "created_at_min": start_iso,
            "created_at_max": end_iso,
            "limit": 250,  # max permitido por la API
            "fields": (
                "id,name,created_at,processed_at,cancelled_at,"
                "currency,total_price,subtotal_price,total_discounts,total_tax,"
                "total_shipping_price_set,"
                "financial_status,fulfillment_status,"
                "source_name,discount_codes,discount_applications,"
                "tags,test,line_items"
            ),
        }

        return list(self._paginate_orders(params))

    def get_resumen_ventas(self, fecha_inicio: date, fecha_fin: date) -> dict:
        """
        Procesa las ordenes y devuelve metricas reales de Marfil.

        Reglas de calculo:
        - Una orden cancelada (cancelled_at != null) NO cuenta como venta.
        - Una orden con financial_status in {refunded, voided} NO cuenta.
        - El "precio bruto" de una venta es subtotal_price + total_discounts
          (= lo que cuesta el producto antes del descuento, equivalente a
          total_declared_value en envia.com).
        - El "precio neto cobrado" es total_price (lo que efectivamente paga
          el cliente despues del descuento).
        - Unidades = sum(line_items[].quantity) excluyendo gift cards.

        Retorna estructura ya lista para inyectar en dashboard.json.
        """
        orders = self.get_orders(fecha_inicio, fecha_fin)

        # Acumuladores
        ventas_brutas = 0.0      # precio antes de descuento (declared)
        ventas_netas = 0.0       # precio efectivamente cobrado (total_price)
        descuentos_total = 0.0
        unidades = 0
        ordenes_validas = 0

        # Drop-outs
        canceladas_count = 0
        canceladas_monto = 0.0
        refunded_count = 0
        refunded_monto = 0.0

        # Histogramas
        ventas_por_dia = defaultdict(lambda: {
            "ventas_brutas": 0.0,
            "ventas_netas": 0.0,
            "descuentos": 0.0,
            "unidades": 0,
            "ordenes": 0,
        })
        productos_top = defaultdict(lambda: {"unidades": 0, "ventas": 0.0, "vendor": ""})
        skus_top = defaultdict(lambda: {"unidades": 0, "ventas": 0.0, "title": ""})
        canales = defaultdict(lambda: {"ordenes": 0, "ventas_brutas": 0.0})
        codigos_descuento = defaultdict(lambda: {"usos": 0, "monto": 0.0})

        for o in orders:
            if o.get("test"):
                continue

            cancelled_at = o.get("cancelled_at")
            financial_status = (o.get("financial_status") or "").lower()
            total_price = float(o.get("total_price") or 0)
            subtotal = float(o.get("subtotal_price") or 0)
            total_discounts = float(o.get("total_discounts") or 0)
            bruto = subtotal + total_discounts  # equivalente a "declared value"

            # Saltar canceladas
            if cancelled_at:
                canceladas_count += 1
                canceladas_monto += bruto
                continue

            # Saltar reembolsadas / anuladas
            if financial_status in REFUNDED_STATUSES:
                refunded_count += 1
                refunded_monto += bruto
                continue

            ordenes_validas += 1
            ventas_brutas += bruto
            ventas_netas += total_price
            descuentos_total += total_discounts

            # Unidades
            order_units = 0
            for li in o.get("line_items", []):
                if li.get("gift_card"):
                    continue
                qty = int(li.get("quantity") or 0)
                order_units += qty

                # Top producto (agrupado por title sin variante)
                title = li.get("title") or "(sin titulo)"
                vendor = li.get("vendor") or ""
                price_li = float(li.get("price") or 0) * qty
                productos_top[title]["unidades"] += qty
                productos_top[title]["ventas"] += price_li
                productos_top[title]["vendor"] = vendor

                # Top SKU (mas granular)
                sku = li.get("sku") or "(sin SKU)"
                variante = li.get("variant_title") or ""
                sku_key = f"{sku} - {variante}".strip(" -") if variante else sku
                skus_top[sku_key]["unidades"] += qty
                skus_top[sku_key]["ventas"] += price_li
                skus_top[sku_key]["title"] = title

            unidades += order_units

            # Por dia (en zona Colombia)
            fecha_dia = self._parse_fecha_colombia(o.get("created_at", ""))
            if fecha_dia:
                d = ventas_por_dia[fecha_dia.isoformat()]
                d["ventas_brutas"] += bruto
                d["ventas_netas"] += total_price
                d["descuentos"] += total_discounts
                d["unidades"] += order_units
                d["ordenes"] += 1

            # Canal de venta
            source = o.get("source_name") or "unknown"
            canales[source]["ordenes"] += 1
            canales[source]["ventas_brutas"] += bruto

            # Codigos de descuento
            for dc in o.get("discount_codes", []):
                code = dc.get("code") or "(sin codigo)"
                amount = float(dc.get("amount") or 0)
                codigos_descuento[code]["usos"] += 1
                codigos_descuento[code]["monto"] += amount

        # Ordenar tops
        top_productos = sorted(
            [{"nombre": k, **v} for k, v in productos_top.items()],
            key=lambda x: x["unidades"], reverse=True,
        )[:15]
        top_skus = sorted(
            [{"sku": k, **v} for k, v in skus_top.items()],
            key=lambda x: x["unidades"], reverse=True,
        )[:20]
        canales_list = sorted(
            [{"canal": k, **v} for k, v in canales.items()],
            key=lambda x: x["ventas_brutas"], reverse=True,
        )
        codigos_list = sorted(
            [{"codigo": k, **v} for k, v in codigos_descuento.items()],
            key=lambda x: x["monto"], reverse=True,
        )[:15]

        # Historial diario ordenado
        historial_diario = [
            {"fecha": fecha, **datos}
            for fecha, datos in sorted(ventas_por_dia.items())
        ]

        return {
            "ventas_brutas": round(ventas_brutas),
            "ventas_netas": round(ventas_netas),
            "descuentos_total": round(descuentos_total),
            "unidades": unidades,
            "ordenes": ordenes_validas,
            "canceladas": {
                "ordenes": canceladas_count,
                "monto": round(canceladas_monto),
            },
            "reembolsadas": {
                "ordenes": refunded_count,
                "monto": round(refunded_monto),
            },
            "historial_diario": historial_diario,
            "top_productos": top_productos,
            "top_skus": top_skus,
            "canales": canales_list,
            "codigos_descuento": codigos_list,
        }

    @staticmethod
    def _parse_fecha_colombia(iso_str: str) -> Optional[date]:
        """
        Parsea fecha ISO 8601 de Shopify y devuelve la fecha en zona Colombia.
        Shopify devuelve created_at con offset (ej: 2026-04-10T15:24:42-05:00).
        """
        if not iso_str:
            return None
        try:
            # Python 3.11+ acepta el formato directamente
            dt = datetime.fromisoformat(iso_str)
            # Si vino con tz, convertir a Colombia (-5 fijo)
            if dt.tzinfo is not None:
                # Colombia no tiene DST, siempre UTC-5
                from datetime import timedelta
                colombia = timezone(timedelta(hours=-5))
                dt = dt.astimezone(colombia)
            return dt.date()
        except (ValueError, TypeError):
            return None
