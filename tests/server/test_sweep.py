"""Asistente (barrido de modelos × GPU) de punta a punta sin GPU.

El agente simulado no lanza procesos, así que aquí se sustituye su `/launch` por una función que levanta un
llama-server simulado en el puerto pedido y lo registra en el agente (como lo vería el detector real).
"""

import socket
import threading
import time

import httpx
import pytest
import uvicorn

import server.runs.sweep as sweep_mod
from agent.config import AgentConfig
from agent.processes import RawProcess
from server.app import create_app
from server.fakes.fake_llama import FakeLlama, create_fake_app
from server.settings import Settings
from tests.agent.test_gguf import _kv, _s
from tests.conftest import run_uvicorn, start_agent
from tests.server.test_quality_runs import answerer
from tests.server.test_runs import wait


def write_fit_gguf(path, n_layers=2, layer_bytes=1 << 20, name="Mini", dim=64):
    """GGUF con capas blk.N y tamaños deducibles de los offsets: la calculadora de encaje lo acepta."""
    import struct

    kvs = [
        _kv("general.architecture", 8, _s("llama")),
        _kv("general.name", 8, _s(name)),
        _kv("general.file_type", 4, struct.pack("<I", 15)),
        _kv("llama.block_count", 4, struct.pack("<I", n_layers)),
        _kv("llama.context_length", 4, struct.pack("<I", 32768)),
        _kv("llama.embedding_length", 4, struct.pack("<I", 64)),
        _kv("llama.feed_forward_length", 4, struct.pack("<I", 128)),
        _kv("llama.attention.head_count", 4, struct.pack("<I", 8)),
        _kv("llama.attention.head_count_kv", 4, struct.pack("<I", 4)),
    ]
    names = ["token_embd.weight", *(f"blk.{i}.attn_q.weight" for i in range(n_layers)), "output.weight"]
    tensors = b"".join(
        _s(n) + struct.pack("<I", 2) + struct.pack("<2Q", dim, dim) + struct.pack("<IQ", 0, i * layer_bytes)
        for i, n in enumerate(names)
    )
    head = b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", len(names), len(kvs))
    header = head + b"".join(kvs) + tensors
    pad = (-len(header)) % 32
    path.write_bytes(header + bytes(pad) + bytes(len(names) * layer_bytes))


def serve_on(app, port):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    end = time.monotonic() + 10
    while not server.started and time.monotonic() < end:
        time.sleep(0.02)

    def stop():
        server.should_exit = True
        thread.join(timeout=10)

    return stop


@pytest.fixture
def lab(tmp_path, stoppers, monkeypatch):
    monkeypatch.setattr(sweep_mod, "STOP_WAIT_S", 8.0)
    monkeypatch.setattr(sweep_mod, "POLL_S", 0.2)
    models = tmp_path / "modelos"
    models.mkdir()
    for name in ("alfa-Q4_K_M.gguf", "beta-Q4_K_M.gguf"):
        write_fit_gguf(models / name)
    agent_url, stop_agent, procs = start_agent("nvidia2", servers=[], config=AgentConfig(model_dirs=[models]))
    stoppers.append(stop_agent)
    app = create_app(Settings(data_dir=tmp_path, agents=[agent_url], poll_interval_s=0.1, web_dist=tmp_path / "no"))
    api_url, stop_api = run_uvicorn(app)
    stoppers.append(stop_api)
    c = httpx.Client(base_url=api_url, timeout=15)
    stoppers.append(c.close)

    cfg = {"tps": 3000.0, "responder": answerer}
    launched: dict[int, dict] = {}
    agent = app.state.monitor.agent
    real_get, real_post = agent.get, agent.post
    log: list[tuple[str, str]] = []

    async def post(state, path, body=None):
        if path == "/launch":
            # El puerto de la propuesta puede estar ocupado en esta máquina (p. ej. por un llama-server real)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            pid = 9000 + port
            fake = FakeLlama(tps=cfg["tps"], pp_tps=5000.0, responder=cfg["responder"], model=body["model"])
            stop = serve_on(create_fake_app(fake), port)
            argv = ["/x/llama-server", "-m", body["model"], "--port", str(port)]
            procs.processes.append(RawProcess(pid=pid, exe=argv[0], argv=argv, started_at="2026-10-18T10:00:00+00:00"))
            launched[pid] = {"pid": pid, "port": port, "model": body["model"], "alive": True, "returncode": None,
                             "log_tail": [], "stop": stop, "spec": body}  # fmt: skip
            log.append(("launch", body["model"].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]))
            return {k: v for k, v in launched[pid].items() if k not in ("stop", "spec")}
        if path == "/launch/stop":
            item = launched[body["pid"]]
            item["stop"]()
            item["alive"] = False
            procs.processes[:] = [p for p in procs.processes if p.pid != body["pid"]]
            log.append(("stop", str(body["pid"])))
            return {}
        return await real_post(state, path, body)

    async def get(state, path, params=None, timeout=None):
        if path == "/launched":
            return {"launched": [{k: v for k, v in x.items() if k not in ("stop", "spec")} for x in launched.values()],
                    "available": True}  # fmt: skip
        return await real_get(state, path, params, timeout=timeout)

    agent.post, agent.get = post, get
    host = wait(lambda: next(iter(c.get("/api/hosts").json()), None))
    wait(lambda: c.get(f"/api/hosts/{host['id']}/models").json().get("files"))
    yield c, host, models, launched, log, cfg
    for item in launched.values():
        if item["alive"]:
            item["stop"]()


