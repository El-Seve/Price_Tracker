# Tracker de precios — Honor vs. competencia (Retail Perú)

Captura diaria y gratuita de precios de smartphones (y accesorios) en retailers
peruanos, comparando Honor contra Samsung, Xiaomi, Motorola, Apple, Redmi,
Poco y Huawei.
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
    schema_jsonld.py         # genérico JSON-LD: Samsung Perú (con curl_cffi), Xiaomi Perú, Huawei Perú
    magento_html.py          # Hiraoka, La Curacao, Tiendas EFE (Magento, precios server-side)
    shopify_json.py          # Covers Store, iShop, Mac Center (Shopify -- /products.json)
    woocommerce_store_api.py # Celivery Perú (WooCommerce Store API pública)
    honor_official.py        # HONOR Perú tienda oficial (endpoint de precios descubierto en su JS)
    playwright_browser.py    # helper genérico con browser real, para sitios con Cloudflare
    ripley.py                # Ripley vía Playwright -- soportado y activo en el cron
    movistar.py              # Movistar vía Playwright -- pendiente, ver sección abajo
  debug_playwright_dump.py # herramienta para diagnosticar Ripley/Movistar si el parseo falla
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
  aparece acá, ordenado de mayor a menor dispersión. Tiene filtros por tipo de
  producto (Smartphones / Tablets / Wearables / Audio) para no mezclar, por
  ejemplo, un celular con un smartwatch al buscar dispersión.
- **Sany**: pestaña dedicada a todo lo que vende Sany (aparece como vendedor
  marketplace en PlazaVea/Promart y también en Falabella, no es exclusivo de
  una plataforma) comparado contra el precio más bajo del resto del mercado
  para la misma familia.
- **Tendencia**: evolución de precio (mínimo/promedio/máximo) de cada familia
  Honor día a día, Honor vs. el mínimo de la competencia por segmento a lo
  largo del tiempo, un mapa de calor de qué vendedor mueve precio más seguido,
  y la tabla de qué cambió desde la corrida anterior. Con 1 día de captura
  estas vistas muestran un aviso ("vuelve mañana") en vez de un gráfico vacío
  o roto -- se arman solas, sin tocar código, a medida que se acumulan días.
- **Análisis**: lecturas que no salen de mirar una tabla de precios --
  ranking de qué vendedores cobran sistemáticamente por encima/por debajo del
  mercado (no un caso aislado, un patrón sostenido en 3+ productos), qué % del
  catálogo Honor depende de un solo vendedor (riesgo de quedarse sin
  alternativa si ese vendedor sube precio o se queda sin stock), y en qué
  segmento de precio el mercado es menos disciplinado (mayor dispersión
  relativa entre vendedores).

### Segmentación por tipo de producto

Cada oferta capturada (Honor y competencia) se clasifica automáticamente en
**Smartphone**, **Tablet**, **Wearable** (watch/band), **Audio**
(earbuds/audífonos) o **Accesorio** (funda, cargador, cable, mica, power
bank, parlante -- se descarta del dashboard, no aporta a ninguna
comparación de precio). La clasificación mira solo las primeras palabras del
nombre del producto, para no confundir un bundle "celular + regalo" (p.ej.
"600 Smart 5G ... + Earbuds X7L") con el regalo mismo.

Por qué separarlos:

- Comparar el precio de una tablet o un smartwatch contra el de un celular
  no tiene sentido -- vienen de mercados de precio completamente distintos.
  Por eso la comparación "Honor vs Competencia por segmento de precio" (la
  tabla principal) queda restringida solo a Smartphones.
- Tablets y Wearables se comparan aparte, en una tabla propia dentro de
  "Honor vs Competencia" ("Tablets y Wearables: comparación directa"),
  con el mínimo de Honor vs. el mínimo de la competencia sin banding por
  precio (el rango de precios de estas categorías es angosto, no hace
  falta segmentar). Si un día no hay ofertas de alguna categoría, la tabla
  lo indica ("Sin datos de Tablets hoy") en vez de mostrar una fila vacía o
  rota.
