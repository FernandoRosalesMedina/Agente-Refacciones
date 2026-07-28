# Agente de Refacciones Críticas — GM Fundición

Reemplaza la dependencia de Glean + SharePoint por un stack 100% en GitHub:
- **Datos**: `data/matriz_criticidad.xlsx` (602 refacciones críticas, cambia poco) y `data/ZMADE.csv` (export diario de SAP, ya autorizado por IPG). Un script los cruza y genera `data/maestro.json`.
- **Interfaz**: `index.html` estático (filtros + dashboard + tabla), servido por GitHub Pages.
- **Chat con IA**: un Cloudflare Worker hace de puente seguro hacia la API de Claude, con búsqueda web automática para refacciones sin cruce o sin stock.
- **Actualización diaria**: subes el nuevo `ZMADE.csv` al repo y un GitHub Action hace el cruce automáticamente.

El script `generar_datos.py` acepta el ZMADE tanto en `.csv` como en `.xlsx`, y detecta
automáticamente en qué fila empieza el encabezado real (por si tu export trae filas de
título arriba, o si ya viene limpio).

## 1. Subir este repo a GitHub

Sube todo el contenido de esta carpeta tal cual a tu repositorio.

## 2. Activar GitHub Pages

Settings → Pages → Source: rama `main`, carpeta `/ (root)`. Tu sitio queda en:
`https://TU-USUARIO.github.io/agente-refacciones/`

## 3. Cómo se cruzan los datos

`scripts/generar_datos.py` toma:
- `data/matriz_criticidad.xlsx` — columnas: Taller, Codigo Comun (GM), Numero de Parte Fabricante, Descripcion, Fabricante (Matriz), Partes por Maquina, Costo Unitario MXN, Lead Time (dias), Stock (Matriz Criticidad), Min, Max.
- `data/ZMADE.xlsx` — tu export crudo de SAP (el encabezado real empieza en la fila 8, el script ya lo maneja).

Cruza por **Codigo Comun (GM) = Material**, el mismo criterio que ya usabas manualmente
(reproduce el 79.4% de match que ya conocías: 478 de 602 cruzadas).

Genera `data/maestro.json` con estos campos por refacción:

| Campo | Origen |
|---|---|
| `taller`, `codigo_gm`, `no_parte_fabricante`, `descripcion`, `fabricante_matriz`, `partes_por_maquina`, `costo_unitario_mxn`, `lead_time_dias`, `stock_matriz_criticidad`, `min`, `max` | matriz de criticidad |
| `stock_sap`, `punto_reorden_sap`, `stock_maximo_sap`, `almacenes_sap`, `fabricante_sap` | ZMADE (LibrUtiliz, Pto.pedido, StockMáx, Alm., Nombre Fabricante) |
| `fuente_stock_sap` | `"OK - cruzado con ZMADE"` o `"SIN CRUCE - revisar codigo"` |

## 4. Flujo diario (lo único que repites)

1. Exporta el ZMADE de SAP como siempre y guárdalo/conviértelo a CSV.
2. En GitHub, sube ese archivo reemplazando `data/ZMADE.csv` (Add file → Upload files, arrastra el nuevo archivo — GitHub detecta que es el mismo nombre y lo sobrescribe).
3. El Action corre solo, regenera `data/maestro.json` y `data/historial_kpis.json`, y revisa alertas.

Si algún día cambia la lista de las 602 refacciones críticas (agregan/quitan una), actualizas
`data/matriz_criticidad.xlsx` de la misma forma.

## 5. Desplegar el Worker (proxy del chat)

Necesario porque GitHub Pages no puede esconder tu API key de Anthropic.

```bash
npm install -g wrangler
cd worker
wrangler login
wrangler secret put ANTHROPIC_API_KEY   # pega tu key cuando la pida
```

Edita `worker.js` → `ALLOWED_ORIGIN` con tu URL real de GitHub Pages (paso 2).

```bash
wrangler deploy
```

Esto te da una URL tipo `https://agente-refacciones-proxy.TU-SUBDOMINIO.workers.dev`.

## 6. Conectar frontend y Worker

En `index.html`, busca:
```js
const WORKER_URL = "https://agente-refacciones-proxy.TU-SUBDOMINIO.workers.dev";
```
y pon la URL real que te dio `wrangler deploy`. Sube el cambio a GitHub.

## Búsqueda web para refacciones sin cruce o sin stock

El chat activa búsqueda web automáticamente solo cuando:
- La refacción consultada tiene `stock_sap` en 0/null, o `fuente_stock_sap` = "SIN CRUCE - revisar codigo".
- Pides explícitamente proveedores, precios o disponibilidad externa.

Busca el número de parte fabricante para encontrar proveedores/distribuidores (prioriza México) y cita las fuentes debajo de la respuesta. Para preguntas que ya responden tus datos (por taller, por costo, etc.) no sale a internet.

## Dashboard de KPIs y exportar CSV

Arriba de la tabla: total de refacciones, % cruzadas con ZMADE, en stock cero, y bajo mínimo.
El botón **"⭳ Exportar CSV"** descarga la tabla filtrada tal como la tengas en pantalla (abre directo en Excel).

## Alertas automáticas de stock crítico (Microsoft Teams)

Cada corrida del Action revisa si hay refacciones con `stock_sap` en 0 (toda la lista ya es
crítica, así que cualquier renglón en cero es una alerta real) y, si las hay, manda un mensaje
a Teams.

**Configurar el webhook (una sola vez):**
1. En el canal de Teams → **"..."** → **Conectores** → **Webhook entrante** → nómbralo (ej. "Alertas Refacciones") → **Crear** → copia la URL.
2. En GitHub: Settings → Secrets and variables → Actions → **New repository secret**.
   - Name: `TEAMS_WEBHOOK_URL`
   - Value: la URL que copiaste.

Si no configuras el secret, el Action omite este paso sin fallar.

## Historial de tendencia

Cada corrida agrega un snapshot a `data/historial_kpis.json` (fecha, total, % cruce, en stock
cero, bajo mínimo — últimos 200 registros). El dashboard compara la corrida actual contra la
anterior y muestra si las refacciones en cero subieron o bajaron. Se genera solo.

## Notas

- Costo: GitHub Pages y Actions son gratis para repos normales. Cloudflare Workers tiene capa gratuita de 100,000 requests/día.
- Si GM bloquea Cloudflare en el futuro, la alternativa es una Azure Function con el mismo código.
- El chat manda todo el JSON de refacciones como contexto (602 filas caben sin problema). Si la matriz de criticidad crece mucho más, conviene filtrar el contexto por taller antes de mandarlo.
- Si tu Excel de matriz de criticidad cambia de nombre de columnas, ajusta `COLS_CRITICIDAD` en `scripts/generar_datos.py`. Si SAP cambia el layout de ZMADE (columnas o fila de encabezado), ajusta `ZMADE_HEADER_ROW` y los nombres en `cargar_zmade()`.
