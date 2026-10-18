// Formularios de las suites de calidad: los campos vienen del servidor (`Suite.fields`) y aquí se
// convierten entre lo que se edita (texto, casillas) y los parámetros que acepta la API.
import type { Suite, SuiteField } from "../api/types";

export type FormState = Record<string, string | number | string[]>;

/** Lista de enteros desde «2048, 4096 8192»; null si algo no es un número. */
export function parseNumList(text: string): number[] | null {
  const parts = text.split(/[\s,;]+/).filter(Boolean);
  if (!parts.length) return null;
  const nums = parts.map((p) => Number(p.replace(",", ".")));
  return nums.every((n) => Number.isFinite(n)) ? nums : null;
}

/** «pregunta | respuesta» por línea → pares; las líneas sin separador se ignoran. */
export function parsePairs(text: string): { pregunta: string; respuesta: string }[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.split("|"))
    .filter((p) => p.length >= 2)
    .map((p) => ({ pregunta: p[0].trim(), respuesta: p.slice(1).join("|").trim() }))
    .filter((p) => p.pregunta && p.respuesta);
}

export function pairsToText(pairs: unknown): string {
  if (!Array.isArray(pairs)) return "";
  return pairs.map((p: { pregunta?: string; respuesta?: string }) => `${p.pregunta ?? ""} | ${p.respuesta ?? ""}`).join("\n");
}

/** Estado inicial del formulario a partir de los valores por defecto de la suite. */
export function initialState(suite: Suite): FormState {
  const out: FormState = {};
  for (const f of suite.fields ?? []) {
    const d = suite.defaults[f.key];
    if (f.type === "numlist") out[f.key] = Array.isArray(d) ? d.join(", ") : "";
    else if (f.type === "choices") out[f.key] = Array.isArray(d) ? (d as string[]) : [];
    else if (f.type === "pairs") out[f.key] = pairsToText(d);
    else out[f.key] = (d as string | number | undefined) ?? "";
  }
  return out;
}

/** Parámetros de la API desde el estado del formulario. Lanza Error con un mensaje legible. */
export function toParams(suite: Suite, state: FormState): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of suite.fields ?? []) {
    const v = state[f.key];
    out[f.key] = convert(f, v);
  }
  return out;
}

function convert(f: SuiteField, v: FormState[string] | undefined): unknown {
  switch (f.type) {
    case "number": {
      if (v === "" || v === undefined) throw new Error(`Falta «${f.label}»`);
      const n = Number(v);
      if (!Number.isFinite(n)) throw new Error(`«${f.label}» debe ser un número`);
      return n;
    }
    case "numlist": {
      const list = parseNumList(String(v ?? ""));
      if (!list) throw new Error(`«${f.label}»: lista de números separados por comas`);
      return list;
    }
    case "choices":
      return Array.isArray(v) && v.length ? v : null; // sin marcar = todos
    case "pairs":
      return parsePairs(String(v ?? ""));
    default:
      return String(v ?? "");
  }
}

/** Resumen legible de los parámetros para etiquetar una batalla o un run. */
export function describeScope(suite: Suite, state: FormState): string {
  const parts: string[] = [];
  for (const f of suite.fields ?? []) {
    if (f.type === "choices") {
      const n = Array.isArray(state[f.key]) ? (state[f.key] as string[]).length : 0;
      parts.push(n ? `${n} de ${f.choices?.length ?? "?"}` : "todas");
    }
  }
  return parts.join(" · ");
}
