import http.client
import json
import threading

import pytest

from agent.api import AgentApp, check_bind, is_loopback, make_server
from agent.model import AGENT_API, DeviceInfo, GpuSample, HostInfo, RamSample
from agent.providers import NullProvider, detect_providers
from agent.providers.base import TelemetryProvider
from agent.sampler import Sampler

HOST = HostInfo(host_id="abc123", hostname="prueba", os="linux")


class FakeGpu(TelemetryProvider):
    name = "fake"

    def devices(self):
        return [DeviceInfo(device_id="fake:GPU-1", provider="fake", kind="gpu", name="Falsa", index=0)]

    def sample(self):
        return {"fake:GPU-1": GpuSample(temp_c=55.0, power_w=float("nan"), fan_pct=None)}

    def ram(self):
        return RamSample(used_mib=1000, total_mib=4000)


class Broken(TelemetryProvider):
    name = "roto"

    def devices(self):
        raise RuntimeError("sin driver")

    def sample(self):
        raise RuntimeError("timeout")


@pytest.fixture
def agent_url():
    servers = []

    def start(providers, token=None):
        sampler = Sampler(providers)
        sampler.refresh_devices()
        sampler.sample_once()
        server = make_server(AgentApp(HOST, sampler, token=token), "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server.server_address[1]

    yield start
    for s in servers:
        s.shutdown()
        s.server_close()


def get(port, path, method="GET", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, headers=headers or {})
    resp = conn.getresponse()
    body = json.loads(resp.read().decode("utf-8"))
    conn.close()
    return resp.status, body


def test_health_lleva_version_del_contrato(agent_url):
    status, body = get(agent_url([NullProvider()]), "/health")
    assert status == 200
    assert body["status"] == "ok"
    assert body["agent_api"] == AGENT_API
    assert body["agent_version"]


def test_info_sin_gpu_no_inventa_dispositivos(agent_url):
    status, body = get(agent_url([NullProvider()]), "/info")
    assert status == 200
    assert body["host"]["host_id"] == "abc123"
    assert body["host"]["cpu_model"] is None
    assert body["devices"] == []
    assert body["providers"] == ["null"]


def test_metrics_nan_y_ausentes_son_null(agent_url):
    status, body = get(agent_url([FakeGpu()]), "/metrics")
    assert status == 200
    gpu = body["snapshot"]["devices"]["fake:GPU-1"]
    assert gpu["temp_c"] == 55.0
    assert gpu["power_w"] is None  # NaN → null
    assert gpu["fan_pct"] is None
    assert body["snapshot"]["ram"] == {"used_mib": 1000, "total_mib": 4000}
    assert body["snapshot"]["t"] is not None


def test_proveedor_roto_no_tumba_a_los_demas(agent_url):
    port = agent_url([FakeGpu(), Broken()])
    _, info = get(port, "/info")
    assert [d["device_id"] for d in info["devices"]] == ["fake:GPU-1"]
    assert "sin driver" in info["errors"]["roto"]
    _, metrics = get(port, "/metrics")
    assert "fake:GPU-1" in metrics["snapshot"]["devices"]
    assert "timeout" in metrics["snapshot"]["errors"]["roto"]


def test_ruta_desconocida_y_metodo(agent_url):
    port = agent_url([NullProvider()])
    status, body = get(port, "/nada")
    assert status == 404 and body["error"]["code"] == "not_found"
    status, body = get(port, "/info", method="POST")
    assert status == 405


def test_token_obligatorio_si_esta_configurado(agent_url):
    port = agent_url([NullProvider()], token="s3creto")
    assert get(port, "/health")[0] == 401
    assert get(port, "/health", headers={"X-Token": "otro"})[0] == 401
    assert get(port, "/health", headers={"X-Token": "s3creto"})[0] == 200


def test_sin_token_rechaza_host_no_local(agent_url):
    port = agent_url([NullProvider()])
    status, body = get(port, "/info", headers={"Host": "atacante.example:9100"})
    assert status == 403 and body["error"]["code"] == "host"
    assert get(port, "/info", headers={"Host": f"localhost:{port}"})[0] == 200


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "[::1]", "127.5.5.5"])
def test_loopback(host):
    assert is_loopback(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::", "arena.lan"])
def test_no_loopback(host):
    assert not is_loopback(host)


def test_fuera_de_localhost_exige_token():
    with pytest.raises(ValueError):
        check_bind("0.0.0.0", None)
    check_bind("0.0.0.0", "tok")
    check_bind("127.0.0.1", None)


def test_sin_proveedores_de_gpu_usa_el_nulo(monkeypatch):
    import agent.providers as providers

    monkeypatch.setattr(providers, "GPU_PROVIDERS", [])
    assert [p.name for p in detect_providers()][0] == "null"


def test_intervalo_invalido():
    with pytest.raises(ValueError):
        Sampler([NullProvider()], interval_s=0)
