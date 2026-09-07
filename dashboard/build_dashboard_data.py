#!/usr/bin/env python3
"""
Genera docs/dashboard_data.json a partir de data/precios.db.

Este es el paso que conecta la captura diaria (run.py) con el dashboard
estático (docs/index.html, publicado por GitHub Pages). Se corre después de
run.py, y su salida es el único archivo que el dashboard lee -- no hay
backend, todo el cálculo de KPIs/oportunidades pasa aquí, una vez al día.

Uso:
    python -m dashboard.build_dashboard_data
    python -m dashboard.build_dashboard_data --out docs/dashboard_data.json
"""
import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path

from dashboard.normalize import (
    modelo_a_familia, es_producto_valido, segmento_de_precio,
    es_texto_barcode, es_accesorio_por_nombre, PRECIO_MINIMO_CELULAR, _sin_acentos,
)
import db

ROOT = Path(__file__).parent.parent
DEFAULT_OUT = ROOT / "docs" / "dashboard_data.json"
RETAILERS_CONFIG = ROOT / "retailers.json"

# Umbral a partir del cual una dispersión de precio del mismo SKU Honor se
# marca como oportunidad accionable (no toda dispersión de 2-3% amerita una
# alerta -- eso es ruido normal de redondeo/promos puntuales).
UMBRAL_DISPERSION_PCT = 12.0

# Umbral para marcar una brecha Honor-vs-competencia-más-barata-del-segmento
# como oportunidad de precio (a favor o en contra de Honor).
UMBRAL_GAP_SEGMENTO_PCT = 10.0


def _fecha_mas_reciente(conn) -> str | None:
    row = conn.execute("SELECT MAX(fecha) FROM capturas").fetchone()
    return row[0] if row and row[0] else None


def _cobertura(conn, fecha_hoy: str) -> dict:
    """Qué retailers configurados realmente trajeron datos hoy -- para no
    esconder un fallo de scraping detrás de un dashboard que luce normal."""
    try:
        with open(RETAILERS_CONFIG, encoding="utf-8") as f:
            config = json.load(f)
        nombres_activos = [r["nombre"] for r in config.get("retailers", [])]
    except Exception:
        nombres_activos = []

    cur = conn.execute(
        "SELECT retailer, COUNT(*), SUM(CASE WHEN marca='HONOR' THEN 1 ELSE 0 END) "
        "FROM capturas WHERE fecha = ? GROUP BY retailer",
        (fecha_hoy,),
    )
    filas_hoy = {row[0]: {"filas": row[1], "filas_honor": row[2]} for row in cur.fetchall()}

    detalle = []
    for nombre in nombres_activos:
        info = filas_hoy.get(nombre)
        detalle.append({
            "retailer": nombre,
            "filas": info["filas"] if info else 0,
            "filas_honor": info["filas_honor"] if info else 0,
            "ok": info is not None and info["filas"] > 0,
        })
    # Por si algún retailer trajo datos hoy pero ya no está en retailers.json
    # (se sacó de la config pero la fila quedó en la BD) -- no ocultarlo.
    for nombre, info in filas_hoy.items():
        if nombre not in nombres_activos:
            detalle.append({"retailer": nombre, "filas": info["filas"],
                             "filas_honor": info["filas_honor"], "ok": True,
                             "nota": "no está en retailers.json activos"})

    detalle.sort(key=lambda d: (-d["filas_honor"], d["retailer"]))
    return {
        "retailers_configurados": len(nombres_activos),
        "retailers_con_datos_hoy": sum(1 for d in detalle if d["ok"]),
        "detalle": detalle,
    }


def _filas_honor_hoy(conn, fecha_hoy: str) -> list[dict]:
    cur = conn.execute(
        "SELECT retailer, categoria, modelo, precio_regular, precio_oferta, "
        "vendedor, vendedor_tercero, url FROM capturas "
        "WHERE fecha = ? AND marca = 'HONOR'",
        (fecha_hoy,),
    )
    cols = ["retailer", "categoria", "modelo", "precio_regular", "precio_oferta",
            "vendedor", "vendedor_tercero", "url"]
    out = []
    for row in cur.fetchall():
        r = dict(zip(cols, row))
        if not es_producto_valido(r["modelo"]):
            continue
        if not r["precio_oferta"]:
            continue
        r["familia"] = modelo_a_familia(r["modelo"])
        out.append(r)
    return out


