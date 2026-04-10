"""
Client para la API de Meta Marketing (Facebook Ads).
Obtiene métricas de gasto publicitario de 2 cuentas.

Base URL: https://graph.facebook.com/v21.0/
Auth: Access token de larga duración
"""

import requests
from datetime import date
from typing import Optional


class MetaAPIError(Exception):
    """Error devuelto por la API de Meta. Incluye detalles útiles (no el token)."""
    pass


class MetaAdsClient:
    BASE_URL = "https://graph.facebook.com/v21.0"

    def __init__(self, access_token: str, account_ids: list[str]):
        """
        access_token: Token de acceso de Meta (larga duración).
        account_ids: Lista de IDs de cuentas publicitarias (ej: ["act_123", "act_456"]).
        """
        self.access_token = access_token
        self.account_ids = account_ids

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Hace GET request a la API de Meta."""
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        if params is None:
            params = {}
        params["access_token"] = self.access_token
        response = requests.get(url, params=params, timeout=30)
        if not response.ok:
            # Extraer mensaje de error de Meta sin exponer el token
            try:
                err = response.json().get("error", {})
                meta_msg = err.get("message", response.text)
                meta_type = err.get("type", "?")
                meta_code = err.get("code", "?")
                fbtrace = err.get("fbtrace_id", "?")
                raise MetaAPIError(
                    f"Meta API {response.status_code} en {endpoint} — "
                    f"{meta_type} (code {meta_code}): {meta_msg} [fbtrace_id={fbtrace}]"
                )
            except ValueError:
                raise MetaAPIError(
                    f"Meta API {response.status_code} en {endpoint} — respuesta no-JSON: {response.text[:500]}"
                )
        return response.json()

    def get_account_insights(self, account_id: str, fecha_inicio: date, fecha_fin: date) -> dict:
        """
        Obtiene insights de una cuenta publicitaria para un rango de fechas.

        Retorna:
        {
            "spend": float,
            "impressions": int,
            "clicks": int,
            "actions": int (purchases),
            "cpa": float,
            "cpc": float,
        }
        """
        params = {
            "fields": "spend,impressions,clicks,actions,cost_per_action_type,cpc",
            "time_range": f'{{"since":"{fecha_inicio.isoformat()}","until":"{fecha_fin.isoformat()}"}}',
            "level": "account",
        }

        data = self._get(f"{account_id}/insights", params)
        results = data.get("data", [])

        if not results:
            return {
                "spend": 0.0,
                "impressions": 0,
                "clicks": 0,
                "purchases": 0,
                "cpa": 0.0,
                "cpc": 0.0,
            }

        row = results[0]

        # Extraer purchases de actions
        purchases = 0
        actions = row.get("actions", [])
        for action in actions:
            if action.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase"):
                purchases += int(action.get("value", 0))

        # Extraer CPA de cost_per_action_type
        cpa = 0.0
        cost_per_actions = row.get("cost_per_action_type", [])
        for cpa_item in cost_per_actions:
            if cpa_item.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase"):
                cpa = float(cpa_item.get("value", 0))

        return {
            "spend": float(row.get("spend", 0)),
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "purchases": purchases,
            "cpa": cpa,
            "cpc": float(row.get("cpc", 0)),
        }

    def get_account_daily_insights(self, account_id: str, fecha_inicio: date, fecha_fin: date) -> list[dict]:
        """Obtiene insights diarios de una cuenta."""
        params = {
            "fields": "spend,impressions,clicks,actions",
            "time_range": f'{{"since":"{fecha_inicio.isoformat()}","until":"{fecha_fin.isoformat()}"}}',
            "time_increment": 1,
            "level": "account",
            "limit": 100,
        }

        data = self._get(f"{account_id}/insights", params)
        results = data.get("data", [])

        daily = []
        for row in results:
            purchases = 0
            for action in row.get("actions", []):
                if action.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase"):
                    purchases += int(action.get("value", 0))

            daily.append({
                "fecha": row.get("date_start", ""),
                "spend": float(row.get("spend", 0)),
                "impressions": int(row.get("impressions", 0)),
                "clicks": int(row.get("clicks", 0)),
                "purchases": purchases,
            })

        return daily

    def get_all_accounts_data(self, fecha_inicio: date, fecha_fin: date) -> dict:
        """
        Obtiene datos de todas las cuentas configuradas.

        Retorna:
        {
            "gasto_total": float,
            "cuentas": [{"nombre": str, "gasto": float, "impressions": int, ...}],
            "roas": float (se calcula en main.py con las ventas),
            "cpa": float,
            "historial_diario": [{"fecha": str, "gasto": float}],
        }
        """
        cuentas = []
        gasto_total = 0
        purchases_total = 0
        all_daily = {}

        for i, account_id in enumerate(self.account_ids):
            insights = self.get_account_insights(account_id, fecha_inicio, fecha_fin)
            nombre = f"Cuenta {str(i + 1).zfill(2)}"

            cuentas.append({
                "nombre": nombre,
                "account_id": account_id,
                "gasto": insights["spend"],
                "impressions": insights["impressions"],
                "clicks": insights["clicks"],
                "purchases": insights["purchases"],
                "cpa": insights["cpa"],
            })

            gasto_total += insights["spend"]
            purchases_total += insights["purchases"]

            # Daily data
            daily = self.get_account_daily_insights(account_id, fecha_inicio, fecha_fin)
            for day in daily:
                fecha = day["fecha"]
                if fecha not in all_daily:
                    all_daily[fecha] = 0
                all_daily[fecha] += day["spend"]

        cpa_total = gasto_total / purchases_total if purchases_total > 0 else 0

        historial_diario = [
            {"fecha": fecha, "gasto": gasto}
            for fecha, gasto in sorted(all_daily.items())
        ]

        return {
            "gasto_total": gasto_total,
            "cuentas": cuentas,
            "cpa": cpa_total,
            "purchases_total": purchases_total,
            "historial_diario": historial_diario,
        }
