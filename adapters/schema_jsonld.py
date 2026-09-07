"""
Adaptador genérico para sitios que exponen su catálogo vía JSON-LD estándar
(schema.org ItemList de Product + Offer) directamente en el HTML.

Casos confirmados:
- Samsung Perú (samsung.com/pe/smartphones/all-smartphones/): ItemList de
  Product con offers.price en soles. Bloqueado por Akamai después de 2-3
  requests con una conexión nueva por request -- se resuelve reutilizando
  una sola sesión (ver fetch_category_cffi, requiere `curl_cffi`).
- Xiaomi Perú (mi.com/pe/v2/product-list/phone): mismo formato ItemList, sin
  ningún bloqueo. OJO: esa página lista Xiaomi + Redmi + Poco mezclados bajo
  el mismo catálogo -- extract_rows detecta la sub-marca real por la primera
  palabra del nombre en vez de forzar "XIAOMI" a todo.

Huawei (huawei.com/pe) usa un formato JSON-LD distinto (productGroup con
variantes anidadas, no ItemList) -- ver fetch_product_groups_from_sitemap /
extract_rows_product_group más abajo, específico para ese caso.
"""
import json
import re
import time
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

LDJSON_RE = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)

# Sub-marcas que pueden aparecer mezcladas en un catálogo de "marca_fija"
# (caso Xiaomi Perú, que vende Xiaomi/Redmi/Poco bajo el mismo listado) --
# se detectan por la primera palabra del nombre para no mal-etiquetar un
# Redmi o Poco como "XIAOMI" en la comparación de precio.
_SUBMARCAS_CONOCIDAS = {"XIAOMI", "REDMI", "POCO"}


def _parse_itemlist(html: str) -> list[dict]:
    """Extrae los Product embebidos en bloques ItemList JSON-LD de un HTML."""
    productos = []
    for block in LDJSON_RE.findall(html):
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


def fetch_category(url: str, timeout: int = 20) -> list[dict]:
    """Trae los Product de una página sin bloqueo anti-bot (ej. Xiaomi)."""
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return _parse_itemlist(r.text)


def fetch_category_cffi(url: str, session=None, timeout: int = 20) -> list[dict]:
    """Igual que fetch_category, pero usando curl_cffi con una sesión TCP/TLS
    reutilizada (impersonando un navegador real) -- necesario para Samsung
    Perú, donde Akamai bloquea con 403 apenas detecta una conexión nueva por
    cada request (no es un límite de volumen, es huella de conexión). Pasar
    la MISMA `session` entre llamadas si se consultan varias categorías del
    mismo sitio en una corrida, en vez de crear una por request.

    OJO: en pruebas reales, el PRIMER request de una sesión recién creada a
    veces sale con 403 y el segundo ya funciona (parece que Akamai tarda un
    request en "aceptar" la sesión) -- por eso reintenta una vez antes de
    darse por vencido.

    Requiere `pip install curl_cffi`. Si no está instalado, lanza
    ImportError -- quien llama decide cómo avisar/saltar ese retailer."""
    from curl_cffi import requests as cffi_requests
    sess = session or cffi_requests.Session(impersonate="edge101")
    ultimo_error = None
    for intento, espera in enumerate((0, 2, 5)):
        if espera:
            time.sleep(espera)
        try:
            r = sess.get(url, timeout=timeout)
            r.raise_for_status()
            return _parse_itemlist(r.text)
        except Exception as e:
            ultimo_error = e
    raise ultimo_error


def extract_rows(productos: list[dict], categoria: str, retailer: str,
                  marca_fija: str, target_brands: set[str] | None = None) -> list[dict]:
    """marca_fija: en un sitio de marca (ej. Samsung Perú) todo el catálogo
    es de esa marca -- no viene un campo 'brand' confiable en el Product.
    Si el nombre del producto empieza con una sub-marca conocida (Redmi,
    Poco dentro del catálogo de Xiaomi), se usa esa en vez de marca_fija."""
    rows = []
    for p in productos:
        modelo = p.get("name", "").strip()
        if not modelo:
            continue
        primera_palabra = modelo.upper().split()[0]
        marca = primera_palabra if primera_palabra in _SUBMARCAS_CONOCIDAS else marca_fija.upper()
        if target_brands and marca not in target_brands:
            continue
        offer = p.get("offers", {})
        if isinstance(offer, list):
            offer = offer[0] if offer else {}
        precio = offer.get("price")
        try:
            precio = float(precio)
        except (TypeError, ValueError):
            continue
        if precio <= 0:
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


def fetch_product_groups_from_sitemap(sitemap_url: str, url_pattern: str,
                                       timeout: int = 20, delay: float = 0.3) -> list[dict]:
    """Caso Huawei: la categoría general no trae nada (ItemList vacío), pero
    cada página de producto individual sí trae un bloque JSON-LD tipo
    "productGroup" con las variantes (hasVariant) y sus ofertas. El sitemap
    público lista todas esas páginas sin necesidad de adivinar URLs a mano
    ni usar un browser."""
    r = requests.get(sitemap_url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    urls = sorted(set(re.findall(url_pattern, r.text)))
    productos = []
    for url in urls:
        try:
            rp = requests.get(url, headers=HEADERS, timeout=timeout)
        except requests.RequestException:
            continue
        if rp.status_code != 200:
            continue
        for block in LDJSON_RE.findall(rp.text):
            try:
                data = json.loads(block)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and str(data.get("@type", "")).lower() == "productgroup":
                productos.append(data)
        time.sleep(delay)
    return productos


def extract_rows_product_group(productos: list[dict], categoria: str, retailer: str,
                                marca_fija: str, target_brands: set[str] | None = None) -> list[dict]:
    """Recorre el formato anidado productGroup -> hasVariant[] -> offers[]
    (Huawei), una fila por SKU/oferta. Si el offer trae priceSpecification
    con priceType "StrikethroughPrice", ese es el precio regular (tachado);
    si no, precio_regular = precio_oferta (no había descuento ese día)."""
    marca = marca_fija.upper()
    if target_brands and marca not in target_brands:
        return []

    rows = []
    for group in productos:
        base_name = group.get("name", "").strip()
        base_url = group.get("url", "")
        for variant in group.get("hasVariant", []):
            modelo = (variant.get("name") or base_name).strip()
            if not modelo:
                continue
            for offer in variant.get("offers", []):
                precio = offer.get("price")
                try:
                    precio = float(precio)
                except (TypeError, ValueError):
                    continue
                if precio <= 0:
                    continue
                sku = offer.get("sku")
                modelo_sku = f"{modelo} {sku}" if sku else modelo
                precio_regular = precio
                spec = offer.get("priceSpecification")
                if isinstance(spec, dict) and str(spec.get("priceType", "")).endswith("StrikethroughPrice"):
                    try:
                        precio_regular = float(spec.get("price"))
                    except (TypeError, ValueError):
                        precio_regular = precio
                rows.append({
                    "retailer": retailer,
                    "categoria": categoria,
                    "marca": marca,
                    "modelo": modelo_sku,
                    "precio_regular": precio_regular,
                    "precio_oferta": precio,
                    "vendedor": retailer,
                    "vendedor_tercero": False,
                    "url": offer.get("url") or variant.get("url") or base_url,
                })
    return rows
