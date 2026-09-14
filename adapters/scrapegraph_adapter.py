"""
Respaldo de extracción vía LLM (ScrapeGraphAI + Gemini) para páginas donde
el parseo por patrón de texto (playwright_browser.extraer_ofertas_por_patron)
no encuentra nada -- por ejemplo si un sitio cambia de estructura y el
patrón "MARCA en mayúscula al inicio de línea + precio S/ debajo" deja de
calzar, o si un sitio nuevo (Bitel, Juntoz) tiene un formato que todavía no
conocemos bien.

Este módulo NO reemplaza el parseo por patrón -- es más caro (llamada a un
LLM externo) y depende de un servicio de terceros, así que solo se usa como
último recurso. Ver playwright_browser.extraer_ofertas_con_fallback, que es
quien decide cuándo llamar a esto.

Requiere la variable de entorno GEMINI_API_KEY (ver README para cómo
conseguirla gratis en Google AI Studio y cómo cargarla como secret de
GitHub Actions). Sin ella, `disponible()` devuelve False y todo el módulo
se salta en silencio -- igual que Movistar hoy sin datos, no rompe la
corrida.

Costo aproximado (verificado 14/09/2026, precios de Gemini 2.5 Flash-Lite):
una página de categoría típica (~15K tokens de texto) sale en menos de
$0.002 -- para los 2-3 retailers que podrían necesitar esto, corriendo una
vez al día, es centavos al mes. La API propia de ScrapeGraphAI (hosted) NO
se usa acá a propósito -- sale carísima en comparación ($20/mes mínimo)
para lo poco que necesitamos.

--- Aviso de fragilidad ---
`scrapegraphai` (el paquete de PyPI) depende de una parte del ecosistema
langchain que está cambiando rápido y ya viene con un problema de
compatibilidad interno (ver _scrapegraph_compat.py). Es una pieza más
frágil que el resto del tracker -- si un día este respaldo deja de andar
(y solo este, el resto del tracker no depende de esto), revisar primero
si scrapegraphai/langchain-community se actualizaron solos a versiones
nuevas.
"""
import os
import sys

from . import _scrapegraph_compat  # noqa: F401 -- debe importarse antes de scrapegraphai

MODELO_LLM = "google_genai/gemini-2.5-flash-lite"

# Tope de caracteres del texto que se manda al LLM -- una página de
# categoría completa puede traer miles de líneas; cortamos para no disparar
# el costo/tiempo de respuesta por accidente si un sitio devuelve una
# página gigante. 60K caracteres es de sobra para una sola página de
# catálogo (Gemini Flash-Lite además tiene ventana de contexto enorme).
MAX_CHARS_TEXTO = 60_000


def disponible() -> bool:
    """True si hay una API key de Gemini configurada -- si no, este
    respaldo se salta en silencio en vez de fallar."""
    return bool(os.environ.get("GEMINI_API_KEY"))


def extraer_via_llm(texto: str, marcas: set[str], retailer_nombre: str) -> list[dict]:
    """Le pide al LLM que extraiga productos de las marcas objetivo del
    texto visible de una página ya renderizada (Playwright) -- devuelve una
    lista de dicts con las mismas llaves que extraer_ofertas_por_patron:
    marca, modelo, precio_oferta, precio_regular."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or not texto or not texto.strip():
        return []

    from scrapegraphai.graphs import SmartScraperGraph

    marcas_str = ", ".join(sorted(marcas))
    prompt = (
        f"De este texto de una página de catálogo de {retailer_nombre}, extrae SOLO los "
        f"productos que sean de una de estas marcas: {marcas_str}. "
        "Para cada producto, devuelve un objeto JSON con: "
        "marca (una de la lista pedida, en MAYÚSCULAS), "
        "modelo (el nombre completo del producto tal como aparece en el texto), "
        "precio_oferta (el precio final que paga el cliente hoy, como número sin 'S/' ni comas), "
        "precio_regular (el precio de lista antes de descuento si se muestra aparte o tachado; "
        "si no hay descuento visible, repite el mismo valor de precio_oferta). "
        "Ignora accesorios sueltos (fundas, cargadores, cables, micas, power banks) y cualquier "
        "producto que no sea claramente de las marcas pedidas. Devuelve una lista de estos objetos."
    )
    graph_config = {
        "llm": {
            "api_key": api_key,
            "model": MODELO_LLM,
            "model_tokens": 100_000,
        },
        "verbose": False,
    }
    graph = SmartScraperGraph(
        prompt=prompt,
        source=texto[:MAX_CHARS_TEXTO],
        config=graph_config,
    )
    try:
        resultado = graph.run()
    except Exception as e:
        print(f"[!] {retailer_nombre}: el respaldo LLM también falló: {e}", file=sys.stderr)
        return []

    marcas_upper = {m.upper() for m in marcas}
    ofertas = []
    for p in _normalizar_resultado(resultado):
        marca = str(p.get("marca", "")).strip().upper()
        modelo = str(p.get("modelo", "")).strip()
        if not marca or not modelo or marca not in marcas_upper:
            continue
        try:
            precio_oferta = float(p.get("precio_oferta"))
        except (TypeError, ValueError):
            continue
        try:
            precio_regular = float(p.get("precio_regular"))
        except (TypeError, ValueError):
            precio_regular = precio_oferta
        ofertas.append({
            "marca": marca, "modelo": modelo,
            "precio_oferta": precio_oferta, "precio_regular": precio_regular,
        })
    return ofertas


def _normalizar_resultado(resultado) -> list[dict]:
    """SmartScraperGraph.run() puede devolver formas ligeramente distintas
    según cómo interprete el prompt (lista directa, o un dict con la lista
    adentro bajo alguna llave tipo 'products'/'content') -- esto tolera las
    formas más comunes en vez de asumir una sola y fallar silenciosamente."""
    if isinstance(resultado, list):
        return resultado
    if isinstance(resultado, dict):
        for key in ("productos", "products", "content", "result", "items"):
            val = resultado.get(key)
            if isinstance(val, list):
                return val
        if "modelo" in resultado or "marca" in resultado:
            return [resultado]
    return []
