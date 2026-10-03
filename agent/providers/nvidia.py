"""Proveedor NVIDIA basado en `nvidia-smi` (sin NVML ni paquetes).

Descubrimiento de campos: al arrancar se pide la lista completa; si el driver
rechaza un campo (`Field "x" is not a valid field to query.`) se prueba su
alias o se descarta y se reintenta. Los valores N/A o no soportados son `None`.
"""

import csv
import io
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

from agent import throttle
from agent.model import DeviceInfo, DeviceSample, GpuSample, ProcessGpuUse
from agent.providers.base import TelemetryProvider

Runner = Callable[[list[str]], tuple[int, str, str]]

NA_MARKERS = ("N/A", "Not Supported", "Unknown Error", "Insufficient Permissions", "Not Available")
INVALID_FIELD_RE = re.compile(r'Field "([^"]+)" is not a valid field to query')


@dataclass(frozen=True)
class FieldSpec:
    key: str
    candidates: tuple[str, ...]  # nombre en nvidia-smi y alias de otras versiones del driver
    kind: str = "float"  # str | int | float | mask


INFO_FIELDS = (
    FieldSpec("uuid", ("uuid",), "str"),
    FieldSpec("index", ("index",), "int"),
    FieldSpec("name", ("name",), "str"),
    FieldSpec("pci_bus_id", ("pci.bus_id",), "str"),
    FieldSpec("memory_total_mib", ("memory.total",), "int"),
    FieldSpec("driver", ("driver_version",), "str"),
    FieldSpec("power_limit_w", ("power.limit",)),
    FieldSpec("power_limit_max_w", ("power.max_limit",)),
    FieldSpec("compute_capability", ("compute_cap",), "str"),
    FieldSpec("driver_model", ("driver_model.current",), "str"),
)

SAMPLE_FIELDS = (
    FieldSpec("uuid", ("uuid",), "str"),
    FieldSpec("temp_c", ("temperature.gpu",)),
    FieldSpec("power_w", ("power.draw", "power.draw.average")),
    FieldSpec("power_limit_w", ("power.limit",)),
    FieldSpec("util_gpu_pct", ("utilization.gpu",)),
    FieldSpec("util_mem_pct", ("utilization.memory",)),
    FieldSpec("mem_used_mib", ("memory.used",)),
    FieldSpec("mem_total_mib", ("memory.total",)),
    FieldSpec("clock_sm_mhz", ("clocks.sm",)),
    FieldSpec("clock_mem_mhz", ("clocks.mem",)),
    FieldSpec("fan_pct", ("fan.speed",)),
    FieldSpec("pstate", ("pstate",), "str"),
    FieldSpec("throttle_mask", ("clocks_event_reasons.active", "clocks_throttle_reasons.active"), "mask"),
    FieldSpec("pcie_gen", ("pcie.link.gen.current",), "int"),
    FieldSpec("pcie_width", ("pcie.link.width.current",), "int"),
)


def default_runner(args: list[str]) -> tuple[int, str, str]:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=flags,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout, proc.stderr


def convert(raw: str | None, kind: str):
    if raw is None:
        return None
    raw = raw.strip()
    if not raw or any(m in raw for m in NA_MARKERS):
        return None
    if kind == "str":
        return raw
    if kind == "mask":
        return throttle.parse_mask(raw)
    try:
        num = float(raw.split()[0])  # tolera unidades si no se usó nounits
    except (ValueError, IndexError):
        return None
    return int(num) if kind == "int" else num


def parse_csv(text: str) -> list[list[str]]:
    return [
        [c.strip() for c in row]
        for row in csv.reader(io.StringIO(text))
        if row and any(c.strip() for c in row)
    ]


def parse_temperature_limits(text: str) -> dict[str, dict[str, float | None]]:
    """`nvidia-smi -q -d TEMPERATURE` → {bus_id normalizado: {slowdown, shutdown, target}}."""
    result: dict[str, dict[str, float | None]] = {}
    current: dict[str, float | None] | None = None
    labels = {
        "GPU Slowdown Temp": "slowdown",
        "GPU Shutdown Temp": "shutdown",
        "GPU Target Temperature": "target",
        "GPU Max Operating Temp": "max_operating",
    }
    for line in text.splitlines():
        m = re.match(r"^GPU ([0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+\.[0-9A-Fa-f]+)\s*$", line.strip())
        if m:
            current = result.setdefault(normalize_bus_id(m.group(1)), {})
            continue
        if current is None or ":" not in line:
            continue
        label, _, value = (s.strip() for s in line.partition(":"))
        if label in labels:
            current[labels[label]] = convert(value.replace("C", "").strip(), "float")
    return result


def normalize_bus_id(bus: str) -> str:
    """'00000000:08:00.0' y '0000:08:00.0' → '08:00.0' en minúsculas."""
    parts = bus.strip().lower().split(":")
    return ":".join(parts[-2:]) if len(parts) >= 2 else bus.strip().lower()


