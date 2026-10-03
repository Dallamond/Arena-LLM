"""Perfiles de hardware simulados.

Sirven para desarrollar sin GPU y para demostrar en los tests que nada depende
del PC de Lucas. Los valores siguen un ciclo de carga determinista (reposo →
carga → enfriamiento) con ruido de semilla fija, para que la GUI se mueva.

- `nvidia2`: dos GPU NVIDIA con todos los campos.
- `cpu-only`: sin GPU (proveedor nulo) + CPU/RAM.
- `partial`: una GPU que no expone ventilador, potencia, throttling ni
  temperatura de slowdown (como una tarjeta pasiva o un driver antiguo).
"""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from agent import throttle
from agent.model import CpuSample, DeviceInfo, DeviceSample, GpuSample, HostInfo, RamSample
from agent.providers.base import TelemetryProvider
from agent.providers.null import NullProvider

PROFILES = ("nvidia2", "cpu-only", "partial")

Clock = Callable[[], float]

#: Ciclo de carga en segundos: reposo, carga, enfriamiento.
CYCLE = (20.0, 40.0, 20.0)


def load_at(t: float, phase: float = 0.0) -> float:
    """Carga 0..1 en el instante t (ciclo `CYCLE`, desplazado por `phase`)."""
    idle, busy, cool = CYCLE
    x = (t + phase) % (idle + busy + cool)
    if x < idle:
        return 0.0
    if x < idle + busy:
        return 1.0
    return 0.0


@dataclass
class SimGpuSpec:
    uuid: str
    name: str
    index: int
    pci_bus_id: str
    memory_total_mib: int
    compute_capability: str
    power_idle_w: float
    power_max_w: float
    temp_idle_c: float
    temp_load_c: float
    clock_max_mhz: float
    clock_mem_mhz: float
    temp_slowdown_c: float | None = 95.0
    temp_shutdown_c: float | None = 98.0
    has_fan: bool = True
    has_power: bool = True
    has_throttle: bool = True
    driver_model: str | None = None
    phase: float = 0.0
    model_vram_mib: float = 0.0  # VRAM ocupada por el "modelo" cargado
    missing: list[str] = field(default_factory=list)


class SimGpuProvider(TelemetryProvider):
    name = "nvidia"

    def __init__(self, specs: list[SimGpuSpec], clock: Clock = time.time, seed: int = 1):
        self.specs = specs
        self.clock = clock
        self.rng = random.Random(seed)
        self.temp = {s.uuid: s.temp_idle_c for s in specs}
        self.last_t: float | None = None

    def devices(self) -> list[DeviceInfo]:
        out = []
        for s in self.specs:
            missing = list(s.missing)
            if not s.has_fan:
                missing.append("fan_pct")
            if not s.has_power:
                missing += ["power_w", "power_limit_w", "power_limit_max_w"]
            if not s.has_throttle:
                missing.append("throttle_mask")
            if s.temp_slowdown_c is None:
                missing.append("temp_slowdown_c")
            out.append(
                DeviceInfo(
                    device_id=f"nvidia:{s.uuid}",
                    provider=self.name,
                    kind="gpu",
                    name=s.name,
                    index=s.index,
                    uuid=s.uuid,
                    pci_bus_id=s.pci_bus_id,
                    memory_total_mib=s.memory_total_mib,
                    power_limit_w=s.power_max_w if s.has_power else None,
                    power_limit_max_w=s.power_max_w if s.has_power else None,
                    temp_slowdown_c=s.temp_slowdown_c,
                    temp_shutdown_c=s.temp_shutdown_c,
                    driver="sim-1.0",
                    driver_model=s.driver_model,
                    compute_capability=s.compute_capability,
                    fields_unavailable=sorted(set(missing)),
                )
            )
        return out

    def sample(self) -> dict[str, DeviceSample]:
        now = self.clock()
        dt = 1.0 if self.last_t is None else max(0.0, now - self.last_t)
        self.last_t = now
        out: dict[str, DeviceSample] = {}
        for s in self.specs:
            load = load_at(now, s.phase)
            target = s.temp_idle_c + load * (s.temp_load_c - s.temp_idle_c)
            k = min(1.0, dt / 12.0)  # inercia térmica (~12 s)
            self.temp[s.uuid] += (target - self.temp[s.uuid]) * k
            temp = self.temp[s.uuid] + self.rng.uniform(-0.4, 0.4)
            hot = s.temp_slowdown_c is not None and temp >= s.temp_slowdown_c - 10
            noise = self.rng.uniform(-0.03, 0.03)
            power = s.power_idle_w + max(0.0, load + noise) * (s.power_max_w - s.power_idle_w)
            clock = s.clock_max_mhz * (0.25 + 0.75 * load) * (0.9 if hot else 1.0)
            mask = (0x1 if load == 0 else 0) | (0x20 if hot and load else 0)
            mem_used = 300 + s.model_vram_mib + load * 600
            out[f"nvidia:{s.uuid}"] = GpuSample(
                temp_c=round(temp, 1),
                power_w=round(power, 2) if s.has_power else None,
                power_limit_w=s.power_max_w if s.has_power else None,
                util_gpu_pct=round(min(100.0, max(0.0, 97 * load + 3 + noise * 20)), 1),
                util_mem_pct=round(min(100.0, max(0.0, 60 * load + 2)), 1),
                mem_used_mib=round(mem_used, 1),
                mem_total_mib=float(s.memory_total_mib),
                clock_sm_mhz=round(clock),
                clock_mem_mhz=s.clock_mem_mhz,
                fan_pct=round(30 + 50 * load) if s.has_fan else None,
                pstate="P0" if load else "P8",
                throttle_mask=mask if s.has_throttle else None,
                throttle=throttle.decode(mask) if s.has_throttle else None,
                pcie_gen=3 if load else 1,
                pcie_width=16,
            )
        return out


