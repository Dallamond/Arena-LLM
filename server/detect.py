"""Detección de servidores de inferencia (la GUI detecta, no controla).

Cada `DETECT_EVERY_S` segundos, por cada equipo en línea:
1. Pide al agente `/servers` (procesos, línea de comandos, GPU por proceso).
2. Consulta a cada llama-server `/health`, `/props`, `/slots` y `/v1/models`
   (parseo tolerante: se guarda el JSON crudo).
3. Calcula una huella de configuración; si cambia, registra el cambio con su
   diff. Un reinicio con la misma configuración se registra como "reinicio".
"""

import asyncio
import hashlib
import json
import logging
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from server.agents import AgentError, AgentMonitor, HostState
from server.db import Database
from server.hub import EventHub

log = logging.getLogger(__name__)

DETECT_EVERY_S = 5.0
WILDCARD_HOSTS = {"", "0.0.0.0", "::", "[::]", "*"}
#: Campos de /props que no aportan a la configuración y pesan mucho.
PROPS_DROP = {"chat_template", "media_marker"}


def reach_host(server_host: str, agent_url: str) -> str:
    """Dirección para llegar al llama-server desde el servidor Arena."""
    agent_host = urlsplit(agent_url).hostname or "127.0.0.1"
    if server_host in WILDCARD_HOSTS:
        return agent_host
    return server_host


def base_url_for(server: dict[str, Any], agent_url: str) -> str | None:
    port = server.get("port")
    if not isinstance(port, int):
        return None
    host = reach_host(str(server.get("host") or ""), agent_url)
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}"


