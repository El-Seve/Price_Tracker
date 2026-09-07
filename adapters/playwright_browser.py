"""
Adaptador genérico con browser real (Playwright) para sitios protegidos por
Cloudflare (Movistar, Ripley) que bloquean cualquier request simple --
`requests` o `curl_cffi` con fingerprint TLS falso siguen recibiendo el
challenge ("Just a moment...") porque el bloqueo exige ejecutar JS de
verdad, no solo parecer un navegador a nivel de protocolo.

Estado (actualizado 07/09/2026):
- Ripley: VALIDADO EN VIVO -- `python run.py --retailer Ripley` trae datos
  reales (212 filas en la primera corrida de Seve). El HTML que devuelve
  una vez pasado el challenge es texto plano renderizado en servidor (sin
  JSON embebido), por eso el parseo es por patrón de texto y no por JSON.
  Ojo con el timing: el challenge de Cloudflare consume varios segundos por
  sí solo, así que hay que esperar explícitamente a que aparezca contenido
  real (`wait_for_text="S/"`) antes de leer la página -- un wait fijo
  corto (probado: 5s) puede devolver la página todavía sin cargar del todo
  y capturar 0 productos sin ningún error.
- Movistar: TODAVÍA NO -- tienda.movistar.com.pe usa una SPA vieja tipo
  Angular (placeholders "{{...}}" en el HTML crudo, precios client-side) y
  al renderizarla con Playwright real devuelve una página de "Estamos en
  mantenimiento" en vez del catálogo -- puede ser downtime real del sitio o
  un soft-block anti-bot disfrazado de mantenimiento; no diferenciado
  todavía. `run.py` corriendo normal la salta con un aviso `[!] falló` sin
  romper el resto de la captura, así que no hace daño dejarla en
  retailers.json mientras se investiga aparte.

`playwright` ya está en requirements.txt y el workflow de GitHub Actions
instala chromium (`playwright install --with-deps chromium`) antes de
correr `run.py` -- ver debug_playwright_dump.py para diagnosticar si algún
sitio deja de calzar con el patrón de extracción más adelante.
"""
import re

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

_CHALLENGE_MARKERS = ["just a moment", "verificando que usted es un ser humano",
                       "cf-turnstile", "challenge-platform", "estamos en mantenimiento"]


