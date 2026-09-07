# Tracker de precios — Honor vs. competencia (Retail Perú)

Captura diaria y gratuita de precios de smartphones (y accesorios) en retailers
peruanos, comparando Honor contra Samsung, Xiaomi, Motorola, Apple y Redmi.
Nace del piloto hecho a mano con PlazaVea y Falabella — esto es la versión
que corre sola, todos los días, sin depender de una conversación de chat.

## Por qué existe

Los precios de smartphones/tablets/accesorios en retail cambian a diario.
Revisar esto a mano, retailer por retailer, no escala. Este proyecto:

- No usa ninguna herramienta de scraping de pago (Bright Data, Nimble, etc.) —
  cada retailer soportado hoy expone sus datos gratis, sin bloqueo, si sabes
  dónde mirar (ver `adapters/`).
- Guarda histórico real en SQLite (`data/precios.db`), no solo la foto de hoy —
  así se puede ver cuándo bajó de precio un modelo, no solo el precio actual.
- Corre solo, gratis, vía GitHub Actions (`.github/workflows/daily_scrape.yml`) —
  no consume tu cuota de Claude ni depende de que abras el chat.

## Cómo está armado

```
pricetracker/
  adapters/
    vtex.py                  # PlazaVea, Promart, Oechsle, Claro, Metro, Wong, Carsa, Coolbox (VTEX)
    falabella_nextjs.py      # Falabella, Sodimac, Tottus (JSON embebido __NEXT_DATA__)
    entel_endeca.py          # Entel (Oracle ATG/Endeca -- JSON pidiendo Accept: application/json)
    schema_jsonld.py         # genérico JSON-LD (funciona en Samsung Perú, pero bloqueado por Akamai -- ver abajo)
    magento_html.py          # Hiraoka, La Curacao, Tiendas EFE (Magento, precios server-side)
    shopify_json.py          # Covers Store, iShop, Mac Center (Shopify -- /products.json)
    woocommerce_store_api.py # Celivery Perú (WooCommerce Store API pública)
  dashboard/
    normalize.py              # nombre de producto -> familia comparable + filtros de calidad
    build_dashboard_data.py   # lee precios.db, calcula KPIs/oportunidades, escribe docs/dashboard_data.json
  docs/
    index.html                # el dashboard (página estática, la sirve GitHub Pages)
    dashboard_data.json       # generado por build_dashboard_data.py, se regenera cada corrida
  retailers.json          # qué retailer, qué plataforma, qué categorías/vendedores
  db.py                    # esquema SQLite + inserción + detección de cambios
  run.py                   # orquestador: lee config -> llama adaptador -> guarda
  data/precios.db          # se crea solo en la primera corrida
```

Cada adaptador expone la misma forma: una función `fetch_*` que trae productos
crudos de la plataforma, y una función `extract_*` que los normaliza a filas
`{retailer, categoria, marca, modelo, precio_regular, precio_oferta, vendedor,
vendedor_tercero, url}`.

### Por qué "por vendedor" y no solo "por categoría"

En Falabella/Sodimac/Tottus (plataforma marketplace), un mismo producto lo
pueden vender varios sellers a precios distintos, y navegar solo por
categoría no siempre trae TODO el catálogo de un vendedor (paginación, orden
por relevancia).

Por eso `run_falabella_nextjs` en `run.py` hace descubrimiento automático:
mientras recorre cada categoría, identifica todos los vendedores (marketplace)
que aparecen vendiendo alguna de las marcas objetivo, y baja el catálogo
completo de cada uno por separado, en paralelo (hasta 8 a la vez, para que la
corrida no tarde una eternidad -- Falabella solo puede tener 80+ vendedores
distintos de Honor/Samsung/Xiaomi/etc. en una sola categoría).

Esto reemplazó el enfoque anterior de mantener una lista manual de slugs
conocidos (`vendedores_honor_conocidos`) -- ese enfoque causó un bug real: el
slug de "Sany Distribuidor Autorizado" se escribió a mano mal
(`sany-distribuidor-autorizado`, con guiones, que no existe) y nunca trajo
nada, sin que nadie lo notara hasta que se revisó a mano. `retailers.json`
todavía acepta `vendedores_honor_conocidos` como lista opcional de
refuerzo/override, pero ya no es necesaria para el funcionamiento normal.

El slug real de un vendedor se obtiene de una página de producto real (el
link "Vendido por"), NO adivinando a partir del nombre -- ver
`discover_seller_slug()` en `adapters/falabella_nextjs.py`.

## Cómo correrlo

```bash
pip install -r requirements.txt
python run.py                                    # todos los retailers
python run.py --retailer PlazaVea                 # solo uno
python run.py --export-csv data/hoy.csv           # además, exportar CSV del día
```

La primera corrida crea `data/precios.db`. Las siguientes van sumando filas
con fecha, y al final imprimen qué precios de Honor cambiaron desde la última
corrida.

## Cómo dejarlo corriendo solo (gratis)

1. Crear un repositorio en GitHub y subir esta carpeta (`git init`, `git add .`,
   `git commit`, `git push`).
