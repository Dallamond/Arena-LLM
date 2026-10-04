"""Ejecución de `llama-bench` desde el agente (un trabajo cada vez).

Seguridad: el agente **no es una shell remota**. Solo lanza el ejecutable que
dice su configuración local (`llama_bench`), con una lista cerrada de flags
cuyos valores se validan uno a uno, sin shell y con modelos dentro de
`model_dirs`. Todo lo demás se rechaza.

El orden de los dispositivos se fija con `CUDA_DEVICE_ORDER=PCI_BUS_ID` para
que `CUDA0, CUDA1…` coincidan con el índice de `nvidia-smi`.
"""

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Rangos permitidos de cada flag numérico (valor mínimo, máximo).
INT_FLAGS: dict[str, tuple[str, int, int]] = {
    # clave en la especificación → (flag de llama-bench, mín, máx)
    "n_prompt": ("-p", 0, 65536),
    "n_gen": ("-n", 0, 8192),
    "n_depth": ("-d", 0, 262144),
    "n_gpu_layers": ("-ngl", 0, 999),
    "threads": ("-t", 1, 1024),
    "batch": ("-b", 1, 65536),
    "ubatch": ("-ub", 1, 65536),
    "n_cpu_moe": ("-ncmoe", 0, 999),
}
CACHE_TYPES = ("f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1")
FLASH_ATTN = ("on", "off", "auto")
SPLIT_MODES = ("none", "layer", "row")
TS_RE = re.compile(r"^\d{1,3}(\.\d{1,3})?(/\d{1,3}(\.\d{1,3})?){0,15}$")
DEV_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
MAX_VALUES = 32  # valores por flag (barridos)
MAX_REPETITIONS = 50
MAX_TIMEOUT_S = 6 * 3600
STDERR_LINES = 60
DEVICES_TTL_S = 300.0  # la lista de dispositivos apenas cambia; la memoria libre la da la telemetría
LIST_DEVICES_RE = re.compile(r"^\s*([A-Za-z][\w-]*\d+):\s*(.+?)\s*\((\d+)\s*MiB,\s*(\d+)\s*MiB free\)")


class BenchError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _int_list(name: str, raw: Any, lo: int, hi: int) -> list[int]:
    vals = raw if isinstance(raw, list) else [raw]
    if not vals or len(vals) > MAX_VALUES:
        raise BenchError("spec", f"'{name}': entre 1 y {MAX_VALUES} valores")
    out = []
    for v in vals:
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise BenchError("spec", f"'{name}': {v!r} no es un entero entre {lo} y {hi}")
        out.append(v)
    return out


@dataclass
class BenchSpec:
    """Especificación validada de un trabajo de llama-bench."""

    model: Path
    ints: dict[str, list[int]] = field(default_factory=dict)
    repetitions: int = 3
    tensor_split: list[str] = field(default_factory=list)
    devices: list[str] = field(default_factory=list)  # una entrada por combinación: "CUDA0", "CUDA0/CUDA1", "none"
    flash_attn: str | None = None
    cache_type_k: str | None = None
    cache_type_v: str | None = None
    split_mode: str | None = None
    timeout_s: float = 3600.0

    def argv(self, exe: Path) -> list[str]:
        args = [str(exe), "-m", str(self.model), "-o", "jsonl", "-r", str(self.repetitions)]
        for key, values in self.ints.items():
            args += [INT_FLAGS[key][0], ",".join(map(str, values))]
        if self.tensor_split:
            # La coma separa valores de un barrido; la barra, el reparto entre GPU
            args += ["-ts", ",".join(self.tensor_split)]
        if self.devices:
            args += ["-dev", ",".join(self.devices)]
        for flag, val in (("-fa", self.flash_attn), ("-ctk", self.cache_type_k), ("-ctv", self.cache_type_v),
                          ("-sm", self.split_mode)):  # fmt: skip
            if val:
                args += [flag, val]
        return args


