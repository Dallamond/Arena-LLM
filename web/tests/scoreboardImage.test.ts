import { describe, expect, it } from "vitest";
import type { CompareMetric, CompareResponse } from "../src/api/types";
import { buildScoreboardSvg, clip, escapeXml } from "../src/lib/scoreboardImage";

const metric = (key: string, label: string, values: (number | null)[], over: Partial<CompareMetric> = {}): CompareMetric => ({
  key, label, unit: "", better: "high", digits: 1, values, best: [1], ...over,
});

const base = (): CompareResponse =>
  ({
    runs: [
      { id: 1, title: "#1", side: "A", label: null },
      { id: 2, title: "#2", side: "B", label: null },
    ],
    comparability: { level: "parcial", label: "Parcialmente comparables", reasons: ["Cambia el modelo & la cuantización"], changes: ["modelo"] },
    config_diff: [],
    metrics: [
      metric("tps", "t/s <generación>", [30.25, 45], { unit: "t/s" }),
      metric("tps_per_w", "t/s por W", [0.2, 0.3], { group: "normalizada", estimated: true }),
    ],
    verdicts: [{ key: "tps", title: "Más rápido", run_index: 1, value: 45, runner_up: 30.25, margin_pct: 48.8 }],
    items: [],
    series: [],
  }) as unknown as CompareResponse;

describe("imagen del marcador", () => {
  it("escapa texto y recorta", () => {
    expect(escapeXml(`<a href="x">&'`)).toBe("&lt;a href=&quot;x&quot;&gt;&amp;&#39;");
    expect(clip("abcdefghij", 5)).toBe("abcd…");
    expect(clip("abc", 5)).toBe("abc");
  });
  it("genera un SVG con el tamaño pedido, veredictos y métricas", () => {
    const svg = buildScoreboardSvg(base(), { width: 1920, height: 1080, date: new Date("2026-10-20T00:00:00Z") });
    expect(svg).toMatch(/^<svg [^>]*width="1920" height="1080"/);
    expect(svg.endsWith("</svg>")).toBe(true);
    expect(svg).toContain("20/10/2026");
    expect(svg).toContain("MÁS RÁPIDO");
    expect(svg).toContain("t/s &lt;generación&gt;"); // escapado
    expect(svg).toContain("45,0 t/s ▲".replace("45,0", "45,0"));
    expect(svg).not.toContain("<generación>");
  });
  it("las normalizadas solo salen si se piden, con el aviso de estimado", () => {
    expect(buildScoreboardSvg(base())).not.toContain("t/s por W");
    expect(buildScoreboardSvg(base(), { normalized: true })).toContain("t/s por W (est.)");
  });
  it("caben todas las métricas a cualquier tamaño 16:9 (todo escala con la altura)", () => {
    const c = base();
    for (const key of ["accuracy", "ttft", "pp", "degradation", "temp_max", "power_mean", "vram_peak", "tokens_per_wh", "tps_per_gib", "wh_per_ktok"]) {
      c.metrics.push(metric(key, `m-${key}`, [1, 2]));
    }
    for (const [width, height] of [[640, 360], [1280, 720], [1920, 1080]]) {
      const svg = buildScoreboardSvg(c, { width, height, normalized: true });
      expect(svg).toContain("m-vram_peak");
      expect(svg).toContain("m-wh_per_ktok");
      expect(svg).not.toContain("métricas más en Comparar");
    }
  });
});
