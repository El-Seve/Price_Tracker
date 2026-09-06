#!/usr/bin/env python3
"""
Orquestador diario del tracker de precios Honor vs. competencia.

Uso:
    python run.py                 # corre todos los retailers de retailers.json
    python run.py --retailer PlazaVea
    python run.py --export-csv data/captura_hoy.csv

Qué hace:
  1. Lee retailers.json (qué retailers, qué plataforma, qué categorías/vendedores).
  2. Por cada retailer, llama al adaptador correspondiente (vtex / falabella_nextjs).
  3. Normaliza todo a filas {retailer, categoria, marca, modelo, precio_regular,
     precio_oferta, vendedor, vendedor_tercero, url}.
  4. Inserta en data/precios.db (SQLite), con fecha de hoy. INSERT OR IGNORE evita
     duplicar si se corre dos veces el mismo día.
  5. Imprime un resumen y, si hay una corrida anterior, qué precios de Honor
     cambiaron desde la última vez.

Para agregar un retailer nuevo: sumar su entrada en retailers.json. Si su
plataforma no es VTEX ni el Next.js de Falabella, hay que escribir un adaptador
nuevo en adapters/ (misma interfaz: fetch_algo() -> lista de dicts crudos,
extract_rows()/extract_all_offers() -> lista de filas normalizadas).
"""
import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import date

from adapters import (
    vtex, falabella_nextjs, entel_endeca, schema_jsonld,
    magento_html, shopify_json, woocommerce_store_api,
)
import db

CONFIG_PATH = Path(__file__).parent / "retailers.json"


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def run_vtex(retailer_cfg: dict, target_brands: set[str]) -> list[dict]:
    rows = []
    for categoria, path in retailer_cfg.get("categorias", {}).items():
        productos = vtex.fetch_category(retailer_cfg["base_domain"], path)
        rows += vtex.extract_all_offers(productos, categoria, retailer_cfg["nombre"], target_brands)
    return rows


def run_falabella_nextjs(retailer_cfg: dict, target_brands: set[str]) -> list[dict]:
    rows = []
    nombre = retailer_cfg["nombre"]
    vendedores_a_expandir = {}  # sellerName -> url de muestra (para descubrir el slug real)

    for categoria, url in retailer_cfg.get("categorias", {}).items():
        productos = falabella_nextjs.fetch_category(url)
        rows += falabella_nextjs.extract_rows(productos, categoria, nombre, target_brands)
        # Descubrimiento automático: cualquier vendedor (marketplace) que aparezca
        # vendiendo alguna de las marcas objetivo se agrega a la lista a expandir.
        # Esto reemplaza la lista manual 'vendedores_honor_conocidos' -- ya no
        # depende de que alguien adivine/confirme un slug a mano (ver bug de
        # Sany Distribuidor Autorizado, que quedó con un slug inventado y nunca
        # trajo nada). La categoría sola no siempre trae TODO lo que un
        # vendedor tiene publicado (paginación, orden por relevancia), por eso
        # igual vale la pena bajar su catálogo completo aparte.
        nuevos = falabella_nextjs.discover_sellers(productos, target_brands, exclude_names={nombre})
        vendedores_a_expandir.update(nuevos)

    # Vendedores manuales opcionales (fallback/override): por si algún vendedor
    # no aparece en la muestra de esta corrida puntual, o su página de producto
    # no revela el slug real vía discover_seller_slug.
    for slug in retailer_cfg.get("vendedores_honor_conocidos", []):
        productos = falabella_nextjs.fetch_seller(retailer_cfg["base_domain"], slug)
        rows += falabella_nextjs.extract_rows(productos, "Smartphones (vendedor)", nombre, target_brands)

    # El descubrimiento automático puede encontrar 50-100+ vendedores por
    # categoría (Falabella es un marketplace grande) -- expandirlos uno por
    # uno tomaría demasiado (~5s cada uno = 7-8 min solo por Falabella). Como
    # cada vendedor es un request de red independiente, paralelizamos con un
    # puñado de workers -- no tantos como para forzar el servidor, suficientes
    # para que la corrida diaria termine en minutos y no en media hora.
    def _expandir_vendedor(item):
        seller_name, sample_url = item
        slug = falabella_nextjs.discover_seller_slug(sample_url)
        if not slug:
            return []
        productos = falabella_nextjs.fetch_seller(retailer_cfg["base_domain"], slug)
        return falabella_nextjs.extract_rows(productos, "Smartphones (vendedor)", nombre, target_brands)

    if vendedores_a_expandir:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_expandir_vendedor, item) for item in vendedores_a_expandir.items()]
            for fut in as_completed(futures):
                rows += fut.result()

    return rows


