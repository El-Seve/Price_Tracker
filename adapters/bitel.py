"""
Adaptador para Bitel (tienda.bitel.com.pe).

Estado (14/09/2026): NO VALIDADO EN VIVO todavía -- este sandbox no pudo
siquiera llegar al sitio (net::ERR_CONNECTION_RESET con Playwright,
consistente con el bloqueo de reputación de IP que ya estaba documentado
en retailers.json/no_soportados). Como Ripley y Movistar en su momento,
esto necesita probarse desde una IP "normal" (la de Seve, o el runner de
GitHub Actions) con:

    python run.py --retailer Bitel

y revisar con debug_playwright_dump.py si el texto capturado no calza con
el patrón esperado (marca en mayúscula + precio "S/" debajo).

La ruta de categoría en retailers.json (categorias.Smartphones) es una
suposición razonable, NO confirmada -- si al probar en vivo la página no
es esa, hay que corregirla ahí (no hace falta tocar este archivo, solo el
config). Este adaptador además tiene el respaldo por LLM
(extraer_ofertas_con_fallback) para el caso en que el parseo por patrón no
encuentre nada por diferencias de formato -- ver playwright_browser.py.
"""
from . import playwright_browser as pb

BASE_URL = "https://tienda.bitel.com.pe"


def fetch_category(category_path: str, max_pages: int = 3, retailer_nombre: str = "Bitel") -> list[str]:
    """Renderiza hasta `max_pages` páginas de una categoría y devuelve el
    texto visible de cada una. Paginación por ?page=N -- ajustar si Bitel
    usa otro esquema (revisar en vivo)."""
    separador = "&" if "?" in category_path else "?"
    textos = []
    for pagina in range(1, max_pages + 1):
        url = f"{BASE_URL}{category_path}{separador}page={pagina}"
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