2. El workflow `.github/workflows/daily_scrape.yml` ya está configurado para
   correr todos los días a las 9am hora Perú, sin que hagas nada — GitHub
   Actions es gratis para repos públicos y da minutos gratis de sobra en
   repos privados para una tarea tan corta.
3. Cada corrida hace commit de la base de datos actualizada y un CSV del día
   dentro de `data/` — el historial de commits ES el historial de precios.
4. Se puede disparar manualmente desde la pestaña "Actions" del repo
   ("Run workflow") sin esperar al cron.

## Dashboard de oportunidades de precio

Además de guardar el histórico crudo, cada corrida genera un dashboard
publicado (`docs/index.html` + `docs/dashboard_data.json`), construido según
**IS Design System v1.0**. Muestra:

- **Resumen**: KPIs del día (ofertas Honor capturadas, familias detectadas,
  cuántas oportunidades hay) + las alertas más relevantes (Evidencia →
  Interpretación → Acción) + tabla de qué retailers sí trajeron datos hoy.
- **Honor vs Competencia**: por segmento de precio (Hasta S/600, S/600-1,000,
  etc.), el Honor más barato disponible vs. el competidor (Samsung, Xiaomi,
  Motorola, Apple, Redmi, Poco) más barato del mismo segmento -- no se puede
  matchear modelo exacto entre marcas, así que el segmento de precio es el
  proxy de "gama equivalente".
- **Explorador**: dispersión de precio del mismo SKU Honor entre retailers y
  vendedores -- si el mismo modelo cuesta S/449 en un lado y S/899 en otro,
  aparece acá, ordenado de mayor a menor dispersión.
- **Sany**: pestaña dedicada a todo lo que vende Sany (aparece como vendedor
  marketplace en PlazaVea/Promart y también en Falabella, no es exclusivo de
  una plataforma) comparado contra el precio más bajo del resto del mercado
  para la misma familia.
- **Tendencia**: qué precios de Honor cambiaron desde la corrida anterior.
  Se vuelve más útil día a día, a medida que se acumula historial.

### Cómo publicarlo (una sola vez)

GitHub Pages gratis y automático requiere que el repositorio sea público.
Como se decidió tratar los datos como sensibles por defecto, la config
recomendada es: **repo público, pero con el link de la página sin listar**
(no aparece en buscadores ni en ningún directorio, solo quien tenga el link
exacto puede verla) -- nadie va a *encontrar* la página por accidente, pero
técnicamente el repo deja de ser privado. Si eso no es aceptable, la
alternativa es GitHub Pro/Team (pago) para mantener Pages sobre un repo
privado, o simplemente no publicar la página y quedarse con el dashboard
corriendo solo en local (`python -m dashboard.build_dashboard_data` y abrir
`docs/index.html` a mano).

Pasos (una sola vez):

1. **Hacer público el repo**: Settings → General → bajar hasta "Danger Zone"
   → "Change visibility" → "Make public" → escribir el nombre del repo para
   confirmar.
2. **Activar GitHub Pages**: Settings → Pages → en "Build and deployment",
   Source = "Deploy from a branch" → Branch = `main`, carpeta = `/docs` →
   Save.
3. GitHub tarda 1-2 minutos en publicarla la primera vez. La URL queda como
   `https://<tu-usuario>.github.io/<nombre-del-repo>/` -- ese es el link sin
   listar para compartir con jefatura/equipo.
4. Cada corrida diaria de `daily_scrape.yml` ya regenera
   `docs/dashboard_data.json` y lo commitea -- la página se actualiza sola,
   no hay que volver a tocar nada.

### Correrlo/probarlo en local

```bash
python -m dashboard.build_dashboard_data   # genera/actualiza docs/dashboard_data.json
python -m http.server 8000 --directory docs   # servirlo localmente
# abrir http://localhost:8000 en el navegador
```

## Cómo agregar un retailer nuevo

1. Confirmar qué plataforma usa (ver `adapters/vtex.py` y
   `adapters/falabella_nextjs.py` para las pistas: `xmlns:vtex` en el HTML,
   o un `<script id="__NEXT_DATA__">`).
2. Si es una de esas dos plataformas, solo hay que agregar su entrada en
   `retailers.json` (dominio + rutas de categoría).
3. Si es una plataforma distinta, escribir un adaptador nuevo en `adapters/`
   con la misma interfaz (`fetch_*` + `extract_*`), y registrarlo en el
   diccionario `ADAPTERS` de `run.py`.

### Estado de los operadores móviles (investigado 06/09/2026)

- **Claro**: soportado. VTEX estándar (`tienda.claro.com.pe`), mismo adaptador
  que PlazaVea/Promart.
- **Entel**: soportado. NO es VTEX -- corre en Oracle ATG/Endeca. La página de
  categoría normal no trae los datos en el HTML, pero la misma URL responde
  el catálogo completo en JSON si se pide con header `Accept:
  application/json`. Adaptador propio: `adapters/entel_endeca.py`.
- **Bitel**: NO soportado por ahora. `tienda.bitel.com.pe` está detrás de
  Cloudflare y devuelve HTTP 401 a cualquier request simple, headers de
  navegador incluidos. Necesita browser real o una herramienta tipo Bright
  Data para pasar el challenge.