def _filas_competencia_hoy(conn, fecha_hoy: str) -> list[dict]:
    cur = conn.execute(
        "SELECT retailer, marca, modelo, precio_oferta, vendedor FROM capturas "
        "WHERE fecha = ? AND marca != 'HONOR' AND precio_oferta IS NOT NULL AND precio_oferta > 0",
        (fecha_hoy,),
    )
    cols = ["retailer", "marca", "modelo", "precio_oferta", "vendedor"]
    filas = [dict(zip(cols, row)) for row in cur.fetchall()]
    # Mismo filtro de calidad que a Honor: descartar códigos de barra sueltos
    # y precios por debajo de lo que cuesta un celular real -- si no, un
    # accesorio mal etiquetado con marca "SAMSUNG" a S/39 hace parecer que
    # Honor está carísimo en el segmento "Hasta S/600", cuando en realidad
    # se está comparando un celular contra una mica de pantalla.
    return [
        r for r in filas
        if not es_texto_barcode(r["modelo"])
        and r["precio_oferta"] >= PRECIO_MINIMO_CELULAR
        and not es_accesorio_por_nombre(_sin_acentos(r["modelo"].upper()))
    ]


def _dispersion_interna(filas_honor: list[dict]) -> list[dict]:
    """Para cada familia Honor, cuánto varía el precio de oferta entre
    retailers/vendedores -- la oportunidad más directa: mismo producto,
    precio distinto según dónde lo mires."""
    por_familia = defaultdict(list)
    for r in filas_honor:
        if r["familia"].startswith("OTRO:"):
            continue
        por_familia[r["familia"]].append(r)

    resultado = []
    for familia, ofertas in por_familia.items():
        precios = [o["precio_oferta"] for o in ofertas]
        p_min, p_max = min(precios), max(precios)
        spread_pct = round((p_max - p_min) / p_min * 100, 1) if p_min else 0.0
        ofertas_ordenadas = sorted(ofertas, key=lambda o: o["precio_oferta"])
        resultado.append({
            "familia": familia,
            "n_ofertas": len(ofertas),
            "precio_min": p_min,
            "precio_max": p_max,
            "spread_pct": spread_pct,
            "es_oportunidad": spread_pct >= UMBRAL_DISPERSION_PCT,
            "ofertas": [
                {
                    "retailer": o["retailer"],
                    "vendedor": o["vendedor"],
                    "vendedor_tercero": bool(o["vendedor_tercero"]),
                    "precio": o["precio_oferta"],
                    "modelo": o["modelo"],
                    "url": o["url"],
                }
                for o in ofertas_ordenadas
            ],
        })
    resultado.sort(key=lambda x: -x["spread_pct"])
    return resultado


def _vs_competencia(filas_honor: list[dict], filas_competencia: list[dict]) -> list[dict]:
    """Por segmento de precio, el Honor más barato disponible hoy vs. el
    competidor (Samsung/Xiaomi/Motorola/Apple/Redmi/Poco) más barato del
    mismo segmento -- no hay forma confiable de matchear modelo exacto entre
    marcas, así que el segmento de precio es el proxy de 'gama equivalente'."""
    honor_por_segmento = defaultdict(list)
    for r in filas_honor:
        seg = segmento_de_precio(r["precio_oferta"])
        honor_por_segmento[seg].append(r)

    comp_por_segmento = defaultdict(list)
    for r in filas_competencia:
        seg = segmento_de_precio(r["precio_oferta"])
        comp_por_segmento[seg].append(r)

    orden_segmentos = ["Hasta S/600", "S/600 - S/1,000", "S/1,000 - S/1,500",
                       "S/1,500 - S/2,500", "S/2,500 - S/4,000", "Más de S/4,000"]

    resultado = []
    for seg in sorted(set(honor_por_segmento) | set(comp_por_segmento),
                       key=lambda s: orden_segmentos.index(s) if s in orden_segmentos else 99):
        honor_ofertas = honor_por_segmento.get(seg, [])
        comp_ofertas = comp_por_segmento.get(seg, [])
        if not honor_ofertas or not comp_ofertas:
            continue
        honor_min = min(honor_ofertas, key=lambda o: o["precio_oferta"])
        comp_min = min(comp_ofertas, key=lambda o: o["precio_oferta"])
        gap_pct = round((honor_min["precio_oferta"] - comp_min["precio_oferta"]) / comp_min["precio_oferta"] * 100, 1)
        resultado.append({
            "segmento": seg,
            "honor_mas_barato": {
                "familia": honor_min["familia"], "modelo": honor_min["modelo"],
                "retailer": honor_min["retailer"], "precio": honor_min["precio_oferta"],
            },
            "competidor_mas_barato": {
                "marca": comp_min["marca"], "modelo": comp_min["modelo"],
                "retailer": comp_min["retailer"], "precio": comp_min["precio_oferta"],
            },
            "gap_pct": gap_pct,
            "honor_mas_caro_que_competencia": gap_pct > 0,
            "es_oportunidad": abs(gap_pct) >= UMBRAL_GAP_SEGMENTO_PCT,
        })
    return resultado


