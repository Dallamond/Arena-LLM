// Imagen del marcador de una comparación o batalla: SVG propio (sin librerías ni CDN) y PNG vía canvas.
// El SVG usa fuentes del sistema: un <img> con SVG no puede cargar fuentes web.
import type { CompareResponse } from "../api/types";
import { fmt } from "./format";

export interface ScoreboardOptions {
  width?: number;
  height?: number;
  /** Incluye las métricas normalizadas (por GiB, por W, por ktok). */
  normalized?: boolean;
  date?: Date;
}

/** Métricas que cuentan en la imagen, en orden de importancia. */
const KEYS = ["accuracy", "tps", "ttft", "pp", "degradation", "temp_max", "power_mean", "vram_peak", "tokens_per_wh"];
const NORMALIZED = ["tps_per_gib", "tps_per_w", "wh_per_ktok"];
const RUN_COLORS = ["#4cc9f0", "#ff9f43", "#f472b6", "#a3e635", "#facc15", "#60a5fa"];
const BG = "#000000";
const PANEL = "#1c1c1e";
const INK = "#f2f2f7";
const FAINT = "#8e8e93";
const LINE = "#38383a";
const FONT = "Inter, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";
const MONO = "'JetBrains Mono', Consolas, 'Courier New', monospace";

export const runColor = (i: number) => RUN_COLORS[i % RUN_COLORS.length];

export const escapeXml = (s: string): string =>
  s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);

/** Recorta con puntos suspensivos para que quepa en `max` caracteres. */
export const clip = (s: string, max: number): string => (s.length <= max ? s : `${s.slice(0, Math.max(1, max - 1))}…`);

const LEVEL_COLOR: Record<string, string> = { si: "#7ee787", parcial: "#ffb347", no: "#ff6b6b" };

/** Texto «#id · lado · modelo» corto para cabeceras de columna. */
const runName = (r: CompareResponse["runs"][number]): string => (r.side ? `Lado ${r.side} · #${r.id}` : `#${r.id}`);

