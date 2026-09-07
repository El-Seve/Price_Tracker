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


MAX_DIAS_HISTORIAL = 60  # no tiene sentido graficar un histórico infinito


def _todas_las_fechas(conn) -> list[str]:
    cur = conn.execute(
        f"SELECT DISTINCT fecha FROM capturas ORDER BY fecha DESC LIMIT {MAX_DIAS_HISTORIAL}"
    )
    return sorted(row[0] for row in cur.fetchall())


def _tendencia_familias(conn, fechas: list[str]) -> dict:
    """Serie de tiempo por familia Honor: min/promedio/max de precio de
    oferta por día, a lo largo de todas las fechas capturadas. Con una sola
    fecha en la base (recién empezando) el gráfico va a mostrar un solo
    punto -- el motor queda listo para enriquecerse solo con cada corrida
    diaria nueva, sin tener que tocar código de nuevo."""
    cur = conn.execute(
        "SELECT fecha, modelo, precio_oferta FROM capturas WHERE marca = 'HONOR' AND fecha IN ({})".format(
            ",".join("?" for _ in fechas)
        ),
        fechas,
    )
    por_familia_fecha = defaultdict(lambda: defaultdict(list))
    for fecha, modelo, precio in cur.fetchall():
        if not precio or not es_producto_valido(modelo):
            continue
        familia = modelo_a_familia(modelo)
        if familia.startswith("OTRO:"):
            continue
        por_familia_fecha[familia][fecha].append(precio)

    series = {}
    for familia, por_fecha in por_familia_fecha.items():
        # Solo vale la pena graficar familias con al menos algo de volumen
        # sostenido -- una familia que aparece una sola vez en todo el
        # histórico no aporta una "tendencia".
        puntos = []
        for fecha in fechas:
            precios = por_fecha.get(fecha)
            if not precios:
                continue
            puntos.append({
                "fecha": fecha,
                "precio_min": min(precios),
                "precio_promedio": round(sum(precios) / len(precios), 0),
                "precio_max": max(precios),
                "n_ofertas": len(precios),
            })
        if puntos:
            series[familia] = puntos

    return series


def _tendencia_vs_competencia(conn, fechas: list[str]) -> dict:
    """Igual que _vs_competencia pero por fecha, para poder graficar si Honor
    se mueve en la misma dirección que el segmento o no."""
    orden_segmentos = ["Hasta S/600", "S/600 - S/1,000", "S/1,000 - S/1,500",
                       "S/1,500 - S/2,500", "S/2,500 - S/4,000", "Más de S/4,000"]
    series = {seg: [] for seg in orden_segmentos}

    for fecha in fechas:
        filas_honor = _filas_honor_hoy(conn, fecha)
        filas_comp = _filas_competencia_hoy(conn, fecha)
        honor_por_segmento = defaultdict(list)
        for r in filas_honor:
            honor_por_segmento[segmento_de_precio(r["precio_oferta"])].append(r["precio_oferta"])
        comp_por_segmento = defaultdict(list)
        for r in filas_comp:
            comp_por_segmento[segmento_de_precio(r["precio_oferta"])].append(r["precio_oferta"])
        for seg in orden_segmentos:
            if seg in honor_por_segmento and seg in comp_por_segmento:
                series[seg].append({
                    "fecha": fecha,
                    "honor_min": min(honor_por_segmento[seg]),
                    "competencia_min": min(comp_por_segmento[seg]),
                })

    return {seg: puntos for seg, puntos in series.items() if puntos}


_VENDOR_DISPLAY_CACHE: dict[str, str] = {}


def _vendedor_key(nombre: str) -> str:
    return _sin_acentos((nombre or "").strip().upper())