def _sany(filas_honor: list[dict]) -> dict:
    """Pestaña dedicada: todo lo que vende Sany (aparece como vendedor
    marketplace en más de un retailer/plataforma, no solo Falabella) y cómo
    se compara contra el resto del mercado en la misma familia."""
    ofertas_sany = [r for r in filas_honor if r["vendedor"] and "SANY" in r["vendedor"].upper()]
    if not ofertas_sany:
        return {"total_productos": 0, "productos": []}

    resto_por_familia = defaultdict(list)
    for r in filas_honor:
        if r["vendedor"] and "SANY" in r["vendedor"].upper():
            continue
        resto_por_familia[r["familia"]].append(r["precio_oferta"])

    productos = []
    for r in ofertas_sany:
        resto = resto_por_familia.get(r["familia"], [])
        precio_min_resto = min(resto) if resto else None
        diferencia_pct = None
        if precio_min_resto:
            diferencia_pct = round((r["precio_oferta"] - precio_min_resto) / precio_min_resto * 100, 1)
        productos.append({
            "familia": r["familia"],
            "modelo": r["modelo"],
            "retailer": r["retailer"],
            "precio_sany": r["precio_oferta"],
            "precio_min_resto_mercado": precio_min_resto,
            "diferencia_pct": diferencia_pct,
            "sany_es_mas_barato": diferencia_pct is not None and diferencia_pct < 0,
            "url": r["url"],
        })
    productos.sort(key=lambda p: (p["diferencia_pct"] if p["diferencia_pct"] is not None else 0))
    return {"total_productos": len(productos), "productos": productos}


def _cambios_precio(conn) -> list[dict]:
    cambios = db.price_changes_since_last_run(conn, marca="HONOR")
    return [
        {"retailer": retailer, "modelo": modelo, "vendedor": vendedor,
         "precio_antes": antes, "precio_ahora": ahora,
         "bajo": ahora < antes,
         "variacion_pct": round((ahora - antes) / antes * 100, 1) if antes else None}
        for retailer, modelo, vendedor, antes, ahora in cambios
    ]


def _insights(dispersion: list[dict], vs_comp: list[dict], sany: dict, cambios: list[dict]) -> list[dict]:
    """Evidence -> Interpretation -> Action, siguiendo el contrato de
    insights de IS Design System. Nada de generar texto especulativo: cada
    insight sale directo de un número ya calculado arriba."""
    insights = []

    top_dispersion = [d for d in dispersion if d["es_oportunidad"]][:5]
    for d in top_dispersion:
        barato = d["ofertas"][0]
        caro = d["ofertas"][-1]
        insights.append({
            "tipo": "dispersion_interna",
            "severidad": "alta" if d["spread_pct"] >= 20 else "media",
            "evidencia": f"{d['familia']}: precio de S/{d['precio_min']:.0f} en {barato['retailer']}"
                         f" ({barato['vendedor']}) hasta S/{d['precio_max']:.0f} en {caro['retailer']}"
                         f" ({caro['vendedor']}) -- {d['n_ofertas']} ofertas activas.",
            "interpretacion": f"Dispersión de {d['spread_pct']}% para el mismo SKU. "
                               f"El precio en {caro['retailer']} está {d['spread_pct']}% por encima del más barato del mercado.",
            "accion": f"Revisar la estrategia de precio de {d['familia']} en {caro['retailer']} "
                      f"({caro['vendedor']}) frente al resto del canal.",
            "confianza": "alta",
        })

    gaps = [g for g in vs_comp if g["es_oportunidad"]]
    for g in sorted(gaps, key=lambda x: -abs(x["gap_pct"]))[:5]:
        if g["honor_mas_caro_que_competencia"]:
            interp = (f"Honor está {g['gap_pct']}% más caro que {g['competidor_mas_barato']['marca']} "
                      f"en el segmento {g['segmento']}.")
            accion = f"Evaluar ajuste de precio o refuerzo de argumento de valor de {g['honor_mas_barato']['familia']} en {g['segmento']}."
        else:
            interp = (f"Honor está {abs(g['gap_pct'])}% más barato que {g['competidor_mas_barato']['marca']} "
                      f"en el segmento {g['segmento']} -- posible espacio para subir precio sin perder competitividad.")
            accion = f"Evaluar si {g['honor_mas_barato']['familia']} tiene margen para subir precio en {g['segmento']}."
        insights.append({
            "tipo": "vs_competencia",
            "severidad": "media",
            "evidencia": f"Segmento {g['segmento']}: Honor más barato es {g['honor_mas_barato']['familia']}"
                         f" (S/{g['honor_mas_barato']['precio']:.0f} en {g['honor_mas_barato']['retailer']});"
                         f" {g['competidor_mas_barato']['marca']} más barato es S/{g['competidor_mas_barato']['precio']:.0f}"
                         f" en {g['competidor_mas_barato']['retailer']}.",
            "interpretacion": interp,
            "accion": accion,
            "confianza": "media",
        })

    if sany.get("total_productos"):
        mas_caros = [p for p in sany["productos"] if p["diferencia_pct"] and p["diferencia_pct"] > 5]
        if mas_caros:
            peor = max(mas_caros, key=lambda p: p["diferencia_pct"])
            insights.append({
                "tipo": "sany",
                "severidad": "alta" if peor["diferencia_pct"] >= 15 else "media",
                "evidencia": f"Sany vende {peor['familia']} a S/{peor['precio_sany']:.0f} en {peor['retailer']}, "
                             f"{peor['diferencia_pct']}% sobre el precio más bajo del mercado (S/{peor['precio_min_resto_mercado']:.0f}).",
                "interpretacion": "Sany tiene precio más alto que el resto del canal en al menos un SKU Honor.",
                "accion": f"Conversar con Sany sobre el precio de {peor['familia']} -- puede estar perdiendo venta frente al resto del canal.",
                "confianza": "alta",
            })

    for c in cambios[:5]:
        if c["bajo"] and c["variacion_pct"] and c["variacion_pct"] <= -5:
            insights.append({
                "tipo": "cambio_precio",
                "severidad": "media",
                "evidencia": f"{c['modelo']} en {c['retailer']} ({c['vendedor']}): S/{c['precio_antes']:.0f} -> S/{c['precio_ahora']:.0f}.",
                "interpretacion": f"Bajó {abs(c['variacion_pct'])}% desde la corrida anterior.",
                "accion": "Confirmar si es promoción puntual o ajuste de precio de lista.",
                "confianza": "alta",
            })

    return insights


