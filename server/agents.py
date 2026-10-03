"""Sondeo de agentes: una tarea por equipo registrado.

Cada tarea pide `/metrics` cada `poll_interval_s` y `/info` al conectar y cada
`info_interval_s` (o si aparece un dispositivo nuevo), guarda los dispositivos
con su color estable y publica los cambios en el `EventHub`.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from server.db import Database
from server.hub import EventHub

log = logging.getLogger(__name__)

OFFLINE_RETRY_S = 3.0


class AgentError(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class HostState:
    pk: int
    agent_url: str
    name: str | None = None
    token: str | None = None
    status: str = "connecting"  # connecting | online | offline | unauthorized | error
    error: str | None = None
    info: dict[str, Any] | None = None
    info_at: float = 0.0
    metrics: dict[str, Any] | None = None
    last_ok: float | None = None
    colors: dict[str, int | None] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        info = self.info or {}
        devices = [{**d, "color_index": self.colors.get(d["device_id"])} for d in info.get("devices", [])]
        return {
            "id": self.pk,
            "agent_url": self.agent_url,
            "name": self.name or (info.get("host") or {}).get("hostname") or self.agent_url,
            "status": self.status,
            "error": self.error,
            "has_token": bool(self.token),
            "last_ok": self.last_ok,
            "agent_version": info.get("agent_version"),
            "agent_api": info.get("agent_api"),
            "simulated": info.get("simulated"),
            "host": info.get("host"),
            "devices": devices,
            "providers": info.get("providers", []),
            "errors": info.get("errors", {}),
        }


class AgentClient:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def get(
        self, state: HostState, path: str, params: dict | None = None, timeout: float | None = None
    ) -> dict[str, Any]:
        return await self.request(state, "GET", path, params=params, timeout=timeout)

    async def post(self, state: HostState, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.request(state, "POST", path, json=body or {})

    async def request(
        self,
        state: HostState,
        method: str,
        path: str,
        params: dict | None = None,
        json: Any = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        headers = {"X-Token": state.token} if state.token else {}
        extra = {"timeout": timeout} if timeout is not None else {}
        try:
            r = await self.client.request(
                method, state.agent_url.rstrip("/") + path, headers=headers, params=params, json=json, **extra
            )
        except httpx.TimeoutException as exc:
            raise AgentError("offline", "El agente no responde (tiempo agotado)") from exc
        except httpx.HTTPError as exc:
            raise AgentError("offline", f"No se puede conectar con el agente: {type(exc).__name__}") from exc
        try:
            body = r.json()
        except ValueError as exc:
            raise AgentError("error", f"Respuesta no JSON del agente (HTTP {r.status_code})") from exc
        if r.status_code in (401, 403) and isinstance(body.get("error"), dict):
            raise AgentError("unauthorized", body["error"].get("message", "No autorizado"))
        if r.status_code >= 400:
            msg = body.get("error", {}).get("message") if isinstance(body.get("error"), dict) else None
            raise AgentError("error", msg or f"HTTP {r.status_code}")
        return body


class AgentMonitor:
    def __init__(self, db: Database, hub: EventHub, client: httpx.AsyncClient, poll_s: float, info_s: float):
        self.db = db
        self.hub = hub
        self.agent = AgentClient(client)
        self.poll_s = poll_s
        self.info_s = info_s
        self.states: dict[int, HostState] = {}
        self.tasks: dict[int, asyncio.Task] = {}
        #: Funciones llamadas con cada muestra buena (p. ej. el gestor de runs)
        self.listeners: list[Callable[[HostState, dict[str, Any]], None]] = []

    def start_all(self) -> None:
        for h in self.db.list_hosts():
            self.start(h)

    def start(self, host: dict[str, Any]) -> HostState:
        state = HostState(pk=host["id"], agent_url=host["agent_url"], name=host.get("name"), token=host.get("token"))
        if host.get("info"):  # última ficha conocida: la GUI muestra algo mientras conecta
            state.info = host["info"]
            state.colors = self.db.upsert_devices(
                (host["info"].get("host") or {}).get("host_id", ""), host["info"].get("devices", [])
            )
        self.states[state.pk] = state
        self.tasks[state.pk] = asyncio.create_task(self._loop(state), name=f"agent-{state.pk}")
        return state

    async def stop(self, pk: int) -> None:
        task = self.tasks.pop(pk, None)
        self.states.pop(pk, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def stop_all(self) -> None:
        for pk in list(self.tasks):
            await self.stop(pk)

    def _set_status(self, state: HostState, status: str, error: str | None) -> None:
        if (state.status, state.error) != (status, error):
            state.status, state.error = status, error
            self.hub.publish("host", state.public())

    async def refresh_info(self, state: HostState) -> None:
        info = await self.agent.get(state, "/info")
        host_id = (info.get("host") or {}).get("host_id", "")
        state.colors = self.db.upsert_devices(host_id, info.get("devices", []))
        state.info = info
        state.info_at = time.monotonic()
        self.db.save_host_info(state.pk, info)
        self.hub.publish("host", state.public())

    async def poll_once(self, state: HostState) -> None:
        if state.info is None or state.status != "online" or time.monotonic() - state.info_at > self.info_s:
            await self.refresh_info(state)
        body = await self.agent.get(state, "/metrics")
        snap = body.get("snapshot") or {}
        known = {d["device_id"] for d in (state.info or {}).get("devices", [])}
        if set(snap.get("devices", {})) - known:  # dispositivo nuevo: volver a pedir la ficha
            await self.refresh_info(state)
        state.metrics = snap
        state.last_ok = time.time()
        self._set_status(state, "online", None)
        self.hub.publish("metrics", {"host": state.pk, "snapshot": snap})
        for listener in self.listeners:
            try:
                listener(state, snap)
            except Exception:
                log.exception("Listener de métricas falló")

    async def _loop(self, state: HostState) -> None:
        while True:
            started = time.monotonic()
            delay = self.poll_s
            try:
                await self.poll_once(state)
            except AgentError as exc:
                self._set_status(state, exc.status, exc.message)
                delay = max(self.poll_s, OFFLINE_RETRY_S)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # nunca dejar de sondear por un fallo inesperado
                log.exception("Agente %s: error inesperado", state.agent_url)
                self._set_status(state, "error", f"{type(exc).__name__}: {exc}")
                delay = max(self.poll_s, OFFLINE_RETRY_S)
            await asyncio.sleep(max(0.0, delay - (time.monotonic() - started)))