def _heatmap_vendedores(conn, fechas: list[str]) -> dict:
    """Cuadrícula vendedor x fecha: cuántos precios Honor de ese vendedor
    cambiaron respecto al día anterior. Sirve para detectar quién mueve
    precio seguido (agresivo/reactivo) y quién no se mueve nunca (pasivo) --
    con solo un día de historial no hay "cambio" que mostrar todavía, pero
    la estructura queda lista."""
    if len(fechas) < 2:
        return {"fechas": fechas, "vendedores": []}

    cur = conn.execute(
        "SELECT fecha, retailer, modelo, vendedor, precio_oferta FROM capturas "
        "WHERE marca = 'HONOR' AND fecha IN ({})".format(",".join("?" for _ in fechas)),
        fechas,
    )
    # (vendedor_key, retailer, modelo) -> {fecha: precio}
    historial = defaultdict(dict)
    display_names = {}
    for fecha, retailer, modelo, vendedor, precio in cur.fetchall():
        if not vendedor or not precio:
            continue
        vkey = _vendedor_key(vendedor)
        display_names.setdefault(vkey, vendedor)
        historial[(vkey, retailer, modelo)][fecha] = precio

    cambios_por_vendedor_fecha = defaultdict(lambda: defaultdict(int))
    ofertas_por_vendedor = defaultdict(int)
    for (vkey, retailer, modelo), por_fecha in historial.items():
        ofertas_por_vendedor[vkey] += 1
        for i in range(1, len(fechas)):
            hoy, ayer = fechas[i], fechas[i - 1]
            if hoy in por_fecha and ayer in por_fecha and por_fecha[hoy] != por_fecha[ayer]:
                cambios_por_vendedor_fecha[vkey][hoy] += 1

    vendedores = []
    for vkey, n_ofertas in sorted(ofertas_por_vendedor.items(), key=lambda x: -x[1])[:25]:
        vendedores.append({
            "vendedor": display_names[vkey],
            "n_ofertas": n_ofertas,
            "cambios_por_fecha": [cambios_por_vendedor_fecha[vkey].get(f, 0) for f in fechas],
            "total_cambios": sum(cambios_por_vendedor_fecha[vkey].values()),
        })
    vendedores.sort(key=lambda v: -v["total_cambios"])
    return {"fechas": fechas, "vendedores": vendedores}


# Un vendedor necesita al menos esta cantidad de ofertas Honor comparables
# (familias con más de un vendedor) para que su "sobreprecio promedio" sea
# una lectura confiable y no ruido de 1-2 productos sueltos.
MIN_OFERTAS_PARA_RANKING = 3


