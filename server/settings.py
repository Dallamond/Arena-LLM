"""Ajustes del servidor: variables de entorno y argumentos. Nada específico de un equipo."""

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("ARENA_DATA_DIR") or ROOT / "data"))
    host: str = "127.0.0.1"
    # 8090 y no 8080: 8080 es el puerto por defecto de llama-server y chocarían.
    port: int = 8090
    #: Agentes que se registran al arrancar si no existen (ARENA_AGENTS="http://a:9100,http://b:9100").
    agents: list[str] = field(
        default_factory=lambda: [u.strip() for u in os.environ.get("ARENA_AGENTS", "").split(",") if u.strip()]
    )
    poll_interval_s: float = 1.0
    info_interval_s: float = 30.0
    request_timeout_s: float = 3.0
    web_dist: Path = ROOT / "web" / "dist"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "arena.db"
