"""Tests de contrato: la API se comporta igual con cualquier hardware.

Se ejecutan contra los tres perfiles simulados y, si hay proveedores reales
disponibles, contra este equipo. Ningún test depende de una GPU concreta.
"""

from dataclasses import fields

import pytest

from agent.api import AgentApp
from agent.host import enrich_host, host_info
from agent.model import AGENT_API, CpuSample, GpuSample
from agent.providers import detect_providers
from agent.sampler import Sampler
from agent.simulate import PROFILES, build_profile, load_at

GPU_KEYS = {f.name for f in fields(GpuSample)}
CPU_KEYS = {f.name for f in fields(CpuSample)}
NUMERIC = (int, float)


class FakeClock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def make_app(profile: str, clock=None):
    if profile == "real":
        host, providers = host_info(), detect_providers()
    else:
        host, providers = build_profile(profile, clock=clock or FakeClock())
    sampler = Sampler(providers)
    devices = sampler.refresh_devices()
    first = sampler.sample_once()
    return AgentApp(
        enrich_host(host, devices, first.ram), sampler, simulated=None if profile == "real" else profile
    )


def call(app, path):
    status, body = app.handle("GET", path, {"Host": "127.0.0.1"})
    assert status == 200, body
    return body


TARGETS = [*PROFILES, "real"]


@pytest.mark.parametrize("profile", TARGETS)
def test_contrato_info_y_metrics(profile):
    app = make_app(profile)
    app.sampler.sample_once()  # segunda lectura: ya hay uso de CPU
    info = call(app, "/info")
    snap = call(app, "/metrics")["snapshot"]

    host = info["host"]
    assert host.host_id and host.hostname and host.os
    assert host.ram_total_mib and host.ram_total_mib > 0
    assert not info["errors"], info["errors"]
    assert not snap.errors, snap.errors

    ids = [d.device_id for d in info["devices"]]
    assert len(ids) == len(set(ids)), "device_id duplicado"
    kinds = {d.kind for d in info["devices"]}
    assert "cpu" in kinds
    for d in info["devices"]:
        assert d.device_id.startswith(f"{d.provider}:")
        assert d.device_id in snap.devices, f"{d.device_id} sin muestra"
        sample = snap.devices[d.device_id]
        if d.kind == "gpu":
            assert isinstance(sample, GpuSample)
            assert d.memory_total_mib and d.memory_total_mib > 0
            # Lo que el dispositivo declara no disponible nunca aparece con valor
            for key in set(d.fields_unavailable) & GPU_KEYS:
                assert getattr(sample, key) is None, f"{key} declarado ausente pero con valor"
            for key in ("temp_c", "mem_used_mib", "util_gpu_pct"):
                v = getattr(sample, key)
                assert v is None or isinstance(v, NUMERIC)
            if sample.mem_used_mib is not None:
                assert 0 <= sample.mem_used_mib <= d.memory_total_mib
        else:
            assert isinstance(sample, CpuSample)
            u = sample.util_pct
            assert u is None or 0 <= u <= 100

    assert snap.ram is not None
    assert 0 < snap.ram.used_mib <= snap.ram.total_mib


def test_cpu_only_no_tiene_gpu():
    info = call(make_app("cpu-only"), "/info")
    assert [d.kind for d in info["devices"]] == ["cpu"]
    assert info["providers"] == ["null", "cpu"]
    assert info["simulated"] == "cpu-only"


def test_nvidia2_tiene_dos_gpu_distintas():
    info = call(make_app("nvidia2"), "/info")
    gpus = [d for d in info["devices"] if d.kind == "gpu"]
    assert len(gpus) == 2
    assert len({g.memory_total_mib for g in gpus}) == 2
    assert all(g.temp_slowdown_c for g in gpus)


def test_partial_declara_lo_que_falta():
    app = make_app("partial")
    [gpu] = [d for d in call(app, "/info")["devices"] if d.kind == "gpu"]
    assert {"fan_pct", "power_w", "throttle_mask", "temp_slowdown_c"} <= set(gpu.fields_unavailable)
    sample = call(app, "/metrics")["snapshot"].devices[gpu.device_id]
    assert sample.fan_pct is None and sample.power_w is None and sample.throttle is None
    assert sample.temp_c is not None  # lo que sí tiene, lo da


def test_simulacion_responde_a_la_carga():
    clock = FakeClock(19.0)
    app = make_app("nvidia2", clock=clock)
    gpu_id = next(d.device_id for d in call(app, "/info")["devices"] if d.kind == "gpu")
    idle = app.sampler.sample_once().devices[gpu_id]
    assert load_at(19.0) == 0.0 and load_at(20.0) == 1.0
    temps = []
    for t in range(20, 60):  # fase de carga, segundo a segundo
        clock.t = float(t)
        temps.append(app.sampler.sample_once().devices[gpu_id].temp_c)
    busy = app.sampler.latest().devices[gpu_id]
    assert busy.power_w > idle.power_w
    assert busy.util_gpu_pct > 90
    assert temps[-1] > temps[0] + 10, "la temperatura sube con inercia"
    assert "gpu_idle" in idle.throttle and "gpu_idle" not in busy.throttle


def test_simulacion_determinista():
    a = make_app("nvidia2", clock=FakeClock(25.0)).sampler.sample_once()
    b = make_app("nvidia2", clock=FakeClock(25.0)).sampler.sample_once()
    assert a.devices == b.devices


def test_perfil_desconocido():
    with pytest.raises(ValueError):
        build_profile("amd9")


def test_version_del_contrato_en_respuestas():
    from agent.api import envelope

    assert b'"agent_api": %d' % AGENT_API in envelope({})