class SimCpuRamProvider(TelemetryProvider):
    name = "cpu"

    def __init__(self, host_id: str, total_mib: float, clock: Clock = time.time, seed: int = 2):
        self.device_id = f"cpu:{host_id}"
        self.total_mib = total_mib
        self.clock = clock
        self.rng = random.Random(seed)
        self.started = False

    def devices(self) -> list[DeviceInfo]:
        return [
            DeviceInfo(
                device_id=self.device_id,
                provider=self.name,
                kind="cpu",
                name="CPU simulada",
                cores=8,
                threads=16,
            )
        ]

    def sample(self) -> dict[str, DeviceSample]:
        if not self.started:  # como el real: la primera lectura no tiene con qué comparar
            self.started = True
            return {self.device_id: CpuSample(util_pct=None, freq_mhz=None)}
        load = load_at(self.clock())
        util = 4 + 30 * load + self.rng.uniform(-2, 2)
        return {
            self.device_id: CpuSample(util_pct=round(max(0.0, util), 1), freq_mhz=round(3600 + 600 * load))
        }

    def ram(self) -> RamSample | None:
        load = load_at(self.clock())
        return RamSample(used_mib=round(self.total_mib * (0.35 + 0.15 * load), 1), total_mib=self.total_mib)


def _gpu(i: int, **kw) -> SimGpuSpec:
    base = dict(
        uuid=f"GPU-51a00000-0000-0000-0000-00000000000{i}",
        index=i,
        pci_bus_id=f"00000000:0{i + 1}:00.0",
        clock_mem_mhz=7000.0,
    )
    return SimGpuSpec(**{**base, **kw})


def build_profile(profile: str, clock: Clock = time.time) -> tuple[HostInfo, list[TelemetryProvider]]:
    if profile not in PROFILES:
        raise ValueError(f"Perfil desconocido: {profile} (válidos: {', '.join(PROFILES)})")
    host = HostInfo(
        host_id=f"sim-{profile}",
        hostname=f"simulado-{profile}",
        os="simulado",
        os_version=f"Perfil simulado {profile}",
    )
    cpu = SimCpuRamProvider(host.host_id, total_mib=32768.0, clock=clock)
    if profile == "cpu-only":
        return host, [NullProvider(), cpu]
    if profile == "nvidia2":
        gpus = [
            _gpu(
                0,
                name="GPU simulada 12 GB",
                memory_total_mib=12288,
                compute_capability="8.6",
                power_idle_w=18,
                power_max_w=170,
                temp_idle_c=40,
                temp_load_c=72,
                clock_max_mhz=1800,
                model_vram_mib=6200,
                driver_model="WDDM",
            ),
            _gpu(
                1,
                name="GPU simulada 24 GB",
                memory_total_mib=24576,
                compute_capability="5.2",
                power_idle_w=30,
                power_max_w=250,
                temp_idle_c=45,
                temp_load_c=88,
                clock_max_mhz=1100,
                clock_mem_mhz=3000.0,
                model_vram_mib=17500,
                driver_model="TCC",
                phase=7.0,
            ),
        ]
    else:  # partial
        gpus = [
            _gpu(
                0,
                name="GPU simulada parcial 8 GB",
                memory_total_mib=8192,
                compute_capability="6.1",
                power_idle_w=10,
                power_max_w=120,
                temp_idle_c=42,
                temp_load_c=80,
                clock_max_mhz=1500,
                temp_slowdown_c=None,
                temp_shutdown_c=None,
                has_fan=False,
                has_power=False,
                has_throttle=False,
                model_vram_mib=4000,
            )
        ]
    return host, [SimGpuProvider(gpus, clock=clock), cpu]
