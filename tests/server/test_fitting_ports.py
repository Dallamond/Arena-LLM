"""Los servidores recién lanzados por el agente reservan su puerto aunque aún no estén detectados."""

import asyncio
from types import SimpleNamespace

from server import fitting
from server.agents import AgentError
from server.fit import FitParams


class FakeAgent:
    def __init__(self, launched=None, fail=False):
        self.launched = launched or []
        self.fail = fail

    async def get(self, state, path, query=None, timeout=None):
        if path == "/gguf":
            return {"gguf": {"name": "m"}}
        if self.fail:
            raise AgentError("down", "sin respuesta")
        return {"launched": self.launched}


def run(monkeypatch, agent, reserved=None):
    seen = {}
    monkeypatch.setattr(fitting, "estimate", lambda g, p: {})
    monkeypatch.setattr(fitting, "gpus_from_state", lambda *a: [])
    monkeypatch.setattr(fitting, "ram_free_from_metrics", lambda m: None)
    monkeypatch.setattr(fitting, "fit", lambda *a: {})
    monkeypatch.setattr(fitting.launch, "build", lambda **kw: seen.update(kw) or {})
    monitor = SimpleNamespace(states={1: SimpleNamespace(info={}, metrics=None)}, agent=agent)
    db = SimpleNamespace(list_endpoints=lambda host_id: [])
    asyncio.run(fitting.fit_model(monitor, db, 1, "x.gguf", FitParams(), reserved or {8090}))
    return seen["reserved_ports"]


def test_reserva_el_puerto_de_lo_recien_lanzado(monkeypatch):
    agent = FakeAgent([{"port": 8080, "alive": True}, {"port": 8081, "alive": False}, {"port": None, "alive": True}])
    assert run(monkeypatch, agent) == {8090, 8080}  # el muerto y el que no trae puerto no cuentan


def test_si_el_agente_no_responde_a_launched_sigue_como_antes(monkeypatch):
    assert run(monkeypatch, FakeAgent(fail=True)) == {8090}
