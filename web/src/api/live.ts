// Estado en vivo: un único EventSource a /api/events alimenta toda la GUI.

import { computed, reactive, ref } from "vue";
import type {
  Appearance,
  ConfigChange,
  CpuSample,
  DeviceInfo,
  Endpoint,
  GpuSample,
  HostState,
  Run,
  RunLive,
  Snapshot,
  ThresholdOverrides,
} from "./types";

export const HISTORY_POINTS = 120; // 2 min a 1 Hz

export interface Point {
  t: number;
  temp: number | null;
  power: number | null;
  util: number | null;
  mem: number | null;
}

type Connection = "connecting" | "open" | "closed";

const SELECTED_KEY = "arena.selectedHost";

function readSelected(): number | null {
  try {
    const v = localStorage.getItem(SELECTED_KEY);
    return v ? Number(v) : null;
  } catch {
    return null;
  }
}

export const live = reactive({
  connection: "connecting" as Connection,
  hosts: {} as Record<number, HostState>,
  metrics: {} as Record<number, Snapshot>,
  history: {} as Record<string, Point[]>,
  selectedId: readSelected(),
  endpoints: {} as Record<number, Endpoint[]>,
  changes: [] as ConfigChange[],
  runs: {} as Record<number, Run>,
  runLive: {} as Record<number, RunLive>,
  thresholds: {} as ThresholdOverrides,
  appearance: null as Partial<Appearance> | null,
});

// --- bus de eventos para vistas que necesitan cada mensaje (gráficas en vivo) ---
type Handler = (data: any) => void; // eslint-disable-line @typescript-eslint/no-explicit-any
const handlers: Record<string, Set<Handler>> = {};

/** Suscribe a un evento SSE; devuelve la función para darse de baja. */
export function onEvent(name: string, fn: Handler): () => void {
  (handlers[name] ??= new Set()).add(fn);
  return () => handlers[name]?.delete(fn);
}

function emit(name: string, data: unknown): void {
  handlers[name]?.forEach((fn) => fn(data));
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (r.status === 204) return undefined as T;
  const body = await r.json().catch(() => null);
  if (!r.ok) {
    const detail = body?.detail;
    throw new Error(typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join(" · ") : `HTTP ${r.status}`);
  }
  return body as T;
}

export async function refreshEndpoints(): Promise<void> {
  const list = await api<Endpoint[]>("/api/endpoints");
  const byHost: Record<number, Endpoint[]> = {};
  for (const e of list) (byHost[e.host_pk] ??= []).push(e);
  live.endpoints = byHost;
}

export async function refreshRuns(): Promise<void> {
  const list = await api<Run[]>("/api/runs?limit=300");
  const map: Record<number, Run> = {};
  for (const r of list) map[r.id] = r;
  live.runs = map;
}

export const runList = computed(() => Object.values(live.runs).sort((a, b) => b.id - a.id));
export const activeRuns = computed(() => runList.value.filter((r) => r.status === "running" || r.status === "pending"));

/** Reloj de 1 s para "hace X s" y detección de datos viejos. */
export const now = ref(Date.now() / 1000);

export const hostList = computed(() => Object.values(live.hosts).sort((a, b) => a.id - b.id));

export const currentHost = computed<HostState | null>(() => {
  const list = hostList.value;
  if (!list.length) return null;
  return (live.selectedId !== null && live.hosts[live.selectedId]) || list[0];
});

export const currentSnapshot = computed<Snapshot | null>(() =>
  currentHost.value ? live.metrics[currentHost.value.id] ?? null : null,
);

/** Segundos desde el último dato bueno del equipo actual. */
export const staleness = computed<number | null>(() => {
  const h = currentHost.value;
  return h?.last_ok ? Math.max(0, now.value - h.last_ok) : null;
});

export function selectHost(id: number): void {
  live.selectedId = id;
  try {
    localStorage.setItem(SELECTED_KEY, String(id));
  } catch {
    /* almacenamiento no disponible: solo se pierde la preferencia */
  }
}

export function gpus(host: HostState | null): DeviceInfo[] {
  return (host?.devices ?? [])
    .filter((d) => d.kind === "gpu")
    .sort((a, b) => (a.index ?? 99) - (b.index ?? 99) || a.device_id.localeCompare(b.device_id));
}

export function cpu(host: HostState | null): DeviceInfo | null {
  return host?.devices.find((d) => d.kind === "cpu") ?? null;
}

export function gpuSample(snap: Snapshot | null, id: string): GpuSample | undefined {
  return snap?.devices[id] as GpuSample | undefined;
}

