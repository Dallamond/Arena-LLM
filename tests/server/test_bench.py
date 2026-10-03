"""Rendimiento por componente (F6): cálculos puros y run de punta a punta con el bench simulado."""

import time

import httpx
import pytest

from agent.config import AgentConfig
from server.app import create_app
from server.runs.bench import (
    BENCH_SUITES,
    BenchSpecError,
    bandwidth_gbs,
    bench_summary,
    build_spec,
    default_ngl,
    default_threads,
    default_ts,
    layers_pct,
    normalize_row,
    row_test,
)
from server.settings import Settings
from tests.agent.test_gguf import write_gguf
from tests.conftest import run_uvicorn, start_agent
from tests.server.test_runs import run_finished, wait

# --- cálculos -----------------------------------------------------------------


def test_barridos_por_defecto_derivados_del_equipo():
    assert default_threads(6, 12) == [1, 2, 3, 6, 12]
    assert default_threads(4, 4) == [1, 2, 4]
    assert default_threads(None, None) == [1, 2, 4]
    assert default_ngl(28) == [0, 7, 14, 22, 29]  # 28 capas + salida
    assert default_ngl(None) == [0, 8, 16, 24, 99]
    assert default_ts([12288]) == []
    assert default_ts([12288, 24576]) == ["1/1", "1/2", "3/1", "2/1", "1/3"]
    assert default_ts([8000, 8000, 16000])[:2] == ["1/1/1", "1/1/2"]


def test_metricas_derivadas():
    assert layers_pct(29, 28, False) == 100.0
    assert layers_pct(999, 28, False) == 100.0
    assert layers_pct(0, 28, False) == 0.0
    assert round(layers_pct(14, 28, False), 1) == 48.3
    assert layers_pct(99, 28, True) == 0.0  # -dev none: nada en GPU
    assert layers_pct(10, None, False) is None  # sin capas conocidas: sin datos, no 0
    assert bandwidth_gbs(8_092_571_648, 34.5, False) == pytest.approx(279.2, abs=0.1)
    assert bandwidth_gbs(8e9, 30.0, True) is None  # MoE: la aproximación no vale
    assert bandwidth_gbs(None, 30.0, False) is None
    assert (row_test({"n_prompt": 512, "n_gen": 0}), row_test({"n_prompt": 0, "n_gen": 128})) == ("pp", "tg")
    assert row_test({"n_prompt": 512, "n_gen": 128}) == "pg"


def test_fila_y_resumen():
    suite = BENCH_SUITES["bench-ngl"]
    model = {"block_count": 28, "expert_count": None}
    raws = [
        {"n_prompt": 512, "n_gen": 0, "n_gpu_layers": 0, "avg_ts": 100.0, "stddev_ts": 2.0, "model_size": 8e9,
         "samples_ts": [99, 101], "devices": "auto"},
        {"n_prompt": 0, "n_gen": 128, "n_gpu_layers": 0, "avg_ts": 5.0, "stddev_ts": 0.1, "model_size": 8e9,
         "samples_ts": [5, 5], "devices": "auto"},
        {"n_prompt": 512, "n_gen": 0, "n_gpu_layers": 29, "avg_ts": 1500.0, "stddev_ts": 9.0, "model_size": 8e9,
         "devices": "auto"},
        {"n_prompt": 0, "n_gen": 128, "n_gpu_layers": 29, "avg_ts": 34.0, "stddev_ts": 0.5, "model_size": 8e9,
         "devices": "auto", "build_commit": "abc"},
    ]  # fmt: skip
    rows = [normalize_row(suite, r, model) for r in raws]
    assert rows[1]["derived"] == {"layers_pct": 0.0, "bandwidth_gbs": 40.0, "sweep": 0}
    assert rows[0]["derived"]["bandwidth_gbs"] is None  # solo en generación
    assert rows[0]["reps"] == 2 and rows[2]["reps"] is None
    b = bench_summary(suite, rows)["bench"]
    assert b["best_tg"]["t_s"] == 34.0 and b["best_tg"]["sweep"] == 29
    assert b["best_pp"]["t_s"] == 1500.0
    assert [p["x"] for p in b["curve"]["tg"]] == [0, 29]
    assert bench_summary(suite, [])["bench"]["best_tg"] is None


def test_construccion_de_la_especificacion():
    params = {"n_prompt": [512], "n_gen": [128], "repetitions": 3, "timeout_s": 600}
    gpu = build_spec(BENCH_SUITES["bench-dispositivo"], params, "/m.gguf", ["CUDA1"], False)
    assert (gpu["devices"], gpu["n_gpu_layers"]) == (["CUDA1"], [999])
    cpu = build_spec(BENCH_SUITES["bench-dispositivo"], params, "/m.gguf", [], True)
    assert (cpu["devices"], cpu["n_gpu_layers"]) == (["none"], [0])
    sweep = build_spec(BENCH_SUITES["bench-cpu"], {**params, "sweep": [1, 6]}, "/m.gguf", [], True)
    assert sweep["threads"] == [1, 6] and sweep["devices"] == ["none"]
    ts = build_spec(BENCH_SUITES["bench-ts"], {**params, "sweep": ["1/1"]}, "/m.gguf", ["CUDA0", "CUDA1"], False)
    assert ts["devices"] == ["CUDA0/CUDA1"] and ts["tensor_split"] == ["1/1"]
    with pytest.raises(BenchSpecError):
        build_spec(BENCH_SUITES["bench-ts"], {**params, "sweep": ["1/1"]}, "/m.gguf", ["CUDA0"], False)
    with pytest.raises(BenchSpecError):
        build_spec(BENCH_SUITES["bench-ngl"], params, "/m.gguf", [], False)


