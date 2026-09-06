"""
Adaptador genérico para sitios que exponen su catálogo vía JSON-LD estándar
(schema.org ItemList de Product + Offer) directamente en el HTML.

Caso confirmado: samsung.com/pe -- la página de categoría trae un
<script type="application/ld+json"> con @type "ItemList" cuyo
itemListElement[].item es un Product con offers.price ya en soles.

No sirve para Xiaomi (mi.com/pe) ni Huawei (huawei.com/pe): ninguno de los
dos expone este bloque en la home/categoría probada -- quedan pendientes.
"""
import json
import re
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

LDJSON_RE = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)


def fetch_category(url: str, timeout: int = 20) -> list[dict]:
    """Trae los Product embebidos en bloques ItemList JSON-LD de una página."""
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    productos = []
    for block in LDJSON_RE.findall(r.text):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "ItemList":
            for entry in data.get("itemListElement", []):
                item = entry.get("item") if isinstance(entry, dict) else None
                if isinstance(item, dict) and item.get("@type") == "Product":
                    productos.append(item)
    return productos


def extract_rows(productos: list[dict], categoria: str, retailer: str,
                  marca_fija: str, target_brands: set[str] | None = None) -> list[dict]:
    """marca_fija: en un sitio de marca (ej. Samsung Perú) todo el catálogo
    es de esa marca -- no viene un campo 'brand' confiable en el Product."""
    marca = marca_fija.upper()
    if target_brands and marca not in target_brands:
        return []

    rows = []
    for p in productos:
        modelo = p.get("name", "").strip()
        offer = p.get("offers", {})
        if isinstance(offer, list):
            offer = offer[0] if offer else {}
        precio = offer.get("price")
        try:
            precio = float(precio)
        except (TypeError, ValueError):
            continue
        if not modelo or precio <= 0:
            continue
        rows.append({
            "retailer": retailer,
            "categoria": categoria,
            "marca": marca,
            "modelo": modelo,
            "precio_regular": precio,
            "precio_oferta": precio,
            "vendedor": retailer,
            "vendedor_tercero": False,
            "url": p.get("url") or p.get("@id") or "",
        })
    return rows
