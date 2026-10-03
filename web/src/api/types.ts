// Espejo del contrato del agente (agent/model.py, agent_api 1) y de la API del servidor.
// Regla: null = el equipo no expone el dato. Nunca se sustituye por 0.

export interface HostInfo {
  host_id: string;
  hostname: string;
  os: string;
  os_version: string | null;
  cpu_model: string | null;
  cpu_cores: number | null;
  cpu_threads: number | null;
  ram_total_mib: number | null;
}

export interface DeviceInfo {
  device_id: string;
  provider: string;
  kind: "gpu" | "cpu" | string;
  name: string | null;
  index: number | null;
  uuid: string | null;
  pci_bus_id: string | null;
  memory_total_mib: number | null;
  power_limit_w: number | null;
  power_limit_max_w: number | null;
  temp_slowdown_c: number | null;
  temp_shutdown_c: number | null;
  driver: string | null;
  driver_model: string | null;
  compute_capability: string | null;
  cores: number | null;
  threads: number | null;
  fields_unavailable: string[];
  color_index: number | null;
}

export interface GpuSample {
  temp_c: number | null;
  power_w: number | null;
  power_limit_w: number | null;
  util_gpu_pct: number | null;
  util_mem_pct: number | null;
  mem_used_mib: number | null;
  mem_total_mib: number | null;
  clock_sm_mhz: number | null;
  clock_mem_mhz: number | null;
  fan_pct: number | null;
  pstate: string | null;
  throttle_mask: number | null;
  throttle: string[] | null;
  pcie_gen: number | null;
  pcie_width: number | null;
}

export interface CpuSample {
  util_pct: number | null;
  freq_mhz: number | null;
}

export interface RamSample {
  used_mib: number | null;
  total_mib: number | null;
}

export interface Snapshot {
  t: number | null;
  interval_s: number | null;
  devices: Record<string, GpuSample | CpuSample>;
  ram: RamSample | null;
  errors: Record<string, string>;
}

export type HostStatus = "connecting" | "online" | "offline" | "unauthorized" | "error";

export interface HostState {
  id: number;
  agent_url: string;
  name: string;
  status: HostStatus;
  error: string | null;
  has_token: boolean;
  last_ok: number | null;
  agent_version: string | null;
  agent_api: number | null;
  simulated: string | null;
  host: HostInfo | null;
  devices: DeviceInfo[];
  providers: string[];
  errors: Record<string, string>;
}

export interface ProcessGpuUse {
  device_id: string;
  mem_used_mib: number | null;
}

export interface DetectedServer {
  pid: number;
  engine: string;
  exe: string | null;
  started_at: string | null;
  argv: string[];
  flags: Record<string, unknown>;
  unknown: Record<string, unknown>;
  positional: string[];
  model_path: string | null;
  model_file: string | null;
  host: string;
  port: number | null;
  port_source: "flag" | "default";
  devices: ProcessGpuUse[];
  gpu_link: string | null;
}

export interface ServersResponse {
  servers: DetectedServer[];
  errors: Record<string, string>;
  detected_at: number;
}

// --- Servidores detectados (F3) ---------------------------------------------

export interface EndpointSnapshot {
  engine: string | null;
  base_url: string;
  pid: number | null;
  started_at: string | null;
  exe: string | null;
  argv: string[] | null;
  flags: Record<string, unknown>;
  unknown: Record<string, unknown>;
  model_path: string | null;
  model_file: string | null;
  port_source: string | null;
  devices: ProcessGpuUse[];
  gpu_link: string | null;
  status: string;
  props: Record<string, unknown> | null;
  slots: unknown;
  models: unknown;
  derived: {
    model_path: string | null;
    model_alias: string | null;
    model_ftype: string | null;
    build_info: string | null;
    n_ctx_slot: number | null;
    total_slots: number | null;
    n_ctx_total: number | null;
    slots_busy: number | null;
    chat_template_sha: string | null;
    modalities: Record<string, boolean> | null;
  };
  detected_at: number;
}

export interface Endpoint {
  id: number;
  host_pk: number;
  base_url: string;
  alias: string | null;
  engine: string | null;
  status: "listo" | "cargando" | "sin respuesta" | "detenido" | string;
  fingerprint: string | null;
  snapshot: EndpointSnapshot | null;
  first_seen_at: number;
  last_seen_at: number;
}

export interface ConfigChange {
  id: number;
  endpoint_id: number;
  t: number;
  kind: "nuevo" | "cambio" | "reinicio" | "detenido" | "vuelve" | string;
  diff: Record<string, [unknown, unknown]> | null;
  base_url?: string;
}

// --- Pruebas (F4–F5) ----------------------------------------------------------

export interface Suite {
  id: string;
  name: string;
  version: string;
  mode: "items" | "duration";
  description: string;
  defaults: Record<string, unknown>;
  prompts: string[];
}

export type RunStatus = "pending" | "running" | "done" | "error" | "aborted" | "cancelled";

export interface Stat {
  n: number;
  mean: number | null;
  median: number | null;
  p10: number | null;
  min: number | null;
  max: number | null;
  std: number | null;
}

