# REPORTE MARFIL

Dashboard ejecutivo para Marfil (marca de lentes de sol, Colombia).

## Arquitectura (WAT Framework)

- **TOOLS** = scripts Python en `tools/` (una responsabilidad cada uno)
- **main.py** = orquestador que jala datos de 3 APIs y genera `dashboard.json`
- **index.html** = dashboard single-file que consume `dashboard.json`

## Fuentes de datos

| Fuente | Client | Datos |
|--------|--------|-------|
| envia.com API | `tools/envia/envia_client.py` | Ventas digitales (pedidos, montos, unidades) |
| Meta Ads API | `tools/meta/meta_client.py` | Gasto publicitario (2 cuentas), ROAS, CPA |
| Google Sheets | `tools/sheets/sheets_client.py` | Ventas POS (3 puntos), gastos, costos fijos, config |

## Puntos de venta

- Caracolí — Bucaramanga
- Titan Plaza — Bogotá
- Fundadores — Manizales

## Variables de entorno (.env)

```
ENVIA_API_KEY=
META_ACCESS_TOKEN=
META_ACCOUNT_ID_1=
META_ACCOUNT_ID_2=
GOOGLE_SHEETS_CREDENTIALS_PATH=
SPREADSHEET_ID=
```

## Ejecución

```bash
# Local
python main.py

# GitHub Actions: 8am, 9am, 10am, 11am, 2pm COT
```

## Spec completo

`docs/superpowers/specs/2026-03-30-reporte-marfil-design.md` (en workspace root)
