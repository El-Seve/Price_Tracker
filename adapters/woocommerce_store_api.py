"""
Adaptador para tiendas WordPress + WooCommerce.

WooCommerce (desde la v8+) expone una API pública de solo lectura, la
"Store API", pensada para que el propio tema JS del carrito la consuma --
no requiere API key ni autenticación para listar productos:

    GET https://<tienda>/wp-json/wc/store/products?search=<marca>&per_page=50

Los precios vienen en centavos según `currency_minor_unit` (normalmente 2
para soles) -- hay que dividir entre 10**currency_minor_unit.

Confirmado en: Celivery Perú (celiveryperu.com).
"""
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


def fetch_products_by_brand(base_domain: str, marca: str, per_page: int = 50,
                             max_pages: int = 5, timeout: int = 20) -> list[dict]:
    """Busca productos por término de marca (la Store API no siempre trae un
    campo 'brand' separado, así que buscamos por texto igual que en su buscador)."""
    productos = []
    for page in range(1, max_pages + 1):
        url = f"{base_domain}/wp-json/wc/store/products"
        params = {"search": marca, "per_page": per_page, "page": page}
        r = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
        if r.status_code != 200:
            break
        data = r.json()
        if not data:
            break
        productos.extend(data)
        if len(data) < per_page:
            break
    return productos


def extract_rows(productos: list[dict], categoria: str, retailer: str, marca: str) -> list[dict]:
    rows = []
    seen_ids = set()
    for p in productos:
        pid = p.get("id")
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        prices = p.get("prices", {})
        minor_unit = prices.get("currency_minor_unit", 2)
        divisor = 10 ** minor_unit

        try:
            precio_oferta = float(prices.get("sale_price") or prices.get("price")) / divisor
            precio_regular = float(prices.get("regular_price") or prices.get("price")) / divisor
        except (TypeError, ValueError):
            continue

        if not precio_oferta or precio_oferta <= 0:
            continue
        if not precio_regular or precio_regular <= 0:
            precio_regular = precio_oferta

        rows.append({
            "retailer": retailer,
            "categoria": categoria,
            "marca": marca.upper(),
            "modelo": p.get("name", "").strip(),
            "precio_regular": precio_regular,
            "precio_oferta": precio_oferta,
            "vendedor": retailer,
            "vendedor_tercero": False,
            "url": p.get("permalink", ""),
        })
    return rows
