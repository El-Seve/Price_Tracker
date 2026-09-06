"""
Adaptador para tiendas Magento peruanas que renderizan el listado de
categoría/marca del lado del servidor (sin JS, sin API que simular).

Confirmado en: Hiraoka, La Curacao, Tiendas EFE. Las tres usan el mismo
theme/plantilla de listado (probablemente la misma agencia/plataforma detrás),
así que un solo adaptador les sirve a las tres.

A diferencia de VTEX (que trae `brand` como campo), acá el nombre de marca no
viene separado -- hay que matchear la marca dentro del nombre del producto.
También es un marketplace: cada tarjeta de producto trae "Por <vendedor>"
(label-sold-by), así que si un tercero vende ahí, se captura igual que en
Falabella.

Paginación: `?p=2`, `?p=3`, ... hasta que una página no traiga productos
nuevos.
"""
import re
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

PRODUCT_BLOCK_RE = re.compile(r'product-item-name.*?</div>\s*</li>', re.DOTALL)
NAME_RE = re.compile(r'product-item-link"\s*\r?\n?\s*href="([^"]+)"[^>]*>\s*([^<]+?)\s*</a>')
SOLD_BY_RE = re.compile(r'label-sold-by">\s*<span>Por\s*</span>\s*<span>([^<]+)</span>', re.DOTALL)
SPECIAL_PRICE_RE = re.compile(r'special-price.*?data-price-amount="([\d.]+)"', re.DOTALL)
OLD_PRICE_RE = re.compile(r'old-price.*?data-price-amount="([\d.]+)"', re.DOTALL)
FINAL_PRICE_RE = re.compile(r'data-price-amount="([\d.]+)"\s*\r?\n?\s*data-price-type="finalPrice"')


def fetch_category(url: str, max_pages: int = 10, delay: float = 0.3) -> list[str]:
    """Trae los bloques HTML crudos de producto de todas las páginas de una
    categoría/marca (ej. la página '.../curacao/honor.html')."""
    import time
    blocks = []
    seen_names = set()
    for page in range(1, max_pages + 1):
        sep = "&" if "?" in url else "?"
        page_url = url if page == 1 else f"{url}{sep}p={page}"
        r = requests.get(page_url, headers=HEADERS, timeout=25)
        if r.status_code != 200:
            break
        page_blocks = PRODUCT_BLOCK_RE.findall(r.text)
        if not page_blocks:
            break
        new_this_page = 0
        for b in page_blocks:
            m = NAME_RE.search(b)
            key = m.group(1) if m else b[:80]
            if key in seen_names:
                continue
            seen_names.add(key)
            blocks.append(b)
            new_this_page += 1
        if new_this_page == 0:
            break
        time.sleep(delay)
    return blocks


def extract_rows(blocks: list[str], categoria: str, retailer: str,
                  target_brands: set[str] | None = None) -> list[dict]:
    rows = []
    for b in blocks:
        m = NAME_RE.search(b)
        if not m:
            continue
        url, nombre = m.group(1), m.group(2).strip()
        nombre_upper = nombre.upper()

        marca = None
        if target_brands:
            for tb in target_brands:
                if tb in nombre_upper:
                    marca = tb
                    break
            if marca is None:
                continue
        else:
            marca = nombre_upper.split()[0]

        special = SPECIAL_PRICE_RE.search(b)
        old = OLD_PRICE_RE.search(b)
        final = FINAL_PRICE_RE.search(b)

        if special:
            precio_oferta = float(special.group(1))
            precio_regular = float(old.group(1)) if old else precio_oferta
        elif final:
            precio_oferta = float(final.group(1))
            precio_regular = precio_oferta
        else:
            continue

        sold_by = SOLD_BY_RE.search(b)
        vendedor = sold_by.group(1).strip() if sold_by else retailer
        vendedor_tercero = bool(sold_by) and vendedor.upper() != retailer.upper()

        rows.append({
            "retailer": retailer,
            "categoria": categoria,
            "marca": marca,
            "modelo": nombre,
            "precio_regular": precio_regular,
            "precio_oferta": precio_oferta,
            "vendedor": vendedor,
            "vendedor_tercero": vendedor_tercero,
            "url": url,
        })
    return rows
