"""llama-bench desde el agente: validación cerrada de flags, ejecución y API."""

import http.client
import json
import sys
import threading
import time

import pytest

from agent.api import AgentApp, make_server
from agent.bench import BenchError, BenchRunner, parse_list_devices, parse_spec
from agent.config import AgentConfig
from agent.host import enrich_host
from agent.processes import ServerDetector
from agent.sampler import Sampler
from agent.simulate import build_profile
from tests.agent.test_gguf import write_gguf

LIST_DEVICES = """\
ggml_cuda_init: found 2 CUDA devices (Total VRAM: 36863 MiB):
load_backend: loaded CUDA backend from D:\\llama\\ggml-cuda.dll
Available devices:
  CUDA0: NVIDIA GeForce RTX 3060 (12287 MiB, 11245 MiB free)
  CUDA1: Tesla M40 24GB (24576 MiB, 24400 MiB free)
"""


@pytest.fixture
def model(tmp_path):
    d = tmp_path / "modelos"
    d.mkdir()
    f = d / "mini-Q4_K_M.gguf"
    write_gguf(f)
    return AgentConfig(model_dirs=[d]), f


def test_lista_de_dispositivos():
    devs = parse_list_devices(LIST_DEVICES)
    assert [(d["name"], d["description"], d["total_mib"], d["free_mib"]) for d in devs] == [
        ("CUDA0", "NVIDIA GeForce RTX 3060", 12287, 11245),
        ("CUDA1", "Tesla M40 24GB", 24576, 24400),
    ]


def test_spec_valida_y_linea_de_comandos(model, tmp_path):
    cfg, f = model
    spec = parse_spec(
        {"model": str(f), "n_prompt": [512], "n_gen": [128], "n_gpu_layers": [0, 10, 99], "repetitions": 2,
         "devices": ["CUDA0/CUDA1"], "tensor_split": ["1/1", "3/1"], "flash_attn": "on", "cache_type_k": "q8_0"},
        cfg.allowed_model,
    )  # fmt: skip
    argv = spec.argv(tmp_path / "llama-bench")
    assert argv[1:] == [
        "-m", str(f.resolve()), "-o", "jsonl", "-r", "2", "-p", "512", "-n", "128", "-ngl", "0,10,99",
        "-ts", "1/1,3/1", "-dev", "CUDA0/CUDA1", "-fa", "on", "-ctk", "q8_0",
    ]  # fmt: skip


@pytest.mark.parametrize(
    "bad",
    [
        {"n_prompt": [512], "rpc": "1.2.3.4"},  # flag fuera de la lista cerrada
        {"n_prompt": ["512; rm -rf /"]},
        {"n_prompt": [-1]},
        {"n_gpu_layers": [True]},
        {"n_gpu_layers": list(range(40))},  # demasiados valores
        {"devices": ["CUDA0 && calc"]},
        {"devices": ["--rpc"]},
        {"tensor_split": ["1,1"]},
        {"tensor_split": ["1/1 -o"]},
        {"flash_attn": "maybe"},
        {"cache_type_k": "q3"},
        {"timeout_s": 1},
    ],
)
def test_spec_rechaza_todo_lo_demas(model, bad):
    cfg, f = model
    with pytest.raises(BenchError):
        parse_spec({"model": str(f), **bad}, cfg.allowed_model)


def test_spec_rechaza_modelos_fuera_de_las_carpetas(model, tmp_path):
    cfg, _ = model
    fuera = tmp_path / "fuera.gguf"
    write_gguf(fuera)
    for path in (str(fuera), "", "../../etc/passwd", str(tmp_path / "modelos")):
        with pytest.raises(BenchError) as e:
            parse_spec({"model": path}, cfg.allowed_model)
        assert e.value.status == 403


FAKE_BENCH = r'''
import json, sys, time
args = sys.argv[1:]
if "--list-devices" in args:
    print("Available devices:\n  CUDA0: GPU de prueba (8192 MiB, 8000 MiB free)")
    sys.exit(0)
if "--version" in args:
    print("version: 9.9 (build 1234, commit abc)", file=sys.stderr)
    sys.exit(0)
v = dict(zip(args[::2], args[1::2]))
if v.get("-p") == "666":
    print("error: fallo provocado", file=sys.stderr)
    sys.exit(3)
for ngl in v.get("-ngl", "99").split(","):
    for test, n in (("p", v.get("-p", "512")), ("n", v.get("-n", "128"))):
        if v.get("-p") == "777":
            time.sleep(30)
        row = {"model_size": 1000, "n_gpu_layers": int(ngl), "n_prompt": int(n) if test == "p" else 0,
               "n_gen": int(n) if test == "n" else 0, "avg_ts": 10.0 + int(ngl), "stddev_ts": 0.1,
               "samples_ts": [10.0, 10.2]}
        print("ruido que no es json")
        print(json.dumps(row), flush=True)
'''


