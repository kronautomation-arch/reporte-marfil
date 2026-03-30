"""
Script para crear la plantilla completa del Sheets con todas las fechas de 2026,
colores por sección y formato profesional.
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import date, timedelta
import sys
from pathlib import Path

# Configuración
YEAR = 2026
SPREADSHEET_ID = "1243GjnVVj9IeBsbSPcWFr_duTH_u5VVPEpEFrWe0E2g"
CREDS_PATH = Path(__file__).resolve().parent.parent.parent / "credentials.json"

# Colores (RGB 0-1)
COLORS = {
    "caracoli": {"red": 0.18, "green": 0.63, "blue": 0.45},       # Verde esmeralda
    "titan": {"red": 0.24, "green": 0.35, "blue": 0.82},          # Azul indigo
    "fundadores": {"red": 0.90, "green": 0.58, "blue": 0.15},     # Naranja dorado
    "digital": {"red": 0.56, "green": 0.27, "blue": 0.78},        # Morado
    "config": {"red": 0.33, "green": 0.33, "blue": 0.33},         # Gris oscuro
    "sub_header": {"red": 0.93, "green": 0.93, "blue": 0.93},     # Gris claro
    "col_header": {"red": 0.85, "green": 0.85, "blue": 0.85},     # Gris medio
    "month_even": {"red": 1, "green": 1, "blue": 1},              # Blanco
    "month_odd": {"red": 0.96, "green": 0.97, "blue": 1},         # Azul muy claro
    "white": {"red": 1, "green": 1, "blue": 1},
}


def get_all_dates(year):
    """Genera todas las fechas del año."""
    dates = []
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    while d <= end:
        dates.append(d)
        d += timedelta(days=1)
    return dates


def build_pos_block(name, city, dates):
    """Construye las filas de un bloque POS."""
    rows = []

    # Header del bloque
    rows.append([f"{name} - {city}", "", ""])

    # Costos fijos
    rows.append([""])
    rows.append(["COSTOS FIJOS MENSUALES", "", ""])
    rows.append(["Concepto", "Monto Mensual", ""])
    rows.append(["Arriendo", "", ""])
    rows.append(["Salario Vendedor 1", "", ""])
    rows.append(["Salario Vendedor 2", "", ""])
    rows.append(["Otros fijos", "", ""])
    rows.append([""])

    # Ventas diarias
    rows.append(["VENTAS DIARIAS", "", ""])
    rows.append(["Fecha", "Unidades", "Total Venta"])
    for d in dates:
        rows.append([d.strftime("%Y-%m-%d"), "", ""])
    rows.append([""])

    # Gastos diarios
    rows.append(["GASTOS DIARIOS", "", ""])
    rows.append(["Fecha", "Concepto", "Monto"])
    for d in dates:
        rows.append([d.strftime("%Y-%m-%d"), "", ""])

    rows.append([""])
    rows.append([""])

    return rows


def build_digital_block(dates):
    """Construye el bloque DIGITAL."""
    rows = []

    rows.append(["DIGITAL", "", ""])

    # Costos fijos
    rows.append([""])
    rows.append(["COSTOS FIJOS MENSUALES", "", ""])
    rows.append(["Concepto", "Monto Mensual", ""])
    rows.append(["Arriendo Oficina", "", ""])
    rows.append(["Salarios equipo digital", "", ""])
    rows.append(["Herramientas/Software", "", ""])
    rows.append(["Otros fijos", "", ""])
    rows.append([""])

    # Gastos variables
    rows.append(["GASTOS VARIABLES", "", ""])
    rows.append(["Fecha", "Concepto", "Monto"])
    for d in dates:
        rows.append([d.strftime("%Y-%m-%d"), "", ""])

    rows.append([""])
    rows.append([""])

    return rows


def build_config_block():
    """Construye el bloque CONFIG."""
    rows = []
    rows.append(["CONFIG", "", ""])
    rows.append(["Parámetro", "Valor", ""])
    rows.append(["Costo unitario gafa", "45000", ""])
    rows.append(["% Devoluciones digital", "15%", ""])
    return rows


def apply_formatting(sheet, spreadsheet):
    """Aplica colores y formato al Sheets."""
    ws = sheet.sheet1
    all_values = ws.get_all_values()
    total_rows = len(all_values)

    requests = []

    # Ajustar ancho de columnas
    requests.append({
        "updateDimensionProperties": {
            "range": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 220},
            "fields": "pixelSize"
        }
    })
    requests.append({
        "updateDimensionProperties": {
            "range": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
            "properties": {"pixelSize": 180},
            "fields": "pixelSize"
        }
    })
    requests.append({
        "updateDimensionProperties": {
            "range": {"sheetId": 0, "dimension": "COLUMNS", "startIndex": 2, "endIndex": 3},
            "properties": {"pixelSize": 180},
            "fields": "pixelSize"
        }
    })

    # Recorrer filas y aplicar formato según contenido
    block_colors = {
        "CARACOLÍ - BUCARAMANGA": COLORS["caracoli"],
        "TITAN PLAZA - BOGOTÁ": COLORS["titan"],
        "FUNDADORES - MANIZALES": COLORS["fundadores"],
        "DIGITAL": COLORS["digital"],
        "CONFIG": COLORS["config"],
    }

    sub_headers = ["COSTOS FIJOS MENSUALES", "VENTAS DIARIAS", "GASTOS DIARIOS", "GASTOS VARIABLES"]
    col_headers_text = ["Concepto", "Fecha", "Parámetro"]

    current_block_color = None

    for i, row in enumerate(all_values):
        cell_text = row[0].strip() if row else ""

        # Block headers (CARACOLÍ, TITAN PLAZA, etc.)
        if cell_text in block_colors:
            current_block_color = block_colors[cell_text]
            requests.append(format_row(i, 3, current_block_color, bold=True, font_color=COLORS["white"], font_size=12))
            continue

        # Sub-headers (COSTOS FIJOS, VENTAS DIARIAS, etc.)
        if cell_text in sub_headers:
            bg = {k: min(1, v + 0.6) for k, v in current_block_color.items()} if current_block_color else COLORS["sub_header"]
            requests.append(format_row(i, 3, bg, bold=True, font_size=10))
            continue

        # Column headers (Concepto, Fecha, Parámetro)
        if cell_text in col_headers_text:
            requests.append(format_row(i, 3, COLORS["col_header"], bold=True, font_size=9))
            continue

        # Date rows - alternate color by month
        if cell_text and len(cell_text) == 10 and cell_text[4] == '-':
            try:
                month = int(cell_text[5:7])
                bg = COLORS["month_odd"] if month % 2 == 1 else COLORS["month_even"]
                requests.append(format_row(i, 3, bg, bold=False, font_size=9))
            except ValueError:
                pass

    # Ejecutar en batches de 500 (límite de la API)
    batch_size = 500
    for start in range(0, len(requests), batch_size):
        batch = requests[start:start + batch_size]
        spreadsheet.batch_update({"requests": batch})
        print(f"  Formato aplicado: {start + len(batch)}/{len(requests)} requests")


def format_row(row_idx, cols, bg_color, bold=False, font_color=None, font_size=10):
    """Genera un request de formato para una fila."""
    cell_format = {
        "backgroundColor": bg_color,
        "textFormat": {
            "bold": bold,
            "fontSize": font_size,
        }
    }
    if font_color:
        cell_format["textFormat"]["foregroundColor"] = font_color

    return {
        "repeatCell": {
            "range": {
                "sheetId": 0,
                "startRowIndex": row_idx,
                "endRowIndex": row_idx + 1,
                "startColumnIndex": 0,
                "endColumnIndex": cols,
            },
            "cell": {"userEnteredFormat": cell_format},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }
    }


def main():
    print("=== Creando plantilla Reporte Marfil 2026 ===")

    # Conectar
    creds = Credentials.from_service_account_file(str(CREDS_PATH), scopes=["https://www.googleapis.com/auth/spreadsheets"])
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(SPREADSHEET_ID)
    ws = sheet.sheet1

    # Generar fechas
    dates = get_all_dates(YEAR)
    print(f"Fechas generadas: {len(dates)} días ({dates[0]} a {dates[-1]})")

    # Construir todas las filas
    print("Construyendo estructura...")
    all_rows = []
    all_rows.extend(build_pos_block("CARACOLÍ", "BUCARAMANGA", dates))
    all_rows.extend(build_pos_block("TITAN PLAZA", "BOGOTÁ", dates))
    all_rows.extend(build_pos_block("FUNDADORES", "MANIZALES", dates))
    all_rows.extend(build_digital_block(dates))
    all_rows.extend(build_config_block())

    print(f"Total filas: {len(all_rows)}")

    # Expandir hoja si es necesario
    if ws.row_count < len(all_rows):
        ws.resize(rows=len(all_rows) + 10, cols=3)
        print(f"Hoja redimensionada a {len(all_rows) + 10} filas")

    # Limpiar hoja
    ws.clear()
    print("Hoja limpiada")

    # Escribir en batches (máximo ~50k celdas por request)
    batch_size = 500
    for start in range(0, len(all_rows), batch_size):
        end = min(start + batch_size, len(all_rows))
        batch = all_rows[start:end]
        cell_range = f"A{start + 1}:C{end}"
        ws.update(values=batch, range_name=cell_range)
        print(f"  Escrito: filas {start + 1} a {end}")

    # Aplicar formato
    print("Aplicando colores y formato...")
    spreadsheet = sheet
    # Necesitamos el objeto spreadsheet para batch_update
    apply_formatting(sheet, gc.http_client)

    print("\n=== Plantilla creada exitosamente! ===")
    print(f"Abre tu Sheets: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")


if __name__ == "__main__":
    main()
