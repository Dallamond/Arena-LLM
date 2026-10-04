"""Configuración local del agente (JSON). Nada de esto va en el código.

Orden de búsqueda: `--config`, variable `ARENA_AGENT_CONFIG`, y la carpeta de
configuración del usuario (`%APPDATA%\\ArenaLLM\\agent.json` en Windows,
`$XDG_CONFIG_HOME/arena-llm/agent.json` o `~/.config/arena-llm/agent.json`).

Ejemplo:
    {"model_dirs": ["D:/modelos"], "llama_bench": "D:/dev-tools/llama.cpp/llama-bench.exe"}

`llama_server` es opcional: si falta, se busca `llama-server` junto a `llama-bench`.
Solo se usa para proponer el comando de arranque; el agente nunca lo ejecuta.
"""

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentConfig:
    model_dirs: list[Path] = field(default_factory=list)
    llama_bench: Path | None = None
    llama_server: Path | None = None
    source: Path | None = None  # fichero del que se cargó

    def llama_server_path(self) -> Path | None:
        """`llama_server` configurado, o el `llama-server` que haya junto a `llama-bench`."""
        if self.llama_server:
            return self.llama_server
        if self.llama_bench:
            name = "llama-server" + (".exe" if self.llama_bench.suffix.lower() == ".exe" else "")
            candidate = self.llama_bench.with_name(name)
            if candidate.is_file():
                return candidate
        return None

    def allowed_model(self, raw: str) -> Path | None:
        """Ruta resuelta si es un .gguf dentro de una carpeta permitida; si no, None."""
        if not raw:
            return None
        try:
            p = Path(raw).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        if p.suffix.lower() != ".gguf" or not p.is_file():
            return None
        for d in self.model_dirs:
            try:
                if p.is_relative_to(d.resolve()):
                    return p
            except OSError:
                continue
        return None


def default_config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "ArenaLLM"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "arena-llm"
    return base / "agent.json"


def load_config(
    path: str | Path | None = None, extra_model_dirs: list[str] | None = None, llama_bench: str | None = None
) -> AgentConfig:
    explicit = path or os.environ.get("ARENA_AGENT_CONFIG")
    cfg_path = Path(explicit) if explicit else default_config_path()
    data: dict = {}
    if cfg_path.exists():
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{cfg_path}: se esperaba un objeto JSON")
    elif explicit:
        raise FileNotFoundError(f"No existe el fichero de configuración {cfg_path}")
    dirs = [Path(d).expanduser() for d in [*data.get("model_dirs", []), *(extra_model_dirs or [])]]
    bench = llama_bench or data.get("llama_bench")
    server = data.get("llama_server")
    return AgentConfig(
        model_dirs=dirs,
        llama_bench=Path(bench).expanduser() if bench else None,
        llama_server=Path(server).expanduser() if server else None,
        source=cfg_path if cfg_path.exists() else None,
    )