@pytest.fixture
def fake_exe(tmp_path):
    script = tmp_path / "fake_bench.py"
    script.write_text(FAKE_BENCH, encoding="utf-8")
    if sys.platform == "win32":
        exe = tmp_path / "llama-bench.cmd"
        exe.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        exe = tmp_path / "llama-bench"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        exe.chmod(0o755)
    return exe


def wait_job(runner, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = runner.status()["job"]
        if job and job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("el trabajo no terminó")


def test_runner_real_lee_jsonl_y_errores(model, fake_exe):
    cfg, f = model
    runner = BenchRunner(fake_exe)
    assert runner.version() == "9.9 (build 1234, commit abc)"
    assert runner.list_devices()[0]["name"] == "CUDA0"
    runner.start(parse_spec({"model": str(f), "n_gpu_layers": [0, 99], "n_prompt": [64], "n_gen": [16]},
                            cfg.allowed_model))  # fmt: skip
    with pytest.raises(BenchError):  # uno cada vez
        runner.start(parse_spec({"model": str(f)}, cfg.allowed_model))
    job = wait_job(runner)
    assert job["status"] == "done" and job["returncode"] == 0
    assert [(r["n_gpu_layers"], r["n_prompt"], r["n_gen"]) for r in job["rows"]] == [
        (0, 64, 0), (0, 0, 16), (99, 64, 0), (99, 0, 16)
    ]  # fmt: skip
    assert len(runner.status(since=3)["job"]["rows"]) == 1

    runner.start(parse_spec({"model": str(f), "n_prompt": [666]}, cfg.allowed_model))
    job = wait_job(runner)
    assert job["status"] == "error" and "código 3" in job["error"] and "fallo provocado" in job["error"]


def test_runner_cancela(model, fake_exe):
    cfg, f = model
    runner = BenchRunner(fake_exe)
    runner.start(parse_spec({"model": str(f), "n_prompt": [777]}, cfg.allowed_model))
    time.sleep(0.5)
    runner.cancel()
    assert wait_job(runner, 10)["status"] == "cancelled"


def test_sin_llama_bench_configurado(model):
    cfg, f = model
    runner = BenchRunner(None)
    assert not runner.available
    with pytest.raises(BenchError) as e:
        runner.start(parse_spec({"model": str(f)}, cfg.allowed_model))
    assert e.value.status == 501


def _request(url, method, path, body=None, headers=None):
    host = url.split("//")[1]
    conn = http.client.HTTPConnection(host, timeout=5)
    data = json.dumps(body).encode() if body is not None else None
    conn.request(method, path, body=data, headers={"Content-Type": "application/json", **(headers or {})})
    r = conn.getresponse()
    return r.status, json.loads(r.read())


def test_api_del_agente_con_bench_simulado(model):
    cfg, f = model
    host, providers, procs = build_profile("nvidia2")
    sampler = Sampler(providers, interval_s=0.2)
    devices = sampler.refresh_devices()
    app = AgentApp(enrich_host(host, devices, sampler.sample_once().ram), sampler, simulated="nvidia2",
                   detector=ServerDetector(procs, providers), config=cfg)  # fmt: skip
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, body = _request(url, "GET", "/bench/devices")
        assert status == 200 and body["simulated"] is True
        gpu_ids = {d.device_id for d in devices if d.kind == "gpu"}
        assert [d["name"] for d in body["devices"]] == ["CUDA0", "CUDA1"]
        assert {d["device_id"] for d in body["devices"]} == gpu_ids
        assert _request(url, "GET", "/info")[1]["capabilities"]["bench"] is True

        spec = {"model": str(f), "n_gpu_layers": [0, 99], "n_prompt": [64], "n_gen": [16], "repetitions": 1}
        # Desde un navegador (cabecera Origin) no se lanzan procesos
        assert _request(url, "POST", "/bench", spec, {"Origin": "http://evil.example"})[0] == 403
        assert _request(url, "GET", "/bench/cancel")[0] == 405
        assert _request(url, "POST", "/bench", {**spec, "shell": "x"})[0] == 422
        status, body = _request(url, "POST", "/bench", spec)
        assert status == 200 and body["job"]["status"] == "running"
        end = time.monotonic() + 10
        while (job := _request(url, "GET", "/bench")[1]["job"])["status"] == "running" and time.monotonic() < end:
            time.sleep(0.05)
        assert job["status"] == "done" and len(job["rows"]) == 4
        pp_cpu, tg_cpu, pp_gpu, tg_gpu = (r["avg_ts"] for r in job["rows"])
        assert tg_gpu > tg_cpu and pp_gpu > pp_cpu  # la curva tiene sentido
    finally:
        server.shutdown()
        server.server_close()
        sampler.stop()
