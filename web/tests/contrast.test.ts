// Contraste AA de los tokens de color: texto ≥ 4,5:1 y elementos de interfaz/gráficos ≥ 3:1.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { contrast, mix } from "../src/lib/contrast";

const css = readFileSync(resolve(process.cwd(), "src/styles/tokens.css"), "utf-8");

/** Variables de un bloque `selector { … }` (sin comentarios). */
function vars(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`No hay bloque ${selector}`);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start)).replace(/\/\*[\s\S]*?\*\//g, "");
  return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)].map((m) => [m[1], m[2]]));
}

const base = vars(":root");
const themes: Record<string, Record<string, string>> = {
  normal: base,
  "contraste alto": { ...base, ...vars(':root[data-contrast="alto"]') },
  "modo vídeo": { ...base, ...vars(":root.video-mode") },
};

describe.each(Object.entries(themes))("contraste AA · %s", (_name, t) => {
  const surfaces = ["bg", "panel", "panel-raised"];
  it.each(surfaces)("los textos se leen sobre --%s", (surface) => {
    for (const ink of ["ink", "ink-dim", "ink-faint", "crit-ink", "ok", "warn", "accent"]) {
      expect(contrast(t[ink], t[surface]), `${ink} sobre ${surface}`).toBeGreaterThanOrEqual(4.5);
    }
  });
  it("el texto de estado se lee sobre su fondo tintado", () => {
    for (const k of ["crit-ink", "warn", "ok"]) {
      const tinted = mix(t[k.replace("-ink", "")], t["panel-raised"], 0.14);
      expect(contrast(t[k], tinted), `${k} sobre su tinte`).toBeGreaterThanOrEqual(4.5);
    }
  });
  it("las GPU y la CPU se distinguen del fondo (gráficos ≥ 3:1)", () => {
    for (const d of ["dev-1", "dev-2", "dev-3", "dev-4", "dev-5", "dev-6", "dev-cpu", "dev-ram"]) {
      expect(contrast(t[d], t["bg"]), d).toBeGreaterThanOrEqual(3);
      expect(contrast(t[d], t["panel"]), `${d} sobre panel`).toBeGreaterThanOrEqual(3);
    }
  });
  it("las líneas fuertes se ven (≥ 3:1 sobre el fondo)", () => {
    expect(contrast(t["line-strong"], t["bg"])).toBeGreaterThanOrEqual(3);
  });
});

describe("utilidades de contraste", () => {
  it("negro sobre blanco es 21:1", () => expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5));
  it("mezcla con opacidad", () => expect(mix("#ffffff", "#000000", 0.5)).toBe("#808080"));
});
