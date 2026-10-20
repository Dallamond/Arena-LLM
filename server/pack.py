"""Paquete de resultados (`arena-pack`): exportar runs a un JSON y importarlos en otra instalación.

El paquete lleva todo lo necesario para comparar (ficha de equipo, servidor detectado, modelo, versión de
prueba, parámetros, ítems, series y muestras), pero **no** datos personales: las rutas se reducen al nombre de
fichero, se descartan URLs, tokens y claves, y no viaja ningún id local (`host_pk`, `endpoint_id`).
"""

import hashlib
import json
import re
import time
from typing import Any

from server import __version__
from server.db import Database

FORMAT = "arena-pack"
VERSION = 1
MAX_RUNS = 50
MAX_BYTES = 64 * 1024 * 1024

#: Claves que no salen nunca del equipo (se comparan sin distinguir mayúsculas).
SECRET_KEY = re.compile(r"(^|_|-)(token|secret|password|passwd|api_?key|authorization|cookie|urls?)$", re.I)
#: «C:\x\y.gguf» o «\\srv\x» (puede llevar espacios) y «/home/x/y.gguf» o «~/x/y» (sin espacios): rutas de fichero.
PATH_LIKE = re.compile(r"^(?:(?:[A-Za-z]:[\\/]|\\\\)[^\r\n]+|(?:/|~/)\S+/\S+)$")

RUN_FIELDS = (
    "kind", "suite", "suite_version", "suite_hash", "label", "status", "created_at", "started_at",
    "finished_at", "error", "abort_reason", "notes", "side",
)  # fmt: skip
RUN_JSON_FIELDS = ("params", "servers_snapshot", "host_snapshot", "summary", "tags")
ITEM_FIELDS = (
    "idx", "name", "prompt", "response", "reasoning", "metrics", "eval", "error", "started_at", "finished_at",
)  # fmt: skip
BENCH_FIELDS = (
    "idx", "test", "n_prompt", "n_gen", "n_depth", "params", "t_s_mean", "t_s_std", "reps", "samples", "t", "derived",
)  # fmt: skip


class PackError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


def _basename(path: str) -> str:
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def sanitize(value: Any) -> Any:
    """Copia del valor sin secretos ni rutas personales (recursivo)."""
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items() if not (isinstance(k, str) and SECRET_KEY.search(k))}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str) and PATH_LIKE.match(value):
        return _basename(value)
    return value


def _clean_run(db: Database, run: dict[str, Any]) -> dict[str, Any]:
    run_id = run["id"]
    out: dict[str, Any] = {k: run.get(k) for k in RUN_FIELDS}
    for k in RUN_JSON_FIELDS:
        out[k] = sanitize(run.get(k))
    out["items"] = [{k: it.get(k) for k in ITEM_FIELDS} for it in db.list_items(run_id)]
    out["tps"] = db.list_tps(run_id)
    out["samples"] = db.list_samples(run_id)
    out["bench_rows"] = [{k: r.get(k) for k in BENCH_FIELDS} for r in db.list_bench_rows(run_id)]
    return out


def content_hash(clean: dict[str, Any]) -> str:
    """Hash del contenido del run (no de cuándo ni dónde se exportó): detecta duplicados al importar."""
    body = {k: v for k, v in clean.items() if k not in ("label", "notes", "tags")}
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def export_pack(db: Database, run_ids: list[int]) -> dict[str, Any]:
    runs = db.get_runs(run_ids)
    if not runs:
        raise PackError("Ningún run encontrado", 404)
    active = [r["id"] for r in runs if r["status"] in ("running", "pending")]
    if active:
        raise PackError(f"Hay runs en marcha ({', '.join(f'#{i}' for i in active)}): espera a que terminen", 409)
    cleaned = [_clean_run(db, r) for r in runs]
    for run, clean in zip(runs, cleaned, strict=True):
        db.set_pack_hash(run["id"], content_hash(clean))  # así reimportarlo aquí se detecta como duplicado
    return {
        "format": FORMAT,
        "version": VERSION,
        "arena_version": __version__,
        "exported_at": time.time(),
        "runs": cleaned,
    }