export function cpuSample(snap: Snapshot | null, id: string): CpuSample | undefined {
  return snap?.devices[id] as CpuSample | undefined;
}

export function historyKey(hostId: number, deviceId: string): string {
  return `${hostId}|${deviceId}`;
}

function pushHistory(hostId: number, snap: Snapshot): void {
  const t = snap.t ?? Date.now() / 1000;
  for (const [id, s] of Object.entries(snap.devices)) {
    const key = historyKey(hostId, id);
    const arr = (live.history[key] ??= []);
    const g = s as GpuSample;
    const c = s as CpuSample;
    arr.push({
      t,
      temp: g.temp_c ?? null,
      power: g.power_w ?? null,
      util: g.util_gpu_pct ?? c.util_pct ?? null,
      mem: g.mem_used_mib ?? null,
    });
    if (arr.length > HISTORY_POINTS) arr.splice(0, arr.length - HISTORY_POINTS);
  }
  if (snap.ram) {
    const arr = (live.history[historyKey(hostId, "ram")] ??= []);
    arr.push({ t, temp: null, power: null, util: null, mem: snap.ram.used_mib });
    if (arr.length > HISTORY_POINTS) arr.splice(0, arr.length - HISTORY_POINTS);
  }
}

let source: EventSource | null = null;
/** Reloj del navegador − reloj del servidor (segundos). */
let clockOffset = 0;

/** Hora actual en el reloj del servidor (epoch s). */
export function serverNow(): number {
  return Date.now() / 1000 - clockOffset;
}

export function connect(url = "/api/events"): void {
  if (source) return;
  refreshEndpoints().catch(() => {});
  refreshRuns().catch(() => {});
  api<Record<string, unknown>>("/api/settings")
    .then((s) => {
      live.thresholds = (s.thresholds as ThresholdOverrides) ?? {};
      live.appearance = (s.appearance as Partial<Appearance>) ?? {};
    })
    .catch(() => {});
  setInterval(() => (now.value = Date.now() / 1000), 1000);
  source = new EventSource(url);
  source.onopen = () => {
    live.connection = "open";
    // Tras una reconexión se recupera lo que se haya perdido
    refreshEndpoints().catch(() => {});
    refreshRuns().catch(() => {});
  };
  source.onerror = () => (live.connection = "closed"); // EventSource reintenta solo
  source.addEventListener("hello", (e) => {
    const { t } = JSON.parse((e as MessageEvent).data) as { t: number };
    clockOffset = Date.now() / 1000 - t;
  });
  source.addEventListener("host", (e) => {
    const h = JSON.parse((e as MessageEvent).data) as HostState;
    const prev = live.hosts[h.id];
    // last_ok llega con el reloj del servidor: se pasa al del navegador con el desfase de "hello"
    const fromServer = h.last_ok !== null ? h.last_ok + clockOffset : null;
    h.last_ok = Math.max(prev?.last_ok ?? 0, fromServer ?? 0) || null;
    live.hosts[h.id] = h;
  });
  source.addEventListener("host_removed", (e) => {
    const { id } = JSON.parse((e as MessageEvent).data) as { id: number };
    delete live.hosts[id];
    delete live.metrics[id];
  });
  source.addEventListener("metrics", (e) => {
    const { host, snapshot } = JSON.parse((e as MessageEvent).data) as { host: number; snapshot: Snapshot };
    live.metrics[host] = snapshot;
    pushHistory(host, snapshot);
    const h = live.hosts[host];
    // Al conectar, el servidor reenvía las últimas métricas guardadas: solo cuentan como
    // dato fresco si el equipo está en línea. Reloj del navegador, el mismo que `now`.
    if (h && h.status === "online") h.last_ok = Date.now() / 1000;
    emit("metrics", { host, snapshot });
  });
  const on = (name: string, fn: (d: any) => void) => // eslint-disable-line @typescript-eslint/no-explicit-any
    source!.addEventListener(name, (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      fn(data);
      emit(name, data);
    });
  on("endpoints", (d: { host: number; endpoints: Endpoint[] }) => (live.endpoints[d.host] = d.endpoints));
  on("config_change", (d: ConfigChange) => live.changes.unshift(d));
  on("run", (r: Run) => {
    live.runs[r.id] = r;
    if (r.status !== "running") delete live.runLive[r.id];
  });
  on("run_live", (d: RunLive) => (live.runLive[d.run] = { ...live.runLive[d.run], ...d }));
  on("run_item", () => {});
  on("settings", (d: { key: string; value: unknown }) => {
    if (d.key === "thresholds") live.thresholds = d.value as ThresholdOverrides;
    if (d.key === "appearance") live.appearance = d.value as Partial<Appearance>;
  });
}
