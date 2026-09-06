"""
Adaptador para retailers que corren sobre VTEX (PlazaVea, Promart, Oechsle, ...).

Usa la API pública de catálogo de VTEX (`/api/catalog_system/pub/products/search/...`),
sin autenticación y sin bloqueo anti-bot. Devuelve TODAS las ofertas (vendedores) de
cada producto, no solo la primera -- en VTEX, cuando el producto lo vende un tercero,
el arreglo `sellers` igual trae un registro placeholder del retailer (Price=0,
IsAvailable=false) delante del vendedor real, así que hay que recorrer todas las
ofertas y quedarse solo con las que tengan Price > 0 e IsAvailable = true.

VTEX limita la paginación por offset a ~2550 resultados por categoría (_from/_to);
más allá de eso responde 400. Para categorías más grandes, filtrar por marca
(fq=B:<marca>) reduce el universo y evita ese techo.
"""
import time
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

PAGE_SIZE = 50
VTEX_OFFSET_CAP = 2550


def fetch_category(base_domain: str, category_path: str, max_items: int = VTEX_OFFSET_CAP, delay: float = 0.25):
    """
    base_domain: p.ej. "https://www.plazavea.com.pe"
    category_path: p.ej. "tecnologia/telefonia/celulares-y-smartphones" (sin slashes al inicio/final)
    """
    url_base = f"{base_domain}/api/catalog_system/pub/products/search/{category_path}"
    return _paginate(url_base, max_items, delay)


def fetch_seller(base_domain: str, seller_id: str, max_items: int = VTEX_OFFSET_CAP, delay: float = 0.25):
    """Catálogo completo de un vendedor específico dentro del marketplace VTEX."""
    url_base = f"{base_domain}/api/catalog_system/pub/products/search"
    params_suffix = f"&fq=seller:{seller_id}"
    return _paginate(url_base, max_items, delay, extra=params_suffix)


def _paginate(url_base: str, max_items: int, delay: float, extra: str = ""):
    all_items = []
    start = 0
    while start < max_items:
        end = start + PAGE_SIZE - 1
        url = f"{url_base}?map=c,c,c&_from={start}&_to={end}{extra}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
        except requests.RequestException:
            break
        if r.status_code == 400:
            break  # tope de paginación de VTEX
        if r.status_code not in (200, 206):
            break
        try:
            batch = r.json()
        except ValueError:
            break
        if not batch:
            break
        all_items.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        start += PAGE_SIZE
        time.sleep(delay)
    return all_items


def pick_seller_offer(sellers):
    """Del arreglo de vendedores de un item, elige la oferta real (disponible y con precio)."""
    available = [s for s in sellers if s["commertialOffer"].get("IsAvailable") and s["commertialOffer"].get("Price", 0) > 0]
    if available:
        return available[0]
    with_price = [s for s in sellers if s["commertialOffer"].get("Price", 0) > 0]
    if with_price:
        return with_price[0]
    return sellers[0] if sellers else None


def extract_all_offers(products, categoria: str, retailer: str, target_brands: set[str] | None = None):
    """
    Convierte la respuesta cruda de VTEX en filas normalizadas, UNA POR CADA
    vendedor real (no solo la primera oferta) -- así se capturan todos los
    marketplace sellers de un mismo producto, como en el caso SanyPeru.
    """
    rows = []
    for p in products:
        brand = (p.get("brand") or "").upper()
        if target_brands and brand not in target_brands:
            continue
        for item in p.get("items", []):
            for seller in item.get("sellers", []):
                offer = seller.get("commertialOffer", {})
                price = offer.get("Price")
                if not price or price <= 0 or not offer.get("IsAvailable"):
                    continue
                seller_name = seller.get("sellerName")
                rows.append({
                    "retailer": retailer,
                    "categoria": categoria,
                    "marca": brand,
                    "modelo": item.get("name"),
                    "precio_regular": offer.get("ListPrice"),
                    "precio_oferta": price,
                    "vendedor": seller_name,
                    "vendedor_tercero": seller_name != retailer,
                    "url": p.get("link"),
                })
    return rows
