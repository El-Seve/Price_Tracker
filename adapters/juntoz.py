"""
Adaptador para Juntoz (juntoz.com), marketplace peruano.

Estado (14/09/2026): NO VALIDADO EN VIVO todavía -- confirmado desde afuera
(requests simple) que el sitio existe, corre sobre Next.js, y que la home y
la página de búsqueda mencionan "honor" en el texto -- pero los datos de
producto se cargan client-side (no hay __NEXT_DATA__ ni API pública
detectable en el HTML crudo), así que hace falta un browser real. Este
sandbox no pudo renderizarlo con Playwright (net::ERR_CONNECTION_RESET,
parece que el tráfico de un browser real no sale por la misma ruta que
`requests`/`curl` desde acá) -- probar en vivo con:

    python run.py --retailer Juntoz

y ajustar si el patrón de texto no calza (debug_playwright_dump.py). Este
adaptador busca por marca (como Movistar) en vez de listar una categoría
completa, usando el buscador propio del sitio (?q=<marca>) -- es menos
elegante que una categoría fija, pero no depende de encontrar la URL
"correcta" de la categoría de celulares, que tampoco pudimos confirmar
desde acá.

Tiene el mismo respaldo por LLM que Bitel/Movistar para cuando el parseo
por patrón no encuentre nada (ver playwright_browser.py).
"""
from . import playwright_browser as pb

BASE_URL = "https://juntoz.com"


def fetch_por_marca(marca: str, retailer_nombre: str = "Juntoz") -> str:
    url = f"{BASE_URL}/busqueda?q={marca.lower()}"
    texto = pb.fetch_rendered_text(url, wait_ms=8000, wait_for_text="S/")
    if pb.parece_challenge_o_mantenimiento(texto):
        raise RuntimeError(f"{retailer_nombre}: sigue mostrando challenge/mantenimiento en {url}")
    return texto


def extract_rows(textos_por_marca: dict[str, str], categoria: str, retailer: str,
                  target_brands: set[str]) -> list[dict]:
    rows = []
    vistos = set()
    for texto in textos_por_marca.values():
        for oferta in pb.extraer_ofertas_con_fallback(texto, target_brands, retailer):
            key = (oferta["marca"], oferta["modelo"], oferta["precio_oferta"])
            if key in vistos:
                continue
            vistos.add(key)
            rows.append({
                "retailer": retailer,
                "categoria": categoria,
                "marca": oferta["marca"],
                "modelo": oferta["modelo"],
                "precio_regular": oferta["precio_regular"],
                "precio_oferta": oferta["precio_oferta"],
                "vendedor": retailer,
                "vendedor_tercero": False,
                "url": "",
            })
    return rows
