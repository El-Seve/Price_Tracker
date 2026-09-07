"""
Adaptador para HONOR Perú, tienda oficial (honor.com/pe).

El HTML de categoría usa plantillas Handlebars sin resolver
(p.ej. {{colorObj.lastPrdPackagePrice}}) -- el precio se rellena por
JS/AJAX después de cargar la página. Encontrado el endpoint real que llama
el propio JS del sitio (función ecCom.ajaxReq dentro de base.min.js): un
POST a la API de "selfservice" de Honor, mandando los productIds sacados
del atributo data-ec-product-id de cada tarjeta de producto en la página
de categoría. No requiere cookies ni token -- responde igual sin sesión.
"""
import re
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

_PRODUCT_ID_RE = re.compile(r'data-ec-product-id="(\d+)"')

_PRICE_API_URL = ("https://selfservice-sg.hihonor.com/ccpcmd/services/dispatch/secured/"
                   "CCPC/EN/eCommerce/queryPrdInfoByOfficial/1000")


def fetch_category(category_url: str, timeout: int = 20) -> list[dict]:
    """Descubre los productIds en la página de categoría y consulta sus
    precios reales en un solo POST. Devuelve la lista cruda
    officialPrdDisplayInfos de la respuesta (puede traer entradas sin
    cheapestSku para series/tablets sin SKU vendible -- se filtran en
    extract_rows)."""
    r = requests.get(category_url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    product_ids = sorted(set(_PRODUCT_ID_RE.findall(r.text)))
    if not product_ids:
        return []

    resp = requests.post(
        _PRICE_API_URL,
        json={"productIds": product_ids, "siteCode": "PE", "loginFrom": "1"},
        headers={
            **HEADERS,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://www.honor.com",
            "Referer": category_url,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return (data.get("data") or {}).get("officialPrdDisplayInfos") or []


def extract_rows(productos: list[dict], categoria: str, retailer: str) -> list[dict]:
    """Todo el catálogo de honor.com/pe es HONOR -- no hace falta filtrar
    por marca ni target_brands, siempre es la marca del propio tracker."""
    rows = []
    for item in productos:
        sku = item.get("cheapestSku") or {}
        precio_oferta = sku.get("unitPrice")
        precio_regular = sku.get("orderPrice") or precio_oferta
        modelo = item.get("briefName") or item.get("productName")
        try:
            precio_oferta = float(precio_oferta)
        except (TypeError, ValueError):
            continue
        if not modelo or precio_oferta <= 0:
            continue
        try:
            precio_regular = float(precio_regular)
        except (TypeError, ValueError):
            precio_regular = precio_oferta
        rows.append({
            "retailer": retailer,
            "categoria": categoria,
            "marca": "HONOR",
            "modelo": modelo,
            "precio_regular": precio_regular,
            "precio_oferta": precio_oferta,
            "vendedor": retailer,
            "vendedor_tercero": False,
            "url": item.get("url") or "",
        })
    return rows