- El resumen del día (KPI "Ofertas Honor capturadas hoy") desglosa cuántas
  ofertas son de cada tipo, y el Explorador permite filtrar la dispersión
  interna por tipo de producto.

Agregar una línea nueva (celular, tablet, wearable o audio) es sumar una
entrada a la lista correspondiente en `dashboard/normalize.py`
(`FAMILIAS_HONOR`, `FAMILIAS_WEARABLE_HONOR` o `FAMILIAS_AUDIO_HONOR`) --
no requiere tocar el resto del pipeline.

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
- **Bitel**: NO soportado. `tienda.bitel.com.pe` bloquea por reputación de IP
  a nivel de borde de Cloudflare (probado con varios fingerprints TLS
  distintos, siempre el mismo 401 de 9 bytes) -- no es un problema de
  fingerprint resoluble con librerías gratis, solo cambiando la IP de origen
  (residencial), lo cual no es viable para una corrida automática en servidor.
- **Movistar**: PENDIENTE, ver sección "Ripley (Playwright) y el pendiente de
  Movistar" más abajo -- la tienda real vive en `tienda.movistar.com.pe` (no
  en el dominio de marketing), tiene adaptador nuevo, pero al renderizarla
  con Playwright real devuelve una página de "Estamos en mantenimiento" en
  vez del catálogo -- sin confirmar todavía si es downtime real o un
  soft-block anti-bot.

Bitel queda en `no_soportados` dentro de `retailers.json`, con el motivo
documentado, para no repetir la investigación desde cero más adelante.

### Tiendas propias / grupos retail (investigado 06/09/2026)

- **Tottus**: soportado. Mismo grupo/plataforma que Falabella (Next.js), reusa
  `adapters/falabella_nextjs.py` sin ningún cambio.
- **Metro** y **Wong**: soportados. VTEX estándar (grupo Cencosud), mismo
  adaptador que PlazaVea/Promart/Claro.

### Sitios de marca (investigado 06/09/2026, destrabados 07/09/2026)

- **Samsung Perú**: soportado. La categoría trae un bloque JSON-LD estándar
  (`schema.org` `ItemList`/`Product`/`Offer`) en
  `samsung.com/pe/smartphones/all-smartphones/`. El bloqueo de Akamai (403 a
  la 2da/3ra request) resultó ser por abrir una conexión nueva por cada
  request, no por volumen -- se resuelve con `curl_cffi` (`impersonate=
  "edge101"`) reutilizando UNA sola sesión para todas las categorías de la
  corrida, con reintento automático (hasta 3 intentos con backoff 0s/2s/5s,
  porque el primer request de una sesión nueva a veces sale 403 y el
  siguiente ya funciona). No es 100% infalible -- Akamai puede seguir
  bloqueando algún día puntual -- pero si falla, ese retailer simplemente
  queda sin datos ese día sin romper el resto de la corrida. Requiere
  `pip install curl_cffi` (ya en `requirements.txt`); si no está instalado,
  se salta con un aviso en vez de fallar.
- **Xiaomi Perú**: soportado. La URL real del catálogo es
  `mi.com/pe/v2/product-list/phone` (no la home/categoría genérica, que no
  tiene nada) -- trae el mismo formato ItemList que Samsung, sin bloqueo.
  Esa página mezcla Xiaomi + Redmi + Poco bajo un solo listado, así que el
  adaptador detecta la sub-marca real por la primera palabra del nombre del
  producto en vez de etiquetar todo como "XIAOMI".
- **Huawei Perú**: soportado, con un formato distinto al de Samsung/Xiaomi.
  La categoría general viene vacía, pero cada página de producto individual
  trae un JSON-LD tipo `productGroup` (variantes anidadas, precio tachado
  incluido cuando hay descuento). El `sitemap.xml` público lista todas esas
  páginas de producto sin necesidad de adivinar URLs. Se agregó **HUAWEI**
  a `target_brands` -- antes no estaba entre las marcas comparadas.
- **Lenovo Perú**: descartado (no un bloqueo, sino que no aplica). Lenovo no
  vende celulares con marca propia en Perú, esa web solo tiene "smart
  devices" genéricos. La marca de teléfonos del grupo es **Motorola**, que
  sí se agregó: `motorola.com.pe` corre sobre VTEX estándar, así que reusa
  `adapters/vtex.py` sin ningún cambio de código, solo un dominio nuevo.
