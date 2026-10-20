import { describe, expect, it } from "vitest";
import type { CompareResponse, RunItem } from "../src/api/types";
import { itemsToRows, toCsv, toMarkdown, visibleMetrics } from "../src/lib/compare";

const item = (idx: number, prompt: string, response: string, over: Partial<RunItem> = {}): RunItem => ({
  id: idx + 100,
  idx,
  name: `prompt ${idx + 1}`,
  prompt,
  response,
  reasoning: null,
  metrics: { completion_tokens: 12, tps_client: 30.5, ttft_s: 0.2, finish_reason: "stop" },
  error: null,
  started_at: null,
  finished_at: null,
  ...over,
});

const cmp = (): CompareResponse => ({
  runs: [
    { id: 1, title: "#1 · lado A · qwen|7b.gguf", label: null, kind: "free", suite: "libre", suite_version: "1", suite_hash: "h", status: "done", battle_id: 3, side: "A", started_at: 0, base_url: null, metrics: {}, bench_rows: 0 },
    { id: 2, title: "#2 · lado B · llama.gguf", label: null, kind: "free", suite: "libre", suite_version: "1", suite_hash: "h", status: "done", battle_id: 3, side: "B", started_at: 0, base_url: null, metrics: {}, bench_rows: 0 },
  ],
  comparability: { level: "si", label: "Comparables", reasons: [], changes: ["modelo"] },
  config_diff: [
    { key: "modelo", factor: "modelo", values: ["qwen.gguf", "llama.gguf"], same: false },
    { key: "build", factor: "build", values: ["b1", "b1"], same: true },
  ],
  metrics: [{ key: "tps", label: "t/s", unit: "t/s", better: "high", digits: 1, values: [30.25, 45], best: [1] }],
  verdicts: [{ key: "tps", title: "Más rápido", run_index: 1, value: 45, runner_up: 30.25, margin_pct: 48.8 }],
  items: [{ prompt: "¿Cuánto es 2+2?\nResponde corto.", rep: 0, cells: [{ response: "4", reasoning: null, error: null, tokens: 1, tps: 1, ttft: 0.1, finish: "stop" }, null] }],
  series: [],
});

describe("comparar", () => {
  it("convierte ítems en filas por prompt y repetición, ordenadas por idx", () => {
    const rows = itemsToRows([item(2, "p1", "c"), item(0, "p1", "a"), item(1, "p2", "b")]);
    expect(rows.map((r) => [r.prompt, r.rep, r.cells[0]?.response])).toEqual([
      ["p1", 0, "a"],
      ["p2", 0, "b"],
      ["p1", 1, "c"],
    ]);
    expect(rows[0].cells[0]).toMatchObject({ tokens: 12, tps: 30.5, ttft: 0.2, finish: "stop" });
  });

  it("Markdown para el vault: YAML válido, mejor valor en negrita, solo lo que cambia y respuestas", () => {
    const text = toMarkdown(cmp(), new Date("2026-10-04T12:00:00Z"));
    const [, yaml] = text.split("---\n");
    expect(yaml).toContain("fecha_creacion: 2026-10-04");
    expect(yaml).toContain("tipo: proyecto");
    expect(yaml).toContain("fecha_limite: ~");
    expect(text).toContain("# Comparación Arena LLM — 04/10/2026");
    expect(text).toContain("cambia: modelo");
    expect(text).toContain("| t/s (t/s) | 30,25 | **45** |");
    expect(text).toContain("qwen\|7b.gguf"); // la barra no rompe la tabla
    expect(text).toContain("| modelo | qwen.gguf | llama.gguf |");
    expect(text).not.toContain("| build |");
    expect(text).toContain("> ¿Cuánto es 2+2?\n> Responde corto.");
    expect(text).toContain("_sin respuesta_");
    expect(text).toContain("- **Más rápido:** #2 · lado B · llama.gguf (45)");
  });

  it("CSV con punto y coma y comillas", () => {
    const csv = toCsv(cmp()).trim().split("\n");
    expect(csv[0]).toBe('"run";"titulo";"t/s (t/s)"');
    expect(csv[1]).toBe('"1";"#1 · lado A · qwen|7b.gguf";"30,25"');
  });
});

describe("comparar · etiquetas y notas", () => {
  it("el Markdown lista etiquetas y notas de cada run", () => {
    const c = cmp();
    c.runs[0].tags = ["M40", "Q4 K"];
    c.runs[0].notes = "primera pasada";
    const md = toMarkdown(c, new Date("2026-10-20T10:00:00Z"));
    expect(md).toContain("## Runs");
    expect(md).toContain("#M40 #Q4-K");
    expect(md).toContain("primera pasada");
  });
  it("sin etiquetas ni notas no añade la sección", () => {
    expect(toMarkdown(cmp(), new Date("2026-10-20T10:00:00Z"))).not.toContain("## Runs");
  });
});

describe("comparar · métricas normalizadas", () => {
  const withNorm = (): CompareResponse => {
    const c = cmp();
    c.metrics.push({ key: "tps_per_w", label: "t/s por W", unit: "t/s/W", better: "high", digits: 2, values: [0.2, 0.3], best: [1], group: "normalizada", estimated: true });
    return c;
  };
  it("las normalizadas se pueden ocultar", () => {
    expect(visibleMetrics(withNorm(), false).map((m) => m.key)).toEqual(["tps"]);
    expect(visibleMetrics(withNorm(), true).map((m) => m.key)).toEqual(["tps", "tps_per_w"]);
  });
  it("el Markdown y el CSV respetan el interruptor y marcan lo estimado", () => {
    const d = new Date("2026-10-20T10:00:00Z");
    expect(toMarkdown(withNorm(), d, false)).not.toContain("t/s por W");
    expect(toMarkdown(withNorm(), d, true)).toContain("_(estimado)_");
    expect(toCsv(withNorm(), false)).not.toContain("t/s por W");
    expect(toCsv(withNorm(), true)).toContain("t/s por W");
  });
});

describe("comparar · Markdown para el vault", () => {
  it("el frontmatter YAML es válido: abre y cierra con --- y cada línea es «clave: valor»", () => {
    const md = toMarkdown(cmp(), new Date("2026-10-20T10:00:00Z"));
    const lines = md.split("\n");
    expect(lines[0]).toBe("---");
    const end = lines.indexOf("---", 1);
    expect(end).toBeGreaterThan(1);
    const fm = lines.slice(1, end);
    for (const l of fm) expect(l).toMatch(/^[a-z_]+: .+$/);
    const keys = fm.map((l) => l.split(":")[0]);
    for (const k of ["fecha_creacion", "fecha_modificacion", "tipo", "categoria", "tags", "estado", "fecha_limite", "relacionado"]) {
      expect(keys).toContain(k);
    }
    expect(fm).toContain("fecha_creacion: 2026-10-20");
    expect(fm).toContain('relacionado: ["Arena LLM"]');
    expect(lines[end + 1].startsWith("# Comparación Arena LLM")).toBe(true);
  });
});
