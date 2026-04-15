"""
Google Sheets client para GUFFO ECUADOR.
Layout vertical, mas simple que el de Marfil. 3 pestañas:

1. "ventas"  — una fila por dia por plataforma
   fecha (YYYY-MM-DD) | plataforma | ordenes | unidades | ventas_usd | descuentos_usd

2. "costos_fijos" — costos mensuales en COP
   concepto | monto_mensual_cop

3. "config" — constantes del negocio
   clave | valor
   Claves esperadas:
     - costo_unitario_zapato_cop   (default 41550)
     - comision_ventas_pct         (default 0.02, ej 2%)
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials


SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def _to_float(value: str) -> float:
    if value is None:
        return 0.0
    s = str(value).strip()
    if not s:
        return 0.0
    s = s.replace("$", "").replace(" ", "")
    # Si hay punto Y coma: el punto es miles, la coma decimal (es-CO)
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    # Punto como separador de miles (ej 41.550 -> 41550) solo si hay mas de un punto
    if s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _to_int(value: str) -> int:
    try:
        return int(_to_float(value))
    except (TypeError, ValueError):
        return 0


def _to_pct(value: str) -> float:
    """'2%' -> 0.02. '0.02' -> 0.02."""
    s = str(value).strip() if value else ""
    if not s:
        return 0.0
    if s.endswith("%"):
        return _to_float(s[:-1]) / 100.0
    v = _to_float(s)
    return v / 100.0 if v > 1 else v


def _parse_date(value: str) -> Optional[date]:
    if not value:
        return None
    s = str(value).strip()
    # Soporta YYYY-MM-DD y DD/MM/YYYY
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            from datetime import datetime

            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


class GuffoSheetsClient:
    def __init__(self, credentials_path: str, spreadsheet_id: str):
        creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
        self.gc = gspread.authorize(creds)
        self.spreadsheet_id = spreadsheet_id

    def _open(self):
        return self.gc.open_by_key(self.spreadsheet_id)

    def _read_tab(self, tab_name: str) -> list[list[str]]:
        try:
            ws = self._open().worksheet(tab_name)
            return ws.get_all_values()
        except Exception:
            return []

    def get_ventas(self, fecha_inicio: date, fecha_fin: date) -> list[dict]:
        """Lee la pestaña 'ventas' y retorna filas filtradas por rango."""
        rows = self._read_tab("ventas")
        if not rows:
            return []
        # Primera fila = header
        header = [h.strip().lower() for h in rows[0]]
        idx = {k: header.index(k) for k in header}
        out = []
        for r in rows[1:]:
            if not r or not r[0].strip():
                continue
            f = _parse_date(r[idx.get("fecha", 0)])
            if not f or f < fecha_inicio or f > fecha_fin:
                continue
            out.append({
                "fecha": f.isoformat(),
                "plataforma": (r[idx["plataforma"]] if "plataforma" in idx and idx["plataforma"] < len(r) else "").strip().lower() or "otro",
                "ordenes": _to_int(r[idx["ordenes"]]) if "ordenes" in idx and idx["ordenes"] < len(r) else 0,
                "unidades": _to_int(r[idx["unidades"]]) if "unidades" in idx and idx["unidades"] < len(r) else 0,
                "ventas_usd": _to_float(r[idx["ventas_usd"]]) if "ventas_usd" in idx and idx["ventas_usd"] < len(r) else 0.0,
                "descuentos_usd": _to_float(r[idx["descuentos_usd"]]) if "descuentos_usd" in idx and idx["descuentos_usd"] < len(r) else 0.0,
            })
        return out

    def get_costos_fijos(self) -> dict:
        """Lee la pestaña 'costos_fijos'. Retorna dict {concepto: monto_cop}."""
        rows = self._read_tab("costos_fijos")
        if not rows:
            return {}
        out = {}
        for r in rows[1:]:  # skip header
            if not r or not r[0].strip():
                continue
            concepto = r[0].strip()
            monto = _to_float(r[1] if len(r) > 1 else "")
            if monto > 0:
                out[concepto] = monto
        return out

    def get_config(self) -> dict:
        """Lee la pestaña 'config'. Retorna dict {clave: valor_tipado}."""
        rows = self._read_tab("config")
        config = {
            "costo_unitario_zapato_cop": 41550.0,
            "comision_ventas_pct": 0.02,
        }
        if not rows:
            return config
        for r in rows[1:]:
            if not r or not r[0].strip():
                continue
            k = r[0].strip().lower().replace(" ", "_")
            v = r[1].strip() if len(r) > 1 else ""
            if "comision" in k or "pct" in k:
                config[k] = _to_pct(v)
            else:
                config[k] = _to_float(v)
        # Normalizar claves esperadas
        if "costo_unitario_zapato_cop" not in config:
            # aceptar variantes
            for k in list(config.keys()):
                if "costo" in k and "zapato" in k:
                    config["costo_unitario_zapato_cop"] = config[k]
                    break
        return config

    def get_data(self, fecha_inicio: date, fecha_fin: date) -> dict:
        return {
            "ventas": self.get_ventas(fecha_inicio, fecha_fin),
            "costos_fijos": self.get_costos_fijos(),
            "config": self.get_config(),
        }
