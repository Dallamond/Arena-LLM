import { describe, expect, it } from "vitest";
import type { FitResponse } from "../src/api/types";
import { quantQuality, recommend } from "../src/lib/recommend";

const GIB = 1024 ** 3;
const short = (n: string | null | undefined) => n ?? "?";

function model(over: {
  name: string;
  params: number;
  type?: string;
  need: number;
  verdict?: "gpu" | "split" | "ram";
  free?: number[];
  ctx?: number;
  arch?: string;
}): FitResponse {
  const free = over.free ?? [12 * GIB];
  return {
    path: over.name,
    estimated: true,
    model: {
      name: over.name,
      architecture: over.arch ?? "llama",
      general_type: "model",
      file_type: over.type ?? "Q4_K_M",
      size_label: null,
      n_params: over.params,
      context_length: over.ctx ?? 32768,
      expert_count: null,
      file_size: 0,
    },
    estimate: { kind: "model" },
    fit: {
      verdict: over.verdict ?? "gpu",
      label: null,
      need_full_gpu: over.need,
      gpus: free.map((f, i) => ({
        device_id: `gpu${i}`,
        name: `GPU ${i}`,
        need: over.need,
        free: f,
        fits: over.need <= f,
        fits_if_empty: true,
      })),
    },
  } as unknown as FitResponse;
}

const item = (r: FitResponse) => ({ path: r.path, r });

describe("recomendación de modelos", () => {
  it("prefiere el modelo mayor que cabe con margen frente a uno pequeño casi sin cuantizar", () => {
    const small = model({ name: "peq", params: 7e9, type: "F16", need: 11 * GIB });
    const big = model({ name: "grande", params: 14e9, type: "Q4_K_M", need: 9 * GIB });
    const rec = recommend([item(small), item(big)], "auto", 8192, short);
    expect(rec.get("grande")?.rank).toBe(1);
    expect(rec.has("peq")).toBe(false); // además no cabe con margen del 90 %
  });

  it("descarta lo que no cabe entero, los embeddings y los de contexto insuficiente", () => {
    const no = model({ name: "no", params: 70e9, need: 40 * GIB });
    const emb = model({ name: "emb", params: 1e9, need: 2 * GIB, arch: "nomic-bert" });
    const short_ctx = model({ name: "corto", params: 7e9, need: 6 * GIB, ctx: 4096 });
    const ok = model({ name: "ok", params: 3e9, need: 3 * GIB });
    const rec = recommend([no, emb, short_ctx, ok].map(item), "auto", 8192, short);
    expect([...rec.keys()]).toEqual(["ok"]);
  });

  it("deja solo la mejor cuantización de cada familia", () => {
    const q4 = model({ name: "fam", params: 8e9, type: "Q4_K_M", need: 5 * GIB });
    const q8 = model({ name: "fam", params: 8e9, type: "Q8_0", need: 9 * GIB });
    q4.path = "fam-q4";
    q8.path = "fam-q8";
    const rec = recommend([item(q4), item(q8)], "auto", 8192, short);
    expect([...rec.keys()]).toEqual(["fam-q8"]);
  });

  it("con GPU destino solo cuenta lo que cabe en ella", () => {
    const m = model({ name: "m", params: 20e9, need: 20 * GIB, free: [10 * GIB, 24 * GIB] });
    expect(recommend([item(m)], "gpu0", 8192, short).size).toBe(0);
    expect(recommend([item(m)], "gpu1", 8192, short).get("m")?.where).toBe("GPU 1");
  });

  it("solo recomienda los cercanos al mejor y hasta tres", () => {
    const ms = [30e9, 28e9, 26e9, 25e9, 5e9].map((p, i) => model({ name: `m${i}`, params: p, need: 2 * GIB }));
    const rec = recommend(ms.map(item), "auto", 8192, short);
    expect([...rec.keys()]).toEqual(["m0", "m1", "m2"]);
    expect(rec.has("m4")).toBe(false);
  });

  it("sin datos de cuantización no inventa calidad alta", () => {
    expect(quantQuality(null)).toBeLessThan(quantQuality("Q4_K_M"));
    expect(quantQuality("Q2_K")).toBeLessThan(quantQuality("Q4_K_M"));
  });
});
