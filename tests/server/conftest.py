"""Laboratorio sin GPU para los tests del servidor: llama-server simulado + agente simulado + Arena."""

import httpx
import pytest

import server.detect
from server.app import create_app
from server.fakes.fake_llama import FakeLlama, create_fake_app
from server.settings import Settings
from tests.conftest import run_uvicorn, start_agent

SIM_PID_GPU0 = 4201  # el perfil nvidia2 asocia este pid a su primera GPU


@pytest.fixture(autouse=True)
def fast_detection(monkeypatch):
    monkeypatch.setattr(server.detect, "DETECT_EVERY_S", 0.2)


@pytest.fixture
def lab(tmp_path, stoppers):
    """Arranca el laboratorio completo y devuelve (cliente, fake)."""

    def make(**fake_kw):
        fake = FakeLlama(**{"tps": 200.0, "pp_tps": 5000.0, **fake_kw})
        llama_url, stop_llama = run_uvicorn(create_fake_app(fake))
        stoppers.append(stop_llama)
        port = int(llama_url.rsplit(":", 1)[1])
        agent_url, stop_agent, _ = start_agent("nvidia2", servers=[(SIM_PID_GPU0, port)])
        stoppers.append(stop_agent)
        settings = Settings(data_dir=tmp_path, agents=[agent_url], poll_interval_s=0.1, web_dist=tmp_path / "no")
        api_url, stop_api = run_uvicorn(create_app(settings))
        stoppers.append(stop_api)
        client = httpx.Client(base_url=api_url, timeout=10)
        stoppers.append(client.close)
        return client, fake

    return make
