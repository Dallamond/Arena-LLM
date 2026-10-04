"""Batalla de punta a punta sin GPU: dos llama-server simulados (uno por GPU del perfil nvidia2)."""

import httpx
import pytest

import server.detect
from server.app import create_app
from server.fakes.fake_llama import FakeLlama, create_fake_app
from server.runs.battle import side_params
from server.runs.manager import RunError
from server.settings import Settings
from tests.conftest import run_uvicorn, start_agent
from tests.server.test_runs import wait

PIDS = (4201, 4202)  # el perfil nvidia2 asocia estos pid a sus dos GPU
PROMPTS = ["Primera pregunta", "Segunda pregunta"]


@pytest.fixture(autouse=True)
def fast_detection(monkeypatch):
    monkeypatch.setattr(server.detect, "DETECT_EVERY_S", 0.2)


@pytest.fixture
def arena(tmp_path, stoppers):
    fakes = [
        FakeLlama(tps=300.0, pp_tps=5000.0),
        FakeLlama(tps=150.0, pp_tps=5000.0, model="/modelos/otro-14b-Q4_K_M.gguf"),
    ]
    ports = []
    for f in fakes:
        url, stop = run_uvicorn(create_fake_app(f))
        stoppers.append(stop)
        ports.append(int(url.rsplit(":", 1)[1]))
    agent_url, stop_agent, _ = start_agent("nvidia2", servers=list(zip(PIDS, ports, strict=True)))
    stoppers.append(stop_agent)
    settings = Settings(data_dir=tmp_path, agents=[agent_url], poll_interval_s=0.1, web_dist=tmp_path / "no")
    api_url, stop_api = run_uvicorn(create_app(settings))
    stoppers.append(stop_api)
    c = httpx.Client(base_url=api_url, timeout=15)
    stoppers.append(c.close)
    eps = wait(
        lambda: (ls := [e for e in c.get("/api/endpoints").json() if e["status"] == "listo"]) and len(ls) == 2 and ls
    )
    return c, fakes, sorted(eps, key=lambda e: e["base_url"] != f"http://127.0.0.1:{ports[0]}")


def finished(c, bid, timeout=30):
    return wait(
        lambda: (b := c.get(f"/api/battles/{bid}").json())["status"] not in ("running", "pending") and b, timeout
    )


def body(eps, mode="paralelo", **kw):
    return {
        "mode": mode,
        "label": "prueba",
        "prompts": PROMPTS,
        "common": {"seed": 7, "max_tokens": 16, "baseline_s": 0.5, "temperature": 0},
        "sides": [{"endpoint_id": eps[0]["id"]}, {"endpoint_id": eps[1]["id"], "params": {"temperature": 0.8}}],
        **kw,
    }


def test_batalla_en_paralelo_mismos_prompts_y_semilla(arena):
    c, fakes, eps = arena
    r = c.post("/api/battles", json=body(eps))
    assert r.status_code == 201, r.text
    b = finished(c, r.json()["id"])
    assert b["status"] == "done", b
    assert [s["side"] for s in b["sides"]] == ["A", "B"]
    runs = b["runs"]
    assert all(x["status"] == "done" and x["battle_id"] == b["id"] for x in runs)
    assert [x["side"] for x in runs] == ["A", "B"]
    # Mismos prompts, en el mismo orden, y misma semilla en las peticiones que llegaron a cada servidor
    for f in fakes:
        assert [m["messages"][-1]["content"] for m in f.bodies] == PROMPTS
        assert {m["seed"] for m in f.bodies} == {7}
    assert {m["temperature"] for m in fakes[0].bodies} == {0}
    assert {m["temperature"] for m in fakes[1].bodies} == {0.8}
    assert [i["prompt"] for i in runs[0]["items"]] == [i["prompt"] for i in runs[1]["items"]] == PROMPTS
    # Telemetría separada por GPU: cada lado vigila su propia tarjeta
    watched = [set(x["summary"]["thresholds"]) for x in runs]
    assert watched[0] and watched[1] and watched[0] != watched[1]
    # La comparación de los dos lados: cambian modelo, GPU y temperatura → parcialmente comparables
    cmp = c.get("/api/compare", params={"runs": f"{runs[0]['id']},{runs[1]['id']}"}).json()
    assert cmp["comparability"]["level"] == "parcial"
    assert len(cmp["items"]) == 2 and all(cell["response"] for row in cmp["items"] for cell in row["cells"])
    hist = c.get("/api/runs").json()
    assert {(h["battle_id"], h["side"]) for h in hist} == {(b["id"], "A"), (b["id"], "B")}


def test_batalla_secuencial_en_el_mismo_servidor(arena):
    c, fakes, eps = arena
    data = body(eps, mode="secuencial")
    data["sides"] = [{"endpoint_id": eps[0]["id"]}, {"endpoint_id": eps[0]["id"], "params": {"max_tokens": 8}}]
    r = c.post("/api/battles", json=data)
    assert r.status_code == 201, r.text
    b = finished(c, r.json()["id"])
    assert b["status"] == "done", b
    a, bb = b["runs"]
    assert a["finished_at"] <= bb["started_at"]  # uno detrás de otro
    assert [len(f.bodies) for f in fakes] == [4, 0]
    cmp = c.get("/api/compare", params={"runs": f"{a['id']},{bb['id']}"}).json()
    assert cmp["comparability"]["level"] == "si" and cmp["comparability"]["changes"] == ["parámetros de la prueba"]


def test_validaciones(arena):
    c, _, eps = arena
    same = body(eps)
    same["sides"][1]["endpoint_id"] = eps[0]["id"]
    r = c.post("/api/battles", json=same)
    assert r.status_code == 422 and "secuencial" in r.json()["detail"]
    one = body(eps)
    one["sides"] = one["sides"][:1]
    assert c.post("/api/battles", json=one).status_code == 422
    seed = body(eps)
    seed["sides"][1]["params"] = {"seed": 1}
    r = c.post("/api/battles", json=seed)
    assert r.status_code == 422 and "seed" in r.json()["detail"]
    assert c.post("/api/battles", json=body(eps, prompts=["  "])).status_code == 422
    assert c.post("/api/battles", json=body(eps, mode="raro")).status_code == 422
    assert c.get("/api/battles").json() == []  # nada se quedó a medias


def test_cancelar_y_borrar(arena):
    c, _, eps = arena
    data = body(eps, mode="secuencial")
    data["common"]["baseline_s"] = 5
    bid = c.post("/api/battles", json=data).json()["id"]
    assert c.post(f"/api/battles/{bid}/cancel").status_code == 202
    b = finished(c, bid)
    assert b["status"] == "cancelled"
    assert b["sides"][1]["run_id"] is None  # el lado B no llegó a lanzarse
    assert c.delete(f"/api/battles/{bid}").status_code == 204
    assert c.get(f"/api/battles/{bid}").status_code == 404
    assert c.get("/api/runs").json() == []


def test_parametros_por_lado():
    p = side_params(["x"], {"seed": 3, "temperature": 0, "repeats": 2}, {"temperature": 1.0})
    assert p == {"seed": 3, "temperature": 1.0, "repeats": 2, "prompts": ["x"]}
    with pytest.raises(RunError):
        side_params(["x"], {}, {"repeats": 3})
