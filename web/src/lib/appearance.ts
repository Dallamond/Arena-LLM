// Apariencia configurable (Ajustes → Apariencia): acento, contraste, tamaño, croquis y rejilla.
// Se guarda en el servidor (igual en todos los navegadores) y en localStorage para aplicarla
// antes de conectar y evitar el parpadeo.

import { watch } from "vue";
import type { Appearance } from "../api/types";
import { api, live } from "../api/live";

export const ACCENTS: { id: string; label: string; value: string }[] = [
  { id: "azul", label: "Azul plano", value: "#6cb4ff" },
  { id: "cian", label: "Cian", value: "#4dd8e6" },
  { id: "ambar", label: "Ámbar", value: "#ffb347" },
  { id: "verde", label: "Verde", value: "#7ee787" },
  { id: "violeta", label: "Violeta", value: "#c4a7ff" },
  { id: "blanco", label: "Blanco", value: "#e8f0ff" },
];

export const SCALES = [
  { value: 1, label: "Normal" },
  { value: 1.1, label: "Grande" },
  { value: 1.25, label: "Muy grande" },
];

export const DEFAULT_APPEARANCE: Appearance = {
  accent: ACCENTS[0].value,
  contrast: "normal",
  scale: 1,
  sketch: true,
  grid: "normal",
};

const CACHE_KEY = "arena.appearance";

export function normalize(a: Partial<Appearance> | null | undefined): Appearance {
  const out = { ...DEFAULT_APPEARANCE, ...(a ?? {}) };
  if (!/^#[0-9a-f]{6}$/i.test(out.accent)) out.accent = DEFAULT_APPEARANCE.accent;
  if (!SCALES.some((s) => s.value === out.scale)) out.scale = 1;
  if (out.contrast !== "alto") out.contrast = "normal";
  if (!["normal", "tenue", "off"].includes(out.grid)) out.grid = "normal";
  out.sketch = out.sketch !== false;
  return out;
}

/** Mezcla un color hex con negro (amount < 0) o blanco (amount > 0). */
export function shade(hex: string, amount: number): string {
  const n = parseInt(hex.slice(1), 16);
  const mix = (c: number) => Math.round(amount < 0 ? c * (1 + amount) : c + (255 - c) * amount);
  const r = mix((n >> 16) & 255);
  const g = mix((n >> 8) & 255);
  const b = mix(n & 255);
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`;
}

export function apply(a: Appearance): void {
  const root = document.documentElement;
  root.style.setProperty("--accent", a.accent);
  root.style.setProperty("--accent-soft", shade(a.accent, -0.55));
  root.style.setProperty("--zoom", String(a.scale));
  root.dataset.contrast = a.contrast;
  root.dataset.sketch = a.sketch ? "on" : "off";
  root.dataset.grid = a.grid;
}

export function readCached(): Appearance {
  try {
    return normalize(JSON.parse(localStorage.getItem(CACHE_KEY) ?? "null"));
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

export async function save(a: Appearance): Promise<void> {
  const v = normalize(a);
  apply(v);
  live.appearance = v;
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(v));
  } catch {
    /* sin almacenamiento: solo se pierde la caché local */
  }
  await api("/api/settings/appearance", { method: "PUT", body: JSON.stringify(v) });
}

/** Aplica la caché al arrancar y sigue los cambios que lleguen del servidor. */
export function initAppearance(): void {
  apply(readCached());
  watch(
    () => live.appearance,
    (a) => {
      if (!a) return;
      const v = normalize(a);
      apply(v);
      try {
        localStorage.setItem(CACHE_KEY, JSON.stringify(v));
      } catch {
        /* sin almacenamiento */
      }
    },
    { deep: true },
  );
}