def _analisis_avanzado(filas_honor: list[dict], dispersion: list[dict]) -> dict:
    """Lecturas que no saltan a la vista mirando una tabla: quién cobra de
    más de forma sistemática, dónde el catálogo Honor depende de un solo
    vendedor (riesgo de cobertura), y en qué franja de precio el mercado es
    más inestable en términos relativos."""
    precio_min_por_familia = {d["familia"]: d["precio_min"] for d in dispersion}

    # --- Ranking de vendedores por sobreprecio sistemático ---
    acumulado = defaultdict(lambda: {"sobreprecios": [], "n_ofertas": 0, "display": None, "vendedor_tercero": False})
    for r in filas_honor:
        if r["familia"].startswith("OTRO:") or not r["vendedor"]:
            continue
        precio_min = precio_min_por_familia.get(r["familia"])
        if not precio_min:
            continue
        vkey = _vendedor_key(r["vendedor"])
        entry = acumulado[vkey]
        entry["display"] = entry["display"] or r["vendedor"]
        entry["n_ofertas"] += 1
        entry["vendedor_tercero"] = entry["vendedor_tercero"] or bool(r["vendedor_tercero"])
        entry["sobreprecios"].append((r["precio_oferta"] - precio_min) / precio_min * 100)

    vendedores_ranking = []
    for vkey, entry in acumulado.items():
        if entry["n_ofertas"] < MIN_OFERTAS_PARA_RANKING:
            continue
        promedio = round(sum(entry["sobreprecios"]) / len(entry["sobreprecios"]), 1)
        vendedores_ranking.append({
            "vendedor": entry["display"],
            "vendedor_tercero": entry["vendedor_tercero"],
            "n_ofertas": entry["n_ofertas"],
            "sobreprecio_promedio_pct": promedio,
            "clasificacion": (
                "premium/caro" if promedio >= 15 else
                "agresivo/barato" if promedio <= 3 else
                "alineado al mercado"
            ),
        })
    vendedores_ranking.sort(key=lambda v: -v["sobreprecio_promedio_pct"])

    # --- Concentración / riesgo de cobertura por familia ---
    concentracion = []
    por_familia_vendedores = defaultdict(set)
    por_familia_retailers = defaultdict(set)
    for r in filas_honor:
        if r["familia"].startswith("OTRO:"):
            continue
        if r["vendedor"]:
            por_familia_vendedores[r["familia"]].add(_vendedor_key(r["vendedor"]))
        por_familia_retailers[r["familia"]].add(r["retailer"])

    for familia in por_familia_retailers:
        n_vend = len(por_familia_vendedores.get(familia, set()))
        n_ret = len(por_familia_retailers[familia])
        riesgo = "alto" if n_vend <= 1 else "medio" if n_vend == 2 else "bajo"
        concentracion.append({
            "familia": familia,
            "n_vendedores_distintos": n_vend,
            "n_retailers_distintos": n_ret,
            "riesgo_concentracion": riesgo,
        })
    concentracion.sort(key=lambda c: (c["n_vendedores_distintos"], -c["n_retailers_distintos"]))
    familias_riesgo_alto = sum(1 for c in concentracion if c["riesgo_concentracion"] == "alto")

    # --- Dispersión relativa por segmento de precio ---
    por_segmento = defaultdict(list)
    for d in dispersion:
        por_segmento[segmento_de_precio(d["precio_min"])].append(d["spread_pct"])
    orden_segmentos = ["Hasta S/600", "S/600 - S/1,000", "S/1,000 - S/1,500",
                       "S/1,500 - S/2,500", "S/2,500 - S/4,000", "Más de S/4,000"]
    dispersion_por_segmento = []
    for seg in orden_segmentos:
        spreads = por_segmento.get(seg)
        if not spreads:
            continue
        dispersion_por_segmento.append({
            "segmento": seg,
            "n_familias": len(spreads),
            "spread_promedio_pct": round(sum(spreads) / len(spreads), 1),
            "spread_max_pct": round(max(spreads), 1),
        })

    return {
        "vendedores_ranking": vendedores_ranking,
        "concentracion": concentracion,
        "familias_riesgo_alto": familias_riesgo_alto,
        "total_familias_evaluadas": len(concentracion),
        "dispersion_por_segmento": dispersion_por_segmento,
    }