export interface DeviceRunSummary {
  temp_idle_c: number | null;
  temp_mean_c: number | null;
  temp_max_c: number | null;
  temp_rise_c: number | null;
  power_idle_w: number | null;
  power_mean_w: number | null;
  power_max_w: number | null;
  energy_wh: number | null;
  util_mean_pct: number | null;
  vram_peak_mib: number | null;
  clock_sm_mean_mhz: number | null;
  clock_sm_min_mhz: number | null;
  throttle_pct: number | null;
  cpu_util_mean_pct: number | null;
  ram_used_peak_mib?: number | null;
  n_samples: number;
}

export interface RunSummary {
  requests: number;
  requests_ok: number;
  requests_error: number;
  requests_cut: number;
  completion_tokens: number;
  prompt_tokens: number;
  duration_s: number | null;
  tps_client: Stat;
  tps_server: Stat;
  pp_server: Stat;
  ttft_s: Stat;
  latency_s: Stat;
  tps_aggregate: Stat;
  degradation_pct: number | null;
  energy_wh: number | null;
  tokens_per_wh: number | null;
  wh_per_1000_tokens: number | null;
  devices: Record<string, DeviceRunSummary>;
  thresholds: Record<string, { name: string | null; warn: number; crit: number; source: string }>;
  phases: { load_start: number | null; load_end: number | null };
}

export interface Run {
  id: number;
  kind: string;
  suite: string;
  suite_version: string | null;
  suite_hash?: string | null;
  label: string | null;
  status: RunStatus;
  host_pk: number | null;
  endpoint_id: number | null;
  params: Record<string, unknown> | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  summary: RunSummary | null;
  error: string | null;
  abort_reason: string | null;
  notes?: string | null;
  tags?: string[] | null;
}

export interface RunItem {
  id: number;
  idx: number;
  name: string | null;
  prompt: string | null;
  response: string | null;
  reasoning: string | null;
  metrics: Record<string, number | string | null> | null;
  error: string | null;
  started_at: number | null;
  finished_at: number | null;
}

export interface Sample {
  t: number;
  phase: "reposo" | "carga" | "enfriamiento" | string;
  device_id: string;
  data: Record<string, unknown>;
}

export interface TpsPoint {
  t: number;
  tokens: number;
  tps: number;
}

export interface RunDetail extends Run {
  servers_snapshot: EndpointSnapshot | null;
  host_snapshot: (HostState & { thresholds: RunSummary["thresholds"] }) | null;
  items: RunItem[];
  tps: TpsPoint[];
  samples: Sample[];
}

export interface RunLive {
  run: number;
  phase: string;
  t: number;
  elapsed_s: number;
  load_elapsed_s: number | null;
  tokens: number;
  requests_done: number;
  requests_error: number;
  max_temp: Record<string, number>;
  abort_reason: string | null;
  tps?: number;
  text?: string;
}

// --- Ajustes -------------------------------------------------------------------

export interface Appearance {
  accent: string;
  contrast: "normal" | "alto";
  scale: number;
  sketch: boolean;
  grid: "normal" | "tenue" | "off";
}

export type ThresholdOverrides = Record<string, { warn?: number; crit?: number }>;

/** Fichero GGUF de las carpetas de modelos del agente. */
export interface ModelFile {
  path: string;
  file: string;
  dir: string;
  size: number;
  mtime: number;
  split_part: number | null;
  split_total: number | null;
}

export interface ModelsResponse {
  model_dirs: string[];
  files: ModelFile[];
  errors: Record<string, string>;
}

export interface FitParams {
  ctx: number;
  parallel: number;
  kv_type: string;
}

/** Desglose ESTIMADO (bytes). `kv`/`compute` son null si faltan datos en la cabecera. */
export interface FitEstimate {
  kind: "model" | "mmproj" | "unsupported";
  notes: string[];
  n_layers?: number;
  weights?: number;
  weights_layers?: number;
  token_embd?: number;
  output?: number;
  kv?: number | null;
  kv_layers?: number;
  recurrent?: number;
  compute?: number | null;
  params?: FitParams & { ubatch: number; reserve_mib: number };
}

export interface FitGpu {
  device_id: string;
  name: string | null;
  need: number;
  free: number | null;
  fits: boolean;
  fits_if_empty: boolean;
}

export interface FitVerdict {
  verdict: "gpu" | "split" | "ram" | "cpu" | "no" | "unknown" | "mmproj" | "unsupported";
  label: string | null;
  need_full_gpu?: number;
  ngl?: number | null;
  ram_need?: number | null;
  gpus: FitGpu[];
  hint?: string;
}

export interface FitResponse {
  path: string;
  estimated: true;
  model: GgufHeader;
  estimate: FitEstimate;
  fit: FitVerdict;
}

export interface GgufHeader {
  name: string | null;
  architecture: string | null;
  general_type: string | null;
  file_type: string | null;
  size_label: string | null;
  n_params: number;
  context_length: number | null;
  expert_count: number | null;
  file_size: number;
}
