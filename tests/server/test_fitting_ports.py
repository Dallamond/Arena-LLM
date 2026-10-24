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


def test_dev_de_un_servidor_lanzado_por_arena_se_traduce_a_su_gpu():
    from server.launch import devices_for_dev_flag

    devs = [
        {"device_id": "nvidia:A", "provider": "nvidia", "index": 0},
        {"device_id": "nvidia:B", "provider": "nvidia", "index": 1},
        {"device_id": "cpu", "provider": "cpu"},
    ]
    assert devices_for_dev_flag("CUDA1", devs) == ["nvidia:B"]
    assert devices_for_dev_flag("CUDA0,CUDA1", devs) == ["nvidia:A", "nvidia:B"]
    assert devices_for_dev_flag("CUDA2", devs) is None  # no existe
    assert devices_for_dev_flag("Vulkan0", devs) is None  # backend sin traducción
    assert devices_for_dev_flag(None, devs) is None


def test_borrar_un_equipo_retira_sus_servidores(tmp_path):
    from server.db import Database

    db = Database(tmp_path / "x.db")
    a = db.add_host("http://127.0.0.1:9100")
    b = db.add_host("http://127.0.0.1:9101")
    ep_a, _ = db.upsert_endpoint(a["id"], "http://127.0.0.1:8080", "llama.cpp", "listo", "x", {})
    ep_b, _ = db.upsert_endpoint(b["id"], "http://127.0.0.1:18081", "llama.cpp", "listo", "y", {})
    assert db.delete_host(b["id"]) is True
    assert [e["id"] for e in db.list_endpoints()] == [ep_a["id"]]
    assert ep_b["id"] not in [e["id"] for e in db.list_endpoints()]
    db.close()


def test_los_id_de_servidor_no_se_reutilizan(tmp_path):
    from server.db import Database

    db = Database(tmp_path / "x.db")
    host = db.add_host("http://127.0.0.1:9100")["id"]
    a, _ = db.upsert_endpoint(host, "http://127.0.0.1:8080", "llama.cpp", "listo", "x", {})
    db.delete_endpoint(a["id"])
    b, _ = db.upsert_endpoint(host, "http://127.0.0.1:8081", "llama.cpp", "listo", "y", {})
    assert b["id"] > a["id"]  # antes el borrado liberaba el número
    db.close()


def test_la_migracion_no_reparte_id_que_ya_usa_un_run(tmp_path):
    import sqlite3

    from server.db import MIGRATIONS, Database

    path = tmp_path / "viejo.db"
    con = sqlite3.connect(path)
    for i, sql in enumerate(MIGRATIONS[:8], start=1):  # una base de antes de la migración 9
        con.executescript(f"BEGIN;{sql};PRAGMA user_version={i};COMMIT;")
    con.execute("INSERT INTO hosts(agent_url, created_at) VALUES ('http://x', 0)")
    con.execute("INSERT INTO runs(kind, suite, status, endpoint_id, created_at) VALUES ('free','libre','done',7,0)")
    con.commit()
    con.close()
    db = Database(path)  # migra
    host = db.list_hosts()[0]["id"]
    ep, _ = db.upsert_endpoint(host, "http://127.0.0.1:8080", "llama.cpp", "listo", "x", {})
    assert ep["id"] > 7  # el 7 ya lo guarda un run: no se vuelve a dar
    db.close()
