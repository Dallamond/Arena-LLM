"""Criterio de F9: comparar 5+ runs de dos equipos distintos, versión distinta = no comparable."""

import json

import httpx
import pytest

import server.detect
from server import pack
from server.app import create_app
from server.fakes.fake_llama import FakeLlama, create_fake_app
from server.settings import Settings
from tests.conftest import run_uvicorn, start_agent
from tests.server.conftest import SIM_PID_GPU0
from tests.server.test_runs import run_finished, wait


@pytest.fixture
def dos_equipos(tmp_path, stoppers, monkeypatch):
    monkeypatch.setattr(server.detect, "DETECT_EVERY_S", 0.2)
    agents = []
    for profile in ("nvidia2", "cpu-only"):
        fake = FakeLlama(tps=200.0, pp_tps=5000.0)
        llama_url, stop_llama = run_uvicorn(create_fake_app(fake))
        stoppers.append(stop_llama)
        port = int(llama_url.rsplit(":", 1)[1])
        agent_url, stop_agent, _ = start_agent(profile, servers=[(SIM_PID_GPU0, port)])
        stoppers.append(stop_agent)
        agents.append(agent_url)
    settings = Settings(data_dir=tmp_path, agents=agents, poll_interval_s=0.1, web_dist=tmp_path / "no")
    api_url, stop_api = run_uvicorn(create_app(settings))
    stoppers.append(stop_api)
    client = httpx.Client(base_url=api_url, timeout=15)
    stoppers.append(client.close)
    return client


def test_cinco_runs_de_dos_equipos_y_version_distinta(dos_equipos):
    c = dos_equipos
    def listos():
        e = c.get("/api/endpoints").json()
        return e if len(e) >= 2 and all(x["status"] == "listo" for x in e) else None

    eps = wait(listos)
    assert len({e["host_pk"] for e in eps}) == 2
    ids = []
    for i in range(6):
        ep = eps[i % 2]
        r = c.post(
            "/api/runs",
            json={"suite": "libre", "endpoint_id": ep["id"], "label": f"r{i}",
                  "params": {"prompts": ["Hola", "Adiós"], "max_tokens": 8, "baseline_s": 0.3}},  # fmt: skip
        )
        assert r.status_code == 201, r.text
        run_finished(c, r.json()["id"], timeout=30)
        ids.append(r.json()["id"])

    rows = [r for r in c.get("/api/runs").json() if r["id"] in ids]
    assert len({r["host_name"] for r in rows}) == 2  # el historial distingue los dos equipos

    out = c.get("/api/compare", params={"runs": ",".join(map(str, ids))}).json()
    assert len(out["runs"]) == 6 and out["comparability"]["label"]
    assert out["comparability"]["level"] in ("si", "parcial")
    norm = {m["key"]: m for m in out["metrics"] if m.get("group") == "normalizada"}
    for m in norm.values():
        assert len(m["values"]) == 6
        assert all(v is None or v > 0 for v in m["values"])  # nunca un 0 inventado
    # El equipo sin GPU no tiene VRAM ni potencia de placa: sus normalizadas salen null (runs pares = cpu-only)
    for key in ("tps_per_gib", "tps_per_w"):
        assert [v is None for v in norm[key]["values"]] == [False, True] * 3, norm[key]

    # Misma carga pero otra versión de prueba (paquete con versión cambiada) → no comparables
    data = c.get(f"/api/runs/pack?runs={ids[0]}").json()
    data["runs"][0]["suite_version"] = "99"
    data["runs"][0]["suite_hash"] = "otra"
    new_id = c.post("/api/runs/import", content=json.dumps(data)).json()["imported"][0]
    bad = c.get("/api/compare", params={"runs": f"{ids[0]},{new_id}"}).json()
    assert bad["comparability"]["level"] == "no" and bad["comparability"]["label"] == "No comparables"
    assert pack.FORMAT == "arena-pack"
