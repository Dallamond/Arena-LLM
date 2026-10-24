"""Lanzar y parar llama-server desde el agente: validación cerrada, argumentos y API."""

import http.client
import json
import threading

import pytest

from agent.api import AgentApp, make_server
from agent.config import AgentConfig
from agent.host import enrich_host
from agent.launcher import LaunchError, ServerLauncher, parse_spec
from agent.processes import ServerDetector
from agent.sampler import Sampler
from agent.simulate import build_profile
from tests.agent.test_gguf import write_gguf


class FakeProc:
    _next = 4000

    def __init__(self, argv, **kw):
        FakeProc._next += 1
        self.pid = FakeProc._next
        self.argv, self.kw = argv, kw
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


@pytest.fixture
def setup(tmp_path):
    d = tmp_path / "modelos"
    d.mkdir()
    f = d / "mini-Q4_K_M.gguf"
    write_gguf(f)
    exe = tmp_path / "llama-server.exe"
    exe.write_bytes(b"")
    cfg = AgentConfig(model_dirs=[d], llama_server=exe)
    launcher = ServerLauncher(cfg.llama_server_path, popen=FakeProc, log_dir=tmp_path)
    return cfg, f, exe, launcher


def test_argumentos_y_entorno(setup):
    cfg, f, exe, _ = setup
    spec = parse_spec(
        {"model": str(f), "ctx": 16384, "parallel": 2, "kv_type": "q8_0", "ngl": 29, "dev": "CUDA1",
         "ts": [10, 5.5], "port": 18090},
        cfg.allowed_model,
    )  # fmt: skip
    assert spec.argv(exe)[1:] == [
        "-m", str(f.resolve()), "-c", "16384", "-np", "2", "-ctk", "q8_0", "-ctv", "q8_0", "-ngl", "29",
        "-dev", "CUDA1", "-ts", "10,5.5", "-fa", "on", "--host", "127.0.0.1", "--port", "18090",
    ]  # fmt: skip
    assert spec.env() == {"CUDA_DEVICE_ORDER": "PCI_BUS_ID"}
    minimo = parse_spec({"model": str(f), "ngl": 99, "port": 18091}, cfg.allowed_model)
    assert minimo.env() == {}
    assert "-dev" not in minimo.argv(exe) and "-np" not in minimo.argv(exe)


@pytest.mark.parametrize(
    "cambio",
    [
        {"ngl": -1},
        {"ngl": "99"},
        {"port": 80},
        {"port": True},
        {"ctx": 10},
        {"kv_type": "raro"},
        {"flash_attn": "si"},
        {"dev": "CUDA0; calc"},
        {"dev": ""},
        {"ts": []},
        {"ts": ["a"]},
        {"ts": [-1]},
        {"parallel": 0},
    ],
)
def test_valores_fuera_de_la_lista_cerrada(setup, cambio):
    cfg, f, _, _ = setup
    base = {"model": str(f), "ngl": 10, "port": 18090}
    with pytest.raises(LaunchError) as e:
        parse_spec({**base, **cambio}, cfg.allowed_model)
    assert e.value.code == "spec"


def test_modelo_fuera_de_las_carpetas_permitidas(setup, tmp_path):
    cfg, _, _, _ = setup
    otro = tmp_path / "fuera.gguf"
    write_gguf(otro)
    with pytest.raises(LaunchError) as e:
        parse_spec({"model": str(otro), "ngl": 1, "port": 18090}, cfg.allowed_model)
    assert e.value.code == "model" and e.value.status == 403


def test_lanzar_registrar_y_parar(setup):
    cfg, f, _, launcher = setup
    spec = parse_spec({"model": str(f), "ngl": 10, "port": 18095}, cfg.allowed_model)
    out = launcher.launch(spec)
    assert out["alive"] and out["port"] == 18095
    assert launcher.status()[0]["pid"] == out["pid"]
    stopped = launcher.stop(out["pid"])
    assert stopped["alive"] is False
    with pytest.raises(LaunchError) as e:
        launcher.stop(1)  # un pid que Arena no lanzó
    assert e.value.status == 404


def test_puerto_ocupado_y_sin_binario(setup, tmp_path):
    cfg, f, _, launcher = setup
    spec = parse_spec({"model": str(f), "ngl": 10, "port": 18096}, cfg.allowed_model)
    launcher.launch(spec)
    with pytest.raises(LaunchError) as e:
        launcher.launch(spec)
    assert e.value.code == "port"
    sin = ServerLauncher(lambda: None, popen=FakeProc, log_dir=tmp_path)
    assert not sin.available
    with pytest.raises(LaunchError) as e:
        sin.launch(spec)
    assert e.value.status == 501


def build_app(config, launcher, simulated=None):
    host, providers, procs = build_profile("nvidia2")
    sampler = Sampler(providers, interval_s=0.05)
    devices = sampler.refresh_devices()
    first = sampler.sample_once()
    return AgentApp(
        enrich_host(host, devices, first.ram),
        sampler,
        simulated=simulated,
        detector=ServerDetector(procs, providers, ttl_s=0),
        config=config,
        launcher=launcher,
    )


def agent(config, launcher):
    app = build_app(config, launcher)
    app.sampler.start()
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return app, server


def call(server, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    c.request(method, path, json.dumps(body) if body is not None else None, headers or {})
    r = c.getresponse()
    return r.status, json.loads(r.read())


def test_api_lanzar_parar_y_origen(setup):
    cfg, f, _, launcher = setup
    app, server = agent(cfg, launcher)
    try:
        _, info = call(server, "GET", "/info")
        assert info["capabilities"]["launch"] is True
        body = {"model": str(f), "ngl": 10, "port": 18097}
        status, out = call(server, "POST", "/launch", body)
        assert status == 200 and out["launch"]["alive"]
        status, listed = call(server, "GET", "/launched")
        assert listed["launched"][0]["pid"] == out["launch"]["pid"]
        # una web no puede lanzar procesos a través del navegador
        status, err = call(server, "POST", "/launch", body, {"Origin": "http://evil.example"})
        assert status == 403 and err["error"]["code"] == "origin"
        status, _ = call(server, "POST", "/launch", {**body, "ngl": "x"})
        assert status == 422
        status, stopped = call(server, "POST", "/launch/stop", {"pid": out["launch"]["pid"]})
        assert status == 200 and stopped["launch"]["alive"] is False
    finally:
        server.shutdown()
        server.server_close()
        app.sampler.stop()


def test_equipo_simulado_no_lanza():
    app = build_app(AgentConfig(), None, simulated="nvidia2")
    assert app.launcher.available is False


def test_un_cuerpo_demasiado_grande_se_rechaza_en_vez_de_tratarlo_como_vacio(setup):
    from agent.api import MAX_BODY

    cfg, f, _, launcher = setup
    app, server = agent(cfg, launcher)
    try:
        c = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        c.request("POST", "/launch", "x" * (MAX_BODY + 1), {"Content-Type": "application/json"})
        r = c.getresponse()
        assert r.status == 413 and json.loads(r.read())["error"]["code"] == "too_large"
        c.close()
        c = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        c.putrequest("POST", "/launch")
        c.putheader("Content-Length", "abc")
        c.endheaders()
        r = c.getresponse()
        assert r.status == 400 and json.loads(r.read())["error"]["code"] == "length"
        c.close()
        status, listed = call(server, "GET", "/launched")  # el agente sigue atendiendo
        assert status == 200 and listed["launched"] == []
    finally:
        server.shutdown()
        server.server_close()