def test_hash_cambia_con_el_perfil():
    s = BENCH_SUITES["bench-ngl"]
    base = s.params({"sweep": [0, 10]})
    assert s.content_hash(base) == s.content_hash(s.params({"sweep": [0, 10]}))
    assert s.content_hash(base) != s.content_hash({**base, "n_prompt": [256]})
    assert s.content_hash(base) != s.content_hash({**base, "sweep": [0, 20]})


# --- de punta a punta ---------------------------------------------------------


@pytest.fixture
def bench_lab(tmp_path, stoppers):
    models = tmp_path / "modelos"
    models.mkdir()
    gguf = models / "mini-Q4_K_M.gguf"
    write_gguf(gguf)
    agent_url, stop_agent, _ = start_agent("nvidia2", config=AgentConfig(model_dirs=[models]))
    stoppers.append(stop_agent)
    settings = Settings(data_dir=tmp_path, agents=[agent_url], poll_interval_s=0.1, web_dist=tmp_path / "no")
    api_url, stop_api = run_uvicorn(create_app(settings))
    stoppers.append(stop_api)
    client = httpx.Client(base_url=api_url, timeout=10)
    stoppers.append(client.close)
    host = wait(lambda: next((h for h in client.get("/api/hosts").json() if h["status"] == "online"), None))
    wait(lambda: client.get(f"/api/hosts/{host['id']}/metrics").json()["snapshot"])
    return client, host, gguf


def test_curva_ngl_de_punta_a_punta(bench_lab):
    c, host, gguf = bench_lab
    devs = c.get(f"/api/hosts/{host['id']}/bench/devices").json()["devices"]
    assert len(devs) == 2 and all(d["device_id"] for d in devs)
    r = c.post("/api/bench", json={"suite": "bench-ngl", "host_id": host["id"], "label": "curva",
                                   "params": {"model": str(gguf), "device_ids": [devs[0]["device_id"]],
                                              "baseline_s": 0, "repetitions": 1}})  # fmt: skip
    assert r.status_code == 201, r.text
    run = run_finished(c, r.json()["id"])
    assert run["status"] == "done", run
    assert run["kind"] == "bench" and run["endpoint_id"] is None
    assert run["params"]["sweep"] == [0, 1, 2, 3]  # derivado de las 2 capas del GGUF
    snap = run["servers_snapshot"]
    assert snap["engine"] == "llama-bench" and snap["model"]["header_sha256"]
    assert snap["spec"]["devices"] == ["CUDA0"] and snap["spec"]["n_gpu_layers"] == [0, 1, 2, 3]
    rows = run["bench_rows"]
    assert len(rows) == 8 and "raw" not in rows[0]
    assert [r["derived"]["layers_pct"] for r in rows if r["test"] == "tg"] == [0.0, pytest.approx(100 / 3),
                                                                                 pytest.approx(200 / 3), 100.0]
    b = run["summary"]["bench"]
    assert b["sweep"] == "n_gpu_layers" and len(b["curve"]["tg"]) == 4
    assert b["best_tg"]["sweep"] == 3  # todo en GPU es lo más rápido
    assert run["summary"]["devices"]  # telemetría muestreada durante el bench
    assert list(run["host_snapshot"]["thresholds"]) == [devs[0]["device_id"]]


def test_validaciones_y_avisos(bench_lab):
    c, host, gguf = bench_lab
    hid = host["id"]

    def post(suite, **params):
        return c.post("/api/bench", json={"suite": suite, "host_id": hid, "params": {"baseline_s": 0, **params}})

    assert post("bench-x", model=str(gguf)).status_code == 404
    assert post("bench-ngl").status_code == 422  # sin modelo
    assert post("bench-ngl", model="/etc/passwd").status_code == 409  # el agente lo rechaza
    assert post("bench-dispositivo", model=str(gguf)).status_code == 422  # sin dispositivo
    assert post("bench-ngl", model=str(gguf), device_ids=["nvidia:NO-EXISTE"]).status_code == 422
    assert post("bench-ngl", model=str(gguf), n_prompt=["512"]).status_code == 422
    r = post("bench-cpu", model=str(gguf), repetitions=1)
    assert r.status_code == 201, r.text
    run = run_finished(c, r.json()["id"])
    assert run["params"]["device_ids"] == ["cpu"] and run["servers_snapshot"]["spec"]["devices"] == ["none"]
    assert run["params"]["sweep"] == sorted(set(run["params"]["sweep"]))
    assert run["host_snapshot"]["thresholds"] == {}  # solo CPU: no se vigila ninguna GPU


def test_cancelar_un_bench(bench_lab):
    c, host, gguf = bench_lab
    r = c.post("/api/bench", json={"suite": "bench-ts", "host_id": host["id"],
                                   "params": {"model": str(gguf), "baseline_s": 0, "n_prompt": [64, 128, 256],
                                              "n_gen": [16, 32, 64]}})  # fmt: skip
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    assert c.post("/api/bench", json={"suite": "bench-cpu", "host_id": host["id"],
                                      "params": {"model": str(gguf)}}).status_code == 409  # fmt: skip
    time.sleep(0.5)
    assert c.post(f"/api/runs/{run_id}/cancel").status_code == 202
    run = run_finished(c, run_id)
    assert run["status"] == "cancelled"
    assert 0 < len(run["bench_rows"]) < 30