def _insights_avanzados(analisis: dict) -> list[dict]:
    """Mismos criterios Evidencia -> Interpretación -> Acción, pero para los
    hallazgos del análisis avanzado -- lo que no se ve mirando una tabla
    simple de precios."""
    insights = []
    ranking = analisis["vendedores_ranking"]

    if ranking:
        peor = ranking[0]
        if peor["sobreprecio_promedio_pct"] >= 10:
            insights.append({
                "tipo": "vendedor_sobreprecio",
                "severidad": "alta" if peor["sobreprecio_promedio_pct"] >= 20 else "media",
                "evidencia": f"{peor['vendedor']} vende {peor['n_ofertas']} SKUs Honor a un precio "
                             f"{peor['sobreprecio_promedio_pct']}% por encima del mínimo de mercado, en promedio.",
                "interpretacion": f"{peor['vendedor']} es sistemáticamente el más caro del canal en los "
                                   f"productos Honor que vende, no un caso aislado.",
                "accion": f"Evaluar si {peor['vendedor']} necesita ajuste de precio o si compite en otro "
                          f"factor (servicio, stock, ubicación) que justifique el sobreprecio.",
                "confianza": "alta",
            })

        agresivos = [v for v in ranking if v["clasificacion"] == "agresivo/barato"]
        if agresivos:
            mejor = min(agresivos, key=lambda v: v["sobreprecio_promedio_pct"])
            insights.append({
                "tipo": "vendedor_agresivo",
                "severidad": "media",
                "evidencia": f"{mejor['vendedor']} vende {mejor['n_ofertas']} SKUs Honor a un promedio de "
                             f"solo {mejor['sobreprecio_promedio_pct']}% sobre el mínimo de mercado.",
                "interpretacion": f"{mejor['vendedor']} es el vendedor de referencia de precio bajo para Honor -- "
                                   f"probablemente ancla la percepción de precio del canal.",
                "accion": f"Monitorear a {mejor['vendedor']} de cerca: cualquier ajuste ahí arrastra la "
                          f"percepción de precio de todo el canal.",
                "confianza": "media",
            })

    if analisis["total_familias_evaluadas"]:
        pct_riesgo = round(analisis["familias_riesgo_alto"] / analisis["total_familias_evaluadas"] * 100, 0)
        if pct_riesgo >= 30:
            insights.append({
                "tipo": "concentracion_riesgo",
                "severidad": "alta" if pct_riesgo >= 50 else "media",
                "evidencia": f"{analisis['familias_riesgo_alto']} de {analisis['total_familias_evaluadas']} "
                             f"familias Honor ({pct_riesgo:.0f}%) dependen de un solo vendedor en todo el canal capturado.",
                "interpretacion": "Si ese vendedor sube precio, se queda sin stock o deja de listar el producto, "
                                   "no hay alternativa visible en el resto del canal.",
                "accion": "Priorizar que esas familias también estén disponibles con al menos un vendedor más "
                          "(propio del retailer o marketplace).",
                "confianza": "alta",
            })

    disp_seg = analisis["dispersion_por_segmento"]
    if disp_seg:
        mas_volatil = max(disp_seg, key=lambda s: s["spread_promedio_pct"])
        if mas_volatil["spread_promedio_pct"] >= 15:
            insights.append({
                "tipo": "volatilidad_segmento",
                "severidad": "media",
                "evidencia": f"El segmento {mas_volatil['segmento']} tiene una dispersión promedio de "
                             f"{mas_volatil['spread_promedio_pct']}% entre vendedores, la más alta de todos los segmentos "
                             f"({mas_volatil['n_familias']} familias Honor evaluadas).",
                "interpretacion": "El precio de Honor en esa franja es el menos disciplinado del catálogo -- "
                                   "más margen de maniobra, pero también más riesgo de que un vendedor rompa precio.",
                "accion": f"Si hay política de precio mínimo (PVP), reforzarla primero en {mas_volatil['segmento']}.",
                "confianza": "media",
            })

    return insights


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

    fechas_historial = _todas_las_fechas(conn)
    tendencia_familias = _tendencia_familias(conn, fechas_historial)
    tendencia_vs_competencia = _tendencia_vs_competencia(conn, fechas_historial)
    heatmap_vendedores = _heatmap_vendedores(conn, fechas_historial)

    analisis_avanzado = _analisis_avanzado(filas_honor, dispersion)
    insights += _insights_avanzados(analisis_avanzado)

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
            "dias_de_historial": len(fechas_historial),
        },
        "cobertura": cobertura,
        "dispersion_interna": dispersion,
        "vs_competencia": vs_comp,
        "sany": sany,
        "cambios_precio": cambios,
        "tendencia": {
            "fechas": fechas_historial,
            "familias": tendencia_familias,
            "vs_competencia_por_segmento": tendencia_vs_competencia,
            "heatmap_vendedores": heatmap_vendedores,
        },
        "analisis_avanzado": analisis_avanzado,
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
