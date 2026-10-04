"""API HTTP del agente (solo biblioteca estándar).

Seguridad:
- Por defecto escucha en loopback. Fuera de loopback exige token (`X-Token`).
- Con token, todas las rutas lo exigen (comparación en tiempo constante).
- Sin token, solo se aceptan peticiones cuyo `Host` sea loopback: evita que una
  web abierta en el navegador llegue al agente por *DNS rebinding*.
"""

import hmac
import ipaddress
import json
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from agent import __version__, gguf
from agent.bench import BenchError, BenchRunner, SimBenchRunner, parse_spec
from agent.config import AgentConfig
from agent.gguf import GgufInfo
from agent.model import AGENT_API, HostInfo, to_jsonable
from agent.processes import ServerDetector
from agent.sampler import Sampler

log = logging.getLogger(__name__)

LOOPBACK_NAMES = {"localhost"}
MAX_MODEL_DEPTH = 4
MAX_BODY = 64 * 1024
SPLIT_RE = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.IGNORECASE)


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def is_loopback(host: str) -> bool:
    host = host.strip("[]").lower()
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_bind(host: str, token: str | None) -> None:
    """Se niega a escuchar fuera de loopback sin token."""
    if not is_loopback(host) and not token:
        raise ValueError(f"Escuchar en {host!r} (fuera de localhost) exige un token (--token o ARENA_AGENT_TOKEN)")