def finished(c, sid, timeout=90):
    done = lambda: (s := c.get(f"/api/sweeps/{sid}").json())["status"] not in ("running", "pending") and s  # noqa: E731
    return wait(done, timeout)


def body(host, mdir, **kw):
    return {
        "host_id": host["id"],
        "models": [str(mdir / "alfa-Q4_K_M.gguf"), str(mdir / "beta-Q4_K_M.gguf")],
        "targets": ["auto"],
        "suite": "qa",
        "params": {"include": ["producto", "australia"], "max_tokens": 64, "baseline_s": 0},
        "load_timeout_s": 60,
        **kw,
    }


def test_barrido_arranca_mide_y_para_cada_modelo(lab):
    c, host, models, launched, log, _ = lab
    r = c.post("/api/sweeps", json=body(host, models, label="prueba"))
    assert r.status_code == 201, r.text
    sw = finished(c, r.json()["id"])
    assert sw["status"] == "done", [(s["state"], s["message"]) for s in sw["steps"]] + [sw["error"]]
    assert [s["state"] for s in sw["steps"]] == ["hecho", "hecho"]
    # arranca y para cada servidor, uno detrás de otro
    assert [k for k, _ in log] == ["launch", "stop", "launch", "stop"]
    assert not any(x["alive"] for x in launched.values())
    ids = [s["run_id"] for s in sw["steps"]]
    assert len(set(ids)) == 2 and set(sw["runs"]) == {str(i) for i in ids} or set(sw["runs"]) == set(ids)
    for run in sw["runs"].values():
        assert run["status"] == "done" and run["summary"]["quality"]["correct"] == 2
    runs = c.get("/api/runs").json()
    assert {x["sweep_id"] for x in runs if x["id"] in ids} == {sw["id"]}
    assert "Asistente" in (c.get(f"/api/runs/{ids[0]}").json()["label"] or "")


def test_comparar_los_runs_del_barrido(lab):
    c, host, models, *_ = lab
    sw = finished(c, c.post("/api/sweeps", json=body(host, models)).json()["id"])
    ids = ",".join(str(s["run_id"]) for s in sw["steps"])
    cmp = c.get(f"/api/compare?runs={ids}").json()
    assert len(cmp["runs"]) == 2 and any(m["key"] == "accuracy" for m in cmp["metrics"])


def test_un_destino_que_no_existe_deja_el_paso_como_no_cabe(lab):
    c, host, models, _, log, _ = lab
    sw = finished(c, c.post("/api/sweeps", json=body(host, models, targets=["gpu-inexistente"])).json()["id"])
    assert sw["status"] == "error"
    assert [s["state"] for s in sw["steps"]] == ["no cabe", "no cabe"]
    assert "GPU" in sw["steps"][0]["message"] and not log


def test_un_paso_que_falla_no_impide_los_siguientes(lab):
    c, host, models, _, log, _ = lab
    paths = [str(models / "no_existe.gguf"), str(models / "beta-Q4_K_M.gguf")]
    sw = finished(c, c.post("/api/sweeps", json={**body(host, models), "models": paths}).json()["id"])
    assert [s["state"] for s in sw["steps"]] == ["error", "hecho"] and sw["status"] == "done"
    assert [k for k, _ in log] == ["launch", "stop"]


def test_cancelar_a_mitad_para_el_servidor_y_omite_el_resto(lab):
    c, host, models, launched, _, cfg = lab
    cfg.update(tps=20.0, responder=lambda p: "palabra " * 300)  # ≈15 s por petición
    slow = body(host, models, suite="concurrencia", params={"levels": [1], "max_tokens": 400, "baseline_s": 0})
    sid = c.post("/api/sweeps", json=slow).json()["id"]
    wait(lambda: c.get(f"/api/sweeps/{sid}").json()["steps"][0]["state"] == "midiendo", 30)
    assert c.post(f"/api/sweeps/{sid}/cancel").status_code == 202
    sw = finished(c, sid)
    assert sw["status"] == "cancelled"
    assert [s["state"] for s in sw["steps"]] == ["detenido", "omitido"]
    assert not any(x["alive"] for x in launched.values())


def test_validacion_del_asistente(lab):
    c, host, models, *_ = lab
    one = str(models / "alfa-Q4_K_M.gguf")
    for patch in (
        {"models": []},
        {"suite": "estres"},
        {"params": {"include": ["no_existe"]}},
        {"ctx": 0},
        {"load_timeout_s": 1},
        {"models": [one] * 1, "targets": [str(i) for i in range(9)]},
    ):
        assert c.post("/api/sweeps", json={**body(host, models), **patch}).status_code == 422, patch
    assert c.post("/api/sweeps", json=body({"id": 999}, models)).status_code == 404


def test_borrar_el_barrido_borra_sus_runs(lab):
    c, host, models, *_ = lab
    sw = finished(c, c.post("/api/sweeps", json=body(host, models)).json()["id"])
    ids = [s["run_id"] for s in sw["steps"]]
    assert c.delete(f"/api/sweeps/{sw['id']}").status_code == 204
    assert c.get(f"/api/sweeps/{sw['id']}").status_code == 404
    assert all(c.get(f"/api/runs/{i}").status_code == 404 for i in ids)