def build(db_path: Path | None = None, out_path: Path | None = None) -> dict:
    if db_path:
        conn = sqlite3.connect(db_path)
    else:
        conn = db.get_connection()  # crea el esquema si data/precios.db no existe todavía
    fecha_hoy = _fecha_mas_reciente(conn)
    if not fecha_hoy:
        raise SystemExit("data/precios.db no tiene capturas todavía -- correr run.py primero.")

    cobertura = _cobertura(conn, fecha_hoy)
    filas_honor = _filas_honor_hoy(conn, fecha_hoy)
    filas_competencia = _filas_competencia_hoy(conn, fecha_hoy)

    dispersion = _dispersion_interna(filas_honor)
    vs_comp = _vs_competencia(filas_honor, filas_competencia)
    sany = _sany(filas_honor)
    cambios = _cambios_precio(conn)
    insights = _insights(dispersion, vs_comp, sany, cambios)

    familias_detectadas = {r["familia"] for r in filas_honor if not r["familia"].startswith("OTRO:")}
    vendedores_detectados = {r["vendedor"] for r in filas_honor if r["vendedor"]}
    retailers_con_honor = {r["retailer"] for r in filas_honor}

    data = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "fecha_captura": fecha_hoy,
        "resumen": {
            "total_ofertas_honor_hoy": len(filas_honor),
            "familias_honor_detectadas": len(familias_detectadas),
            "vendedores_honor_detectados": len(vendedores_detectados),
            "retailers_con_honor_hoy": len(retailers_con_honor),
            "oportunidades_dispersion": sum(1 for d in dispersion if d["es_oportunidad"]),
            "oportunidades_vs_competencia": sum(1 for g in vs_comp if g["es_oportunidad"]),
        },
        "cobertura": cobertura,
        "dispersion_interna": dispersion,
        "vs_competencia": vs_comp,
        "sany": sany,
        "cambios_precio": cambios,
        "insights": insights,
    }

    out_path = out_path or DEFAULT_OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    conn.close()
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", help="Ruta a precios.db (default: data/precios.db)")
    parser.add_argument("--out", help="Ruta de salida (default: docs/dashboard_data.json)")
    args = parser.parse_args()

    data = build(
        db_path=Path(args.db) if args.db else None,
        out_path=Path(args.out) if args.out else None,
    )
    print(f"OK -- {data['resumen']['total_ofertas_honor_hoy']} ofertas Honor, "
          f"{data['resumen']['familias_honor_detectadas']} familias, "
          f"{data['resumen']['oportunidades_dispersion']} oportunidades de dispersión, "
          f"{data['resumen']['oportunidades_vs_competencia']} oportunidades vs. competencia.")


if __name__ == "__main__":
    main()
