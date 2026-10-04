"""Biblioteca de prompts predefinidos (fichero de datos, no código).

La base va en ``server/catalog/prompts.json``. Lucas puede añadir los suyos en
``<data_dir>/prompts.json`` con la misma forma: un ``id`` repetido sustituye al
de la base. Un fichero propio roto no tumba nada: se ignora y se avisa.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

CATALOG_DIR = Path(__file__).resolve().parent / "catalog"
BASE_FILE = CATALOG_DIR / "prompts.json"
USER_FILE_NAME = "prompts.json"


class LibraryError(ValueError):
    pass


def _clean_prompt(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise LibraryError(f"{where}: cada prompt debe ser un objeto")
    for key in ("id", "categoria", "titulo", "prompt"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise LibraryError(f"{where}: falta '{key}' (texto)")
    answer = raw.get("respuesta")
    if answer is not None and not isinstance(answer, str):
        raise LibraryError(f"{where}: 'respuesta' debe ser texto o null")
    max_tokens = raw.get("max_tokens")
    if max_tokens is not None and (isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1):
        raise LibraryError(f"{where}: 'max_tokens' debe ser un entero positivo o null")
    return {
        "id": raw["id"].strip(),
        "categoria": raw["categoria"].strip(),
        "titulo": raw["titulo"].strip(),
        "prompt": raw["prompt"].strip(),
        "respuesta": answer,
        "max_tokens": max_tokens,
    }


def parse(doc: Any, origin: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Valida un documento de biblioteca y devuelve (categorías, prompts)."""
    if not isinstance(doc, dict):
        raise LibraryError(f"{origin}: el fichero debe ser un objeto JSON")
    cats = doc.get("categorias") or {}
    if not isinstance(cats, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in cats.items()):
        raise LibraryError(f"{origin}: 'categorias' debe ser un objeto id → nombre")
    items = doc.get("prompts")
    if not isinstance(items, list):
        raise LibraryError(f"{origin}: falta la lista 'prompts'")
    prompts = [_clean_prompt(p, f"{origin} · prompt {i + 1}") for i, p in enumerate(items)]
    seen: set[str] = set()
    for p in prompts:
        if p["id"] in seen:
            raise LibraryError(f"{origin}: id repetido '{p['id']}'")
        seen.add(p["id"])
    return dict(cats), prompts


def load(data_dir: Path | None) -> dict[str, Any]:
    base_doc = json.loads(BASE_FILE.read_text(encoding="utf-8"))
    cats, prompts = parse(base_doc, "biblioteca base")
    origin = {p["id"]: "base" for p in prompts}
    warnings: list[str] = []

    user_file = data_dir / USER_FILE_NAME if data_dir else None
    if user_file and user_file.is_file():
        try:
            ucats, uprompts = parse(json.loads(user_file.read_text(encoding="utf-8")), str(user_file))
        except (OSError, json.JSONDecodeError, LibraryError) as exc:
            warnings.append(f"Biblioteca propia ignorada: {exc}")
        else:
            cats.update(ucats)
            by_id = {p["id"]: p for p in prompts}
            for p in uprompts:
                by_id[p["id"]] = p
                origin[p["id"]] = "propia"
            prompts = list(by_id.values())

    for p in prompts:
        p["origen"] = origin[p["id"]]
        p["hash"] = hashlib.sha256(p["prompt"].encode("utf-8")).hexdigest()[:12]
        cats.setdefault(p["categoria"], p["categoria"])
    return {
        "version": str(base_doc.get("version", "1")),
        "categorias": [{"id": k, "nombre": v} for k, v in cats.items() if any(p["categoria"] == k for p in prompts)],
        "prompts": prompts,
        "avisos": warnings,
    }