- **HONOR Perú (tienda oficial)**: soportado. Los precios se rellenan por
  JavaScript sobre una plantilla del lado del cliente
  (`{{colorObj.lastPrdPackagePrice}}` literal en el HTML), pero el propio JS
  del sitio (`base.min.js`) llama a un endpoint de precios
  (`selfservice-sg.hihonor.com/.../queryPrdInfoByOfficial`) mandando los
  `productIds` que aparecen como atributo `data-ec-product-id` en cada
  tarjeta de producto -- adaptador nuevo `adapters/honor_official.py`, sin
  necesidad de browser, cookies ni token.

### Ripley (Playwright) y el pendiente de Movistar (investigado/destrabado 07/09/2026)

Estos dos son distintos a todos los anteriores: no alcanza con `requests` ni
con `curl_cffi` (fingerprint TLS falso) porque el bloqueo de Cloudflare en
ambos exige ejecutar JavaScript de verdad para pasar el challenge
("Just a moment..." en Ripley, un Managed Challenge + una SPA vieja tipo
Angular en Movistar). Se confirmó que el catálogo real con precios SÍ está
accesible para un fetcher que se comporta como navegador legítimo -- eso
descarta que sea un bloqueo de reputación de IP irresoluble (como Bitel).

**Ripley: soportado y activo en el cron diario.** `adapters/ripley.py` +
`adapters/playwright_browser.py` renderizan la categoría con Chromium real
y leen el texto visible de la página (Ripley no expone JSON embebido, así
que el parseo empareja nombre de producto + precios por patrón de líneas
consecutivas en vez de por clases CSS). Validado en vivo por Seve:
`python run.py --retailer Ripley` trae ~200 filas reales. El único ajuste
que hizo falta fue el timing -- el challenge de Cloudflare por sí solo
consume varios segundos, así que hay que esperar explícitamente a que
aparezca contenido real (`wait_for_text="S/"`) antes de leer el texto; con
un wait fijo corto la página se lee "vacía" (sin marcas ni precios) y
captura 0 productos sin ningún error, que es justo lo que pasó la primera
vez. `playwright` ya está en `requirements.txt` y el workflow de GitHub
Actions instala chromium (`playwright install --with-deps chromium`) antes
de correr la captura.

**Movistar: pendiente, sin resolver todavía.** `adapters/movistar.py` usa el
mismo enfoque, pero al renderizar `tienda.movistar.com.pe/celulares/<marca>`
con Playwright real, la página muestra "Estamos en mantenimiento ¡Volveremos
pronto!" en vez del catálogo -- confirmado con captura de pantalla. Puede
ser downtime real del sitio (revisar en otro momento) o un soft-block
anti-bot que le muestra esa pantalla a tráfico detectado como automatizado
en vez de tirar un 403 directo -- no diferenciado todavía. Como
`movistar_playwright` está en la lista principal de `retailers.json`, sigue
corriendo cada día en el cron, pero como falla con un aviso `[!] falló`
capturado (no rompe el resto de la corrida), simplemente no aporta datos
hasta que esto se resuelva.

**Si algún día Ripley deja de calzar con el patrón de extracción** (cambio
de diseño del sitio, 0 filas de nuevo, etc.), la herramienta de diagnóstico
sigue disponible:

```bash
python debug_playwright_dump.py "https://simple.ripley.com.pe/tecnologia/celulares/celulares-y-smartphones?s=mdco&page=1"
python debug_playwright_dump.py "https://tienda.movistar.com.pe/celulares/honor"
```

Esto guarda `debug_dump.html`, `debug_dump_texto.txt` y `debug_dump.png`
(captura de pantalla) junto al script -- compártelos para ajustar el patrón
de extracción sin adivinar a ciegas.

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
- **Ripley**: soportado (Playwright), ver sección "Ripley (Playwright) y el
  pendiente de Movistar" más abajo -- Cloudflare con challenge JS activo,
  distinto al bloqueo de Bitel (que es de reputación de IP, sin solución
  gratis).
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
