"""
Client para la API de envia.com (Queries API).
Obtiene datos de envíos para calcular ventas digitales.

Base URL: https://queries.envia.com/
Auth: Bearer token (API Key desde dashboard de envia.com → Desarrolladores)
Docs: https://docs.envia.com/
"""

import requests
from datetime import date, datetime
from typing import Optional


# Status de envia.com que indican que la venta NO ocurrio / fue devuelta.
# Se excluyen del calculo de ventas y se contabilizan en "devoluciones reales".
#
#   4  = Canceled        (tambien marcado como canceled=1)
#   11 = Returned        (envio fisicamente devuelto a la bodega)
#   21 = Address error   (no se pudo entregar por direccion incorrecta)
#   24 = Rejected        (cliente rechazo el paquete al recibir)
#
# Status NO listados aqui = venta valida (Delivered, Shipped, Created, Out for Delivery, etc.)
RETURN_STATUS_IDS = {4, 11, 21, 24}


class EnviaClient:
    BASE_URL = "https://queries.envia.com"

    def __init__(self, api_token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
        })

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Hace GET request a la Queries API."""
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_shipments(self, fecha_inicio: date, fecha_fin: date) -> list[dict]:
        """
        Obtiene lista de envíos en un rango de fechas.
        Endpoint: GET /shipments?date_from=X&date_to=Y&page=N&limit=N
        """
        params = {
            "date_from": fecha_inicio.isoformat(),
            "date_to": fecha_fin.isoformat(),
            "limit": 300,
        }

        all_shipments = []
        page = 1

        while True:
            params["page"] = page
            data = self._get("/shipments", params)

            shipments = data.get("data", [])
            if not shipments:
                break

            all_shipments.extend(shipments)

            # Si obtuvimos menos del limit, ya no hay más páginas
            total = data.get("total", 0)
            if len(all_shipments) >= total:
                break

            page += 1

        return all_shipments

    def get_ventas_digitales(self, fecha_inicio: date, fecha_fin: date) -> dict:
        """
        Procesa envios y retorna resumen de ventas digitales.

        Reglas de calculo (validadas contra flujo real de Marfil - Shopify):
        - El precio REAL de venta es `total_declared_value` (aplica para COD,
          pago parcial con anticipo, y prepago total). `cash_on_delivery_amount`
          solo representa el saldo por cobrar en entrega y subestima las ventas
          con anticipo.
        - Se EXCLUYEN del calculo de ventas los envios cuyo status_id esta en
          RETURN_STATUS_IDS (Canceled / Returned / Address error / Rejected).
          Se reportan por separado en `devoluciones` para poder calcular la
          tasa real en lugar de usar un % arbitrario.
        - 1 shipment = 1 orden. Unidades reales por orden vienen desde Shopify
          (ver tools/shopify/shopify_client.py); aqui `unidades` queda = ordenes.

        Retorna:
        {
            "ventas_brutas": float,          # suma declared de envios OK
            "ordenes": int,                  # envios OK (no devueltos)
            "unidades": int,                 # por ahora = ordenes
            "costo_envio_total": float,      # solo de envios OK
            "devoluciones": {
                "monto": float,              # suma declared de devueltos
                "ordenes": int,
                "tasa_por_monto": float,     # 0..1
                "tasa_por_ordenes": float,   # 0..1
            },
            "ordenes_detalle": [...],        # solo envios OK
            "historial_diario": [...],       # ventas OK por dia (declared)
        }
        """
        shipments = self.get_shipments(fecha_inicio, fecha_fin)

        ventas_brutas = 0
        total_unidades = 0
        costo_envio_total = 0
        ordenes_detalle = []
        ventas_por_dia = {}

        dev_monto = 0
        dev_ordenes = 0

        for ship in shipments:
            status_id = ship.get("status_id", 0)
            canceled = ship.get("canceled", 0) == 1

            # Venta real = declared value (incluye anticipo + COD + prepago)
            monto = float(ship.get("total_declared_value", 0) or 0)

            # Separar devoluciones/rechazos
            if canceled or status_id in RETURN_STATUS_IDS:
                dev_monto += monto
                dev_ordenes += 1
                continue

            # Costo del envio (solo OK)
            costo_envio = float(ship.get("grand_total", 0) or ship.get("total", 0) or 0)

            # Unidades: 1 shipment = 1 orden. Las unidades reales por orden
            # se obtienen desde Shopify en un paso posterior.
            unidades = 1

            # Fecha de creacion del envio
            fecha_str = ship.get("created_at", ship.get("utc_created_at", ""))
            fecha = self._parse_fecha(fecha_str)

            status = ship.get("status", "")

            ventas_brutas += monto
            total_unidades += unidades
            costo_envio_total += costo_envio

            ordenes_detalle.append({
                "fecha": fecha.isoformat() if fecha else fecha_str,
                "monto": monto,
                "unidades": unidades,
                "costo_envio": costo_envio,
                "status": status,
                "status_id": status_id,
                "tracking": ship.get("tracking_number", ""),
                "carrier": ship.get("carrier_description", ship.get("name", "")),
                "destino_ciudad": ship.get("consignee_city", ""),
                "destino_estado": ship.get("consignee_state", ""),
                "shopify_order_id": ship.get("order_identifier", ""),
            })

            # Agrupar por dia
            if fecha:
                dia = fecha.isoformat()
                if dia not in ventas_por_dia:
                    ventas_por_dia[dia] = {"ventas": 0, "ordenes": 0}
                ventas_por_dia[dia]["ventas"] += monto
                ventas_por_dia[dia]["ordenes"] += 1

        historial_diario = [
            {"fecha": dia, "ventas": data["ventas"], "ordenes": data["ordenes"]}
            for dia, data in sorted(ventas_por_dia.items())
        ]

        ordenes_ok = len(ordenes_detalle)
        bruto_total = ventas_brutas + dev_monto
        tasa_monto = (dev_monto / bruto_total) if bruto_total > 0 else 0
        tasa_ord = (dev_ordenes / (ordenes_ok + dev_ordenes)) if (ordenes_ok + dev_ordenes) > 0 else 0

        return {
            "ventas_brutas": ventas_brutas,
            "ordenes": ordenes_ok,
            "unidades": total_unidades,
            "costo_envio_total": costo_envio_total,
            "devoluciones": {
                "monto": dev_monto,
                "ordenes": dev_ordenes,
                "tasa_por_monto": tasa_monto,
                "tasa_por_ordenes": tasa_ord,
            },
            "ordenes_detalle": ordenes_detalle,
            "historial_diario": historial_diario,
        }

    @staticmethod
    def _parse_fecha(fecha_str: str) -> Optional[date]:
        """Parsea fecha de envia.com (formato: YYYY-MM-DD HH:MM:SS)."""
        if not fecha_str:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(fecha_str[:19], fmt).date()
            except ValueError:
                continue
        return None
