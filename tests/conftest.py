"""Utilidades comunes: uvicorn real en un hilo y agentes simulados por HTTP."""

import threading
import time

import pytest

from agent.api import AgentApp, make_server
from agent.host import enrich_host
from agent.processes import RawProcess, ServerDetector
from agent.sampler import Sampler
from agent.simulate import SimProcessSource, build_profile


def run_uvicorn(app):
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    end = time.monotonic() + 10
    while not server.started and time.monotonic() < end:
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]

    def stop():
        server.should_exit = True
        thread.join(timeout=10)

    return f"http://127.0.0.1:{port}", stop


def start_agent(
    profile: str, token: str | None = None, servers: list[tuple[int, int]] | None = None, interval=0.1, config=None
):
    """Agente simulado. `servers`: [(pid, puerto)] para apuntar a llama-servers simulados."""
    host, providers, procs = build_profile(profile)
    if servers is not None:
        procs = SimProcessSource(
            [
                RawProcess(
                    pid=pid,
                    exe="/opt/llama-server",
                    argv=[
                        "/opt/llama-server",
                        "-m",
                        "/modelos/falso-7b-Q4_K_M.gguf",
                        "--port",
                        str(port),
                        "-ngl",
                        "99",
                    ],
                    started_at="2026-10-03T10:00:00+00:00",
                )
                for pid, port in servers
            ]
        )
    sampler = Sampler(providers, interval_s=interval)
    devices = sampler.refresh_devices()
    first = sampler.sample_once()
    app = AgentApp(
        enrich_host(host, devices, first.ram),
        sampler,
        token=token,
        simulated=profile,
        detector=ServerDetector(procs, providers, ttl_s=0),
        config=config,
    )
    sampler.start()
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"

    def stop():
        server.shutdown()
        server.server_close()
        sampler.stop()

    return url, stop, procs


@pytest.fixture
def stoppers():
    """Lista de funciones de parada que se ejecutan al terminar el test."""
    fns = []
    yield fns
    for f in reversed(fns):
        f()
