"""
Adaptador para tiendas Shopify.

Shopify expone el catálogo completo de cualquier colección pública como JSON
limpio agregando `/products.json` a la URL -- no hace falta ni simular
API ni leer HTML. Ejemplo:

    https://www.coversstoreperu.com/collections/celulares/products.json

Cada producto trae `vendor` (marca, casi siempre confiable en Shopify) y
`variants[].price`. Paginación vía `?page=N&limit=250`.

Confirmado en: iShop Perú (pe.tiendasishop.com), Mac Center Perú
(mac-center.com.pe), Covers Store Perú (coversstoreperu.com).
"""
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


def fetch_products(base_url: str, max_pages: int = 10, delay: float = 0.3) -> list[dict]:
    """base_url: dominio o colección, ej. 'https://mac-center.com.pe' o
    'https://www.coversstoreperu.com/collections/celulares'. Se le agrega
    /products.json automáticamente."""
    import time
    base_url = base_url.rstrip("/")
    productos = []
    for page in range(1, max_pages + 1):
        url = f"{base_url}/products.json?limit=250&page={page}"
        r = requests.get(url, headers=HEADERS, timeout=25)
        if r.status_code != 200:
            break
        data = r.json()
        page_products = data.get("products", [])
        if not page_products:
            break
        productos.extend(page_products)
        if len(page_products) < 250:
            break
        time.sleep(delay)
    return productos


def extract_rows(productos: list[dict], categoria: str, retailer: str,
                  target_brands: set[str] | None = None) -> list[dict]:
    rows = []
    for p in productos:
        vendor = (p.get("vendor") or "").upper().strip()
        title = (p.get("title") or "").strip()
        marca = vendor
        if target_brands:
            if vendor not in target_brands:
                # el vendor de Shopify a veces es el nombre de la tienda, no
                # la marca real -- probamos también matchear la marca dentro
                # del título antes de descartar.
                match = next((tb for tb in target_brands if tb in title.upper()), None)
                if not match:
                    continue
                marca = match
        if not marca:
            continue

        variants = p.get("variants", [])
        if not variants:
            continue
        precios = [float(v["price"]) for v in variants if v.get("price")]
        if not precios:
            continue
        precio_oferta = min(precios)
        compare_at = [float(v["compare_at_price"]) for v in variants if v.get("compare_at_price")]
        precio_regular = max(compare_at) if compare_at else precio_oferta

        handle = p.get("handle", "")
        rows.append({
            "retailer": retailer,
            "categoria": categoria,
            "marca": marca,
            "modelo": title,
            "precio_regular": precio_regular,
            "precio_oferta": precio_oferta,
            "vendedor": retailer,
            "vendedor_tercero": False,
            "url": f"/products/{handle}" if handle else "",
        })
    return rows
