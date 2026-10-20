r"""Auditoría de accesibilidad de la web de Arena: axe-core + recorrido con teclado.

Requisitos (fuera del repo, p. ej. en D:\dev-tools): Python con `playwright` y su navegador Chromium, y el paquete npm
`axe-core` (solo se usa su `axe.min.js`; no es dependencia de la web).

Uso (con un servidor Arena y un agente simulado ya en marcha; ver CLAUDE.md, «Comandos»):

    set PLAYWRIGHT_BROWSERS_PATH=D:\dev-tools\ms-playwright
    set AXE_JS=D:\dev-tools\axe\node_modules\axe-core\axe.min.js
    D:\dev-tools\readme-tools\Scripts\python.exe scripts\a11y.py http://127.0.0.1:18120

Opcional: PAGES='["/", "/historial"]' para elegir rutas. Se audita en modo normal, con `prefers-reduced-motion`
emulado y con contraste alto. Sale con código 1 si hay infracciones de axe o controles sin anillo de foco.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
AXE = open(os.environ["AXE_JS"], encoding="utf-8").read()
DEFAULT_PAGES = ["/", "/servidores", "/calidad", "/batalla", "/historial", "/comparar", "/ajustes", "/asistente"]
PAGES = json.loads(os.environ.get("PAGES", "null")) or DEFAULT_PAGES
MODES = [("normal", {}, False), ("movimiento reducido", {"reduced_motion": "reduce"}, False), ("contraste alto", {}, True)]
INTERACTIVE = "a[href],button,input,select,textarea,[tabindex]:not([tabindex='-1']),[role=tab],summary"
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]

MARK = """(sel) => { let n = 0; document.querySelectorAll(sel).forEach((e) => {
  const r = e.getBoundingClientRect();
  if (r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden' && !e.disabled) e.dataset.kid = String(++n);
}); return n; }"""
FOCUS = """() => { const e = document.activeElement; if (!e || e === document.body) return null; const cs = getComputedStyle(e);
  return { kid: e.dataset.kid || null, ring: !cs.outlineStyle.startsWith('none') || cs.boxShadow !== 'none', html: e.outerHTML.slice(0, 100) }; }"""

problems = 0
with sync_playwright() as p:
    browser = p.chromium.launch()
    for mode, kw, high in MODES:
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, **kw)
        page = ctx.new_page()
        if high:
            page.add_init_script(
                "localStorage.setItem('arena.appearance', JSON.stringify({accent:'#f2f2f7',contrast:'alto',scale:1}))"
            )
        for path in PAGES:
            page.goto(BASE + path)
            page.wait_for_timeout(1500)
            page.evaluate(AXE)
            res = page.evaluate("(tags) => axe.run(document, {runOnly: {type: 'tag', values: tags}})", TAGS)
            for v in res["violations"]:
                problems += 1
                print(f"[axe/{mode}] {path}: {v['id']} ({v['impact']}) {v['help']} → {v['nodes'][0]['target'][0]}")
            if mode == "normal":  # el recorrido con teclado no depende del tema
                count = page.evaluate(MARK, INTERACTIVE)
                page.evaluate("document.activeElement && document.activeElement.blur()")
                seen: set[str] = set()
                for _ in range(count + 5):
                    page.keyboard.press("Tab")
                    st = page.evaluate(FOCUS)
                    if not st or st["kid"] in seen:
                        break
                    seen.add(st["kid"])
                    if not st["ring"]:
                        problems += 1
                        print(f"[teclado] {path}: sin anillo de foco → {st['html']}")
        ctx.close()
    browser.close()
print("OK: sin infracciones" if not problems else f"{problems} problema(s)")
sys.exit(1 if problems else 0)
