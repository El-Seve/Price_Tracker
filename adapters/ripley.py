"""
Adaptador para Ripley (simple.ripley.com.pe), protegido por Cloudflare
Turnstile ("Just a moment..."). Ver adapters/playwright_browser.py para el
contexto completo de por qué esto necesita un browser real y qué tan
validado está (poco, todavía -- probar en vivo antes de confiar en el cron).

A diferencia de Movistar, el catálogo de Ripley es HTML renderizado en
servidor (confirmado: no hay JSON embebido) -- una vez que Playwright pasa
el challenge, no debería hacer falta esperar mucho más JS.
"""
from . import playwright_browser as pb

BASE_URL = "https://simple.ripley.com.pe"


def fetch_category(category_path: str, max_pages: int = 5, retailer_nombre: str = "Ripley") -> list[str]:
    """Renderiza hasta `max_pages` páginas de una categoría y devuelve el
    texto visible de cada una (una entrada por página). Ripley pagina con
    ?page=N -- si la categoría ya trae otros query params, se agregan con &."""
    separador = "&" if "?" in category_path else "?"
    textos = []
    for pagina in range(1, max_pages + 1):
        url = f"{BASE_URL}{category_path}{separador}page={pagina}"
        # wait_ms=5000 se quedaba corto: el challenge de Cloudflare solo ya
        # consume varios segundos, y la grilla de productos carga después --
        # con 5s se leía la página "vacía" (sin marcas ni precios) y no se
        # capturaba nada, sin ningún error (confirmado con Seve: 0 filas, sin
        # avisos). wait_for_text="S/" fuerza a esperar a que exista al menos
        # un precio real en pantalla antes de leer el texto, en vez de
        # confiar en un tiempo fijo.
        texto = pb.fetch_rendered_text(url, wait_ms=8000, wait_for_text="S/")
        if pb.parece_challenge_o_mantenimiento(texto):
            raise RuntimeError(f"{retailer_nombre}: sigue mostrando el challenge de Cloudflare en {url}")
        if "no se encontraron" in texto.lower() or "0 resultados" in texto.lower():
            break
        textos.append(texto)
    return textos


def extract_rows(textos: list[str], categoria: str, retailer: str, target_brands: set[str]) -> list[dict]:
    rows = []
    vistos = set()
    for texto in textos:
        for oferta in pb.extraer_ofertas_por_patron(texto, target_brands):
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
                "url": "",  # el parseo por texto no captura el link -- pendiente si hace falta
            })
    return rows