export function buildScoreboardSvg(c: CompareResponse, opts: ScoreboardOptions = {}): string {
  const W = opts.width ?? 1280;
  const H = opts.height ?? 720;
  const k = H / 720; // todo escala con la altura: 1080p = 1,5×
  const pad = 48 * k;
  const iso = (opts.date ?? new Date()).toISOString().slice(0, 10);
  const [y, mo, d] = iso.split("-");
  const n = Math.max(1, c.runs.length);

  const wanted = opts.normalized ? [...KEYS, ...NORMALIZED] : KEYS;
  const metrics = wanted.map((key) => c.metrics.find((m) => m.key === key)).filter((m) => !!m);

  const out: string[] = [];
  const text = (x: number, yy: number, size: number, fill: string, s: string, extra = "") =>
    out.push(`<text x="${x}" y="${yy}" font-size="${size * k}" fill="${fill}" ${extra}>${escapeXml(s)}</text>`);

  out.push(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="${FONT}" role="img" aria-label="Marcador de Arena LLM">`,
    `<rect width="${W}" height="${H}" fill="${BG}"/>`,
  );

  // Cabecera
  text(pad, pad + 14 * k, 30, INK, "Arena LLM · Marcador", 'font-weight="700"');
  text(W - pad, pad + 14 * k, 16, FAINT, `${d}/${mo}/${y}`, 'text-anchor="end"');
  const level = c.comparability.level ?? "";
  const badgeColor = LEVEL_COLOR[level] ?? FAINT;
  const badgeY = pad + 44 * k;
  out.push(`<circle cx="${pad + 6 * k}" cy="${badgeY - 5 * k}" r="${5 * k}" fill="${badgeColor}"/>`);
  text(pad + 20 * k, badgeY, 16, badgeColor, c.comparability.label, 'font-weight="600"');
  const why = c.comparability.reasons[0] ?? (c.comparability.changes.length ? `Cambia: ${c.comparability.changes.join(", ")}` : "");
  if (why) text(pad + 20 * k + (c.comparability.label.length * 9 + 14) * k, badgeY, 14, FAINT, clip(why, Math.floor((W - 2 * pad) / (7.5 * k) - c.comparability.label.length - 4)));

  // Veredictos
  let cursor = badgeY + 26 * k;
  const verdicts = c.verdicts.slice(0, 5);
  if (verdicts.length) {
    const gap = 12 * k;
    const cw = (W - 2 * pad - gap * (verdicts.length - 1)) / verdicts.length;
    const ch = 92 * k;
    verdicts.forEach((v, i) => {
      const x = pad + i * (cw + gap);
      const col = runColor(v.run_index);
      out.push(`<rect x="${x}" y="${cursor}" width="${cw}" height="${ch}" rx="${14 * k}" fill="${PANEL}" stroke="${col}" stroke-opacity="0.6"/>`);
      text(x + 14 * k, cursor + 24 * k, 12, FAINT, v.title.toUpperCase(), 'letter-spacing="0.06em"');
      text(x + 14 * k, cursor + 52 * k, 20, col, clip(runName(c.runs[v.run_index]), Math.floor(cw / (11 * k))), 'font-weight="700"');
      const unit = c.metrics.find((m) => m.key === v.key)?.unit ?? "";
      const digits = v.key === "ttft" ? 2 : v.key === "tps" ? 1 : 0;
      text(x + 14 * k, cursor + 76 * k, 14, INK, fmt(v.value, digits, unit), `font-family="${MONO}"`);
    });
    cursor += ch + 20 * k;
  }

  // Tabla de métricas
  const rowH = 30 * k;
  const room = Math.max(0, Math.floor((H - pad - cursor - 34 * k) / rowH));
  const rows = metrics.slice(0, room);
  const labelW = Math.min(360 * k, (W - 2 * pad) * 0.34);
  const colW = (W - 2 * pad - labelW) / n;
  c.runs.forEach((r, i) => {
    const x = pad + labelW + i * colW;
    out.push(`<rect x="${x}" y="${cursor - 12 * k}" width="${10 * k}" height="${10 * k}" rx="2" fill="${runColor(i)}"/>`);
    text(x + 16 * k, cursor - 3 * k, 14, FAINT, clip(runName(r), Math.floor((colW - 16 * k) / (8 * k))), 'font-weight="600"');
  });
  out.push(`<line x1="${pad}" x2="${W - pad}" y1="${cursor + 6 * k}" y2="${cursor + 6 * k}" stroke="${LINE}"/>`);
  // La cifra más larga manda: se encoge el tamaño (fuente mono ≈ 0,62 em por carácter) hasta que quepa en la columna
  const cell = (m: (typeof rows)[number], i: number) => `${fmt(m.values[i], m.digits, m.unit)}${m.best.includes(i) ? " ▲" : ""}`;
  const longest = Math.max(1, ...rows.flatMap((m) => m.values.map((_, i) => cell(m, i).length)));
  const valueSize = Math.min(16, (colW - 24 * k) / (longest * 0.62 * k));
  rows.forEach((m, ri) => {
    const yy = cursor + 6 * k + (ri + 1) * rowH - 9 * k;
    const label = `${m.label}${m.estimated ? " (est.)" : ""}`;
    text(pad, yy, 14, FAINT, clip(label, Math.floor(labelW / (7.4 * k))));
    m.values.forEach((_, i) => {
      const best = m.best.includes(i);
      text(pad + labelW + i * colW + 16 * k, yy, valueSize, best ? INK : "#c7c7cc", cell(m, i), `font-family="${MONO}"${best ? ' font-weight="700"' : ""}`);
    });
  });
  if (metrics.length > rows.length) text(pad, H - pad + 6 * k, 12, FAINT, `+${metrics.length - rows.length} métricas más en Comparar`);

  out.push("</svg>");
  return out.join("");
}

/** SVG → PNG con un canvas del mismo tamaño. Solo en el navegador. */
export async function svgToPngBlob(svg: string, width: number, height: number): Promise<Blob> {
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const img = new Image();
    img.width = width;
    img.height = height;
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("No se pudo dibujar la imagen del marcador"));
      img.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("El navegador no permite dibujar en un canvas");
    ctx.drawImage(img, 0, 0, width, height);
    return await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("No se pudo crear el PNG"))), "image/png"),
    );
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Genera el PNG del marcador (por defecto 1280×720; 1920×1080 para vídeo). */
export function scoreboardPng(c: CompareResponse, opts: ScoreboardOptions = {}): Promise<Blob> {
  const width = opts.width ?? 1280;
  const height = opts.height ?? 720;
  return svgToPngBlob(buildScoreboardSvg(c, opts), width, height);
}
