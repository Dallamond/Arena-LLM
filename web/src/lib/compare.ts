// Utilidades puras de Comparar: filas de respuestas de un run y formato de exportación.
import type { CompareResponse, CompareRow, RunItem } from "../api/types";

/** Ítems de un run → filas (prompt, repetición) con una sola columna, como la matriz del servidor. */
export function itemsToRows(items: RunItem[]): CompareRow[] {
  const seen: Record<string, number> = {};
  return [...items]
    .sort((a, b) => a.idx - b.idx)
    .map((it) => {
      const prompt = it.prompt ?? it.name ?? `#${it.idx}`;
      const rep = seen[prompt] ?? 0;
      seen[prompt] = rep + 1;
      const m = it.metrics ?? {};
      const num = (v: unknown) => (typeof v === "number" ? v : null);
      return {
        prompt,
        rep,
        cells: [
          {
            response: it.response,
            reasoning: it.reasoning,
            error: it.error,
            tokens: num(m.completion_tokens),
            tps: num(m.tps_client),
            ttft: num(m.ttft_s),
            finish: typeof m.finish_reason === "string" ? m.finish_reason : null,
          },
        ],
      };
    });
}

const cellText = (v: unknown): string => {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2).replace(".", ",");
  if (Array.isArray(v)) return v.map(cellText).join(", ") || "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
};
const md = (s: string) => s.replace(/\|/g, "\|").replace(/\r?\n/g, " ");

/** Markdown para el vault (frontmatter YAML del tipo proyecto + tablas). */
export function toMarkdown(c: CompareResponse, date: Date = new Date()): string {
  const iso = date.toISOString().slice(0, 10);
  const [y, mo, d] = iso.split("-");
  const head = ["métrica", ...c.runs.map((r) => md(r.title))];
  const lines = [
    "---",
    `fecha_creacion: ${iso}`,
    `fecha_modificacion: ${iso}`,
    "tipo: proyecto",
    "categoria: tech",
    "tags: [tech, homelab]",
    "estado: activo",
    "fecha_limite: ~",
    'relacionado: ["Arena LLM"]',
    "---",
    `# Comparación Arena LLM — ${d}/${mo}/${y}`,
    "",
    `**${c.comparability.label}**` + (c.comparability.changes.length ? ` · cambia: ${c.comparability.changes.join(", ")}` : ""),
    ...c.comparability.reasons.map((r) => `- ${r}`),
    "",
  ];
  if (c.verdicts.length) {
    lines.push("## Veredictos", "");
    for (const v of c.verdicts) lines.push(`- **${v.title}:** ${md(c.runs[v.run_index].title)} (${cellText(v.value)})`);
    lines.push("");
  }
  lines.push("## Métricas", "", `| ${head.join(" | ")} |`, `|${head.map(() => "---").join("|")}|`);
  for (const m of c.metrics) {
    const vals = m.values.map((v, i) => (m.best.includes(i) ? `**${cellText(v)}**` : cellText(v)));
    lines.push(`| ${md(m.label)}${m.unit ? ` (${m.unit})` : ""} | ${vals.join(" | ")} |`);
  }
  const diff = c.config_diff.filter((r) => !r.same);
  if (diff.length) {
    lines.push("", "## Configuración que cambia", "", `| clave | ${c.runs.map((r) => md(r.title)).join(" | ")} |`, `|${["", ...c.runs].map(() => "---").join("|")}|`);
    for (const r of diff) lines.push(`| ${md(r.key)} | ${r.values.map((v) => md(cellText(v))).join(" | ")} |`);
  }
  if (c.items.length) {
    lines.push("", "## Respuestas", "");
    c.items.forEach((row, i) => {
      lines.push(`### Prompt ${i + 1}${row.rep ? ` (rep ${row.rep + 1})` : ""}`, "", `> ${row.prompt.replace(/\r?\n/g, "\n> ")}`, "");
      row.cells.forEach((cell, ci) => {
        lines.push(`**${md(c.runs[ci].title)}**`, "", cell?.response?.trim() || "_sin respuesta_", "");
      });
    });
  }
  return lines.join("\n") + "\n";
}

/** CSV de métricas (una fila por run), con ; como separador para Excel en español. */
export function toCsv(c: CompareResponse): string {
  const q = (s: string) => `"${s.replace(/"/g, '""')}"`;
  const head = ["run", "titulo", ...c.metrics.map((m) => `${m.label}${m.unit ? ` (${m.unit})` : ""}`)];
  const rows = c.runs.map((r, i) => [String(r.id), r.title, ...c.metrics.map((m) => cellText(m.values[i]))]);
  return [head, ...rows].map((row) => row.map(q).join(";")).join("\n") + "\n";
}
