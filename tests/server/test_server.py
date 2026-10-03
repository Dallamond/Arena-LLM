"""Servidor contra agentes simulados reales (HTTP en un hilo), sin GPU."""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from agent.api import AgentApp, make_server
from agent.host import enrich_host
from agent.processes import ServerDetector
from agent.sampler import Sampler
from agent.simulate import build_profile
from server.app import create_app
from server.db import Database
from server.settings import Settings


def start_agent(profile: str, token: str | None = None):
    host, providers, procs = build_profile(profile)
    sampler = Sampler(providers, interval_s=0.1)
    devices = sampler.refresh_devices()
    first = sampler.sample_once()
    app = AgentApp(enrich_host(host, devices, first.ram), sampler, token=token, simulated=profile,
                   detector=ServerDetector(procs, providers))  # fmt: skip
    sampler.start()
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"

    def stop():
        server.shutdown()
        server.server_close()
        sampler.stop()

    return url, stop


@pytest.fixture
def agents():
    stops = []

    def make(profile="nvidia2", token=None):
        url, stop = start_agent(profile, token)
        stops.append(stop)
        return url

    yield make
    for s in stops:
        s()


def settings(tmp_path, *agent_urls):
    return Settings(data_dir=tmp_path, agents=list(agent_urls), poll_interval_s=0.05, request_timeout_s=1.0,
                    web_dist=tmp_path / "sin-web")  # fmt: skip


def wait_for(client, pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        hosts = client.get("/api/hosts").json()
        if pred(hosts):
            return hosts
        time.sleep(0.05)
    raise AssertionError(f"condición no alcanzada: {client.get('/api/hosts').json()}")


def test_agente_simulado_en_linea_con_colores_estables(tmp_path, agents):
    url = agents("nvidia2")
    with TestClient(create_app(settings(tmp_path, url))) as c:
        [h] = wait_for(c, lambda hs: hs and hs[0]["status"] == "online" and hs[0]["devices"])
        assert h["simulated"] == "nvidia2"
        gpus = [d for d in h["devices"] if d["kind"] == "gpu"]
        assert sorted(d["color_index"] for d in gpus) == [0, 1]
        assert all(d["color_index"] is None for d in h["devices"] if d["kind"] == "cpu")
        m = c.get(f"/api/hosts/{h['id']}/metrics").json()
        assert set(m["snapshot"]["devices"]) == {d["device_id"] for d in h["devices"]}
        servers = c.get(f"/api/hosts/{h['id']}/servers").json()["servers"]
        assert [s["port"] for s in servers] == [8081, 8082]
        before = {d["device_id"]: d["color_index"] for d in gpus}

    # Reinicio con la misma base de datos y un segundo equipo: los colores no cambian
    url2 = agents("partial")
    with TestClient(create_app(settings(tmp_path, url, url2))) as c:
        hosts = wait_for(c, lambda hs: len(hs) == 2 and all(h["status"] == "online" for h in hs))
        colors = {d["device_id"]: d["color_index"] for h in hosts for d in h["devices"] if d["kind"] == "gpu"}
        assert all(colors[k] == v for k, v in before.items())
        assert len(set(colors.values())) == 3  # la GPU nueva recibe el siguiente color libre


def test_agente_caido(tmp_path):
    with TestClient(create_app(settings(tmp_path, "http://127.0.0.1:1"))) as c:
        [h] = wait_for(c, lambda hs: hs[0]["status"] == "offline")
        assert "conectar" in h["error"] or "no responde" in h["error"]
        assert c.get(f"/api/hosts/{h['id']}/servers").status_code == 502


def test_agente_con_token(tmp_path, agents):
    url = agents("cpu-only", token="t0k")
    with TestClient(create_app(settings(tmp_path))) as c:
        bad = c.post("/api/hosts", json={"agent_url": url}).json()
        wait_for(c, lambda hs: hs[0]["status"] == "unauthorized")
        c.delete(f"/api/hosts/{bad['id']}")
        ok = c.post("/api/hosts", json={"agent_url": url, "token": "t0k"}).json()
        assert ok["has_token"] and "token" not in ok
        [h] = wait_for(c, lambda hs: hs and hs[0]["status"] == "online")
        assert [d["kind"] for d in h["devices"]] == ["cpu"]


def test_alta_validacion_y_baja(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as c:
        assert c.post("/api/hosts", json={"agent_url": "ftp://x"}).status_code == 422
        h = c.post("/api/hosts", json={"agent_url": "http://127.0.0.1:1/"}).json()
        assert h["agent_url"] == "http://127.0.0.1:1"
        assert c.post("/api/hosts", json={"agent_url": "http://127.0.0.1:1"}).status_code == 409
        assert c.delete(f"/api/hosts/{h['id']}").status_code == 204
        assert c.get("/api/hosts").json() == []
        assert c.delete(f"/api/hosts/{h['id']}").status_code == 404


@pytest.fixture
def live_server(tmp_path):
    """uvicorn real en un hilo (TestClient no soporta bien flujos SSE infinitos)."""
    import uvicorn

    servers = []

    def start(app):
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        end = time.monotonic() + 10
        while not server.started and time.monotonic() < end:
            time.sleep(0.02)
        servers.append((server, thread))
        port = server.servers[0].sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    yield start
    for server, thread in servers:
        server.should_exit = True
        thread.join(timeout=10)


def test_eventos_sse_estado_inicial_y_metricas(tmp_path, agents, live_server):
    import httpx

    base = live_server(create_app(settings(tmp_path, agents("nvidia2"))))
    with httpx.Client(base_url=base, timeout=10) as c:
        end = time.monotonic() + 5
        while c.get("/api/hosts").json()[0]["status"] != "online" and time.monotonic() < end:
            time.sleep(0.05)
        seen: list[str] = []
        with c.stream("GET", "/api/events") as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            event = None
            for line in r.iter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: ") and event:
                    data = json.loads(line[6:])
                    seen.append(event)
                    if event == "metrics":
                        assert data["snapshot"]["devices"]
                    if seen.count("metrics") >= 2:
                        break
        assert seen[0] == "hello" and seen[1] == "host"


def test_colores_ciclicos_con_mas_gpu_que_paleta(tmp_path):
    db = Database(tmp_path / "x.db")
    devs = [{"device_id": f"nvidia:{i}", "provider": "nvidia", "kind": "gpu"} for i in range(8)]
    colors = db.upsert_devices("h", devs)
    assert [colors[f"nvidia:{i}"] for i in range(6)] == [0, 1, 2, 3, 4, 5]
    assert all(colors[f"nvidia:{i}"] is not None for i in (6, 7))
    db.close()
