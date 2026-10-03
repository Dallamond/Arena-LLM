import { describe, expect, it } from "vitest";
import type { DeviceInfo, GpuSample } from "../src/api/types";
import { deviceColor, shortName } from "../src/lib/devices";
import { NO_DATA, ago, fmt, gib, gibPair, ratio, throttleReasons } from "../src/lib/format";
import { gpuHealth, thresholdsFor } from "../src/lib/thresholds";

const dev = (over: Partial<DeviceInfo> = {}): DeviceInfo => ({
  device_id: "nvidia:GPU-1",
  provider: "nvidia",
  kind: "gpu",
  name: "GPU de prueba",
  index: 0,
  uuid: "GPU-1",
  pci_bus_id: null,
  memory_total_mib: 12288,
  power_limit_w: null,
  power_limit_max_w: null,
  temp_slowdown_c: 95,
  temp_shutdown_c: 98,
  driver: null,
  driver_model: null,
  compute_capability: null,
  cores: null,
  threads: null,
  fields_unavailable: [],
  color_index: 0,
  ...over,
});

const sample = (over: Partial<GpuSample> = {}): GpuSample => ({
  temp_c: 50,
  power_w: 100,
  power_limit_w: 170,
  util_gpu_pct: 50,
  util_mem_pct: 10,
  mem_used_mib: 4096,
  mem_total_mib: 12288,
  clock_sm_mhz: 1500,
  clock_mem_mhz: 7000,
  fan_pct: null,
  pstate: "P2",
  throttle_mask: 0,
  throttle: [],
  pcie_gen: 4,
  pcie_width: 16,
  ...over,
});

describe("formato: nunca 0 en vez de sin datos", () => {
  it("null y NaN son 'sin datos'", () => {
    expect(fmt(null)).toBe(NO_DATA);
    expect(fmt(undefined, 1, "W")).toBe(NO_DATA);
    expect(fmt(NaN)).toBe(NO_DATA);
    expect(gib(null)).toBe(NO_DATA);
    expect(gibPair(100, null)).toBe(NO_DATA);
  });
  it("0 es un dato real", () => {
    expect(fmt(0, 0, "%")).toBe("0 %");
  });
  it("cifras en español", () => {
    expect(fmt(1234.5, 1)).toBe("1234,5");
    expect(gibPair(8294, 12288)).toBe("8,1 / 12,0 GiB");
  });
  it("ratio y ago", () => {
    expect(ratio(6144, 12288)).toBe(0.5);
    expect(ratio(1, 0)).toBeNull();
    expect(ago(null)).toBe("nunca");
    expect(ago(30)).toBe("hace 30 s");
  });
  it("throttling legible sin reposo", () => {
    expect(throttleReasons(["gpu_idle"])).toEqual([]);
    expect(throttleReasons(["sw_thermal", "gpu_idle"])).toEqual(["térmico SW"]);
    expect(throttleReasons(null)).toEqual([]);
  });
});

describe("umbrales derivados del dispositivo", () => {
  it("desde la temperatura de slowdown", () => {
    expect(thresholdsFor(dev())).toEqual({ warn: 85, crit: 90, source: "dispositivo" });
  });
  it("por defecto si el dispositivo no la reporta", () => {
    expect(thresholdsFor(dev({ temp_slowdown_c: null })).source).toBe("por defecto");
    expect(thresholdsFor(dev({ temp_slowdown_c: null, provider: "otro" })).crit).toBe(85);
  });
  it("niveles", () => {
    expect(gpuHealth(dev(), sample()).level).toBe("ok");
    expect(gpuHealth(dev(), sample({ temp_c: 86 })).level).toBe("warn");
    expect(gpuHealth(dev(), sample({ temp_c: 91 })).level).toBe("crit");
    expect(gpuHealth(dev(), sample({ throttle: ["hw_thermal"] })).level).toBe("warn");
    expect(gpuHealth(dev(), sample({ temp_c: null })).level).toBe("unknown");
    expect(gpuHealth(dev(), undefined).level).toBe("unknown");
  });
});

describe("dispositivos", () => {
  it("color estable por índice y fijo para CPU", () => {
    expect(deviceColor(dev({ color_index: 1 }))).toBe("var(--dev-2)");
    expect(deviceColor(dev({ color_index: 7 }))).toBe("var(--dev-2)");
    expect(deviceColor(dev({ kind: "cpu", color_index: null }))).toBe("var(--dev-cpu)");
  });
  it("nombre corto", () => {
    expect(shortName("NVIDIA GeForce RTX 3060")).toBe("RTX 3060");
    expect(shortName("AMD Ryzen 5 3600 6-Core Processor")).toBe("AMD Ryzen 5 3600");
    expect(shortName(null)).toBe("Dispositivo sin nombre");
  });
});
