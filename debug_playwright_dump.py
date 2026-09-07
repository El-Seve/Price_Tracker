#!/usr/bin/env python3
"""
Herramienta de diagnóstico para Movistar/Ripley (los dos retailers nuevos
que usan Playwright, todavía sin validar en vivo -- ver adapters/
playwright_browser.py).

Uso:
    python debug_playwright_dump.py "https://tienda.movistar.com.pe/celulares/honor"
    python debug_playwright_dump.py "https://simple.ripley.com.pe/tecnologia/celulares/celulares-y-smartphones?s=mdco&page=1"

Guarda dos archivos junto al script:
  - debug_dump.html        -- HTML completo de la página ya renderizada
  - debug_dump_texto.txt   -- solo el texto visible (lo que usa el parser)
  - debug_dump.png         -- captura de pantalla, para ver si quedó
                               atascado en el challenge de Cloudflare o en
                               una pantalla de mantenimiento

Si el parser de adapters/playwright_browser.py no encuentra los productos
esperados, corre esto y mándame debug_dump_texto.txt (o el .png si sospechas
que ni siquiera pasó el challenge) -- con eso ajusto el patrón de
extracción sin tener que adivinar.
"""
import sys

from adapters.playwright_browser import fetch_rendered_text, parece_challenge_o_mantenimiento

if len(sys.argv) < 2:
    print("Uso: python debug_playwright_dump.py <URL>")
    sys.exit(1)

url = sys.argv[1]
wait_for = "S/" if "movistar" in url else None

print(f"Cargando {url} ...")

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        locale="es-PE",
        viewport={"width": 1366, "height": 900},
    )
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    page = ctx.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(8000)
    if wait_for:
        try:
            page.wait_for_function("sel => document.body.innerText.includes(sel)", arg=wait_for, timeout=15000)
        except Exception:
            print("(no llegó a aparecer el texto esperado a tiempo, sigo igual)")
    html = page.content()
    texto = page.inner_text("body")
    page.screenshot(path="debug_dump.png", full_page=True)
    browser.close()

with open("debug_dump.html", "w", encoding="utf-8") as f:
    f.write(html)
with open("debug_dump_texto.txt", "w", encoding="utf-8") as f:
    f.write(texto)

print("Guardado: debug_dump.html, debug_dump_texto.txt, debug_dump.png")
if parece_challenge_o_mantenimiento(texto):
    print("AVISO: el texto visible todavía parece un challenge de Cloudflare o una página de mantenimiento.")
else:
    print("El texto NO parece un challenge -- revisa debug_dump_texto.txt para confirmar que salieron precios reales.")
