// Estado en vivo: un único EventSource a /api/events alimenta toda la GUI.

import { computed, reactive, ref } from "vue";
import type { CpuSample, DeviceInfo, GpuSample, HostState, Snapshot } from "./types";

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
});

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

export function connect(url = "/api/events"): void {
  if (source) return;
  setInterval(() => (now.value = Date.now() / 1000), 1000);
  source = new EventSource(url);
  source.onopen = () => (live.connection = "open");
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
  });
}
