"""Proveedor de CPU y RAM del sistema, sin dependencias.

- Windows: `GetSystemTimes`, `GlobalMemoryStatusEx` y
  `GetLogicalProcessorInformation` por `ctypes`; modelo de CPU del registro.
- Linux: `/proc/stat`, `/proc/meminfo` y `/proc/cpuinfo`.

El uso de CPU se calcula por diferencia entre dos lecturas: la primera muestra
devuelve `None` (no hay con qué comparar).
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from agent.host import host_id
from agent.model import CpuSample, DeviceInfo, DeviceSample, RamSample
from agent.providers.base import TelemetryProvider

MIB = 1024 * 1024


@dataclass(frozen=True)
class CpuTimes:
    idle: int
    total: int


@dataclass(frozen=True)
class CpuStatic:
    model: str | None
    cores: int | None
    threads: int | None


def cpu_util(prev: CpuTimes | None, cur: CpuTimes) -> float | None:
    if prev is None:
        return None
    d_total = cur.total - prev.total
    d_idle = cur.idle - prev.idle
    if d_total <= 0:
        return None
    return round(max(0.0, min(100.0, 100.0 * (1 - d_idle / d_total))), 1)


# --- Linux -----------------------------------------------------------------


def parse_proc_stat(text: str) -> CpuTimes:
    for line in text.splitlines():
        if line.startswith("cpu "):
            vals = [int(v) for v in line.split()[1:]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
            total = sum(vals[:8])  # sin guest/guest_nice (ya incluidos en user/nice)
            return CpuTimes(idle=idle, total=total)
    raise ValueError("línea 'cpu' no encontrada en /proc/stat")


def parse_meminfo(text: str) -> RamSample:
    kib: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            kib[key.strip()] = int(parts[0])
    total = kib.get("MemTotal")
    avail = kib.get("MemAvailable")
    if avail is None and total is not None and "MemFree" in kib:
        avail = kib["MemFree"] + kib.get("Buffers", 0) + kib.get("Cached", 0)
    return RamSample(
        used_mib=round((total - avail) / 1024, 1) if total is not None and avail is not None else None,
        total_mib=round(total / 1024, 1) if total is not None else None,
    )


def parse_cpuinfo(text: str) -> tuple[CpuStatic, float | None]:
    """Devuelve datos fijos y la frecuencia media actual (MHz)."""
    model = None
    cores: set[tuple[str, str]] = set()
    threads = 0
    mhz: list[float] = []
    phys = core = None
    for line in [*text.splitlines(), ""]:
        key, _, value = (s.strip() for s in line.partition(":"))
        if not key:  # fin de bloque de un procesador lógico
            if phys is not None or core is not None:
                cores.add((phys or "0", core or str(len(cores))))
            phys = core = None
            continue
        if key == "processor":
            threads += 1
        elif key == "model name" and model is None:
            model = value
        elif key == "physical id":
            phys = value
        elif key == "core id":
            core = value
        elif key == "cpu MHz":
            try:
                mhz.append(float(value))
            except ValueError:
                pass
    freq = round(sum(mhz) / len(mhz), 1) if mhz else None
    return CpuStatic(model=model, cores=len(cores) or None, threads=threads or None), freq


class _LinuxBackend:
    def __init__(self, proc: Path = Path("/proc")):
        self.proc = proc

    def _read(self, name: str) -> str:
        return (self.proc / name).read_text(encoding="utf-8", errors="replace")

    def static(self) -> CpuStatic:
        info, _ = parse_cpuinfo(self._read("cpuinfo"))
        return CpuStatic(info.model, info.cores, info.threads or os.cpu_count())

    def times(self) -> CpuTimes:
        return parse_proc_stat(self._read("stat"))

    def freq_mhz(self) -> float | None:
        return parse_cpuinfo(self._read("cpuinfo"))[1]

    def ram(self) -> RamSample:
        return parse_meminfo(self._read("meminfo"))


# --- Windows ---------------------------------------------------------------


class _WindowsBackend:
    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        self._MEMORYSTATUSEX = MEMORYSTATUSEX
        self._FILETIME = wintypes.FILETIME

    def _cpu_model(self) -> str | None:
        try:
            import winreg

            path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip() or None
        except OSError:
            return None

    def _physical_cores(self) -> int | None:
        ctypes = self._ctypes
        length = ctypes.c_ulong(0)
        self._k32.GetLogicalProcessorInformation(None, ctypes.byref(length))
        if not length.value:
            return None
        buf = ctypes.create_string_buffer(length.value)
        if not self._k32.GetLogicalProcessorInformation(buf, ctypes.byref(length)):
            return None
        # SYSTEM_LOGICAL_PROCESSOR_INFORMATION: ULONG_PTR mask + int Relationship + unión de 16 bytes
        ptr = ctypes.sizeof(ctypes.c_void_p)
        entry = ptr + 4 + (4 if ptr == 8 else 0) + 16
        rel_off = ptr
        count = 0
        for off in range(0, length.value - entry + 1, entry):
            if (
                int.from_bytes(buf.raw[off + rel_off : off + rel_off + 4], "little") == 0
            ):  # RelationProcessorCore
                count += 1
        return count or None

    def static(self) -> CpuStatic:
        return CpuStatic(self._cpu_model(), self._physical_cores(), os.cpu_count())

    def times(self) -> CpuTimes:
        ctypes = self._ctypes
        idle, kernel, user = self._FILETIME(), self._FILETIME(), self._FILETIME()
        if not self._k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            raise OSError(ctypes.get_last_error(), "GetSystemTimes")

        def ft(v) -> int:
            return (v.dwHighDateTime << 32) | v.dwLowDateTime

        return CpuTimes(idle=ft(idle), total=ft(kernel) + ft(user))  # kernel ya incluye idle

    def freq_mhz(self) -> float | None:
        return None  # Windows no la expone sin contadores de rendimiento; mejor null que inventar

    def ram(self) -> RamSample:
        ctypes = self._ctypes
        st = self._MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(st)
        if not self._k32.GlobalMemoryStatusEx(ctypes.byref(st)):
            raise OSError(ctypes.get_last_error(), "GlobalMemoryStatusEx")
        return RamSample(
            used_mib=round((st.ullTotalPhys - st.ullAvailPhys) / MIB, 1),
            total_mib=round(st.ullTotalPhys / MIB, 1),
        )


# --- Proveedor ---------------------------------------------------------------


class CpuRamProvider(TelemetryProvider):
    name = "cpu"

    def __init__(self, backend=None, device_id: str | None = None):
        if backend is None:
            backend = _WindowsBackend() if sys.platform == "win32" else _LinuxBackend()
        self.backend = backend
        self.device_id = device_id or f"cpu:{host_id()}"
        self._prev: CpuTimes | None = None

    @classmethod
    def available(cls) -> bool:
        return sys.platform == "win32" or Path("/proc/stat").exists()

    def devices(self) -> list[DeviceInfo]:
        st = self.backend.static()
        return [
            DeviceInfo(
                device_id=self.device_id,
                provider=self.name,
                kind="cpu",
                name=st.model,
                cores=st.cores,
                threads=st.threads,
            )
        ]

    def sample(self) -> dict[str, DeviceSample]:
        cur = self.backend.times()
        util = cpu_util(self._prev, cur)
        self._prev = cur
        return {self.device_id: CpuSample(util_pct=util, freq_mhz=self.backend.freq_mhz())}

    def ram(self) -> RamSample | None:
        return self.backend.ram()
