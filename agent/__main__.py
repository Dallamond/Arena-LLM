import argparse
import logging
import os
import sys

from agent import __version__
from agent.api import AgentApp, make_server
from agent.config import load_config
from agent.host import enrich_host, host_info
from agent.processes import ServerDetector, default_process_source
from agent.providers import detect_providers
from agent.sampler import Sampler
from agent.simulate import PROFILES, build_profile


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
    p.add_argument("--config", help="fichero JSON de configuración del agente")
    p.add_argument("--models-dir", action="append", default=[], help="carpeta de modelos GGUF permitida (repetible)")
    p.add_argument("--simulate", choices=PROFILES, help="usar un perfil de hardware simulado")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"Agente Arena {__version__}")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config = load_config(args.config, args.models_dir)
    except (OSError, ValueError) as exc:
        print(f"Configuración inválida: {exc}", file=sys.stderr)
        return 2
    token = args.token or os.environ.get("ARENA_AGENT_TOKEN") or None
    if args.simulate:
        host, providers, procs = build_profile(args.simulate)
        logging.info("Modo simulado: perfil %s", args.simulate)
    else:
        host, providers, procs = host_info(), detect_providers(), default_process_source()
    sampler = Sampler(providers, interval_s=args.interval)
    devices = sampler.refresh_devices()
    first = sampler.sample_once()
    app = AgentApp(
        enrich_host(host, devices, first.ram),
        sampler,
        token=token,
        simulated=args.simulate,
        detector=ServerDetector(procs, providers),
        config=config,
    )
    logging.info(
        "Configuración: %s · carpetas de modelos: %s",
        config.source or "ninguna (valores por defecto)",
        ", ".join(map(str, config.model_dirs)) or "ninguna",
    )
    try:
        server = make_server(app, args.host, args.port)
    except (ValueError, OSError) as exc:
        print(f"No se puede arrancar el agente: {exc}", file=sys.stderr)
        return 2

    sampler.start()
    host, port = server.server_address[:2]
    logging.info("Agente Arena %s en http://%s:%s (token: %s)", __version__, host, port, "sí" if token else "no")
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
