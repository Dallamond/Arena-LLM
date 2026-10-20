// Recomendación de modelos para el hardware actual (ESTIMADO).
// Entre los GGUF que caben ENTEROS en la memoria de la GPU (con margen), gana el que más
// "parámetros efectivos" tiene: parámetros × calidad de la cuantización. Es una heurística:
// un modelo mayor con cuantización razonable suele superar a uno menor casi sin cuantizar.
// No hay umbrales de VRAM ni nombres de modelos: todo sale de la cabecera del GGUF y de la
// memoria libre que mide el equipo.
import type { FitResponse } from "../api/types";

/** Fracción máxima de la memoria libre que puede ocupar el modelo (deja hueco al escritorio y a picos). */
export const MARGIN = 0.9;
/** Un modelo es recomendable si llega a esta fracción del score del mejor. */
export const CLOSE_TO_BEST = 0.75;
/** Máximo de modelos recomendados (de familias distintas). */
export const MAX_RECOMMENDED = 3;

/** Calidad relativa aproximada de cada cuantización frente al modelo sin cuantizar. */
const QUALITY: [RegExp, number][] = [
  [/^(F32|F16|BF16)$/, 1],
  [/^Q8/, 0.99],
  [/^Q6/, 0.97],
  [/^Q5/, 0.95],
  [/^(Q4_K|IQ4|Q4_1|MXFP4)/, 0.92],
  [/^Q4_0/, 0.89],
  [/^(Q3_K_L|Q3_K_M|IQ3_M|IQ3_S)/, 0.8],
  [/^(Q3|IQ3)/, 0.75],
  [/^(Q2|IQ2|TQ2)/, 0.5],
  [/^(IQ1|TQ1)/, 0.35],
];
/** Cuantización desconocida: se asume la media (no se inventa un valor alto). */
const QUALITY_UNKNOWN = 0.85;

/** Arquitecturas que no son modelos de chat (embeddings, visión, voz). */
const NOT_CHAT = /bert|clip|whisper|siglip|t5encoder|rerank/i;

export function quantQuality(fileType: string | null | undefined): number {
  const t = (fileType ?? "").toUpperCase();
  return QUALITY.find(([re]) => re.test(t))?.[1] ?? QUALITY_UNKNOWN;
}

export interface Recommendation {
  /** 1 = mejor opción; 2 y 3 = también recomendados. */
  rank: number;
  score: number;
  /** GPU donde se evaluó ("varias GPU" si necesita repartirse). */
  where: string;
  reason: string;
}

export interface Candidate {
  path: string;
  r: FitResponse | null;
}

function sizeText(nParams: number): string {
  return nParams >= 1e9 ? `${(nParams / 1e9).toFixed(1)} B` : `${(nParams / 1e6).toFixed(0)} M`;
}

/**
 * @param target "auto" (cualquier GPU) o el `device_id` elegido como destino.
 * @param ctxPerSlot contexto por slot elegido: se descartan modelos entrenados con menos.
 * @param shortName nombre corto de GPU para el motivo.
 * @param bandwidth ancho de banda efectivo medido (GB/s, ESTIMADO) por `device_id`: con «Automático», entre las GPU
 *   donde cabe se elige la más rápida medida en vez de la que tiene más memoria libre.
 */
export function recommend(
  items: Candidate[],
  target: string,
  ctxPerSlot: number,
  shortName: (n: string | null | undefined) => string,
  bandwidth: Record<string, number> = {},
): Map<string, Recommendation> {
  const scored: (Recommendation & { path: string; family: string })[] = [];
  for (const { path, r } of items) {
    if (!r || r.estimate.kind !== "model") continue;
    const m = r.model;
    if (NOT_CHAT.test(m.architecture ?? "") || NOT_CHAT.test(m.general_type ?? "")) continue;
    if (!(m.n_params > 0)) continue;
    if (m.context_length && ctxPerSlot > m.context_length) continue;
    const need = r.fit.need_full_gpu;
    if (typeof need !== "number") continue;

    let where: string | null = null;
    let fastest = false;
    if (r.fit.verdict === "gpu") {
      // La GPU con más memoria libre entre las que lo alojan con margen (o la elegida).
      const ok = r.fit.gpus
        .filter((g) => g.fits && typeof g.free === "number" && need <= g.free * MARGIN)
        .filter((g) => target === "auto" || g.device_id === target)
        .sort((a, b) => (bandwidth[b.device_id] ?? 0) - (bandwidth[a.device_id] ?? 0) || (b.free ?? 0) - (a.free ?? 0));
      if (ok.length) {
        where = shortName(ok[0].name);
        if (target === "auto" && ok.length > 1 && bandwidth[ok[0].device_id] > 0) fastest = true;
      }
    } else if (r.fit.verdict === "split" && target === "auto") {
      const free = r.fit.gpus.reduce((a, g) => a + (g.free ?? 0), 0);
      if (need <= free * MARGIN) where = "varias GPU";
    }
    if (!where) continue;

    scored.push({
      path,
      family: (m.name ?? path).toLowerCase(),
      rank: 0,
      score: m.n_params * quantQuality(m.file_type),
      where,
      reason: `${sizeText(m.n_params)} en ${m.file_type ?? "?"}: cabe entero en ${where} con margen${fastest ? " (la GPU con más ancho de banda medido)" : ""}. Estimación; confírmalo midiendo en Calidad o Batalla.`,
    });
  }

  // De cada familia (mismo nombre en varias cuantizaciones) solo la mejor.
  const best = new Map<string, (typeof scored)[number]>();
  for (const s of scored) if (!best.has(s.family) || s.score > best.get(s.family)!.score) best.set(s.family, s);
  const ranked = [...best.values()].sort((a, b) => b.score - a.score || a.path.localeCompare(b.path));
  const out = new Map<string, Recommendation>();
  if (!ranked.length) return out;
  const top = ranked[0].score;
  ranked
    .filter((s) => s.score >= top * CLOSE_TO_BEST)
    .slice(0, MAX_RECOMMENDED)
    .forEach((s, i) => out.set(s.path, { rank: i + 1, score: s.score, where: s.where, reason: s.reason }));
  return out;
}
