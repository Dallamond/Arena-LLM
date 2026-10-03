import argparse
import logging
import os
import sys

from agent import __version__
from agent.api import AgentApp, make_server
from agent.host import enrich_host, host_info
from agent.providers import detect_providers
from agent.sampler import Sampler

SIMULATED_PROFILES = ("nvidia2", "cpu-only", "partial")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m agent", description="Agente Arena LLM")
    p.add_argument("--host", default="127.0.0.1", help="dirección de escucha (por defecto solo localhost)")
    p.add_argument("--port", type=int, default=9100, help="puerto de escucha (por defecto 9100)")
    p.add_argument(
        "--token",
        default=None,
        help="token de acceso; mejor por la variable ARENA_AGENT_TOKEN (la línea de comandos es visible)",
    )
    p.add_argument("--interval", type=float, default=1.0, help="intervalo de muestreo en segundos")
    p.add_argument("--simulate", choices=SIMULATED_PROFILES, help="usar un perfil de hardware simulado")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"Agente Arena {__version__}")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.simulate:
        print("Los perfiles simulados llegan en el paso 5 de F1", file=sys.stderr)
        return 2

    token = args.token or os.environ.get("ARENA_AGENT_TOKEN") or None
    sampler = Sampler(detect_providers(), interval_s=args.interval)
    devices = sampler.refresh_devices()
    first = sampler.sample_once()
    app = AgentApp(enrich_host(host_info(), devices, first.ram), sampler, token=token)
    try:
        server = make_server(app, args.host, args.port)
    except (ValueError, OSError) as exc:
        print(f"No se puede arrancar el agente: {exc}", file=sys.stderr)
        return 2

    sampler.start()
    host, port = server.server_address[:2]
    logging.info(
        "Agente Arena %s en http://%s:%s (token: %s)", __version__, host, port, "sí" if token else "no"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        sampler.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
