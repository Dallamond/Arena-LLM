"""Biblioteca de prompts predefinidos: fichero base válido, fusión con la propia y errores."""

import json

import httpx
import pytest

from server import library
from server.app import create_app
from server.settings import Settings
from tests.conftest import run_uvicorn


def test_base_es_valida_y_tiene_todas_las_categorias():
    lib = library.load(None)
    assert lib["avisos"] == []
    cats = {c["id"] for c in lib["categorias"]}
    assert {"logica", "ci", "mates", "codigo", "formato", "redaccion", "explicar"} <= cats
    assert all(p["categoria"] in cats for p in lib["prompts"])
    ids = [p["id"] for p in lib["prompts"]]
    assert len(ids) == len(set(ids))
    assert all(p["origen"] == "base" and len(p["hash"]) == 12 for p in lib["prompts"])


def test_hash_estable_por_contenido():
    a = {p["id"]: p["hash"] for p in library.load(None)["prompts"]}
    b = {p["id"]: p["hash"] for p in library.load(None)["prompts"]}
    assert a == b


def test_biblioteca_propia_anade_y_sustituye(tmp_path):
    (tmp_path / "prompts.json").write_text(
        json.dumps(
            {
                "categorias": {"mia": "Mis pruebas"},
                "prompts": [
                    {"id": "mia-1", "categoria": "mia", "titulo": "Uno", "prompt": "Hola"},
                    {
                        "id": "mates-tren",
                        "categoria": "mates",
                        "titulo": "Tren mío",
                        "prompt": "Otro tren",
                        "respuesta": "1",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    lib = library.load(tmp_path)
    by_id = {p["id"]: p for p in lib["prompts"]}
    assert by_id["mia-1"]["origen"] == "propia" and by_id["mia-1"]["respuesta"] is None
    assert by_id["mates-tren"]["titulo"] == "Tren mío" and by_id["mates-tren"]["origen"] == "propia"
    assert {"id": "mia", "nombre": "Mis pruebas"} in lib["categorias"]
    assert lib["avisos"] == []


@pytest.mark.parametrize(
    "content",
    [
        "{no es json",
        json.dumps({"prompts": [{"id": "x", "categoria": "c", "titulo": "t"}]}),
        json.dumps({"prompts": [{"id": "x", "categoria": "c", "titulo": "t", "prompt": "p", "max_tokens": 0}]}),
        json.dumps({"prompts": [{"id": "x", "categoria": "c", "titulo": "t", "prompt": "p"}] * 2}),
    ],
)
def test_biblioteca_propia_rota_se_ignora_con_aviso(tmp_path, content):
    (tmp_path / "prompts.json").write_text(content, encoding="utf-8")
    lib = library.load(tmp_path)
    assert len(lib["avisos"]) == 1 and "ignorada" in lib["avisos"][0]
    assert all(p["origen"] == "base" for p in lib["prompts"])


def test_api_prompts(tmp_path, stoppers):
    url, stop = run_uvicorn(create_app(Settings(data_dir=tmp_path, agents=[], web_dist=tmp_path / "no")))
    stoppers.append(stop)
    r = httpx.get(f"{url}/api/prompts", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["version"] and len(body["prompts"]) >= 20
