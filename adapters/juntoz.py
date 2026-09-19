"""
Adaptador para Juntoz (juntoz.com), marketplace peruano.

Estado (18/09/2026): la búsqueda genérica de juntoz.com/busqueda?q=honor daba
0 filas en la primera prueba en vivo. Revisando el Excel de links de Sany
("Products Links of SANY.xlsx") se confirmó por qué: los productos Honor de
Sany en Juntoz NO viven bajo juntoz.com -- viven en una tienda de marca
dedicada, el subdominio honor.juntoz.com/p/<slug> (confirmado con curl: HTTP
200, "Honor" en el texto). Es la misma plataforma (Next.js, mismo dominio
raíz) pero un storefront de marca aparte, así que el buscador genérico de
juntoz.com nunca la indexaba.

Por eso, además de la búsqueda genérica por marca (que sigue sirviendo para
comparar contra la competencia -- Samsung, Xiaomi, etc. si aparecen en
juntoz.com), este adaptador agrega un fetch aparte de la home de
honor.juntoz.com, que al ser la tienda oficial de la marca ya viene
pre-filtrada a productos Honor sin necesidad de adivinar categoría ni marca.

Sigue sin datos embebidos en el HTML crudo (no __NEXT_DATA__, no JSON-LD) --
los precios se pintan client-side, así que sigue haciendo falta un browser
real (Playwright). NO VALIDADO EN VIVO todavía (el sandbox de desarrollo no
puede correr Playwright contra sitios reales) -- probar con:

    python run.py --retailer Juntoz

y ajustar si el patrón de texto no calza (debug_playwright_dump.py). Mismo
respaldo por LLM que Bitel/Movistar para cuando el parseo por patrón no
encuentre nada (ver playwright_browser.py).
"""
from . import playwright_browser as pb

BASE_URL = "https://juntoz.com"
HONOR_STORE_URL = "https://honor.juntoz.com"


def fetch_por_marca(marca: str, retailer_nombre: str = "Juntoz") -> str:
    url = f"{BASE_URL}/busqueda?q={marca.lower()}"
    texto = pb.fetch_rendered_text(url, wait_ms=8000, wait_for_text="S/")
    if pb.parece_challenge_o_mantenimiento(texto):
        raise RuntimeError(f"{retailer_nombre}: sigue mostrando challenge/mantenimiento en {url}")
    return texto


def fetch_tienda_honor(retailer_nombre: str = "Juntoz") -> str:
    """Tienda de marca dedicada (honor.juntoz.com) -- ver nota del módulo.
    Ya viene filtrada a Honor, así que no hace falta pasarle una marca."""
    texto = pb.fetch_rendered_text(HONOR_STORE_URL, wait_ms=8000, wait_for_text="S/")
    if pb.parece_challenge_o_mantenimiento(texto):
        raise RuntimeError(f"{retailer_nombre}: sigue mostrando challenge/mantenimiento en {HONOR_STORE_URL}")
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
