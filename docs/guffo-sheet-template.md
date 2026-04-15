# Google Sheet — Guffo Ecuador

Template para la hoja de cálculo que alimenta el dashboard de Guffo.

## Cómo crearla

1. Crea un Google Sheet nuevo (separado del de Marfil).
2. Comparte el sheet con la **service account email** que ya usas para Marfil
   (está en `credentials.json`, campo `client_email` — algo como
   `marfil-sheets@xxx.iam.gserviceaccount.com`), con permiso de **Lector**.
3. Copia el ID del sheet desde la URL (`docs.google.com/spreadsheets/d/{ID}/edit`).
4. Agrégalo a `.env`:
   ```
   GUFFO_SPREADSHEET_ID=1AbCd...
   META_GUFFO_ACCOUNT_IDS=483006271531368,482917058006173,2382940985441198
   ```
5. También en GitHub Actions → Settings → Secrets → agrega los dos secrets.

## Estructura: 3 pestañas

### Pestaña 1: `ventas`

Una fila por día por plataforma. Header en fila 1.

| fecha      | plataforma | ordenes | unidades | ventas_usd | descuentos_usd |
|------------|------------|---------|----------|------------|----------------|
| 2026-04-14 | effi       | 8       | 10       | 320        | 15             |
| 2026-04-14 | gintracom  | 5       | 6        | 240        | 0              |
| 2026-04-14 | dropi      | 3       | 3        | 180        | 0              |
| 2026-04-15 | effi       | 12      | 14       | 470        | 30             |

**Notas:**
- `fecha` en formato `YYYY-MM-DD` o `DD/MM/YYYY`.
- `plataforma` en minúsculas: `effi`, `gintracom`, `dropi` (puedes agregar más).
- `ventas_usd` y `descuentos_usd` en dólares — el dashboard los convierte a COP
  automáticamente usando la TRM del día (fallback 3700 si no hay internet).

### Pestaña 2: `costos_fijos`

Costos mensuales en COP. Header en fila 1.

| concepto         | monto_mensual_cop |
|------------------|-------------------|
| Arriendo oficina | 800000            |
| Salario Juan     | 1500000           |
| Salario María    | 1200000           |

**Notas:**
- Los costos se prorratean automáticamente por la cantidad de días del
  rango filtrado en el dashboard (ej. si filtras 15 días, se toma 50%).

### Pestaña 3: `config`

Parámetros del negocio. Header en fila 1.

| clave                       | valor |
|-----------------------------|-------|
| costo_unitario_zapato_cop   | 41550 |
| comision_ventas_pct         | 0.02  |

**Notas:**
- `comision_ventas_pct` puede ser `0.02` o `2%` — ambos se interpretan como 2%.
- Si la pestaña no existe, el dashboard usa defaults (41550 COP y 2%).

## Qué ve el dashboard

- **KPIs** en COP: ventas netas, utilidad, órdenes, ROAS, CPA, gasto ads (con ACOS).
- **Gráfico diario** de ventas en COP.
- **Donut** de costos: zapatos + comisión 2% + ads + fijos prorrateados.
- **Desglose por plataforma** (Effi / Gintracom / Dropi).
- **Desglose por cuenta publicitaria** (las 3 cuentas de Meta).
- **P&L final**: Ingresos - Costos = Utilidad, con margen %.

## Fórmula de utilidad

```
Utilidad = Ventas Netas (USD × TRM)
         - (Unidades × Costo Zapato)
         - (Ventas Netas × 2%)      ← comisión vendedores
         - Gasto Ads (ya en COP)
         - (Costos Fijos × días_rango / 30)
```
