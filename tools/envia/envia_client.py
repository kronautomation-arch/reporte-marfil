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
        Procesa envíos y retorna resumen de ventas digitales.

        Campos clave de envia.com:
        - cash_on_delivery_amount: valor de la venta (contra entrega)
        - total_declared_value: valor declarado del paquete
        - total/grand_total: costo del envío
        - status: estado del envío (Created, In Transit, Delivered, etc.)
        - canceled: 1 si fue cancelado

        Retorna:
        {
            "ventas_brutas": float,
            "ordenes": int,
            "unidades": int,
            "costo_envio_total": float,
            "ordenes_detalle": [...],
            "historial_diario": [...]
        }
        """
        shipments = self.get_shipments(fecha_inicio, fecha_fin)

        ventas_brutas = 0
        total_unidades = 0
        costo_envio_total = 0
        ordenes_detalle = []
        ventas_por_dia = {}

        for ship in shipments:
            # Saltar envíos cancelados
            if ship.get("canceled", 0) == 1:
                continue

            # Valor de la venta: cash_on_delivery_amount o total_declared_value
            monto = float(ship.get("cash_on_delivery_amount", 0) or ship.get("total_declared_value", 0) or 0)

            # Costo del envío
            costo_envio = float(ship.get("grand_total", 0) or ship.get("total", 0) or 0)

            # Unidades: contar paquetes
            packages = ship.get("packages", [])
            unidades = len(packages) if packages else 1

            # Fecha de creación
            fecha_str = ship.get("created_at", ship.get("utc_created_at", ""))
            fecha = self._parse_fecha(fecha_str)

            # Status
            status = ship.get("status", "")
            status_id = ship.get("status_id", 0)

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
            })

            # Agrupar por día
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

        return {
            "ventas_brutas": ventas_brutas,
            "ordenes": len([s for s in shipments if s.get("canceled", 0) != 1]),
            "unidades": total_unidades,
            "costo_envio_total": costo_envio_total,
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
