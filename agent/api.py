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
import time
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from agent import __version__
from agent.model import AGENT_API, HostInfo, to_jsonable
from agent.sampler import Sampler

log = logging.getLogger(__name__)

LOOPBACK_NAMES = {"localhost"}


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
        raise ValueError(
            f"Escuchar en {host!r} (fuera de localhost) exige un token (--token o ARENA_AGENT_TOKEN)"
        )


class AgentApp:
    def __init__(self, host: HostInfo, sampler: Sampler, token: str | None = None):
        self.host = host
        self.sampler = sampler
        self.token = token or None
        self.started = time.time()
        self.routes: dict[str, Callable[[], dict[str, Any]]] = {
            "/health": self.health,
            "/info": self.info,
            "/metrics": self.metrics,
        }

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "uptime_s": round(time.time() - self.started, 3)}

    def info(self) -> dict[str, Any]:
        devices, errors = self.sampler.devices()
        return {
            "host": self.host,
            "devices": devices,
            "providers": [p.name for p in self.sampler.providers],
            "errors": errors,
        }

    def metrics(self) -> dict[str, Any]:
        return {"snapshot": self.sampler.latest()}

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

    def handle(self, method: str, path: str, headers: Any) -> tuple[HTTPStatus, dict[str, Any]]:
        try:
            self.authorize(headers)
            route = self.routes.get(urlsplit(path).path.rstrip("/") or "/")
            if route is None:
                raise ApiError(HTTPStatus.NOT_FOUND, "not_found", f"Ruta desconocida: {path}")
            if method != "GET":
                raise ApiError(HTTPStatus.METHOD_NOT_ALLOWED, "method", f"Método no permitido: {method}")
            return HTTPStatus.OK, route()
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
            status, payload = app.handle(self.command, self.path, self.headers)
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