def parse_spec(data: Any, allowed_model) -> BenchSpec:
    """Valida la petición. `allowed_model(ruta)` devuelve la ruta resuelta o None."""
    if not isinstance(data, dict):
        raise BenchError("spec", "Se esperaba un objeto JSON")
    known = {*INT_FLAGS, "model", "repetitions", "tensor_split", "devices", "flash_attn", "cache_type_k",
             "cache_type_v", "split_mode", "timeout_s"}  # fmt: skip
    unknown = sorted(set(data) - known)
    if unknown:
        raise BenchError("spec", f"Parámetros no permitidos: {', '.join(unknown)}")
    model = allowed_model(str(data.get("model") or ""))
    if model is None:
        raise BenchError("path", "Modelo no permitido: debe ser un .gguf dentro de model_dirs", 403)
    spec = BenchSpec(model=model)
    for key, (_, lo, hi) in INT_FLAGS.items():
        if data.get(key) is not None:
            spec.ints[key] = _int_list(key, data[key], lo, hi)
    if data.get("repetitions") is not None:
        spec.repetitions = _int_list("repetitions", data["repetitions"], 1, MAX_REPETITIONS)[0]
    ts = data.get("tensor_split") or []
    if not isinstance(ts, list) or len(ts) > MAX_VALUES or not all(isinstance(x, str) and TS_RE.match(x) for x in ts):
        raise BenchError("spec", "'tensor_split': lista de repartos como \"1/1\" o \"3/1\"")
    spec.tensor_split = list(ts)
    devs = data.get("devices") or []
    ok = isinstance(devs, list) and len(devs) <= MAX_VALUES
    for combo in devs if ok else []:
        parts = combo.split("/") if isinstance(combo, str) else [None]
        ok = ok and (combo == "none" or all(isinstance(p, str) and DEV_RE.match(p) for p in parts))
    if not ok:
        raise BenchError("spec", "'devices': lista como [\"CUDA0\"], [\"CUDA0/CUDA1\"] o [\"none\"]")
    spec.devices = list(devs)
    for key, allowed in (("flash_attn", FLASH_ATTN), ("cache_type_k", CACHE_TYPES), ("cache_type_v", CACHE_TYPES),
                         ("split_mode", SPLIT_MODES)):  # fmt: skip
        v = data.get(key)
        if v is not None:
            if v not in allowed:
                raise BenchError("spec", f"'{key}': uno de {', '.join(allowed)}")
            setattr(spec, key, v)
    if data.get("timeout_s") is not None:
        t = data["timeout_s"]
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not 10 <= t <= MAX_TIMEOUT_S:
            raise BenchError("spec", f"'timeout_s' entre 10 y {MAX_TIMEOUT_S}")
        spec.timeout_s = float(t)
    return spec


def parse_list_devices(text: str) -> list[dict[str, Any]]:
    """Salida de `llama-bench --list-devices` → [{name, description, total_mib, free_mib}]."""
    out = []
    for line in text.splitlines():
        m = LIST_DEVICES_RE.match(line)
        if m:
            out.append({"name": m.group(1), "description": m.group(2), "total_mib": int(m.group(3)),
                        "free_mib": int(m.group(4))})  # fmt: skip
    return out


def bench_env() -> dict[str, str]:
    return {**os.environ, "CUDA_DEVICE_ORDER": "PCI_BUS_ID"}


def _popen_kwargs() -> dict[str, Any]:
    kw: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
                          "env": bench_env(), "text": True, "encoding": "utf-8", "errors": "replace"}  # fmt: skip
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kw


