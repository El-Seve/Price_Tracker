"""
Adaptador para Entel Perú (miportal.entel.pe).

Plataforma: Oracle ATG / Endeca Commerce (no VTEX, no Next.js).
No hay API pública documentada ni JSON embebido en el HTML normal -- pero la
misma URL de categoría que ve un visitante devuelve JSON completo si se pide
con `Accept: application/json` en vez de HTML. Ahí viene el catálogo entero
de la categoría (no hay paginación real en las categorías probadas: `next`
sale None con todo el listado en un solo request).

Ejemplo:
    GET https://miportal.entel.pe/personas/catalogo/liberados
    Accept: application/json
    -> JSON con data["main"][1]["records"] = lista de productos

Cada producto trae, entre decenas de campos de planes/promos, los que nos
interesan: brand, displayName, referencePriceContadoRN (precio regular),
priceContadoRN (precio "de contado" / oferta), sku, productId.
"""
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}


def fetch_category(base_domain: str, category_path: str, timeout: int = 25) -> list[dict]:
    """Trae el catálogo completo de una categoría (ej. 'personas/catalogo/liberados')."""
    url = f"{base_domain}/{category_path}"
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    if "json" not in r.headers.get("content-type", ""):
        return []
    data = r.json()
    return _find_record_groups(data)


def _find_record_groups(obj) -> list[dict]:
    """Busca recursivamente el/los bloques 'records' con productos reales
    (los que traen 'attributes'), ignorando 'recommendedProducts' y otros
    carruseles que Endeca mete de relleno cuando no hay match exacto."""
    found = []
    if isinstance(obj, dict):
        recs = obj.get("records")
        if isinstance(recs, list) and recs and isinstance(recs[0], dict) and "attributes" in recs[0]:
            found.extend(recs)
        for v in obj.values():
            found.extend(_find_record_groups(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_find_record_groups(v))
    return found


def _first(attrs: dict, *keys, default=None):
    for k in keys:
        v = attrs.get(k)
        if v:
            return v[0]
    return default


def extract_rows(records: list[dict], categoria: str, retailer: str,
                  target_brands: set[str] | None = None) -> list[dict]:
    rows = []
    seen_ids = set()
    for rec in records:
        attrs = rec.get("attributes", {})
        marca = str(_first(attrs, "brand", "Brand", default="")).upper().strip()
        if not marca:
            continue
        if target_brands and marca not in target_brands:
            continue

        product_id = _first(attrs, "productId", default="")
        # Endeca repite el mismo producto en varios bloques (main + recommended);
        # evitamos duplicarlo dentro de esta misma corrida de categoría.
        dedupe_key = (product_id, _first(attrs, "sku"))
        if dedupe_key in seen_ids:
            continue
        seen_ids.add(dedupe_key)

        modelo = _first(attrs, "displayName", "sku.displayName", default="")
        if not modelo:
            continue

        precio_oferta = _first(attrs, "priceContadoRN", "priceContadoLN", "priceContadoMG", "listPrice")
        precio_regular = _first(attrs, "referencePriceContadoRN", "referencePriceContadoLN",
                                 "referencePriceContadoMG", default=precio_oferta)
        try:
            precio_oferta = float(precio_oferta) if precio_oferta not in (None, "") else None
        except (TypeError, ValueError):
            precio_oferta = None
        try:
            precio_regular = float(precio_regular) if precio_regular not in (None, "") else precio_oferta
        except (TypeError, ValueError):
            precio_regular = precio_oferta

        if precio_oferta is None or precio_oferta <= 0:
            continue
        if not precio_regular or precio_regular <= 0:
            precio_regular = precio_oferta

        rows.append({
            "retailer": retailer,
            "categoria": categoria,
            "marca": marca,
            "modelo": modelo,
            "precio_regular": precio_regular,
            "precio_oferta": precio_oferta,
            "vendedor": retailer,   # Entel vende todo directo, sin marketplace de terceros
            "vendedor_tercero": False,
            "url": f"https://miportal.entel.pe/personas/producto/equipos/{product_id}" if product_id else "",
        })
    return rows
