"""
Adaptador para retailers que corren sobre la plataforma Next.js de Grupo Falabella
(Falabella.com, Sodimac.com.pe -- comparten el mismo esqueleto __NEXT_DATA__).

No hay API pública documentada: los productos vienen embebidos como JSON dentro
del HTML de la página de categoría/vendedor (bloque <script id="__NEXT_DATA__">),
server-side-rendered. Es gratis y no requiere JS, pero es más frágil que una API
real -- si Falabella cambia la estructura de su frontend, esto puede romperse
(a diferencia del adaptador VTEX, que usa una API pública estable).

Dos fuentes de productos:
  - fetch_category(): pagina una categoría completa (?page=N)
  - fetch_seller(): pagina el catálogo COMPLETO de un vendedor específico
    (necesario porque el listado de categoría no siempre trae todo lo que
    un vendedor tiene publicado -- ver README, sección "Por qué por vendedor").

El slug del vendedor en la URL /seller/<slug> NO es simplemente el sellerName
con espacios reemplazados por %20 -- suele venir en minúsculas y puede diferir
bastante (ej. sellerName "Millennials" -> slug real "millennials", pero no
siempre es solo un .lower()). Usar discover_seller_slug() para obtenerlo del
campo real embebido en la página de producto antes de armar la URL del vendedor.
"""
import re
import time
import json
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL)
SELLER_LINK_RE = re.compile(r'href="https://[^"]+/seller/([^"?]+)"')


def _get_next_data(url: str):
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return None
    m = NEXT_DATA_RE.search(r.text)
    if not m:
        return None
    return json.loads(m.group(1))


def fetch_category(category_url: str, max_pages: int = 15, delay: float = 0.3):
    """category_url: URL completa de la categoría, SIN query params de paginación."""
    return _paginate(category_url, max_pages, delay)


def fetch_seller(base_domain: str, seller_slug: str, max_pages: int = 15, delay: float = 0.3):
    """seller_slug: el slug real tal como aparece en /seller/<slug> (ver discover_seller_slug)."""
    url = f"{base_domain}/{_site_path(base_domain)}/seller/{seller_slug}"
    return _paginate(url, max_pages, delay)


def discover_sellers(products: list, target_brands: set[str] | None = None,
                      exclude_names: set[str] | None = None) -> dict:
    """Recorre productos ya traídos (de fetch_category) y devuelve
    {sellerName: url_de_muestra} para cada vendedor único que vende alguna
    de las target_brands -- sin necesidad de conocerlos de antemano.

    exclude_names: nombres a excluir (típicamente el propio retailer, ej.
    'Falabella'/'Sodimac'/'Tottus' -- ese vendedor ya está cubierto por
    fetch_category, no hace falta bajar su "catálogo de vendedor" aparte).
    """
    exclude_upper = {n.upper() for n in (exclude_names or [])}
    sellers = {}
    for p in products:
        brand = (p.get("brand") or "").upper()
        if target_brands and brand not in target_brands:
            continue
        seller_name = p.get("sellerName")
        if not seller_name or seller_name.upper() in exclude_upper:
            continue
        if seller_name not in sellers:
            sellers[seller_name] = p.get("url")
    return sellers


def discover_seller_slug(product_url: str) -> str | None:
    """
    Dado un URL de producto, busca el link real 'Vendido por' en el HTML y devuelve
    el slug de vendedor tal como lo usa el sitio (evita adivinar mayúsculas/espacios).
    """
    r = requests.get(product_url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return None
    m = SELLER_LINK_RE.search(r.text)
    return m.group(1) if m else None


def _site_path(base_domain: str) -> str:
    # falabella-pe, sodimac-pe, etc. -- coincide con el primer segmento de ruta del sitio.
    if "sodimac" in base_domain:
        return "sodimac-pe"
    return "falabella-pe"


def _paginate(url: str, max_pages: int, delay: float):
    all_results = []
    for page in range(1, max_pages + 1):
        data = _get_next_data(f"{url}?page={page}")
        if not data:
            break
        pp = data.get("props", {}).get("pageProps", {})
        results = pp.get("results", [])
        if not results:
            break
        all_results.extend(results)
        pag = pp.get("pagination", {})
        total, per_page = pag.get("count", 0), pag.get("totalPerPage", 48)
        if page * per_page >= total:
            break
        time.sleep(delay)
    return all_results


def _get_price(prices: list, price_type: str):
    for p in prices:
        if p.get("type") == price_type:
            val = (p.get("price") or [None])[0]
            if val:
                return float(str(val).replace(",", ""))
    return None


def extract_rows(products: list, categoria: str, retailer: str, target_brands: set[str] | None = None):
    rows = []
    for p in products:
        brand = (p.get("brand") or "").upper()
        if target_brands and brand not in target_brands:
            continue
        prices = p.get("prices", [])
        oferta = _get_price(prices, "internetPrice") or _get_price(prices, "cmrPrice")
        regular = _get_price(prices, "normalPrice") or oferta
        if not oferta:
            continue
        seller_name = p.get("sellerName") or retailer
        rows.append({
            "retailer": retailer,
            "categoria": categoria,
            "marca": brand,
            "modelo": p.get("displayName"),
            "precio_regular": regular,
            "precio_oferta": oferta,
            "vendedor": seller_name,
            "vendedor_tercero": seller_name.lower() != retailer.lower(),
            "url": p.get("url"),
        })
    return rows