- **Movistar**: NO soportado por ahora. Es un sitio WordPress que carga los
  precios vía JavaScript -- no hay JSON embebido ni API pública detectada.
  Necesita browser real (Bright Data/Playwright).

Bitel y Movistar quedan en `no_soportados` dentro de `retailers.json`, con el
motivo documentado, para no repetir la investigación desde cero más adelante.

### Tiendas propias / grupos retail (investigado 06/09/2026)

- **Tottus**: soportado. Mismo grupo/plataforma que Falabella (Next.js), reusa
  `adapters/falabella_nextjs.py` sin ningún cambio.
- **Metro** y **Wong**: soportados. VTEX estándar (grupo Cencosud), mismo
  adaptador que PlazaVea/Promart/Claro.

### Sitios de marca (investigado 06/09/2026)

- **Samsung Perú**: el precio SÍ es fácil de sacar -- la página de categoría
  trae un bloque JSON-LD estándar (`schema.org` `ItemList`/`Product`/`Offer`)
  con precios reales, sin falta de API ni JS (`adapters/schema_jsonld.py`).
  El problema es que el sitio está detrás de Akamai: a la segunda o tercera
  request seguida devuelve 403 "Access Denied". No es viable para una corrida
  automática diaria sin una capa de proxy/rotación de IP (Bright Data), así
  que queda en `no_soportados` -- el adaptador queda listo por si en el
  futuro se agrega esa capa.
- **Xiaomi Perú**, **Huawei Perú** y **Lenovo Perú**: sin JSON-LD ni JSON
  embebido detectable en las páginas probadas. Necesitarían más investigación
  o browser real.
- **HONOR Perú (tienda oficial)**: los precios se rellenan por JavaScript
  sobre una plantilla del lado del cliente (`{{colorObj.lastPrdPackagePrice}}`
  literal en el HTML) -- no hay precio estático que leer. Necesita browser real.

### Tiendas especializadas en tecnología (investigado 06/09/2026)

- **Carsa** y **Coolbox**: soportados. VTEX estándar, mismo adaptador que
  PlazaVea/Metro/Wong.
- **Hiraoka**, **La Curacao** y **Tiendas EFE**: soportados. Las tres corren
  Magento con el listado renderizado del lado del servidor (sin JS) --
  adaptador nuevo `adapters/magento_html.py`, que también captura el
  "Por &lt;vendedor&gt;" cuando el producto lo vende un tercero dentro del
  marketplace. OJO: La Curacao y Tiendas EFE son del mismo grupo corporativo
  y comparten el catálogo/precios casi exactos.
- **Covers Store Perú**, **iShop Perú** y **Mac Center Perú**: soportados.
  Las tres son Shopify -- se leen agregando `/products.json` a la colección,
  sin tocar el HTML (`adapters/shopify_json.py`). iShop y Mac Center son
  Apple Premium Partners: todo su catálogo es Apple, sirven como referencia
  de precio Apple pero no traen Honor/otras marcas.
- **Celivery Perú**: soportado, pero con una corrección de dominio -- el que
  aparecía en el directorio original (`celivery.com`) está parkeado/en venta;
  el real es `celiveryperu.com`. Es WordPress + WooCommerce, se lee con la
  Store API pública (`adapters/woocommerce_store_api.py`).
- **Ripley**: NO soportado. Cloudflare con challenge JS activo, igual que
  Bitel -- necesita browser real.
- **Mercado Libre Perú**: NO soportado. Su API pública de búsqueda ahora pide
  token de aplicación (403 sin él) y la web detecta el request como tráfico
  sospechoso. Además es un marketplace gigante -- necesitaría lógica de
  búsqueda por producto, no un catálogo fijo.
- **Rappi Perú**: NO soportado. El catálogo depende de elegir tienda/ubicación
  dentro de la app, no hay una URL de categoría pública fija.
- **Agiletech**: no aplica -- es tienda de laptops/PC/redes, no vende
  celulares (confirmado por búsqueda vacía en su propia API).
- **Juntoz**, **Memory Kings**, **Pasaje Central** y **LoQuiero**
  (`loquiero.pe`, no `.com`): sin plataforma identificada con las firmas
  conocidas (VTEX, Falabella, Magento, Shopify, WooCommerce). Pendientes de
  una revisión más profunda -- no están descartados, solo sin resolver aún.

Todo esto queda documentado en `no_soportados` dentro de `retailers.json`,
con el motivo específico de cada uno, para no repetir la investigación desde
cero más adelante.

## Limitaciones a tener presentes

- El adaptador de Falabella/Sodimac lee un JSON embebido no documentado
  oficialmente — si Falabella cambia su frontend, puede romperse (el
  adaptador VTEX, al ser una API pública, es más estable).
- VTEX limita la paginación por categoría a ~2,550 resultados; para
  categorías más grandes que eso, conviene filtrar por marca en vez de traer
  todo.
- Esto lee datos públicos igual que cualquier visitante de la web —
  respeta límites razonables de frecuencia (no bajar la misma categoría
  cada minuto) para no forzar la infraestructura del retailer.
