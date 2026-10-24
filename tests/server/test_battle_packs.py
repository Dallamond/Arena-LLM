"""Paquetes de batalla: el catálogo base es válido, se fusiona con el propio y los errores no lo tumban."""

import json

from server import battle_packs
from server.library import load as load_library


def test_base_es_valida_y_sus_paquetes_arrancan():
    out = battle_packs.load(None)
    assert out["avisos"] == []
    ids = [p["id"] for p in out["paquetes"]]
    assert len(ids) == len(set(ids)) and {"duelo-rapido", "programador", "memoria-larga"} <= set(ids)
    for p in out["paquetes"]:
        assert p["origen"] == "base" and len(p["hash"]) == 12
        assert (p["suite"] == "libre") == bool(p["prompts"])  # libre lleva prompts resueltos; el resto, no
        assert p["graded"] == (p["suite"] != "libre")
        assert sum(p["pesos"].values()) > 0


def test_pesos_sin_calidad_en_pruebas_libres():
    libres = [p for p in battle_packs.load(None)["paquetes"] if p["suite"] == "libre"]
    assert libres and all(p["pesos"]["quality"] == 0 for p in libres)  # lo no evaluable no puntúa


def test_los_prompts_libres_se_resuelven_desde_la_biblioteca():
    by_id = {p["id"]: p["prompt"] for p in load_library(None)["prompts"]}
    pack = battle_packs.find(None, "velocidad-pura")
    assert pack["prompts"][0] == by_id["explicar-vram"]


def test_hash_estable_y_sensible_al_contenido(tmp_path):
    a = battle_packs.find(None, "duelo-rapido")["hash"]
    assert a == battle_packs.find(None, "duelo-rapido")["hash"]
    doc = {"paquetes": [{**_pack("duelo-rapido"), "params": {"include": ["producto"]}}]}
    (tmp_path / "battles.json").write_text(json.dumps(doc), encoding="utf-8")
    assert battle_packs.find(tmp_path, "duelo-rapido")["hash"] != a


def _pack(pid, **kw):
    return {"id": pid, "nombre": pid, "descripcion": "d", "suite": "qa", "params": {"include": ["producto"]}, **kw}


def test_paquete_propio_se_anade_y_sustituye(tmp_path):
    doc = {"paquetes": [_pack("mio", nombre="Mío"), _pack("duelo-rapido", nombre="Duelo propio")]}
    (tmp_path / "battles.json").write_text(json.dumps(doc), encoding="utf-8")
    out = battle_packs.load(tmp_path)
    by_id = {p["id"]: p for p in out["paquetes"]}
    assert by_id["mio"]["origen"] == "propio" and by_id["duelo-rapido"]["nombre"] == "Duelo propio"
    assert by_id["programador"]["origen"] == "base" and out["avisos"] == []


def test_paquete_invalido_se_descarta_con_aviso_sin_tumbar_el_resto(tmp_path):
    malos = [
        _pack("suite-mala", suite="estres"),
        _pack("id-inexistente", params={"include": ["no-existe"]}),
        _pack("opcion-rara", params={"incluir": ["producto"]}),
        _pack("pesos-mal", pesos={"quality": 1, "velocidad": 2}),
        _pack("pesos-cero", pesos={"quality": 0}),
        {"id": "libre-sin-ids", "nombre": "x", "descripcion": "d", "suite": "libre"},
        {"id": "libre-id-malo", "nombre": "x", "descripcion": "d", "suite": "libre", "prompt_ids": ["nada"]},
        _pack("bueno"),
    ]
    (tmp_path / "battles.json").write_text(json.dumps({"paquetes": malos}), encoding="utf-8")
    out = battle_packs.load(tmp_path)
    ids = {p["id"] for p in out["paquetes"]}
    assert "bueno" in ids and "duelo-rapido" in ids
    assert not ids & {"suite-mala", "id-inexistente", "opcion-rara", "pesos-mal", "pesos-cero", "libre-sin-ids"}
    assert len(out["avisos"]) == 7


def test_fichero_propio_roto_se_ignora_con_aviso(tmp_path):
    (tmp_path / "battles.json").write_text("{no es json", encoding="utf-8")
    out = battle_packs.load(tmp_path)
    assert out["paquetes"] and any("ignorados" in a for a in out["avisos"])
