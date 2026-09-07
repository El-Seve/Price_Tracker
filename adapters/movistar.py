"""
Adaptador para Movistar (tienda.movistar.com.pe), protegido por Cloudflare
Managed Challenge Y con precios renderizados client-side (SPA vieja tipo
Angular, placeholders "{{...}}" visibles en el HTML crudo). Ver
adapters/playwright_browser.py para el contexto completo y qué tan
validado está esto (poco, todavía).

A diferencia de Ripley, acá SÍ hace falta esperar a que la app termine de
pintar los precios -- por eso fetch_category pide explícitamente esperar a
que aparezca el texto "S/" en la página antes de leerla.

Categorías confirmadas por marca (patrón .../celulares/<marca-en-minuscula>):
tienda.movistar.com.pe/celulares/honor, /celulares/samsung, etc.
"""
from . import playwright_browser as pb

BASE_URL = "https://tienda.movistar.com.pe"


def fetch_category(marca_slug: str, retailer_nombre: str = "Movistar") -> str:
    """marca_slug: p.ej. 'honor', 'samsung', 'xiaomi' -- Movistar organiza el
    catálogo de celulares por sub-URL de marca, no por una categoría general
    paginada como Ripley."""
    url = f"{BASE_URL}/celulares/{marca_slug}"
    texto = pb.fetch_rendered_text(url, wait_ms=8000, wait_for_text="S/")
    if pb.parece_challenge_o_mantenimiento(texto):
        raise RuntimeError(f"{retailer_nombre}: sigue mostrando challenge/mantenimiento en {url}")
    return texto


def extract_rows(textos_por_marca: dict[str, str], categoria: str, retailer: str,
                  target_brands: set[str]) -> list[dict]:
    """textos_por_marca: {marca_slug: texto_renderizado} -- una entrada por
    cada URL de marca que se haya consultado."""
    rows = []
    vistos = set()
    for texto in textos_por_marca.values():
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
                "url": "",
            })
    return rows