def run_entel_endeca(retailer_cfg: dict, target_brands: set[str]) -> list[dict]:
    rows = []
    for categoria, path in retailer_cfg.get("categorias", {}).items():
        productos = entel_endeca.fetch_category(retailer_cfg["base_domain"], path)
        rows += entel_endeca.extract_rows(productos, categoria, retailer_cfg["nombre"], target_brands)
    return rows


def run_schema_jsonld(retailer_cfg: dict, target_brands: set[str]) -> list[dict]:
    rows = []
    marca_fija = retailer_cfg.get("marca_fija", retailer_cfg["nombre"])
    for categoria, url in retailer_cfg.get("categorias", {}).items():
        productos = schema_jsonld.fetch_category(url)
        rows += schema_jsonld.extract_rows(productos, categoria, retailer_cfg["nombre"], marca_fija, target_brands)
    return rows


def run_magento_html(retailer_cfg: dict, target_brands: set[str]) -> list[dict]:
    rows = []
    for categoria, url in retailer_cfg.get("categorias", {}).items():
        blocks = magento_html.fetch_category(url)
        rows += magento_html.extract_rows(blocks, categoria, retailer_cfg["nombre"], target_brands)
    return rows


def run_shopify_json(retailer_cfg: dict, target_brands: set[str]) -> list[dict]:
    rows = []
    for categoria, url in retailer_cfg.get("categorias", {}).items():
        productos = shopify_json.fetch_products(url)
        rows += shopify_json.extract_rows(productos, categoria, retailer_cfg["nombre"], target_brands)
    return rows


def run_woocommerce_store_api(retailer_cfg: dict, target_brands: set[str]) -> list[dict]:
    rows = []
    for marca in target_brands:
        productos = woocommerce_store_api.fetch_products_by_brand(retailer_cfg["base_domain"], marca)
        rows += woocommerce_store_api.extract_rows(productos, "Smartphones", retailer_cfg["nombre"], marca)
    return rows


ADAPTERS = {
    "vtex": run_vtex,
    "falabella_nextjs": run_falabella_nextjs,
    "entel_endeca": run_entel_endeca,
    "schema_jsonld": run_schema_jsonld,
    "magento_html": run_magento_html,
    "shopify_json": run_shopify_json,
    "woocommerce_store_api": run_woocommerce_store_api,
}


def dedupe(rows: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for r in rows:
        key = (r["retailer"], r["marca"], r["modelo"], r["vendedor"], r["precio_oferta"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--retailer", help="Correr solo un retailer por nombre (ej. PlazaVea)")
    parser.add_argument("--export-csv", help="Además de SQLite, exportar la captura de hoy a este CSV")
    args = parser.parse_args()

    config = load_config()
    target_brands = set(config["target_brands"])

    all_rows = []
    for retailer_cfg in config["retailers"]:
        if args.retailer and retailer_cfg["nombre"] != args.retailer:
            continue
        plataforma = retailer_cfg["plataforma"]
        fn = ADAPTERS.get(plataforma)
        if not fn:
            print(f"[!] {retailer_cfg['nombre']}: plataforma '{plataforma}' sin adaptador, saltando.", file=sys.stderr)
            continue
        print(f"-> {retailer_cfg['nombre']} ({plataforma})...")
        try:
            rows = fn(retailer_cfg, target_brands)
        except Exception as e:
            print(f"[!] {retailer_cfg['nombre']} falló: {e}", file=sys.stderr)
            continue
        print(f"   {len(rows)} filas capturadas")
        all_rows += rows

    all_rows = dedupe(all_rows)
    print(f"\nTotal filas (todas las marcas, deduplicado): {len(all_rows)}")

    conn = db.get_connection()
    inserted = db.insert_rows(conn, all_rows)
    print(f"Filas nuevas insertadas en {db.DB_PATH.name}: {inserted}")

    cambios = db.price_changes_since_last_run(conn, marca="HONOR")
    if cambios:
        print("\nCambios de precio HONOR desde la corrida anterior:")
        for retailer, modelo, vendedor, antes, ahora in cambios:
            flecha = "bajó" if ahora < antes else "subió"
            print(f"  [{retailer}] {modelo} ({vendedor}): S/{antes} -> S/{ahora} ({flecha})")
    else:
        print("\nSin corrida anterior para comparar, o sin cambios en HONOR.")

    if args.export_csv:
        honor_rows = [r for r in all_rows if r["marca"] == "HONOR"]
        with open(args.export_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["retailer", "categoria", "marca", "modelo",
                                                     "precio_regular", "precio_oferta",
                                                     "vendedor", "vendedor_tercero", "url"])
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\nExportado a {args.export_csv} ({len(all_rows)} filas, {len(honor_rows)} de Honor)")

    conn.close()


if __name__ == "__main__":
    main()
