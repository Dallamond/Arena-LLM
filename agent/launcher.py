"""Arranque y parada de `llama-server` desde el agente.

Seguridad: igual que con `llama-bench`, el agente **no es una shell remota**. Solo
ejecuta el `llama-server` que dice su configuración local (`llama_server`, o el que
haya junto a `llama_bench`), sin shell, con una lista cerrada de flags cuyos valores
se validan uno a uno, con modelos dentro de `model_dirs` y escuchando siempre en
`127.0.0.1`. Solo puede parar los procesos que él mismo lanzó.

El orden de los dispositivos se fija con `CUDA_DEVICE_ORDER=PCI_BUS_ID` cuando se
indica `dev` o `ts`, para que `CUDA0, CUDA1…` coincidan con el índice de `nvidia-smi`.
"""

import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.bench import CACHE_TYPES, FLASH_ATTN

log = logging.getLogger(__name__)

DEV_RE = re.compile(r"^(none|[A-Za-z]{2,8}\d{1,2})$")
MAX_LAUNCHED = 8
LOG_TAIL_BYTES = 6000


class LaunchError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass
class LaunchSpec:
    model: Path
    ctx: int
    parallel: int
    kv_type: str
    ubatch: int
    ngl: int
    flash_attn: str
    port: int
    dev: str | None
    ts: list[float] | None

    def argv(self, exe: Path) -> list[str]:
        a = [str(exe), "-m", str(self.model), "-c", str(self.ctx)]
        if self.parallel > 1:
            a += ["-np", str(self.parallel)]
        if self.kv_type != "f16":
            a += ["-ctk", self.kv_type, "-ctv", self.kv_type]
        if self.ubatch != 512:
            a += ["-ub", str(self.ubatch)]
        a += ["-ngl", str(self.ngl)]
        if self.dev:
            a += ["-dev", self.dev]
        if self.ts:
            a += ["-ts", ",".join(f"{v:g}" for v in self.ts)]
        return [*a, "-fa", self.flash_attn, "--host", "127.0.0.1", "--port", str(self.port)]

    def env(self) -> dict[str, str]:
        return {"CUDA_DEVICE_ORDER": "PCI_BUS_ID"} if (self.ts or self.dev not in (None, "none")) else {}


def _int(data: dict[str, Any], key: str, lo: int, hi: int, default: int | None = None) -> int:
    v = data.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise LaunchError("spec", f"'{key}': entero entre {lo} y {hi}")
    return v


def parse_spec(data: Any, allowed_model: Callable[[str], Path | None]) -> LaunchSpec:
    """Valida la petición. `allowed_model(ruta)` devuelve la ruta resuelta o None."""
    if not isinstance(data, dict):
        raise LaunchError("spec", "Se esperaba un objeto JSON")
    model = allowed_model(str(data.get("model") or ""))
    if model is None:
        raise LaunchError("model", "Modelo no permitido: debe ser un .gguf dentro de model_dirs", 403)
    flash = data.get("flash_attn", "on")
    if flash not in FLASH_ATTN:
        raise LaunchError("spec", f"'flash_attn': uno de {', '.join(FLASH_ATTN)}")
    kv = data.get("kv_type", "f16")
    if kv not in CACHE_TYPES:
        raise LaunchError("spec", f"'kv_type': uno de {', '.join(CACHE_TYPES)}")
    dev = data.get("dev")
    if dev is not None and not (isinstance(dev, str) and DEV_RE.match(dev)):
        raise LaunchError("spec", "'dev': 'none' o un dispositivo como CUDA0")
    ts = data.get("ts")
    if ts is not None:
        if (
            not isinstance(ts, list)
            or not 1 <= len(ts) <= 16
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1e6 for v in ts)
        ):
            raise LaunchError("spec", "'ts': lista de 1 a 16 números no negativos")
        ts = [float(v) for v in ts]
    return LaunchSpec(
        model=model,
        ctx=_int(data, "ctx", 256, 4_194_304, 4096),
        parallel=_int(data, "parallel", 1, 64, 1),
        kv_type=kv,
        ubatch=_int(data, "ubatch", 32, 65536, 512),
        ngl=_int(data, "ngl", 0, 999),
        flash_attn=flash,
        port=_int(data, "port", 1024, 65535),
        dev=dev,
        ts=ts,
    )


