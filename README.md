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
    vtex.py              # PlazaVea, Promart, Oechsle, Claro (misma plataforma VTEX)
    falabella_nextjs.py  # Falabella, Sodimac (JSON embebido __NEXT_DATA__)
    entel_endeca.py      # Entel (Oracle ATG/Endeca -- JSON pidiendo Accept: application/json)
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

En Falabella y PlazaVea/Promart, un mismo producto lo pueden vender varios
sellers de marketplace a precios distintos, y navegar solo por categoría no
siempre trae TODO el catálogo de un vendedor (paginación, orden por
relevancia). Por eso, para los vendedores que ya sabemos que tienen Honor
(`vendedores_honor_conocidos` en `retailers.json`), además de la categoría se
baja su catálogo completo por separado. Si aparece un vendedor nuevo relevante,
se agrega su slug a esa lista.

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

Pendientes de investigar (ver `pendientes_de_investigar` en `retailers.json`):
Tottus, Metro, Wong y los sitios de fabricante (Samsung, Xiaomi, Huawei Perú).

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