def _validate(pack: Any) -> list[dict[str, Any]]:
    if not isinstance(pack, dict) or pack.get("format") != FORMAT:
        raise PackError("No es un paquete de Arena (falta format: arena-pack)")
    if pack.get("version") != VERSION:
        raise PackError(f"Versión de paquete no soportada: {pack.get('version')!r} (esta Arena entiende la {VERSION})")
    runs = pack.get("runs")
    if not isinstance(runs, list) or not runs:
        raise PackError("El paquete no trae ningún run")
    if len(runs) > MAX_RUNS:
        raise PackError(f"Como máximo {MAX_RUNS} runs por paquete")
    for i, r in enumerate(runs, start=1):
        if not isinstance(r, dict):
            raise PackError(f"El run {i} del paquete no es un objeto")
        for k in ("suite", "kind", "status"):
            if not isinstance(r.get(k), str) or not r[k]:
                raise PackError(f"Al run {i} del paquete le falta «{k}»")
        for k in ("items", "tps", "samples", "bench_rows"):
            if not isinstance(r.get(k, []), list):
                raise PackError(f"En el run {i}, «{k}» debe ser una lista")
        if r["status"] in ("running", "pending"):
            raise PackError(f"El run {i} del paquete estaba en marcha: no se puede importar")
    return runs


def import_pack(db: Database, pack: Any) -> dict[str, Any]:
    """Importa los runs de un paquete. Devuelve {imported: [ids], duplicates: [ids ya existentes]}."""
    runs = _validate(pack)
    imported: list[int] = []
    duplicates: list[int] = []
    for raw in runs:
        clean = {**{k: raw.get(k) for k in RUN_FIELDS}, **{k: sanitize(raw.get(k)) for k in RUN_JSON_FIELDS}}
        clean["items"] = [{k: it.get(k) for k in ITEM_FIELDS} for it in raw.get("items", []) if isinstance(it, dict)]
        clean["tps"] = [t for t in raw.get("tps", []) if isinstance(t, dict)]
        clean["samples"] = [s for s in raw.get("samples", []) if isinstance(s, dict)]
        bench = [r for r in raw.get("bench_rows", []) if isinstance(r, dict)]
        clean["bench_rows"] = [{k: r.get(k) for k in BENCH_FIELDS} for r in bench]
        digest = content_hash(clean)
        existing = db.find_run_by_pack_hash(digest)
        if existing is not None:
            duplicates.append(existing)
            continue
        tags = [t for t in (clean.get("tags") or []) if isinstance(t, str)]
        if "importado" not in tags:
            tags.append("importado")
        fields = {k: clean.get(k) for k in RUN_FIELDS if clean.get(k) is not None}
        fields["created_at"] = fields.get("created_at") or time.time()
        for k in ("params", "servers_snapshot", "host_snapshot", "summary"):
            if clean.get(k) is not None:
                fields[k] = clean[k]
        fields.update(tags=tags, origin="importado", pack_hash=digest)
        run = db.create_run(**fields)
        for it in clean["items"]:
            db.add_item(run["id"], int(it.pop("idx") or 0), **{k: v for k, v in it.items() if v is not None})
        for t in clean["tps"]:
            if all(isinstance(t.get(k), (int, float)) for k in ("t", "tokens", "tps")):
                db.add_tps(run["id"], t["t"], int(t["tokens"]), t["tps"])
        by_time: dict[tuple[float, str], dict[str, Any]] = {}
        for s in clean["samples"]:
            if isinstance(s.get("t"), (int, float)) and s.get("device_id") and isinstance(s.get("data"), dict):
                by_time.setdefault((s["t"], str(s.get("phase") or "")), {})[s["device_id"]] = s["data"]
        for (t, phase), devices in sorted(by_time.items()):
            db.add_samples(run["id"], t, phase, devices)
        for r in clean["bench_rows"]:
            if r.get("test"):
                db.add_bench_row(run["id"], int(r.pop("idx") or 0), {k: v for k, v in r.items() if v is not None})
        imported.append(run["id"])
    return {"imported": imported, "duplicates": duplicates}
