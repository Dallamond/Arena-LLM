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
