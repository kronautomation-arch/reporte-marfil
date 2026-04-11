"""
Client para la API de MercadoLibre (tienda Marfil Colombia).

Flujo de autenticacion:
- OAuth 2.0 Authorization Code Grant con refresh_token rotation
- El access_token dura 6 horas, se refresca automaticamente usando
  el refresh_token (que dura 6 meses).
- Cada refresh genera un refresh_token NUEVO — el cliente lo expone
  via `client.refresh_token` despues de cada refresh para que el
  caller pueda actualizarlo en su storage (.env, Secrets, etc).

Endpoints usados:
- /oauth/token               (refresh)
- /users/{user_id}           (nickname, reputacion, nivel)
- /orders/search             (lista de ordenes con filtros)

Docs: https://developers.mercadolibre.com.co/
"""

import json
import os
import time
import requests
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from collections import defaultdict


# Cache local del refresh_token rotado. Se guarda fuera del repo (en el
# directorio del proyecto pero en .gitignore) para que entre ejecuciones
# locales no perdamos el token. En GitHub Actions no existe y se usa
# el del env directamente.
_TOKEN_CACHE_FILE = Path(__file__).resolve().parent.parent.parent / ".meli_token_cache.json"


class MeliAPIError(Exception):
    """Error devuelto por la API de MercadoLibre."""
    pass


class MeliAuthError(MeliAPIError):
    """Error de autenticacion (refresh_token invalido, scopes faltantes)."""
    pass


# Zona horaria Colombia (UTC-5, sin DST)
COLOMBIA_TZ = timezone(timedelta(hours=-5))

# Tags en una orden que indican que la venta se completo / se envio al cliente
DELIVERED_TAGS = {"delivered"}

# Status que cuentan como venta valida
VALID_STATUSES = {"paid"}

# Status que son cancelacion / reembolso / no venta
CANCELED_STATUSES = {"cancelled", "invalid"}


