"""Paquetes de batalla predeterminados (fichero de datos, no código).

Un paquete fija la prueba, sus opciones, los prompts (en las pruebas libres, por id de la biblioteca)
y los pesos de la nota, para lanzar una batalla comparable sin configurar nada. La base va en
``server/catalog/battles.json``; Lucas puede añadir los suyos en ``<data_dir>/battles.json`` con la
misma forma (un ``id`` repetido sustituye al de la base). Un fichero propio roto se ignora con aviso,
y un paquete que no cuadra con las pruebas o la biblioteca se descarta con aviso sin tumbar el resto.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from server import library
from server.runs.battle import BATTLE_SUITES
from server.runs.suites import SUITES
from server.scoring import DIMENSIONS

BASE_FILE = library.CATALOG_DIR / "battles.json"
USER_FILE_NAME = "battles.json"


class PackError(ValueError):
    pass


def _clean(raw: Any, where: str, prompts_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PackError(f"{where}: cada paquete debe ser un objeto")
    for key in ("id", "nombre", "descripcion", "suite"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise PackError(f"{where}: falta '{key}' (texto)")
    suite = raw["suite"].strip()
    if suite not in BATTLE_SUITES:
        raise PackError(f"{where}: la prueba '{suite}' no está disponible en la Batalla")
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        raise PackError(f"{where}: 'params' debe ser un objeto")
    weights = raw.get("pesos")
    if weights is not None:
        if not isinstance(weights, dict) or set(weights) - set(DIMENSIONS):
            raise PackError(f"{where}: 'pesos' admite solo {', '.join(DIMENSIONS)}")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 for v in weights.values()):
            raise PackError(f"{where}: cada peso debe ser un número no negativo")
        if not sum(weights.values()):
            raise PackError(f"{where}: algún peso debe ser mayor que 0")
    minutes = raw.get("minutos")
    if minutes is not None and (isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or minutes <= 0):
        raise PackError(f"{where}: 'minutos' debe ser un número positivo")

    prompts: list[str] = []
    if suite == "libre":
        ids = raw.get("prompt_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
            raise PackError(f"{where}: una prueba libre necesita 'prompt_ids' (ids de la biblioteca)")
        missing = [i for i in ids if i not in prompts_by_id]
        if missing:
            raise PackError(f"{where}: ids que no están en la biblioteca: {', '.join(missing)}")
        prompts = [prompts_by_id[i]["prompt"] for i in ids]
    else:
        # Opciones propias de la prueba: deben existir en su formulario (así un typo no se pierde en silencio)
        known = {f["key"] for f in SUITES[suite].fields} | {"max_tokens", "repeats"}
        unknown = sorted(set(params) - known)
        if unknown:
            raise PackError(f"{where}: opciones que '{suite}' no tiene: {', '.join(unknown)}")
        try:
            SUITES[suite].cases(SUITES[suite].params(params))  # type: ignore[misc]  # valida ids, tamaños, rangos
        except ValueError as exc:
            raise PackError(f"{where}: {exc}") from exc

    content = {"suite": suite, "params": params, "prompts": prompts, "pesos": weights}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
    return {
        "id": raw["id"].strip(),
        "nombre": raw["nombre"].strip(),
        "descripcion": raw["descripcion"].strip(),
        "minutos": minutes,
        "suite": suite,
        "params": params,
        "prompts": prompts,
        "pesos": weights,
        "hash": digest,
        "graded": SUITES[suite].graded,
    }


def _parse(
    doc: Any, origin: str, prompts_by_id: dict[str, dict[str, Any]], warnings: list[str]
) -> list[dict[str, Any]]:
    if not isinstance(doc, dict) or not isinstance(doc.get("paquetes"), list):
        raise PackError(f"{origin}: falta la lista 'paquetes'")
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(doc["paquetes"]):
        try:
            out.append(_clean(raw, f"{origin} · paquete {i + 1}", prompts_by_id))
        except PackError as exc:
            warnings.append(str(exc))
    seen: set[str] = set()
    for p in out:
        if p["id"] in seen:
            raise PackError(f"{origin}: id repetido '{p['id']}'")
        seen.add(p["id"])
    return out


def load(data_dir: Path | None) -> dict[str, Any]:
    lib = library.load(data_dir)
    prompts_by_id = {p["id"]: p for p in lib["prompts"]}
    base_doc = json.loads(BASE_FILE.read_text(encoding="utf-8"))
    warnings: list[str] = []
    packs = _parse(base_doc, "paquetes base", prompts_by_id, warnings)
    origin = {p["id"]: "base" for p in packs}

    user_file = data_dir / USER_FILE_NAME if data_dir else None
    if user_file and user_file.is_file():
        try:
            mine = _parse(json.loads(user_file.read_text(encoding="utf-8")), str(user_file), prompts_by_id, warnings)
        except (OSError, json.JSONDecodeError, PackError) as exc:
            warnings.append(f"Paquetes propios ignorados: {exc}")
        else:
            by_id = {p["id"]: p for p in packs}
            for p in mine:
                by_id[p["id"]] = p
                origin[p["id"]] = "propio"
            packs = list(by_id.values())
    for p in packs:
        p["origen"] = origin[p["id"]]
    return {"version": str(base_doc.get("version", "1")), "paquetes": packs, "avisos": warnings}


def find(data_dir: Path | None, pack_id: str) -> dict[str, Any] | None:
    return next((p for p in load(data_dir)["paquetes"] if p["id"] == pack_id), None)
