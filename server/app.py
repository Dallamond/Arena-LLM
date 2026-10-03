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
from server.hub import EventHub, sse_format
from server.settings import Settings

SSE_HEARTBEAT_S = 15.0


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


def create_app(
    settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings.db_path)
        for url in settings.agents:
            db.ensure_host(url.rstrip("/"))
        client = httpx.AsyncClient(timeout=settings.request_timeout_s, transport=transport)
        hub = EventHub()
        monitor = AgentMonitor(db, hub, client, settings.poll_interval_s, settings.info_interval_s)
        app.state.db, app.state.hub, app.state.monitor = db, hub, monitor
        monitor.start_all()
        try:
            yield
        finally:
            await monitor.stop_all()
            await client.aclose()
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