class MeliClient:
    BASE_URL = "https://api.mercadolibre.com"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        user_id: Optional[str] = None,
    ):
        """
        client_id / client_secret: credenciales de la app en ML Developers.
        refresh_token: token persistente (dura 6 meses, rota en cada refresh).
        user_id: opcional, si no se pasa se obtiene del primer call de refresh.

        Si existe un cache local con un refresh_token mas reciente, lo usa
        en lugar del pasado por parametro (para sobrevivir a rotation entre
        ejecuciones locales).
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = self._load_cached_token() or refresh_token
        self.user_id = user_id
        self._access_token = None
        self._access_token_expires_at = 0

    @staticmethod
    def _load_cached_token() -> Optional[str]:
        """Lee el refresh_token rotado del cache local si existe."""
        try:
            if _TOKEN_CACHE_FILE.exists():
                cache = json.loads(_TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
                return cache.get("refresh_token")
        except (OSError, json.JSONDecodeError):
            pass
        return None

    def _save_cached_token(self):
        """Guarda el refresh_token rotado al cache local."""
        try:
            _TOKEN_CACHE_FILE.write_text(
                json.dumps({
                    "refresh_token": self.refresh_token,
                    "updated_at": datetime.now().isoformat(),
                    "user_id": self.user_id,
                }, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # Auth                                                               #
    # ------------------------------------------------------------------ #

    def _refresh_access_token(self):
        """Intercambia el refresh_token por un nuevo access_token."""
        response = requests.post(
            f"{self.BASE_URL}/oauth/token",
            headers={
                "accept": "application/json",
                "content-type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            },
            timeout=30,
        )
        if not response.ok:
            try:
                err = response.json()
                raise MeliAuthError(
                    f"Meli refresh fallo {response.status_code}: "
                    f"{err.get('error', '?')} — {err.get('message', response.text[:200])}"
                )
            except ValueError:
                raise MeliAuthError(
                    f"Meli refresh fallo {response.status_code}: {response.text[:200]}"
                )

        data = response.json()
        self._access_token = data["access_token"]
        # Refresh_token rotation: ML devuelve uno nuevo y el viejo queda invalido
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        # Pequeno margen de seguridad: renovamos 5 min antes del expiry real
        self._access_token_expires_at = time.time() + int(data.get("expires_in", 21600)) - 300
        if not self.user_id:
            self.user_id = str(data.get("user_id"))
        # Persistir el nuevo refresh_token en cache local para sobrevivir rotation
        self._save_cached_token()

    def _ensure_token(self):
        if self._access_token is None or time.time() >= self._access_token_expires_at:
            self._refresh_access_token()

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """GET autenticado con reintento automatico si el token expira."""
        self._ensure_token()
        url = f"{self.BASE_URL}{endpoint}"
        headers = {"Authorization": f"Bearer {self._access_token}"}

        for attempt in range(3):
            response = requests.get(url, headers=headers, params=params, timeout=30)

            if response.status_code == 401:
                # Token invalido o expirado — forzar refresh y reintentar
                self._refresh_access_token()
                headers["Authorization"] = f"Bearer {self._access_token}"
                continue

            if response.status_code == 429:
                # Rate limit — backoff
                retry_after = float(response.headers.get("Retry-After", "2"))
                time.sleep(retry_after)
                continue

            if not response.ok:
                detail = response.text[:500]
                raise MeliAPIError(
                    f"Meli API {response.status_code} en {endpoint} — {detail}"
                )

            return response.json()

        raise MeliAPIError(f"Meli API no respondio tras 3 intentos en {endpoint}")

    # ------------------------------------------------------------------ #
    # Endpoints                                                          #
    # ------------------------------------------------------------------ #

    def get_user_info(self) -> dict:
        """Info de la cuenta: nickname, reputacion, nivel."""
        self._ensure_token()
        data = self._get(f"/users/{self.user_id}")
        rep = data.get("seller_reputation", {}) or {}
        tx = rep.get("transactions", {}) or {}
        return {
            "nickname": data.get("nickname", ""),
            "country": data.get("country_id", ""),
            "site": data.get("site_id", ""),
            "user_type": data.get("user_type", ""),
            "level_id": rep.get("level_id", ""),
            "power_seller_status": rep.get("power_seller_status"),
            "transactions_total": tx.get("total", 0),
            "transactions_completed": tx.get("completed", 0),
            "transactions_canceled": tx.get("canceled", 0),
        }

    def _search_orders(self, status: str, fecha_inicio: date, fecha_fin: date) -> list[dict]:
        """
        Pagina todas las ordenes con un status especifico en el rango dado.
        ML limita 50 por pagina, usamos offset.
        """
        start_iso = f"{fecha_inicio.isoformat()}T00:00:00.000-05:00"
        end_iso = f"{fecha_fin.isoformat()}T23:59:59.999-05:00"
        all_results = []
        offset = 0
        limit = 50

        while True:
            data = self._get("/orders/search", params={
                "seller": self.user_id,
                "order.status": status,
                "order.date_created.from": start_iso,
                "order.date_created.to": end_iso,
                "sort": "date_desc",
                "limit": limit,
                "offset": offset,
            })
            results = data.get("results", [])
            all_results.extend(results)

            paging = data.get("paging", {})
            total = paging.get("total", 0)
            if offset + limit >= total or not results:
                break
            offset += limit

            # ML limita offset a 1000 en algunos endpoints
            if offset >= 1000:
                break

        return all_results

    def get_resumen_ventas(self, fecha_inicio: date, fecha_fin: date) -> dict:
        """
        Procesa ordenes de MercadoLibre y devuelve metricas listas para el JSON.

        Reglas:
        - Cuenta como venta: status=paid Y tag 'delivered' presente (entregado).
          Si hay 'paid' pero no 'delivered' aun, se cuenta como "en transito".
        - Canceladas: status=cancelled O tag 'not_delivered'.
        - Agrupa por dia usando date_closed (o date_created si no hay closed).
        - "Ventas brutas" = total_amount (lo que el cliente pago).
        - "Comisiones ML" = sum(order_items.sale_fee).
        - "Ventas netas" = ventas_brutas - comisiones (= plata real que llega).
        - Unidades = sum(order_items.quantity).

        Retorna dict con historial_diario, top_productos, totales YTD, etc.
        """
        # Trae "paid" (incluye paid y delivered) + "cancelled"
        paid_orders = self._search_orders("paid", fecha_inicio, fecha_fin)
        cancelled_orders = self._search_orders("cancelled", fecha_inicio, fecha_fin)

        # --- Ventas validas ---
        ventas_brutas = 0.0
        comisiones_total = 0.0
        ventas_netas = 0.0
        unidades = 0
        ordenes_validas = 0

        entregadas_count = 0
        entregadas_monto = 0.0
        en_transito_count = 0
        en_transito_monto = 0.0

        ventas_por_dia = defaultdict(lambda: {
            "ventas_brutas": 0.0,
            "ventas_netas": 0.0,
            "comisiones": 0.0,
            "unidades": 0,
            "ordenes": 0,
        })
        productos_top = defaultdict(lambda: {
            "unidades": 0,
            "ventas": 0.0,
            "comisiones": 0.0,
            "mlc_id": "",
        })

        for o in paid_orders:
            tags = set(o.get("tags") or [])
            total_amount = float(o.get("total_amount") or 0)

            # Suma de sale_fee de cada item
            order_items = o.get("order_items") or []
            comision_orden = 0.0
            unidades_orden = 0
            for li in order_items:
                qty = int(li.get("quantity") or 0)
                sale_fee = float(li.get("sale_fee") or 0)
                comision_orden += sale_fee * qty
                unidades_orden += qty

                it = li.get("item") or {}
                title = it.get("title") or "(sin titulo)"
                unit_price = float(li.get("unit_price") or 0)
                productos_top[title]["unidades"] += qty
                productos_top[title]["ventas"] += unit_price * qty
                productos_top[title]["comisiones"] += sale_fee * qty
                if not productos_top[title]["mlc_id"]:
                    productos_top[title]["mlc_id"] = it.get("id", "")

            ventas_brutas += total_amount
            comisiones_total += comision_orden
            ventas_netas += total_amount - comision_orden
            unidades += unidades_orden
            ordenes_validas += 1

            if "delivered" in tags:
                entregadas_count += 1
                entregadas_monto += total_amount
            else:
                en_transito_count += 1
                en_transito_monto += total_amount

            # Agrupar por dia (date_closed preferido, date_created fallback)
            fecha_raw = o.get("date_closed") or o.get("date_created", "")
            fecha_dia = self._parse_fecha_colombia(fecha_raw)
            if fecha_dia:
                d = ventas_por_dia[fecha_dia.isoformat()]
                d["ventas_brutas"] += total_amount
                d["ventas_netas"] += total_amount - comision_orden
                d["comisiones"] += comision_orden
                d["unidades"] += unidades_orden
                d["ordenes"] += 1

        # --- Canceladas ---
        canceladas_monto = 0.0
        for o in cancelled_orders:
            canceladas_monto += float(o.get("total_amount") or 0)

        # --- Historial diario ordenado ---
        historial_diario = [
            {"fecha": fecha, **datos}
            for fecha, datos in sorted(ventas_por_dia.items())
        ]

        # --- Top productos ---
        top_productos = sorted(
            [
                {"nombre": k, **v, "ventas_netas": v["ventas"] - v["comisiones"]}
                for k, v in productos_top.items()
            ],
            key=lambda x: x["unidades"], reverse=True,
        )[:15]

        # --- Metricas derivadas ---
        pct_comision = (comisiones_total / ventas_brutas) if ventas_brutas > 0 else 0
        ticket_promedio = (ventas_brutas / ordenes_validas) if ordenes_validas > 0 else 0

        return {
            "ventas_brutas": round(ventas_brutas),
            "ventas_netas": round(ventas_netas),
            "comisiones_total": round(comisiones_total),
            "pct_comision": round(pct_comision, 4),
            "ticket_promedio": round(ticket_promedio),
            "unidades": unidades,
            "ordenes": ordenes_validas,
            "entregadas": {"ordenes": entregadas_count, "monto": round(entregadas_monto)},
            "en_transito": {"ordenes": en_transito_count, "monto": round(en_transito_monto)},
            "canceladas": {
                "ordenes": len(cancelled_orders),
                "monto": round(canceladas_monto),
            },
            "historial_diario": historial_diario,
            "top_productos": top_productos,
        }

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_fecha_colombia(iso_str: str) -> Optional[date]:
        """
        Parsea ISO 8601 de ML (ej: '2026-04-09T00:16:10.000-04:00') y devuelve
        la fecha en zona Colombia UTC-5.
        """
        if not iso_str:
            return None
        try:
            # Quitar ms si vienen, dejar solo hasta el offset
            # '2026-04-09T00:16:10.000-04:00' -> '2026-04-09T00:16:10-04:00'
            if "." in iso_str:
                head, rest = iso_str.split(".", 1)
                # rest es tipo '000-04:00'. Encontrar el offset
                for i, ch in enumerate(rest):
                    if ch in "+-" and i > 0:
                        iso_str = head + rest[i:]
                        break
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is not None:
                dt = dt.astimezone(COLOMBIA_TZ)
            return dt.date()
        except (ValueError, TypeError):
            return None
