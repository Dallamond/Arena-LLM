"""API del servidor Arena (FastAPI) y servido de la web compilada."""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from server import __version__
from server.agents import AgentError, AgentMonitor
from server.db import Database
from server.detect import EndpointDetector
from server.hub import EventHub, sse_format
from server.runs.manager import RunError, RunManager, _run_public
from server.runs.suites import SUITES
from server.settings import Settings

SSE_HEARTBEAT_S = 15.0


class RunIn(BaseModel):
    suite: str
    endpoint_id: int
    label: str | None = None
    params: dict[str, Any] = {}


class AliasIn(BaseModel):
    alias: str | None = None


#: Claves de ajustes que acepta la API (el resto se rechaza).
SETTINGS_KEYS = {"appearance", "thresholds"}


class HostIn(BaseModel):
    agent_url: str
    name: str | None = None
    token: str | None = None

    @field_validator("agent_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        parts = urlsplit(v)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("URL del agente inválida (ej.: http://127.0.0.1:9100)")
        return v


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings.db_path)
        for url in settings.agents:
            db.ensure_host(url.rstrip("/"))
        client = httpx.AsyncClient(timeout=settings.request_timeout_s, transport=transport)
        hub = EventHub()
        # Cliente aparte para inferencia: respuestas largas en streaming
        llm = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=600.0), transport=transport)
        hub = EventHub()
        monitor = AgentMonitor(db, hub, client, settings.poll_interval_s, settings.info_interval_s)
        detector = EndpointDetector(db, hub, monitor, client)
        runs = RunManager(db, hub, monitor, llm)
        db.mark_interrupted_runs()
        app.state.db, app.state.hub, app.state.monitor = db, hub, monitor
        app.state.detector, app.state.runs = detector, runs
        monitor.start_all()
        detector.start()
        try:
            yield
        finally:
            await runs.shutdown()
            await detector.stop()
            await monitor.stop_all()
            await client.aclose()
            await llm.aclose()
            db.close()

    app = FastAPI(title="Arena LLM", version=__version__, lifespan=lifespan)

    def monitor(request: Request) -> AgentMonitor:
        return request.app.state.monitor

    def state_or_404(request: Request, host_id: int):
        state = monitor(request).states.get(host_id)
        if state is None:
            raise HTTPException(404, "Equipo no registrado")
        return state

    @app.get("/api/health")
    def health(request: Request) -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "subscribers": request.app.state.hub.subscribers}

    @app.get("/api/hosts")
    def list_hosts(request: Request) -> list[dict[str, Any]]:
        return [s.public() for s in monitor(request).states.values()]

    @app.post("/api/hosts", status_code=201)
    async def add_host(request: Request, body: HostIn) -> dict[str, Any]:
        db: Database = request.app.state.db
        if any(h["agent_url"] == body.agent_url for h in db.list_hosts()):
            raise HTTPException(409, "Ese agente ya está registrado")
        host = db.add_host(body.agent_url, body.name, body.token or None)
        state = monitor(request).start(host)
        request.app.state.hub.publish("host", state.public())
        return state.public()

    @app.delete("/api/hosts/{host_id}", status_code=204)
    async def delete_host(request: Request, host_id: int) -> None:
        state_or_404(request, host_id)
        await monitor(request).stop(host_id)
        request.app.state.db.delete_host(host_id)
        request.app.state.hub.publish("host_removed", {"id": host_id})

    @app.get("/api/hosts/{host_id}/metrics")
    def host_metrics(request: Request, host_id: int) -> dict[str, Any]:
        state = state_or_404(request, host_id)
        return {"host": host_id, "status": state.status, "snapshot": state.metrics}

    async def proxy(request: Request, host_id: int, path: str, params: dict | None = None) -> dict[str, Any]:
        state = state_or_404(request, host_id)
        try:
            return await monitor(request).agent.get(state, path, params)
        except AgentError as exc:
            code = 403 if exc.status == "unauthorized" else 502
            raise HTTPException(code, exc.message) from exc

    @app.get("/api/hosts/{host_id}/servers")
    async def host_servers(request: Request, host_id: int) -> dict[str, Any]:
        return await proxy(request, host_id, "/servers")

    @app.get("/api/hosts/{host_id}/models")
    async def host_models(request: Request, host_id: int) -> dict[str, Any]:
        return await proxy(request, host_id, "/models")

    @app.get("/api/hosts/{host_id}/gguf")
    async def host_gguf(request: Request, host_id: int, path: str) -> dict[str, Any]:
        return await proxy(request, host_id, "/gguf", {"path": path})

    # --- ajustes -------------------------------------------------------------

    @app.get("/api/settings")
    def get_settings(request: Request) -> dict[str, Any]:
        return request.app.state.db.get_settings()

    @app.put("/api/settings/{key}")
    async def put_setting(request: Request, key: str) -> dict[str, Any]:
        if key not in SETTINGS_KEYS:
            raise HTTPException(404, f"Ajuste desconocido: {key}")
        value = await request.json()
        if not isinstance(value, dict):
            raise HTTPException(422, "El valor debe ser un objeto JSON")
        request.app.state.db.set_setting(key, value)
        request.app.state.hub.publish("settings", {"key": key, "value": value})
        return {"key": key, "value": value}

    # --- servidores detectados -----------------------------------------------

    @app.get("/api/endpoints")
    def endpoints(request: Request, host: int | None = None) -> list[dict[str, Any]]:
        return request.app.state.db.list_endpoints(host)

    @app.post("/api/endpoints/detect", status_code=202)
    def detect_now(request: Request) -> dict[str, Any]:
        request.app.state.detector.trigger()
        return {"status": "detectando"}

    @app.patch("/api/endpoints/{endpoint_id}")
    def set_alias(request: Request, endpoint_id: int, body: AliasIn) -> dict[str, Any]:
        db: Database = request.app.state.db
        if db.get_endpoint(endpoint_id) is None:
            raise HTTPException(404, "Servidor no registrado")
        db.set_endpoint_alias(endpoint_id, (body.alias or "").strip() or None)
        return db.get_endpoint(endpoint_id)

    @app.get("/api/changes")
    def changes(request: Request, endpoint: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return request.app.state.db.list_config_changes(endpoint, min(max(limit, 1), 1000))

    # --- pruebas (runs) -------------------------------------------------------

    @app.get("/api/suites")
    def suites() -> list[dict[str, Any]]:
        return [s.public() for s in SUITES.values()]

    @app.get("/api/runs")
    def list_runs(request: Request, limit: int = 200) -> list[dict[str, Any]]:
        return request.app.state.db.list_runs(min(max(limit, 1), 2000))

    @app.post("/api/runs", status_code=201)
    async def start_run(request: Request, body: RunIn) -> dict[str, Any]:
        try:
            run = await request.app.state.runs.start(body.suite, body.endpoint_id, body.params, body.label)
        except RunError as exc:
            raise HTTPException(exc.status, exc.message) from exc
        return _run_public(run)

    @app.get("/api/runs/{run_id}")
    def get_run(request: Request, run_id: int) -> dict[str, Any]:
        db: Database = request.app.state.db
        run = db.get_run(run_id)
        if run is None:
            raise HTTPException(404, "Run no encontrado")
        return {
            **run,
            "items": db.list_items(run_id),
            "tps": db.list_tps(run_id),
            "samples": db.list_samples(run_id),
        }

    @app.post("/api/runs/{run_id}/cancel", status_code=202)
    async def cancel_run(request: Request, run_id: int) -> dict[str, Any]:
        try:
            await request.app.state.runs.cancel(run_id)
        except RunError as exc:
            raise HTTPException(exc.status, exc.message) from exc
        return {"status": "cancelando"}

    @app.delete("/api/runs/{run_id}", status_code=204)
    def delete_run(request: Request, run_id: int) -> None:
        if run_id in request.app.state.runs.active:
            raise HTTPException(409, "La prueba está en marcha: detenla antes de borrarla")
        if not request.app.state.db.delete_run(run_id):
            raise HTTPException(404, "Run no encontrado")

    @app.get("/api/devices")
    def devices(request: Request) -> list[dict[str, Any]]:
        return request.app.state.db.list_devices()

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        hub: EventHub = request.app.state.hub
        mon = monitor(request)

        async def stream() -> AsyncIterator[str]:
            q = hub.subscribe()
            try:
                # Estado inicial completo: la GUI pinta sin esperar al siguiente sondeo
                yield sse_format("hello", f'{{"version":"{__version__}","t":{time.time()}}}')
                for s in mon.states.values():
                    yield sse_format("host", _json(s.public()))
                    if s.metrics is not None:
                        yield sse_format("metrics", _json({"host": s.pk, "snapshot": s.metrics}))
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event, payload = await asyncio.wait_for(q.get(), timeout=SSE_HEARTBEAT_S)
                        yield sse_format(event, payload)
                    except TimeoutError:
                        yield ": latido\n\n"
            finally:
                hub.unsubscribe(q)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    # --- web compilada (web/dist) con retorno a index.html para las rutas de la SPA
    dist = settings.web_dist
    if (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> FileResponse:
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
                return FileResponse(candidate)
            if full_path.startswith("api/"):
                raise HTTPException(404)
            return FileResponse(dist / "index.html")

    return app


def _json(data: Any) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