class NvidiaSmi:
    """Envoltorio de `nvidia-smi` con resolución de campos por versión del driver."""

    def __init__(self, binary: str, runner: Runner = default_runner):
        self.binary = binary
        self.runner = runner
        self._resolved: dict[tuple[FieldSpec, ...], list[tuple[FieldSpec, str]]] = {}
        self.unavailable: set[str] = set()

    def _query(self, names: list[str]) -> tuple[int, str, str]:
        return self.runner([self.binary, f"--query-gpu={','.join(names)}", "--format=csv,noheader,nounits"])

    def resolve(self, specs: tuple[FieldSpec, ...]) -> list[tuple[FieldSpec, str]]:
        if specs in self._resolved:
            return self._resolved[specs]
        choice = {s: 0 for s in specs}
        active = list(specs)
        for _ in range(sum(len(s.candidates) for s in specs) + 1):
            names = [s.candidates[choice[s]] for s in active]
            code, out, err = self._query(names)
            if code == 0:
                break
            m = INVALID_FIELD_RE.search(err + out)
            if not m:
                raise RuntimeError(f"nvidia-smi falló ({code}): {(err or out).strip()[:300]}")
            bad = next((s for s in active if s.candidates[choice[s]] == m.group(1)), None)
            if bad is None:
                raise RuntimeError(f"nvidia-smi rechazó un campo inesperado: {m.group(1)}")
            if choice[bad] + 1 < len(bad.candidates):
                choice[bad] += 1
            else:
                active.remove(bad)
                self.unavailable.add(bad.key)
        else:
            raise RuntimeError("nvidia-smi: no se pudo resolver la lista de campos")
        resolved = [(s, s.candidates[choice[s]]) for s in active]
        self._resolved[specs] = resolved
        return resolved

    def query(self, specs: tuple[FieldSpec, ...]) -> list[dict]:
        resolved = self.resolve(specs)
        code, out, err = self._query([name for _, name in resolved])
        if code != 0:
            raise RuntimeError(f"nvidia-smi falló ({code}): {(err or out).strip()[:300]}")
        rows = []
        for row in parse_csv(out):
            if len(row) != len(resolved):
                continue
            item = {s.key: convert(v, s.kind) for (s, _), v in zip(resolved, row, strict=True)}
            for s in specs:
                item.setdefault(s.key, None)
            rows.append(item)
        return rows

    def temperature_limits(self) -> dict[str, dict[str, float | None]]:
        code, out, _ = self.runner([self.binary, "-q", "-d", "TEMPERATURE"])
        return parse_temperature_limits(out) if code == 0 else {}

    def compute_apps(self) -> list[tuple[int, str, float | None]]:
        code, out, _ = self.runner(
            [self.binary, "--query-compute-apps=pid,gpu_uuid,used_memory", "--format=csv,noheader,nounits"]
        )
        if code != 0:
            return []
        apps = []
        for row in parse_csv(out):
            if len(row) >= 3 and row[0].isdigit():
                apps.append((int(row[0]), row[1], convert(row[2], "float")))
        return apps


def find_nvidia_smi() -> str | None:
    override = os.environ.get("ARENA_NVIDIA_SMI")
    if override:
        return override if os.path.exists(override) else None
    return shutil.which("nvidia-smi")


class NvidiaProvider(TelemetryProvider):
    name = "nvidia"

    def __init__(self, smi: NvidiaSmi | None = None):
        if smi is None:
            binary = find_nvidia_smi()
            if binary is None:
                raise RuntimeError("nvidia-smi no encontrado")
            smi = NvidiaSmi(binary)
        self.smi = smi

    @classmethod
    def available(cls) -> bool:
        return find_nvidia_smi() is not None

    @staticmethod
    def device_id(uuid: str) -> str:
        return f"nvidia:{uuid}"

    def devices(self) -> list[DeviceInfo]:
        limits = self.smi.temperature_limits()
        first = {r["uuid"]: r for r in self.smi.query(SAMPLE_FIELDS) if r.get("uuid")}
        out = []
        for row in self.smi.query(INFO_FIELDS):
            uuid = row.get("uuid")
            if not uuid:
                continue
            lim = limits.get(normalize_bus_id(row["pci_bus_id"]), {}) if row.get("pci_bus_id") else {}
            missing = set(self.smi.unavailable)
            missing |= {k for k, v in first.get(uuid, {}).items() if v is None}
            missing |= {s.key for s in INFO_FIELDS if row.get(s.key) is None}
            if lim.get("slowdown") is None:
                missing.add("temp_slowdown_c")
            out.append(
                DeviceInfo(
                    device_id=self.device_id(uuid),
                    provider=self.name,
                    kind="gpu",
                    name=row.get("name"),
                    index=row.get("index"),
                    uuid=uuid,
                    pci_bus_id=row.get("pci_bus_id"),
                    memory_total_mib=row.get("memory_total_mib"),
                    power_limit_w=row.get("power_limit_w"),
                    power_limit_max_w=row.get("power_limit_max_w"),
                    temp_slowdown_c=lim.get("slowdown"),
                    temp_shutdown_c=lim.get("shutdown"),
                    driver=row.get("driver"),
                    driver_model=row.get("driver_model"),
                    compute_capability=row.get("compute_capability"),
                    fields_unavailable=sorted(missing),
                )
            )
        return out

    def sample(self) -> dict[str, DeviceSample]:
        result: dict[str, DeviceSample] = {}
        for row in self.smi.query(SAMPLE_FIELDS):
            uuid = row.pop("uuid", None)
            if not uuid:
                continue
            sample = GpuSample(**row)
            sample.throttle = throttle.decode(sample.throttle_mask)
            result[self.device_id(uuid)] = sample
        return result

    def processes(self) -> dict[int, list[ProcessGpuUse]]:
        result: dict[int, list[ProcessGpuUse]] = {}
        for pid, uuid, mem in self.smi.compute_apps():
            result.setdefault(pid, []).append(ProcessGpuUse(device_id=self.device_id(uuid), mem_used_mib=mem))
        return result
