// Formato de cifras. Un valor ausente se muestra como "sin datos", nunca como 0.

export const NO_DATA = "sin datos";

export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

export function fmt(v: number | null | undefined, digits = 0, unit = ""): string {
  if (!isNum(v)) return NO_DATA;
  const s = v.toLocaleString("es-ES", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return unit ? `${s} ${unit}` : s;
}

export function gib(mib: number | null | undefined, digits = 1): string {
  return isNum(mib) ? fmt(mib / 1024, digits, "GiB") : NO_DATA;
}

/** "8,1 / 12,0 GiB" o "sin datos". */
export function gibPair(used: number | null | undefined, total: number | null | undefined): string {
  if (!isNum(used) || !isNum(total)) return NO_DATA;
  return `${fmt(used / 1024, 1)} / ${fmt(total / 1024, 1)} GiB`;
}

export function ratio(used: number | null | undefined, total: number | null | undefined): number | null {
  if (!isNum(used) || !isNum(total) || total <= 0) return null;
  return Math.min(1, Math.max(0, used / total));
}

export function ago(seconds: number | null): string {
  if (seconds === null) return "nunca";
  if (seconds < 2) return "ahora";
  if (seconds < 60) return `hace ${Math.round(seconds)} s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)} min`;
  return `hace ${Math.round(seconds / 3600)} h`;
}

/** Número de figura con dos cifras: FIG.01 */
export function fig(n: number): string {
  return `FIG.${String(n).padStart(2, "0")}`;
}

const THROTTLE_LABELS: Record<string, string> = {
  sw_power_cap: "límite de potencia",
  hw_slowdown: "freno HW",
  sw_thermal: "térmico SW",
  hw_thermal: "térmico HW",
  hw_power_brake: "freno de potencia",
};

/** Motivos de throttling legibles (ignora reposo y ajustes de aplicación). */
export function throttleReasons(list: string[] | null | undefined): string[] {
  if (!list) return [];
  return list.filter((r) => r in THROTTLE_LABELS).map((r) => THROTTLE_LABELS[r]);
}
