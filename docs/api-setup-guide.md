# Guía de Configuración de APIs — REPORTE MARFIL

## 1. envia.com API

### Obtener token
1. Inicia sesión en tu cuenta de envia.com
2. Ve a **Configuración** → **API** o **Integraciones**
3. Genera un nuevo token de API
4. Copia el token

### Configurar
```
ENVIA_API_KEY=tu_api_key_aqui
```

### Notas
- El token no expira pero puede ser revocado
- Base URL: `https://api.envia.com`
- Docs: `https://api.envia.com/doc`
- Auth: Bearer token en header `Authorization`

---

## 2. Meta Ads API (Facebook Marketing)

### Paso 1: Crear App en Meta for Developers
1. Ve a https://developers.facebook.com
2. Click en **Mis Apps** → **Crear App**
3. Selecciona tipo **Negocios**
4. Nombra la app (ej: "Marfil Dashboard")

### Paso 2: Agregar Marketing API
1. En tu app, ve a **Agregar productos**
2. Busca **Marketing API** y agrégala

### Paso 3: Obtener Access Token
1. Ve a **Herramientas** → **Explorador de la API de Graph**
2. Selecciona tu app
3. En permisos, agrega: `ads_read`, `ads_management`
4. Click en **Generar token de acceso**
5. Para token de larga duración (60 días):
   ```
   https://graph.facebook.com/v21.0/oauth/access_token?
     grant_type=fb_exchange_token&
     client_id=TU_APP_ID&
     client_secret=TU_APP_SECRET&
     fb_exchange_token=TU_TOKEN_CORTO
   ```

### Paso 4: Obtener IDs de Cuentas Publicitarias
1. Ve a **Business Manager** → **Configuración** → **Cuentas publicitarias**
2. Los IDs tienen formato `act_XXXXXXXXX`
3. Necesitas los IDs de las 2 cuentas

### Configurar
```
META_ACCESS_TOKEN=tu_token_largo
META_ACCOUNT_ID_1=act_XXXXXXXXX
META_ACCOUNT_ID_2=act_XXXXXXXXX
```

### Notas
- El token expira cada 60 días — hay que renovarlo
- Para producción, considera usar System User token (no expira)

---

## 3. Google Sheets API

### Paso 1: Crear proyecto en Google Cloud
1. Ve a https://console.cloud.google.com
2. Click en **Crear Proyecto** → nómbralo "Marfil Dashboard"
3. Selecciona el proyecto

### Paso 2: Habilitar API
1. Ve a **APIs y Servicios** → **Biblioteca**
2. Busca **Google Sheets API** → **Habilitar**

### Paso 3: Crear Service Account
1. Ve a **APIs y Servicios** → **Credenciales**
2. Click en **Crear Credenciales** → **Cuenta de Servicio**
3. Nombre: "marfil-dashboard"
4. Rol: ninguno (no necesita)
5. Click en la cuenta creada → pestaña **Claves**
6. **Agregar Clave** → **Crear nueva clave** → **JSON**
7. Se descarga un archivo `credentials.json` — guárdalo en la carpeta del proyecto

### Paso 4: Compartir el Sheets
1. Abre tu Google Sheets
2. Click en **Compartir**
3. Agrega el email del Service Account (aparece en el JSON: `client_email`)
4. Dale permiso de **Lector**

### Paso 5: Obtener Spreadsheet ID
1. Abre tu Sheets en el navegador
2. La URL es: `https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit`
3. Copia el `SPREADSHEET_ID` de la URL

### Configurar
```
GOOGLE_SHEETS_CREDENTIALS_PATH=credentials.json
SPREADSHEET_ID=tu_spreadsheet_id
```

---

## 4. Configurar GitHub Secrets

Para que GitHub Actions funcione, debes agregar los secrets al repositorio:

1. Ve a tu repo en GitHub → **Settings** → **Secrets and variables** → **Actions**
2. Agrega estos secrets:

| Secret | Valor |
|--------|-------|
| `ENVIA_API_KEY` | Token de envia.com |
| `META_ACCESS_TOKEN` | Token de Meta Ads |
| `META_ACCOUNT_ID_1` | ID primera cuenta publicitaria |
| `META_ACCOUNT_ID_2` | ID segunda cuenta publicitaria |
| `GOOGLE_SHEETS_CREDENTIALS` | Contenido COMPLETO del archivo credentials.json |
| `SPREADSHEET_ID` | ID del Google Sheets |

### Para GOOGLE_SHEETS_CREDENTIALS
Abre `credentials.json` y copia TODO el contenido JSON como valor del secret.

---

## 5. Estructura del Google Sheets

Crea un Google Sheets con UNA sola hoja y estos bloques:

### Formato requerido

Cada bloque empieza con un header en negrita. Las tablas van debajo con sus encabezados de columna.

```
CARACOLÍ - BUCARAMANGA

COSTOS FIJOS MENSUALES
Concepto          | Monto
Arriendo          | 3500000
Salario Vendedor  | 1800000

VENTAS DIARIAS
Fecha       | Unidades | Total Venta
2026-03-01  | 2        | 378000
2026-03-02  | 1        | 189000

GASTOS DIARIOS
Fecha       | Concepto      | Monto
2026-03-01  | Bolsas        | 45000
2026-03-02  | Transporte    | 20000


TITAN PLAZA - BOGOTÁ
(misma estructura)


FUNDADORES - MANIZALES
(misma estructura)


DIGITAL

COSTOS FIJOS MENSUALES
Concepto          | Monto
Arriendo Oficina  | 2000000
Salarios          | 3500000

GASTOS VARIABLES
Fecha       | Concepto      | Monto
2026-03-01  | Devolución    | 189000


CONFIG
Parámetro              | Valor
Costo unitario gafa    | 45000
% Devoluciones digital | 15%
```

### Notas importantes
- Los montos van SIN signo de pesos y SIN puntos de miles (ej: `3500000`, no `$3.500.000`)
- Las fechas en formato `YYYY-MM-DD` (ej: `2026-03-30`) o `DD/MM/YYYY`
- Deja una fila vacía entre bloques para separar visualmente
- El header de cada bloque debe contener exactamente el texto indicado