def fetch_rendered_text(url: str, wait_ms: int = 6000, timeout: int = 45000,
                         wait_for_text: str | None = None) -> str:
    """Renderiza `url` con Chromium real y devuelve el texto visible de la
    página (page.inner_text('body')) -- se usa texto plano en vez de HTML
    porque no conocemos los nombres de clase CSS reales de estos sitios sin
    haberlos inspeccionado en vivo; el texto visible es más estable para un
    primer parseo por patrón (ver extraer_ofertas_por_patron).

    wait_for_text: si se pasa (ej. "S/"), espera hasta que aparezca ese
    texto en la página antes de leerla -- útil para sitios que rellenan
    precios de forma asíncrona (Movistar/Angular)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=USER_AGENT,
            locale="es-PE",
            viewport={"width": 1366, "height": 900},
        )
        # navigator.webdriver=true es la señal más obvia de automatización;
        # Cloudflare la chequea de entrada. No es infalible, pero ayuda.
        ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            page.wait_for_timeout(wait_ms)
            if wait_for_text:
                try:
                    page.wait_for_function(
                        "sel => document.body.innerText.includes(sel)",
                        arg=wait_for_text, timeout=15000,
                    )
                except Exception:
                    pass  # seguimos igual con lo que haya, mejor que reventar
            texto = page.inner_text("body")
        finally:
            browser.close()
    return texto


def parece_challenge_o_mantenimiento(texto: str) -> bool:
    """True si el texto visible sigue siendo la página de challenge de
    Cloudflare o una landing de mantenimiento, en vez del catálogo real --
    para que el adaptador avise claro en vez de devolver 0 productos
    silenciosamente como si el día no hubiera stock de nada."""
    bajo = texto.lower()
    return any(m in bajo for m in _CHALLENGE_MARKERS)


_PRECIO_RE = re.compile(r"S/\s*([\d,]+(?:\.\d{2})?)")


def extraer_ofertas_por_patron(texto: str, marcas: set[str], max_precios_por_bloque: int = 3):
    """Parseo por patrón de texto, línea por línea, sin depender de clases
    CSS (que no conocemos de antemano en estos dos sitios): cada vez que una
    línea empieza con el nombre de una marca objetivo (típico en listados de
    e-commerce: "SMARTPHONE HONOR X7D 256GB..."), toma esa línea como nombre
    de producto y junta los precios "S/ ..." que aparecen en las líneas
    siguientes (hasta max_precios_por_bloque) como candidatos a precio
    regular/oferta -- se queda con el menor como precio_oferta y el mayor
    como precio_regular (en la práctica: precio tachado > precio final).

    Devuelve una lista de dicts {marca, modelo, precio_regular, precio_oferta}.
    Es deliberadamente tolerante -- prioriza no perderse productos reales
    sobre precisión quirúrgica; conviene revisar una muestra a mano la
    primera vez que corra contra datos reales.

    Tres filtros/ajustes clave, confirmados necesarios al probar con texto
    de ejemplo realista de un listado tipo Ripley:
    - se ignoran líneas que son SOLO el nombre de la marca (categoría/badge
      encima de la tarjeta -- "HONOR" solo, sin modelo, no cuenta como
      producto en sí);
    - una línea-marca sola SÍ se recuerda como "contexto" para la línea de
      producto que viene justo después, porque en varios listados el
      nombre del producto no repite la marca (ej. categoría "APPLE" seguida
      de "IPHONE 17 PRO MAX 256GB", que no dice "Apple" en el título);
    - se ignoran precios por debajo de PRECIO_MINIMO como candidatos (montos
      chicos tipo "Incluye regalo a S/0.10" no son el precio del equipo)."""
    PRECIO_MINIMO = 100.0
    MAX_LINEAS_DESDE_CONTEXTO = 2
    lineas = [l.strip() for l in texto.split("\n") if l.strip()]
    marcas_upper = {m.upper() for m in marcas}
    ofertas = []
    marca_contexto = None
    lineas_desde_contexto = 999
    i = 0
    while i < len(lineas):
        linea_upper = lineas[i].upper()
        palabras = lineas[i].split()
        es_solo_la_marca = linea_upper.strip() in marcas_upper

        if es_solo_la_marca:
            marca_contexto = linea_upper.strip()
            lineas_desde_contexto = 0
            i += 1
            continue

        marca_en_linea = next((m for m in marcas_upper if m in linea_upper), None)
        if (not marca_en_linea and marca_contexto and lineas_desde_contexto <= MAX_LINEAS_DESDE_CONTEXTO
                and len(palabras) >= 2 and any(c.isdigit() for c in lineas[i])):
            marca_en_linea = marca_contexto  # ej. "APPLE" (label) -> "IPHONE 17 PRO MAX 256GB" (sin decir Apple)

        lineas_desde_contexto += 1

        if marca_en_linea and len(palabras) >= 2 and len(lineas[i]) < 120:
            modelo = lineas[i]
            precios = []
            for j in range(i + 1, min(i + 1 + 6, len(lineas))):
                m = _PRECIO_RE.search(lineas[j])
                if m:
                    try:
                        precio = float(m.group(1).replace(",", ""))
                    except ValueError:
                        continue
                    if precio >= PRECIO_MINIMO:
                        precios.append(precio)
                if len(precios) >= max_precios_por_bloque:
                    break
            if precios:
                ofertas.append({
                    "marca": marca_en_linea,
                    "modelo": modelo,
                    "precio_oferta": min(precios),
                    "precio_regular": max(precios),
                })
                marca_contexto = None  # ya se usó, no aplicarlo también al siguiente producto
        i += 1
    return ofertas
