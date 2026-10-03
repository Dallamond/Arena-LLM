"""Localiza procesos de servidores de inferencia y su línea de comandos.

- Windows: `Get-CimInstance Win32_Process` vía PowerShell (sin paquetes).
- Linux: `/proc/<pid>/cmdline`, `/proc/<pid>/exe` y la hora de arranque.

Límite conocido: en Windows no se pueden leer las variables de entorno de otro
proceso (p. ej. `CUDA_VISIBLE_DEVICES`); la GPU se asocia por
`nvidia-smi --query-compute-apps` o, en el servidor, por el aumento de VRAM.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePath, PureWindowsPath

from agent.cmdline import parse_llama_server_args, split_windows_cmdline
from agent.model import ProcessGpuUse
from agent.providers.base import TelemetryProvider

#: Nombres de ejecutable de los motores soportados (conocimiento del motor, no del equipo).
SERVER_PROCESS_NAMES = ("llama-server",)
LLAMA_SERVER_DEFAULT_HOST = "127.0.0.1"
LLAMA_SERVER_DEFAULT_PORT = 8080


@dataclass
class RawProcess:
    pid: int
    exe: str | None
    argv: list[str]
    started_at: str | None = None  # ISO 8601 UTC


@dataclass
class DetectedServer:
    pid: int
    engine: str
    exe: str | None
    started_at: str | None
    argv: list[str]  # con secretos ocultos
    flags: dict
    unknown: dict
    positional: list[str]
    model_path: str | None
    model_file: str | None
    host: str
    port: int | None
    port_source: str  # "flag" | "default"
    devices: list[ProcessGpuUse] = field(default_factory=list)
    gpu_link: str | None = None  # "compute-apps" | None (el servidor puede deducirla por VRAM)


def _matches(name: str | None) -> bool:
    if not name:
        return False
    stem = PureWindowsPath(name).name if "\\" in name else PurePath(name).name
    stem = stem.lower().removesuffix(".exe")
    return stem in SERVER_PROCESS_NAMES


class ProcessSource:
    def list(self) -> list[RawProcess]:
        raise NotImplementedError


class WindowsProcessSource(ProcessSource):
    SCRIPT = (
        "$ErrorActionPreference='Stop';"
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        '@(Get-CimInstance Win32_Process -Filter "{filter}" | ForEach-Object {{'
        " [pscustomobject]@{{pid=$_.ProcessId; exe=$_.ExecutablePath; cmd=$_.CommandLine;"
        " start=if($_.CreationDate){{$_.CreationDate.ToUniversalTime().ToString('o')}}else{{$null}}}}"
        "}}) | ConvertTo-Json -Compress -Depth 3"
    )

    def __init__(self, runner: Callable[[list[str]], tuple[int, str, str]] | None = None):
        self.runner = runner or self._run

    @staticmethod
    def _run(args: list[str]) -> tuple[int, str, str]:
        proc = subprocess.run(
            args,
            capture_output=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")

    def list(self) -> list[RawProcess]:
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if shell is None:
            raise RuntimeError("PowerShell no encontrado: no se pueden listar procesos")
        flt = " OR ".join(f"Name LIKE '{n}%'" for n in SERVER_PROCESS_NAMES)
        code, out, err = self.runner(
            [shell, "-NoProfile", "-NonInteractive", "-Command", self.SCRIPT.format(filter=flt)]
        )
        if code != 0:
            raise RuntimeError(f"Get-CimInstance falló ({code}): {err.strip()[:300]}")
        return parse_cim_json(out)


def parse_cim_json(text: str) -> list[RawProcess]:
    text = text.strip()
    if not text:
        return []
    data = json.loads(text)
    if isinstance(data, dict):
        data = [data]
    result = []
    for item in data:
        cmd = item.get("cmd")
        argv = split_windows_cmdline(cmd) if cmd else []
        exe = item.get("exe") or (argv[0] if argv else None)
        if not (_matches(exe) or (argv and _matches(argv[0]))):
            continue
        result.append(RawProcess(pid=int(item["pid"]), exe=exe, argv=argv, started_at=item.get("start")))
    return result


class LinuxProcessSource(ProcessSource):
    def __init__(self, proc: Path = Path("/proc")):
        self.proc = proc

    def _boot_time(self) -> float | None:
        try:
            for line in (self.proc / "stat").read_text().splitlines():
                if line.startswith("btime "):
                    return float(line.split()[1])
        except OSError:
            pass
        return None

    def list(self) -> list[RawProcess]:
        btime = self._boot_time()
        hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        result = []
        for entry in self.proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
            except OSError:
                continue  # proceso terminado o sin permisos
            argv = [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]
            if not argv:
                continue
            try:
                exe = os.readlink(entry / "exe")
            except OSError:
                exe = None
            if not (_matches(exe) or _matches(argv[0])):
                continue
            started = None
            try:
                stat = (entry / "stat").read_text()
                ticks = int(stat.rsplit(")", 1)[1].split()[19])  # campo 22: starttime
                if btime is not None:
                    started = datetime.fromtimestamp(btime + ticks / hz, UTC).isoformat()
            except (OSError, ValueError, IndexError):
                pass
            result.append(RawProcess(pid=int(entry.name), exe=exe, argv=argv, started_at=started))
        return result


def default_process_source() -> ProcessSource:
    return WindowsProcessSource() if sys.platform == "win32" else LinuxProcessSource()


def describe(proc: RawProcess, gpu_map: dict[int, list[ProcessGpuUse]]) -> DetectedServer:
    parsed = parse_llama_server_args(proc.argv[1:])
    flags = parsed.flags
    model = flags.get("model")
    model_file = None
    if isinstance(model, str):
        model_file = PureWindowsPath(model).name if "\\" in model else PurePath(model).name
    port = flags.get("port")
    devices = gpu_map.get(proc.pid, [])
    return DetectedServer(
        pid=proc.pid,
        engine="llama.cpp",
        exe=proc.exe,
        started_at=proc.started_at,
        argv=[proc.argv[0], *parsed.argv_redacted] if proc.argv else [],
        flags=flags,
        unknown=parsed.unknown,
        positional=parsed.positional,
        model_path=model if isinstance(model, str) else None,
        model_file=model_file,
        host=flags.get("host") or LLAMA_SERVER_DEFAULT_HOST,
        port=port if isinstance(port, int) else (None if port is not None else LLAMA_SERVER_DEFAULT_PORT),
        port_source="flag" if port is not None else "default",
        devices=devices,
        gpu_link="compute-apps" if devices else None,
    )


class ServerDetector:
    """Detecta servidores combinando procesos y uso de GPU. Cachea `ttl_s` segundos."""

    def __init__(self, source: ProcessSource, providers: list[TelemetryProvider], ttl_s: float = 2.0):
        self.source = source
        self.providers = providers
        self.ttl_s = ttl_s
        self._lock = threading.Lock()
        self._cache: tuple[float, dict] | None = None

    def detect(self) -> dict:
        with self._lock:
            now = time.monotonic()
            if self._cache and now - self._cache[0] < self.ttl_s:
                return self._cache[1]
            errors: dict[str, str] = {}
            gpu_map: dict[int, list[ProcessGpuUse]] = {}
            for p in self.providers:
                try:
                    for pid, uses in p.processes().items():
                        gpu_map.setdefault(pid, []).extend(uses)
                except Exception as exc:
                    errors[p.name] = f"{type(exc).__name__}: {exc}"
            try:
                servers = [describe(proc, gpu_map) for proc in self.source.list()]
            except Exception as exc:
                servers = []
                errors["processes"] = f"{type(exc).__name__}: {exc}"
            servers.sort(key=lambda s: (s.port or 0, s.pid))
            result = {"servers": servers, "errors": errors, "detected_at": time.time()}
            self._cache = (now, result)
            return result
