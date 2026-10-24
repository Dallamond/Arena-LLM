"""Un servidor detectado que se para desaparece de la lista; los dados de alta a mano se quedan."""

import asyncio
from types import SimpleNamespace

import httpx

from server.agents import AgentError, HostState
from server.db import Database
from server.detect import EndpointDetector
from server.hub import EventHub


class FakeAgent:
    def __init__(self, servers=None, fail=False):
        self.servers = servers or []
        self.fail = fail

    async def get(self, state, path):
        if self.fail:
            raise AgentError("offline", "caído")
        return {"servers": self.servers}


def make(agent):
    db = Database(":memory:")
    host = db.add_host("http://127.0.0.1:1", "equipo")
    state = HostState(pk=host["id"], agent_url=host["agent_url"], status="online")
    monitor = SimpleNamespace(agent=agent, states={state.pk: state})
    client = httpx.AsyncClient(timeout=0.5)
    return db, state, EndpointDetector(db, EventHub(), monitor, client), client


def detect(det, state, client):
    async def run():
        try:
            return await det.detect_host(state)
        finally:
            await client.aclose()

    return asyncio.run(run())


def seed(db, state):
    detected, _ = db.upsert_endpoint(state.pk, "http://127.0.0.1:18081", "llama.cpp", "detenido", "x", {})
    running, _ = db.upsert_endpoint(state.pk, "http://127.0.0.1:18082", "llama.cpp", "listo", "y", {})
    manual = db.add_manual_endpoint(state.pk, "http://127.0.0.1:18083", None, None)
    return detected, running, manual


def test_el_servidor_detectado_que_se_para_desaparece():
    db, state, det, client = make(FakeAgent(servers=[]))
    detected, running, manual = seed(db, state)
    detect(det, state, client)
    left = {e["id"] for e in db.list_endpoints(state.pk)}
    assert left == {manual["id"]}  # el parado y el que ya no está en marcha se van; el manual se queda


def test_con_el_agente_caido_no_se_borra_nada():
    db, state, det, client = make(FakeAgent(fail=True))
    detected, running, manual = seed(db, state)
    detect(det, state, client)
    assert {e["id"] for e in db.list_endpoints(state.pk)} == {detected["id"], running["id"], manual["id"]}


def test_con_el_agente_caido_un_servidor_muerto_deja_de_figurar_como_listo():
    db, state, det, client = make(FakeAgent(fail=True))
    detected, running, manual = seed(db, state)
    detect(det, state, client)  # nada escucha en esos puertos
    by_id = {e["id"]: e["status"] for e in db.list_endpoints(state.pk)}
    assert by_id[running["id"]] == "sin respuesta"  # antes se quedaba «listo» para siempre
    assert by_id[detected["id"]] == "detenido"  # lo ya parado no se toca