class AgentApp:
    def __init__(
        self,
        host: HostInfo,
        sampler: Sampler,
        token: str | None = None,
        simulated: str | None = None,
        detector: ServerDetector | None = None,
        config: AgentConfig | None = None,
        bench: BenchRunner | None = None,
    ):
        self.host = host
        self.config = config or AgentConfig()
        self._gguf_cache: dict[tuple[str, int, int], gguf.GgufInfo] = {}
        self._gguf_lock = threading.Lock()
        self.detector = detector
        self.simulated = simulated
        self.sampler = sampler
        self.token = token or None
        self.started = time.time()
        self.routes: dict[str, Callable[[dict[str, str]], dict[str, Any]]] = {
            "/health": self.health,
            "/info": self.info,
            "/metrics": self.metrics,
            "/servers": self.servers,
            "/models": self.models,
            "/gguf": self.gguf,
            "/bench": self.bench_status,
            "/bench/devices": self.bench_devices,
        }
        self.post_routes: dict[str, Callable[[dict[str, str], Any], dict[str, Any]]] = {
            "/bench": self.bench_start,
            "/bench/cancel": self.bench_cancel,
        }
        if bench is None:
            if simulated and self.config.llama_bench is None:
                gpus, _ = sampler.devices()
                bench = SimBenchRunner(
                    [
                        {"name": f"CUDA{d.index}", "description": d.name, "total_mib": d.memory_total_mib or 0}
                        for d in gpus
                        if d.kind == "gpu" and d.index is not None
                    ]
                )
            else:
                bench = BenchRunner(self.config.llama_bench)
        self.bench = bench

    def health(self, query: dict[str, str] | None = None) -> dict[str, Any]:
        return {"status": "ok", "uptime_s": round(time.time() - self.started, 3), "simulated": self.simulated}

    def info(self, query: dict[str, str] | None = None) -> dict[str, Any]:
        devices, errors = self.sampler.devices()
        return {
            "host": self.host,
            "simulated": self.simulated,
            "devices": devices,
            "providers": [p.name for p in self.sampler.providers],
            "errors": errors,
            "capabilities": {"bench": self.bench.available},
            "tools": {"llama_server": _path_or_none(self.config.llama_server_path())},
        }

    def metrics(self, query: dict[str, str] | None = None) -> dict[str, Any]:
        return {"snapshot": self.sampler.latest()}

    def servers(self, query: dict[str, str] | None = None) -> dict[str, Any]:
        if self.detector is None:
            raise ApiError(HTTPStatus.NOT_IMPLEMENTED, "no_detector", "Detección de servidores no disponible")
        return self.detector.detect()

    def models(self, query: dict[str, str] | None = None) -> dict[str, Any]:
        """Ficheros GGUF de las carpetas permitidas (sin leer cabeceras)."""
        files: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for d in self.config.model_dirs:
            if not d.is_dir():
                errors[str(d)] = "no existe o no es una carpeta"
                continue
            root_depth = len(d.parts)
            for dirpath, dirnames, filenames in os.walk(d):
                if len(Path(dirpath).parts) - root_depth >= MAX_MODEL_DEPTH:
                    dirnames.clear()
                for name in filenames:
                    if not name.lower().endswith(".gguf"):
                        continue
                    fp = Path(dirpath) / name
                    try:
                        st = fp.stat()
                    except OSError:
                        continue
                    m = SPLIT_RE.search(name)
                    files.append(
                        {
                            "path": str(fp),
                            "file": name,
                            "dir": str(d),
                            "size": st.st_size,
                            "mtime": st.st_mtime,
                            "split_part": int(m.group(1)) if m else None,
                            "split_total": int(m.group(2)) if m else None,
                        }
                    )
        files.sort(key=lambda f: f["path"].lower())
        return {"model_dirs": [str(d) for d in self.config.model_dirs], "files": files, "errors": errors}

    def gguf(self, query: dict[str, str] | None = None) -> dict[str, Any]:
        raw = (query or {}).get("path", "")
        if not self.config.model_dirs:
            raise ApiError(HTTPStatus.FORBIDDEN, "no_model_dirs", "No hay carpetas de modelos configuradas")
        path = self.config.allowed_model(raw)
        if path is None:
            raise ApiError(HTTPStatus.FORBIDDEN, "path", "Ruta no permitida: debe ser un .gguf dentro de model_dirs")
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime_ns)
        with self._gguf_lock:
            cached = self._gguf_cache.get(key)
        if cached is None:
            try:
                cached = gguf.read_header(path)
                if (cached.split_count or 1) > 1:
                    self._merge_split_parts(path, cached)
            except gguf.GgufError as exc:
                raise ApiError(HTTPStatus.UNPROCESSABLE_ENTITY, "gguf", str(exc)) from exc
            with self._gguf_lock:
                if len(self._gguf_cache) > 256:
                    self._gguf_cache.clear()
                self._gguf_cache[key] = cached
        return {"gguf": cached}

    def _merge_split_parts(self, path: Path, info: GgufInfo) -> None:
        """Modelo partido: suma el `layout` de las demás partes (si están todas y permitidas)."""
        m = SPLIT_RE.search(path.name)
        if not m:
            return
        total = int(m.group(2))
        layouts, missing = [], []
        for k in range(1, total + 1):
            part = path.with_name(f"{path.name[: m.start()]}-{k:05d}-of-{total:05d}.gguf")
            if part == path:
                layouts.append(info.layout)
                continue
            allowed = self.config.allowed_model(str(part))
            if allowed is None:
                missing.append(part.name)
                continue
            layouts.append(gguf.read_header(allowed).layout)
        info.layout = gguf.merge_layouts(layouts)
        info.layout["split_missing"] = missing

    # --- llama-bench ---------------------------------------------------------

    def bench_status(self, query: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            since = max(0, int((query or {}).get("since", "0")))
        except ValueError:
            since = 0
        return self.bench.status(since)

    def bench_devices(self, query: dict[str, str] | None = None) -> dict[str, Any]:
        """Dispositivos que ve llama-bench, enlazados con los del agente (por nombre y orden PCI)."""
        try:
            listed = self.bench.list_devices()
        except BenchError as exc:
            raise ApiError(HTTPStatus(exc.status), exc.code, exc.message) from exc
        gpus, _ = self.sampler.devices()
        pool = sorted((d for d in gpus if d.kind == "gpu"), key=lambda d: (d.index is None, d.index or 0))
        out = []
        for b in listed:
            match = next((d for d in pool if d.name and d.name in b["description"]), None)
            if match is None and pool:
                match = pool[0]
            if match is not None:
                pool.remove(match)
            out.append({**b, "device_id": match.device_id if match else None})
        exe = self.bench.exe
        return {"devices": out, "version": self.bench.version(), "exe": str(exe) if exe else None,
                "simulated": isinstance(self.bench, SimBenchRunner)}  # fmt: skip

    def bench_start(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        try:
            spec = parse_spec(body, self.config.allowed_model)
            return {"job": self.bench.start(spec)}
        except BenchError as exc:
            raise ApiError(HTTPStatus(exc.status), exc.code, exc.message) from exc

    def bench_cancel(self, query: dict[str, str], body: Any) -> dict[str, Any]:
        try:
            return {"job": self.bench.cancel()}
        except BenchError as exc:
            raise ApiError(HTTPStatus(exc.status), exc.code, exc.message) from exc

    def authorize(self, headers: Any) -> None:
        if self.token:
            given = headers.get("X-Token") or ""
            if not hmac.compare_digest(given.encode("utf-8"), self.token.encode("utf-8")):
                raise ApiError(HTTPStatus.UNAUTHORIZED, "token", "Token ausente o incorrecto")
            return
        host_header = headers.get("Host") or ""
        hostname = urlsplit(f"//{host_header}").hostname or ""
        if not is_loopback(hostname):
            raise ApiError(HTTPStatus.FORBIDDEN, "host", "Sin token solo se aceptan peticiones a localhost")

    def handle(
        self, method: str, path: str, headers: Any, body: bytes = b""
    ) -> tuple[HTTPStatus, dict[str, Any]]:
        try:
            self.authorize(headers)
            route_path = urlsplit(path).path.rstrip("/") or "/"
            query = {k: v[-1] for k, v in parse_qs(urlsplit(path).query).items()}
            if method == "POST" and route_path in self.post_routes:
                if headers.get("Origin"):  # una web no debe poder lanzar procesos a través del navegador
                    raise ApiError(HTTPStatus.FORBIDDEN, "origin", "Peticiones desde navegador no permitidas")
                try:
                    data = json.loads(body.decode("utf-8")) if body else {}
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "json", "Cuerpo JSON inválido") from exc
                return HTTPStatus.OK, self.post_routes[route_path](query, data)
            route = self.routes.get(route_path)
            if route is None:
                if route_path in self.post_routes:
                    raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "method", f"Método no permitido: {method}")
                raise ApiError(HTTPStatus.NOT_FOUND, "not_found", f"Ruta desconocida: {path}")
            if method != "GET":
                raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "method", f"Método no permitido: {method}")
            return HTTPStatus.OK, route(query)
        except ApiError as exc:
            return exc.status, {"error": {"code": exc.code, "message": exc.message}}
        except Exception as exc:
            log.exception("Error interno en %s %s", method, path)
            return HTTPStatus.INTERNAL_SERVER_ERROR, {
                "error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}"}
            }


def envelope(payload: dict[str, Any]) -> bytes:
    body = {"agent_api": AGENT_API, "agent_version": __version__, **payload}
    return json.dumps(to_jsonable(body), ensure_ascii=False, allow_nan=False).encode("utf-8")


def make_handler(app: AgentApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = f"ArenaAgent/{__version__}"
        sys_version = ""

        def _respond(self) -> None:
            body = b""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if 0 < length <= MAX_BODY:
                body = self.rfile.read(length)
            status, payload = app.handle(self.command, self.path, self.headers, body)
            body = envelope(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _respond

        def log_message(self, format: str, *args: Any) -> None:
            log.debug("%s - %s", self.address_string(), format % args)

    return Handler


def make_server(app: AgentApp, host: str, port: int) -> ThreadingHTTPServer:
    check_bind(host, app.token)
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    return server


def _path_or_none(p) -> str | None:
    return str(p) if p else None
