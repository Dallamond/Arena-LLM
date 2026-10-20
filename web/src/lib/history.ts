// Filtros del Historial: lógica pura (la vista solo dibuja los selectores).
import type { Run } from "../api/types";

export interface HistoryFilters {
  host: string;
  device: string;
  suite: string;
  status: string;
  tag: string;
}

export const EMPTY_FILTERS: HistoryFilters = { host: "", device: "", suite: "", status: "", tag: "" };
const KEY = "arena.historyFilters";

/** Valores distintos (ordenados) que aparecen en los runs, para rellenar un selector. */
export function uniqueValues(runs: Run[], pick: (r: Run) => string[]): string[] {
  return [...new Set(runs.flatMap(pick))].sort((a, b) => a.localeCompare(b, "es"));
}

/** Runs que cumplen todos los filtros y el texto de búsqueda (sin distinguir mayúsculas). */
export function filterRuns(
  runs: Run[],
  f: HistoryFilters & { text?: string },
  searchText: (r: Run) => string,
): Run[] {
  const q = (f.text ?? "").trim().toLowerCase();
  return runs.filter(
    (r) =>
      (!f.host || r.host_name === f.host) &&
      (!f.device || (r.device_names ?? []).includes(f.device)) &&
      (!f.suite || r.suite === f.suite) &&
      (!f.status || r.status === f.status) &&
      (!f.tag || (r.tags ?? []).includes(f.tag)) &&
      (!q || searchText(r).toLowerCase().includes(q)),
  );
}

export function loadFilters(): HistoryFilters {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (raw && typeof raw === "object") {
      const pick = (k: keyof HistoryFilters) => (typeof raw[k] === "string" ? raw[k] : "");
      return { host: pick("host"), device: pick("device"), suite: pick("suite"), status: pick("status"), tag: pick("tag") };
    }
  } catch {
    /* sin almacenamiento o JSON roto: filtros vacíos */
  }
  return { ...EMPTY_FILTERS };
}

export function saveFilters(f: HistoryFilters): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(f));
  } catch {
    /* solo se pierde la preferencia */
  }
}
