"""Contrato de datos del agente (versión `AGENT_API`).

Regla: un valor que el equipo no expone es `None` (JSON `null`), nunca 0.
Cambiar un campo de forma incompatible exige subir `AGENT_API`.
"""

import math
from dataclasses import asdict, dataclass, field
from typing import Any

AGENT_API = 1


@dataclass
class HostInfo:
    host_id: str
    hostname: str
    os: str  # "windows" | "linux" | "darwin" | …
    os_version: str | None = None
    cpu_model: str | None = None
    cpu_cores: int | None = None
    cpu_threads: int | None = None
    ram_total_mib: int | None = None


@dataclass
class DeviceInfo:
    device_id: str  # "<proveedor>:<id estable>", p. ej. "nvidia:GPU-…" o "cpu:<host_id>"
    provider: str
    kind: str  # "gpu" | "cpu"
    name: str | None = None
    index: int | None = None
    uuid: str | None = None
    pci_bus_id: str | None = None
    memory_total_mib: int | None = None
    power_limit_w: float | None = None
    power_limit_max_w: float | None = None
    temp_slowdown_c: float | None = None
    temp_shutdown_c: float | None = None
    driver: str | None = None
    driver_model: str | None = None
    compute_capability: str | None = None
    cores: int | None = None  # CPU: núcleos físicos
    threads: int | None = None  # CPU: hilos lógicos
    fields_unavailable: list[str] = field(default_factory=list)


@dataclass
class GpuSample:
    temp_c: float | None = None
    power_w: float | None = None
    power_limit_w: float | None = None
    util_gpu_pct: float | None = None
    util_mem_pct: float | None = None
    mem_used_mib: float | None = None
    mem_total_mib: float | None = None
    clock_sm_mhz: float | None = None
    clock_mem_mhz: float | None = None
    fan_pct: float | None = None
    pstate: str | None = None
    throttle_mask: int | None = None
    throttle: list[str] | None = None
    pcie_gen: int | None = None
    pcie_width: int | None = None


@dataclass
class CpuSample:
    util_pct: float | None = None
    freq_mhz: float | None = None


@dataclass
class RamSample:
    used_mib: float | None = None
    total_mib: float | None = None


DeviceSample = GpuSample | CpuSample


@dataclass
class Snapshot:
    """Último muestreo del equipo. `t` en segundos epoch; `errors` por proveedor."""

    t: float | None = None
    interval_s: float | None = None
    devices: dict[str, DeviceSample] = field(default_factory=dict)
    ram: RamSample | None = None
    errors: dict[str, str] = field(default_factory=dict)


def to_jsonable(obj: Any) -> Any:
    """Convierte dataclasses a tipos JSON; NaN/inf pasan a `None`."""
    if hasattr(obj, "__dataclass_fields__"):
        obj = asdict(obj)
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj
