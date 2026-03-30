"""
Google Sheets client para REPORTE MARFIL.
Lee datos de una sola hoja con layout HORIZONTAL:
- Columna A = conceptos/labels
- Fila 2 = fechas (dd/mm)
- Filas agrupadas por bloque: 3 POS + Digital + Config

Estructura:
  Fila 1: header
  Fila 2: fechas (01/01, 02/01, ..., 31/12)
  --- CARACOLÍ - BUCARAMANGA ---
  Arriendo | Salario 1 | Salario 2 | Otros fijos
  VENTAS - Unidades | VENTAS - Total $
  GASTOS - Monto | GASTOS - Concepto
  --- TITAN PLAZA - BOGOTÁ --- (misma estructura)
  --- FUNDADORES - MANIZALES --- (misma estructura)
  --- DIGITAL ---
  Arriendo | Salarios | Herramientas | Otros fijos
  GASTOS VAR - Monto | GASTOS VAR - Concepto
  --- CONFIG ---
  Costo unitario gafa | % Devoluciones digital
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date
from typing import Optional


SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

BLOCK_HEADERS = {
    "caracoli": "CARACOLÍ - BUCARAMANGA",
    "titan_plaza": "TITAN PLAZA - BOGOTÁ",
    "fundadores": "FUNDADORES - MANIZALES",
    "digital": "DIGITAL",
}
CONFIG_HEADER = "CONFIG"


class SheetsClient:
    def __init__(self, credentials_path: str, spreadsheet_id: str):
        creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
        self.gc = gspread.authorize(creds)
        self.spreadsheet_id = spreadsheet_id

    def _get_all_values(self) -> list[list[str]]:
        """Obtiene todos los valores de la primera hoja."""
        sheet = self.gc.open_by_key(self.spreadsheet_id).sheet1
        return sheet.get_all_values()

    def _parse_money(self, value: str) -> float:
        """Convierte string de dinero a float."""
        if not value:
            return 0.0
        cleaned = value.replace("$", "").replace(",", "").replace(" ", "")
        # Manejar punto como separador de miles (ej: 3.500.000)
        if cleaned.count(".") > 1:
            cleaned = cleaned.replace(".", "")
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    def _parse_date_header(self, header: str, year: int = 2026) -> Optional[date]:
        """Parsea fecha del header (dd/mm) a date."""
        if not header or "/" not in header:
            return None
        try:
            parts = header.strip().split("/")
            day = int(parts[0])
            month = int(parts[1])
            return date(year, month, day)
        except (ValueError, IndexError):
            return None

    def _parse_percent(self, value: str) -> float:
        """Convierte '15%' → 0.15"""
        if not value:
            return 0.0
        cleaned = value.replace("%", "").replace(" ", "").replace(",", ".")
        try:
            return float(cleaned) / 100
        except ValueError:
            return 0.0

    def _find_row(self, rows: list[list[str]], text: str) -> int:
        """Encuentra la fila que contiene el texto en columna A."""
        for i, row in enumerate(rows):
            if row and row[0].strip().upper() == text.upper():
                return i
        return -1

    def _find_row_contains(self, rows: list[list[str]], text: str, start: int = 0) -> int:
        """Encuentra la fila que contiene el texto (parcial) en columna A desde start."""
        for i in range(start, len(rows)):
            if rows[i] and text.upper() in rows[i][0].strip().upper():
                return i
        return -1

    def _get_date_columns(self, rows: list[list[str]]) -> list[tuple[int, date]]:
        """Retorna lista de (col_index, date) para la fila de fechas (fila 2, index 1)."""
        if len(rows) < 2:
            return []
        date_row = rows[1]
        result = []
        for col_idx in range(2, len(date_row)):  # Empezar desde columna C (index 2)
            d = self._parse_date_header(date_row[col_idx])
            if d:
                result.append((col_idx, d))
        return result

    def _get_row_values_for_period(self, row: list[str], date_cols: list[tuple[int, date]],
                                    fecha_inicio: date, fecha_fin: date) -> list[tuple[date, float]]:
        """Obtiene valores de una fila para las columnas dentro del periodo."""
        values = []
        for col_idx, d in date_cols:
            if fecha_inicio <= d <= fecha_fin:
                val = self._parse_money(row[col_idx] if col_idx < len(row) else "")
                if val != 0:
                    values.append((d, val))
        return values

    def _get_row_text_for_period(self, row: list[str], date_cols: list[tuple[int, date]],
                                  fecha_inicio: date, fecha_fin: date) -> list[tuple[date, str]]:
        """Obtiene texto de una fila para las columnas dentro del periodo."""
        values = []
        for col_idx, d in date_cols:
            if fecha_inicio <= d <= fecha_fin:
                val = row[col_idx].strip() if col_idx < len(row) else ""
                if val:
                    values.append((d, val))
        return values

    def _parse_pos_block(self, rows: list[list[str]], block_start: int, date_cols: list[tuple[int, date]],
                         fecha_inicio: date, fecha_fin: date) -> dict:
        """Parsea un bloque POS horizontal."""
        result = {"costos_fijos": {}, "ventas": [], "gastos": []}

        # Costos fijos: filas debajo del header del bloque (Arriendo, Salario, etc.)
        i = block_start + 1
        while i < len(rows) and i < block_start + 8:
            label = rows[i][0].strip() if rows[i] else ""
            if not label or "VENTAS" in label.upper() or "GASTOS" in label.upper():
                break
            # Costos fijos están en columna B
            monto = self._parse_money(rows[i][1] if len(rows[i]) > 1 else "")
            if label.startswith("  "):
                label = label.strip()
            if label and monto > 0:
                result["costos_fijos"][label] = monto
            i += 1

        # Ventas - Unidades
        ventas_unidades_row = self._find_row_contains(rows, "VENTAS - Unidades", block_start)
        ventas_total_row = self._find_row_contains(rows, "VENTAS - Total", block_start)

        if ventas_unidades_row >= 0 and ventas_total_row >= 0:
            unidades_data = self._get_row_values_for_period(rows[ventas_unidades_row], date_cols, fecha_inicio, fecha_fin)
            total_data = self._get_row_values_for_period(rows[ventas_total_row], date_cols, fecha_inicio, fecha_fin)

            # Merge by date
            unidades_map = {d: v for d, v in unidades_data}
            total_map = {d: v for d, v in total_data}
            all_dates = sorted(set(list(unidades_map.keys()) + list(total_map.keys())))

            for d in all_dates:
                result["ventas"].append({
                    "fecha": d.isoformat(),
                    "unidades": int(unidades_map.get(d, 0)),
                    "total": total_map.get(d, 0),
                })

        # Gastos - Monto
        gastos_monto_row = self._find_row_contains(rows, "GASTOS - Monto", block_start)
        gastos_concepto_row = self._find_row_contains(rows, "GASTOS - Concepto", block_start)

        if gastos_monto_row >= 0:
            monto_data = self._get_row_values_for_period(rows[gastos_monto_row], date_cols, fecha_inicio, fecha_fin)
            concepto_data = {}
            if gastos_concepto_row >= 0:
                concepto_data = {d: t for d, t in self._get_row_text_for_period(rows[gastos_concepto_row], date_cols, fecha_inicio, fecha_fin)}

            for d, monto in monto_data:
                result["gastos"].append({
                    "fecha": d.isoformat(),
                    "concepto": concepto_data.get(d, "Gasto"),
                    "monto": monto,
                })

        return result

    def _parse_digital_block(self, rows: list[list[str]], block_start: int, date_cols: list[tuple[int, date]],
                             fecha_inicio: date, fecha_fin: date) -> dict:
        """Parsea el bloque DIGITAL horizontal."""
        result = {"costos_fijos": {}, "gastos": []}

        # Costos fijos
        i = block_start + 1
        while i < len(rows) and i < block_start + 8:
            label = rows[i][0].strip() if rows[i] else ""
            if not label or "GASTOS" in label.upper():
                break
            monto = self._parse_money(rows[i][1] if len(rows[i]) > 1 else "")
            if label.startswith("  "):
                label = label.strip()
            if label and monto > 0:
                result["costos_fijos"][label] = monto
            i += 1

        # Gastos variables
        gastos_monto_row = self._find_row_contains(rows, "GASTOS VAR - Monto", block_start)
        gastos_concepto_row = self._find_row_contains(rows, "GASTOS VAR - Concepto", block_start)

        if gastos_monto_row >= 0:
            monto_data = self._get_row_values_for_period(rows[gastos_monto_row], date_cols, fecha_inicio, fecha_fin)
            concepto_data = {}
            if gastos_concepto_row >= 0:
                concepto_data = {d: t for d, t in self._get_row_text_for_period(rows[gastos_concepto_row], date_cols, fecha_inicio, fecha_fin)}

            for d, monto in monto_data:
                result["gastos"].append({
                    "fecha": d.isoformat(),
                    "concepto": concepto_data.get(d, "Gasto variable"),
                    "monto": monto,
                })

        return result

    def _parse_config(self, rows: list[list[str]], config_start: int) -> dict:
        """Parsea el bloque CONFIG."""
        config = {"costo_unitario_gafa": 0, "pct_devoluciones": 0.0}
        i = config_start + 1
        while i < len(rows):
            row = rows[i]
            if not row or not row[0].strip():
                break
            key = row[0].strip().upper()
            value = row[1].strip() if len(row) > 1 else ""
            if "COSTO" in key and "GAFA" in key:
                config["costo_unitario_gafa"] = self._parse_money(value)
            elif "DEVOLUCI" in key:
                config["pct_devoluciones"] = self._parse_percent(value)
            i += 1
        return config

    def get_data(self, fecha_inicio: Optional[date] = None, fecha_fin: Optional[date] = None) -> dict:
        """
        Lee todos los datos del Sheets horizontal.
        Retorna dict con: pos (3 puntos), digital, config.
        """
        if fecha_inicio is None:
            fecha_inicio = date(2026, 1, 1)
        if fecha_fin is None:
            fecha_fin = date(2026, 12, 31)

        rows = self._get_all_values()
        date_cols = self._get_date_columns(rows)

        # Encontrar bloques
        block_positions = {}
        for key, header in BLOCK_HEADERS.items():
            pos = self._find_row(rows, header)
            if pos >= 0:
                block_positions[key] = pos

        config_pos = self._find_row(rows, CONFIG_HEADER)

        result = {"pos": {}, "digital": {}, "config": {}}

        # POS blocks
        for key in ["caracoli", "titan_plaza", "fundadores"]:
            if key in block_positions:
                result["pos"][key] = self._parse_pos_block(
                    rows, block_positions[key], date_cols, fecha_inicio, fecha_fin
                )

        # Digital
        if "digital" in block_positions:
            result["digital"] = self._parse_digital_block(
                rows, block_positions["digital"], date_cols, fecha_inicio, fecha_fin
            )

        # Config
        if config_pos >= 0:
            result["config"] = self._parse_config(rows, config_pos)

        return result