@dataclass
class Launched:
    pid: int
    port: int
    model: str
    argv: list[str]
    log_path: Path
    started_at: float
    proc: Any = field(repr=False)

    def public(self) -> dict[str, Any]:
        rc = self.proc.poll()
        return {
            "pid": self.pid,
            "port": self.port,
            "model": self.model,
            "argv": self.argv,
            "started_at": self.started_at,
            "alive": rc is None,
            "returncode": rc,
            "log_tail": self._tail(),
        }

    def _tail(self) -> list[str]:
        try:
            with self.log_path.open("rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - LOG_TAIL_BYTES))
                text = f.read().decode("utf-8", "replace")
        except OSError:
            return []
        return [ln.rstrip() for ln in text.splitlines()[-12:] if ln.strip()]


def port_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


class ServerLauncher:
    """Lanza `llama-server` y recuerda lo que lanzó (para poder pararlo y enseñar su registro)."""

    def __init__(
        self,
        exe: Callable[[], Path | None],
        popen: Callable[..., Any] = subprocess.Popen,
        log_dir: Path | None = None,
    ):
        self._exe = exe
        self._popen = popen
        self._log_dir = log_dir
        self._launched: dict[int, Launched] = {}
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        exe = self._exe()
        return bool(exe and Path(exe).is_file())

    @property
    def exe(self) -> Path | None:
        return self._exe()

    def launch(self, spec: LaunchSpec) -> dict[str, Any]:
        exe = self._exe()
        if exe is None or not Path(exe).is_file():
            raise LaunchError(
                "no_server", "llama-server no configurado (clave 'llama_server' o 'llama_bench' en agent.json)", 501
            )
        with self._lock:
            alive = [x for x in self._launched.values() if x.proc.poll() is None]
            if len(alive) >= MAX_LAUNCHED:
                raise LaunchError("busy", f"Ya hay {MAX_LAUNCHED} servidores lanzados desde Arena", 409)
            if port_in_use(spec.port) or any(x.port == spec.port for x in alive):
                raise LaunchError("port", f"El puerto {spec.port} ya está en uso", 409)
            log_dir = self._log_dir or Path(tempfile.gettempdir())
            log_path = log_dir / f"arena-llama-{spec.port}.log"
            argv = spec.argv(Path(exe))
            env = {**os.environ, **spec.env()}
            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            try:
                with log_path.open("wb") as out:
                    proc = self._popen(
                        argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=env,
                        creationflags=flags,
                    )  # fmt: skip
            except OSError as exc:
                raise LaunchError("spawn", f"No se pudo lanzar llama-server: {exc}", 500) from exc
            item = Launched(proc.pid, spec.port, str(spec.model), argv, log_path, time.time(), proc)
            self._launched[proc.pid] = item
        log.info("llama-server #%s lanzado: %s", proc.pid, " ".join(argv))
        return item.public()

    def status(self) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._launched.values())
        return [x.public() for x in sorted(items, key=lambda x: x.started_at, reverse=True)]

    def stop(self, pid: Any) -> dict[str, Any]:
        with self._lock:
            item = self._launched.get(pid) if isinstance(pid, int) and not isinstance(pid, bool) else None
        if item is None:
            raise LaunchError("pid", "Solo se pueden parar los servidores lanzados desde Arena", 404)
        if item.proc.poll() is None:
            item.proc.terminate()
            try:
                item.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                item.proc.kill()
        log.info("llama-server #%s parado", pid)
        return item.public()

    def stop_all_for_tests(self) -> None:  # pragma: no cover - limpieza de pruebas
        for pid in list(self._launched):
            try:
                self.stop(pid)
            except LaunchError:
                pass


class NoLauncher(ServerLauncher):
    """Equipos simulados: no hay llama-server real que lanzar."""

    def __init__(self):
        super().__init__(lambda: None)