def kill_tree(proc: subprocess.Popen) -> None:
    """Mata el proceso y sus hijos (en Windows un lanzador .cmd dejaría al hijo vivo)."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False,
                       creationflags=subprocess.CREATE_NO_WINDOW)  # fmt: skip
    if proc.poll() is None:
        proc.kill()


@dataclass
class BenchJob:
    id: int
    argv: list[str]
    status: str = "running"  # running | done | error | cancelled
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    returncode: int | None = None
    error: str | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    stderr: deque = field(default_factory=lambda: deque(maxlen=STDERR_LINES))
    simulated: bool = False

    def public(self, since: int = 0) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "argv": self.argv,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "returncode": self.returncode,
            "error": self.error,
            "rows_total": len(self.rows),
            "rows": self.rows[since:],
            "since": since,
            "stderr_tail": list(self.stderr),
            "simulated": self.simulated,
        }


class BenchRunner:
    """Un trabajo de llama-bench cada vez, en un hilo; las filas JSONL se leen según salen."""

    def __init__(self, exe: Path | None):
        self.exe = exe
        self.lock = threading.Lock()
        self.job: BenchJob | None = None
        self.proc: subprocess.Popen | None = None
        self._next_id = 1
        self._devices_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._version: str | None = None
        self._list_lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.exe is not None and self.exe.is_file()

    def _require(self) -> Path:
        if self.exe is None:
            raise BenchError("no_bench", "llama-bench no configurado (clave 'llama_bench' o --llama-bench)", 501)
        if not self.exe.is_file():
            raise BenchError("no_bench", f"No existe {self.exe}", 501)
        return self.exe

    def warm(self) -> None:
        """Calienta en segundo plano versión y dispositivos (llama-bench tarda en cargar CUDA)."""

        def run() -> None:
            try:
                self.version()
                self.list_devices()
            except BenchError:
                pass

        if self.available:
            threading.Thread(target=run, daemon=True, name="bench-warm").start()

    def version(self) -> str | None:
        if not self.available:
            return None
        if self._version is not None:
            return self._version
        try:
            r = subprocess.run([str(self.exe), "--version"], timeout=20, **_popen_kwargs())
        except (OSError, subprocess.TimeoutExpired):
            return None
        text = (r.stdout or "") + (r.stderr or "")
        m = re.search(r"version:\s*(.+)", text)
        self._version = m.group(1).strip() if m else None
        return self._version

    def list_devices(self) -> list[dict[str, Any]]:
        exe = self._require()
        with self._list_lock:  # una sola consulta a la vez; las demás esperan y usan la caché
            cached = self._devices_cache
            if cached and time.monotonic() - cached[0] < DEVICES_TTL_S:
                return cached[1]
            try:
                r = subprocess.run([str(exe), "--list-devices"], timeout=60, **_popen_kwargs())
            except subprocess.TimeoutExpired as exc:
                raise BenchError("timeout", "llama-bench --list-devices no respondió", 504) from exc
            devices = parse_list_devices((r.stdout or "") + "\n" + (r.stderr or ""))
            self._devices_cache = (time.monotonic(), devices)
            return devices

    def status(self, since: int = 0) -> dict[str, Any]:
        with self.lock:
            return {"job": self.job.public(since) if self.job else None, "configured": self.exe is not None}

    def start(self, spec: BenchSpec) -> dict[str, Any]:
        exe = self._require()
        with self.lock:
            if self.job and self.job.status == "running":
                raise BenchError("busy", "Ya hay un llama-bench en marcha", 409)
            job = BenchJob(id=self._next_id, argv=spec.argv(exe))
            self._next_id += 1
            self.job = job
        try:
            self.proc = subprocess.Popen(job.argv, **_popen_kwargs())
        except OSError as exc:
            job.status, job.error, job.finished_at = "error", f"No se pudo lanzar llama-bench: {exc}", time.time()
            raise BenchError("launch", job.error, 500) from exc
        threading.Thread(target=self._pump_err, args=(self.proc, job), daemon=True).start()
        threading.Thread(target=self._pump_out, args=(self.proc, job, spec.timeout_s), daemon=True).start()
        log.info("llama-bench #%s: %s", job.id, " ".join(job.argv))
        return job.public()

    def cancel(self) -> dict[str, Any]:
        with self.lock:
            job, proc = self.job, self.proc
        if job is None or job.status != "running":
            raise BenchError("idle", "No hay ningún llama-bench en marcha", 409)
        job.status = "cancelled"
        if proc is not None:
            kill_tree(proc)
        return job.public()

    def _pump_err(self, proc: subprocess.Popen, job: BenchJob) -> None:
        for line in proc.stderr:  # type: ignore[union-attr]
            line = line.rstrip()
            if line:
                job.stderr.append(line)

    def _pump_out(self, proc: subprocess.Popen, job: BenchJob, timeout_s: float) -> None:
        timer = threading.Timer(timeout_s, self._timeout, args=(proc, job, timeout_s))
        timer.daemon = True
        timer.start()
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    row["t"] = time.time()
                    job.rows.append(row)
            job.returncode = proc.wait()
        finally:
            timer.cancel()
        job.finished_at = time.time()
        if job.status == "running":
            if job.returncode == 0:
                job.status = "done"
            else:
                job.status = "error"
                tail = next((ln for ln in reversed(job.stderr) if ln.strip()), "")
                job.error = job.error or f"llama-bench terminó con código {job.returncode}: {tail[:300]}"

    def _timeout(self, proc: subprocess.Popen, job: BenchJob, timeout_s: float) -> None:
        if job.status == "running":
            job.error = f"Tiempo agotado ({timeout_s:.0f} s)"
            job.status = "error"
            kill_tree(proc)


class SimBenchRunner(BenchRunner):
    """llama-bench simulado (modo --simulate): filas creíbles y deterministas, sin GPU.

    t/s de generación ≈ ancho de banda / tamaño; con capas en "RAM" cae según
    la fracción, como la curva real. Sirve para la GUI y los tests.
    """

    def __init__(self, gpus: list[dict[str, Any]], row_delay_s: float = 0.15):
        super().__init__(None)
        self.gpus = gpus  # [{name, description, total_mib}]
        self.row_delay_s = row_delay_s

    @property
    def available(self) -> bool:
        return True

    def _require(self) -> Path:
        return Path("llama-bench-simulado")

    def version(self) -> str | None:
        return "simulado (build 0)"

    def list_devices(self) -> list[dict[str, Any]]:
        return [{**g, "free_mib": int(g["total_mib"] * 0.9)} for g in self.gpus]

    def start(self, spec: BenchSpec) -> dict[str, Any]:
        with self.lock:
            if self.job and self.job.status == "running":
                raise BenchError("busy", "Ya hay un llama-bench en marcha", 409)
            job = BenchJob(id=self._next_id, argv=spec.argv(self._require()), simulated=True)
            self._next_id += 1
            self.job = job
        threading.Thread(target=self._fake, args=(spec, job), daemon=True).start()
        return job.public()

    def cancel(self) -> dict[str, Any]:
        with self.lock:
            job = self.job
        if job is None or job.status != "running":
            raise BenchError("idle", "No hay ningún llama-bench en marcha", 409)
        job.status = "cancelled"
        return job.public()

    def _fake(self, spec: BenchSpec, job: BenchJob) -> None:
        size = spec.model.stat().st_size if spec.model.exists() else 4_000_000_000
        n_layers = 32
        combos: list[dict[str, Any]] = [{}]
        for key in ("n_gpu_layers", "threads", "n_cpu_moe", "batch", "ubatch", "n_depth"):
            if key in spec.ints:
                combos = [{**c, key: v} for c in combos for v in spec.ints[key]]
        combos = [{**c, "tensor_split": ts} for c in combos for ts in (spec.tensor_split or ["0.00"])]
        combos = [{**c, "devices": d} for c in combos for d in (spec.devices or ["auto"])]
        tests = [("pp", p) for p in spec.ints.get("n_prompt", [512]) if p] + [
            ("tg", n) for n in spec.ints.get("n_gen", [128]) if n
        ]
        for c in combos:
            for kind, n in tests:
                if job.status != "running":
                    break
                time.sleep(self.row_delay_s)
                ngl = min(c.get("n_gpu_layers", 99), n_layers + 1)
                cpu_only = c.get("devices") == "none" or ngl == 0
                frac = 0.0 if cpu_only else ngl / (n_layers + 1)
                threads = c.get("threads", 6)
                gpu_bw, cpu_bw = 340e9, 40e9 * min(1.0, threads / 6) ** 0.5
                bw = 1 / (frac / gpu_bw + (1 - frac) / cpu_bw)
                tg = bw / size
                pp = tg * (40 if frac > 0.5 else 4) * (1 + frac * 10)
                ts = pp if kind == "pp" else tg
                row = {
                    "build_commit": "simulado", "build_number": 0, "cpu_info": "CPU simulada",
                    "gpu_info": ", ".join(g["description"] for g in self.gpus), "backends": "CUDA",
                    "model_filename": str(spec.model), "model_type": "simulado", "model_size": size,
                    "model_n_params": int(size / 0.6), "n_batch": c.get("batch", 2048),
                    "n_ubatch": c.get("ubatch", 512), "n_threads": threads, "type_k": spec.cache_type_k or "f16",
                    "type_v": spec.cache_type_v or "f16", "n_gpu_layers": c.get("n_gpu_layers", 99),
                    "n_cpu_moe": c.get("n_cpu_moe", 0), "split_mode": spec.split_mode or "layer",
                    "flash_attn": spec.flash_attn or "auto", "devices": c["devices"],
                    "tensor_split": c["tensor_split"], "n_prompt": n if kind == "pp" else 0,
                    "n_gen": n if kind == "tg" else 0, "n_depth": c.get("n_depth", 0),
                    "avg_ts": ts, "stddev_ts": ts * 0.02, "avg_ns": int(n / ts * 1e9),
                    "samples_ts": _sim_samples(ts, spec.repetitions), "t": time.time(),
                }  # fmt: skip
                job.rows.append(row)
        job.finished_at = time.time()
        if job.status == "running":
            job.status, job.returncode = "done", 0


def _sim_samples(ts: float, reps: int) -> list[float]:
    """Una muestra por repetición, repartidas ±2 % alrededor de la media (llama-bench simulado)."""
    return [ts * (0.98 + 0.04 * i / max(reps - 1, 1)) for i in range(reps)]