def _num(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def derive(props: dict[str, Any] | None, slots: Any, flags: dict[str, Any]) -> dict[str, Any]:
    """Datos normalizados a partir de /props y /slots (tolerante a cambios de campos)."""
    props = props or {}
    dgs = props.get("default_generation_settings") or {}
    n_ctx_slot = _num(dgs.get("n_ctx")) or _num(props.get("n_ctx"))
    if n_ctx_slot is None and isinstance(slots, list) and slots and isinstance(slots[0], dict):
        n_ctx_slot = _num(slots[0].get("n_ctx"))
    total_slots = _num(props.get("total_slots")) or (len(slots) if isinstance(slots, list) else None)
    busy = sum(1 for s in slots if isinstance(s, dict) and s.get("is_processing")) if isinstance(slots, list) else None
    return {
        "model_path": props.get("model_path") or flags.get("model"),
        "model_alias": props.get("model_alias"),
        "model_ftype": props.get("model_ftype"),
        "build_info": props.get("build_info"),
        "n_ctx_slot": n_ctx_slot,
        "total_slots": total_slots,
        "n_ctx_total": n_ctx_slot * total_slots if n_ctx_slot and total_slots else None,
        "slots_busy": busy,
        "chat_template_sha": hashlib.sha256(props["chat_template"].encode()).hexdigest()[:16]
        if isinstance(props.get("chat_template"), str)
        else None,
        "modalities": props.get("modalities"),
    }


def config_view(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Lo que define la configuración (sin pid, horas ni estado de slots)."""
    d = snapshot.get("derived") or {}
    flags = dict(snapshot.get("flags") or {})
    flags.pop("port", None)
    return {
        "modelo": d.get("model_path") or snapshot.get("model_path"),
        "cuantizacion": d.get("model_ftype"),
        "build": d.get("build_info"),
        "ctx_por_slot": d.get("n_ctx_slot"),
        "slots": d.get("total_slots"),
        "plantilla": d.get("chat_template_sha"),
        "gpus": sorted(u["device_id"] for u in snapshot.get("devices") or []),
        **{f"flag:{k}": v for k, v in sorted(flags.items())},
        **{f"flag?:{k}": v for k, v in sorted((snapshot.get("unknown") or {}).items())},
    }


def fingerprint(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config_view(snapshot), sort_keys=True, default=str).encode()).hexdigest()[:20]


def diff_config(before: dict[str, Any] | None, after: dict[str, Any]) -> dict[str, list[Any]]:
    a, b = config_view(before or {}), config_view(after)
    return {k: [a.get(k), b.get(k)] for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}


class EndpointDetector:
    def __init__(self, db: Database, hub: EventHub, monitor: AgentMonitor, client: httpx.AsyncClient):
        self.db = db
        self.hub = hub
        self.monitor = monitor
        self.client = client
        self.task: asyncio.Task | None = None
        self._wake = asyncio.Event()

    def start(self) -> None:
        self.task = asyncio.create_task(self._loop(), name="endpoint-detector")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    def trigger(self) -> None:
        self._wake.set()

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.gather(*(self.detect_host(s) for s in list(self.monitor.states.values())))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Fallo en la detección de servidores")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=DETECT_EVERY_S)
            except TimeoutError:
                pass

    async def _get(self, url: str) -> tuple[int | None, Any]:
        try:
            r = await self.client.get(url)
        except httpx.HTTPError:
            return None, None
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, None

    async def probe(self, base_url: str) -> dict[str, Any]:
        (h_code, health), (p_code, props), (s_code, slots), (m_code, models) = await asyncio.gather(
            self._get(base_url + "/health"),
            self._get(base_url + "/props"),
            self._get(base_url + "/slots"),
            self._get(base_url + "/v1/models"),
        )
        if h_code == 200:
            status = "listo"
        elif h_code == 503:
            status = "cargando"
        elif h_code is None:
            status = "sin respuesta"
        else:
            status = f"error {h_code}"
        props_ok = props if p_code == 200 and isinstance(props, dict) else None
        return {
            "status": status,
            "health": health,
            "props": props_ok,
            "slots": slots if s_code == 200 else None,
            "models": models if m_code == 200 else None,
        }

    async def detect_host(self, state: HostState) -> list[dict[str, Any]]:
        if state.status != "online":
            return []
        try:
            body = await self.monitor.agent.get(state, "/servers")
        except AgentError:
            return []
        seen: set[int] = set()
        out = []
        for srv in body.get("servers", []):
            base = base_url_for(srv, state.agent_url)
            if base is None:
                continue
            probe = await self.probe(base)
            props = probe["props"]
            snapshot = {
                "engine": srv.get("engine"),
                "base_url": base,
                "pid": srv.get("pid"),
                "started_at": srv.get("started_at"),
                "exe": srv.get("exe"),
                "argv": srv.get("argv"),
                "flags": srv.get("flags") or {},
                "unknown": srv.get("unknown") or {},
                "model_path": srv.get("model_path"),
                "model_file": srv.get("model_file"),
                "port_source": srv.get("port_source"),
                "devices": srv.get("devices") or [],
                "gpu_link": srv.get("gpu_link"),
                "status": probe["status"],
                "props": {k: v for k, v in props.items() if k not in PROPS_DROP} if props else None,
                "slots": probe["slots"],
                "models": probe["models"],
                "derived": derive(props, probe["slots"], srv.get("flags") or {}),
                "detected_at": time.time(),
            }
            prev = next((e for e in self.db.list_endpoints(state.pk) if e["base_url"] == base), None)
            # Mientras carga, /props no está: no se compara para no registrar cambios falsos
            fp = fingerprint(snapshot) if probe["status"] == "listo" or prev is None else prev["fingerprint"]
            ep, change = self.db.upsert_endpoint(state.pk, base, "llama.cpp", probe["status"], fp, snapshot)
            seen.add(ep["id"])
            prev_snap = prev["snapshot"] if prev else None
            if change == "nuevo":
                self._change(ep, "nuevo", None, snapshot)
            elif change == "cambio" and probe["status"] == "listo":
                self._change(ep, "cambio", diff_config(prev_snap, snapshot), snapshot)
            elif prev_snap and prev_snap.get("pid") != snapshot["pid"]:
                self._change(ep, "reinicio", {"pid": [prev_snap.get("pid"), snapshot["pid"]]}, snapshot)
            elif prev and prev["status"] == "detenido":
                self._change(ep, "vuelve", None, snapshot)
            out.append(ep)
        for ep in self.db.list_endpoints(state.pk):
            if ep["id"] not in seen and ep["status"] != "detenido":
                self.db.set_endpoint_status(ep["id"], "detenido")
                self._change(ep, "detenido", None, None)
        self.hub.publish("endpoints", {"host": state.pk, "endpoints": self.db.list_endpoints(state.pk)})
        return out

    def _change(self, ep: dict[str, Any], kind: str, diff: dict | None, snapshot: dict | None) -> None:
        row = self.db.add_config_change(ep["id"], kind, diff, snapshot)
        self.hub.publish("config_change", {**row, "snapshot": None, "base_url": ep["base_url"]})
