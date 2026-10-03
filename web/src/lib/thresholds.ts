// Umbrales térmicos derivados de cada dispositivo (HOJA-DE-RUTA §1.5).
// Sin cifras de una tarjeta concreta: se parte de la temperatura de slowdown que
// reporta el dispositivo; si no la reporta, valores por defecto por fabricante.
// El usuario puede fijarlos por dispositivo en Ajustes → Umbrales.

import type { DeviceInfo, GpuSample, ThresholdOverrides } from "../api/types";
import { isNum, throttleReasons } from "./format";

export const WARN_MARGIN_C = 10;
export const CRIT_MARGIN_C = 5;

const PROVIDER_DEFAULTS: Record<string, { warn: number; crit: number }> = {
  nvidia: { warn: 80, crit: 85 },
};
const GENERIC_DEFAULT = { warn: 80, crit: 85 };

export interface Thresholds {
  warn: number;
  crit: number;
  source: "dispositivo" | "por defecto" | "ajustes";
}

/** Prioridad: Ajustes → slowdown del dispositivo → valor por defecto del fabricante (igual que el servidor). */
export function thresholdsFor(
  dev: Pick<DeviceInfo, "provider" | "temp_slowdown_c"> & { device_id?: string },
  overrides?: ThresholdOverrides,
): Thresholds {
  let t: Thresholds;
  if (isNum(dev.temp_slowdown_c)) {
    t = { warn: dev.temp_slowdown_c - WARN_MARGIN_C, crit: dev.temp_slowdown_c - CRIT_MARGIN_C, source: "dispositivo" };
  } else {
    t = { ...(PROVIDER_DEFAULTS[dev.provider] ?? GENERIC_DEFAULT), source: "por defecto" };
  }
  const o = dev.device_id ? overrides?.[dev.device_id] : undefined;
  if (o && isNum(o.warn)) t = { ...t, warn: o.warn, source: "ajustes" };
  if (o && isNum(o.crit)) t = { ...t, crit: o.crit, source: "ajustes" };
  return t;
}

export type Level = "ok" | "warn" | "crit" | "unknown";

export interface DeviceHealth {
  level: Level;
  reasons: string[];
}

export function gpuHealth(dev: DeviceInfo, s: GpuSample | undefined, overrides?: ThresholdOverrides): DeviceHealth {
  if (!s) return { level: "unknown", reasons: ["sin lectura"] };
  const t = thresholdsFor(dev, overrides);
  const reasons: string[] = [];
  let level: Level = "ok";
  if (isNum(s.temp_c)) {
    if (s.temp_c >= t.crit) {
      level = "crit";
      reasons.push(`${Math.round(s.temp_c)} °C ≥ ${t.crit} °C`);
    } else if (s.temp_c >= t.warn) {
      level = "warn";
      reasons.push(`${Math.round(s.temp_c)} °C ≥ ${t.warn} °C`);
    }
  }
  const throttling = throttleReasons(s.throttle);
  if (throttling.length) {
    if (level === "ok") level = "warn";
    reasons.push(`throttling: ${throttling.join(", ")}`);
  }
  if (!isNum(s.temp_c) && level === "ok") level = "unknown";
  return { level, reasons };
}
