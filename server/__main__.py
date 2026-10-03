import argparse
import logging
import sys

from server.settings import Settings


def main(argv: list[str] | None = None) -> int:
    d = Settings()
    p = argparse.ArgumentParser(prog="python -m server", description="Servidor Arena LLM")
    p.add_argument("--host", default=d.host, help="dirección de escucha (por defecto solo localhost)")
    p.add_argument("--port", type=int, default=d.port, help=f"puerto (por defecto {d.port})")
    p.add_argument("--data-dir", default=str(d.data_dir), help="carpeta de datos (o ARENA_DATA_DIR)")
    p.add_argument("--agent", action="append", default=[], help="URL de un agente a registrar (repetible)")
    p.add_argument("--poll", type=float, default=d.poll_interval_s, help="intervalo de sondeo en segundos")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        import uvicorn

        from server.app import create_app
    except ImportError as exc:
        print(f"Faltan dependencias del servidor ({exc.name}). Ejecuta scripts/setup.", file=sys.stderr)
        return 2

    from pathlib import Path

    settings = Settings(
        data_dir=Path(args.data_dir),
        host=args.host,
        port=args.port,
        agents=[*d.agents, *args.agent],
        poll_interval_s=args.poll,
    )
    if not (settings.web_dist / "index.html").exists():
        logging.warning("No hay web compilada en %s: solo API (usa `npm run dev --prefix web`)", settings.web_dist)
    logging.info("Arena LLM en http://%s:%s · datos en %s", settings.host, settings.port, settings.data_dir)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
