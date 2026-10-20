"""Paquete de resultados: exportar, importar en otra instalación, duplicados y datos personales."""

import copy
import json

from server import compare, pack
from server.db import Database
from tests.server.test_runs import endpoint_ready, run_finished


def make_run(c, ep):
    r = c.post(
        "/api/runs",
        json={"suite": "libre", "endpoint_id": ep["id"], "label": "base",
              "params": {"prompts": ["Hola", "Adiós"], "max_tokens": 8, "baseline_s": 0.5}},  # fmt: skip
    )
    assert r.status_code == 201, r.text
    return run_finished(c, r.json()["id"])


def test_sanitize_quita_rutas_y_secretos_pero_no_los_tokens_de_la_medida():
    clean = pack.sanitize(
        {
            "model_path": r"D:\Mis Modelos\qwen 7b.gguf",
            "linux": "/home/lucas/modelos/m.gguf",
            "prompt": "/think responde a/b",
            "base_url": "http://192.168.1.5:8080",
            "api_key": "abc",
            "agent_url": "http://x",
            "token": "t",
            "max_tokens": 256,
            "completion_tokens": 40,
            "lista": [{"path": r"C:\x\y.bin", "ok": 1}],
        }
    )
    assert clean == {
        "model_path": "qwen 7b.gguf",
        "linux": "m.gguf",
        "prompt": "/think responde a/b",  # texto normal: no es una ruta
        "max_tokens": 256,
        "completion_tokens": 40,
        "lista": [{"path": "y.bin", "ok": 1}],
    }


def test_ida_y_vuelta_a_otra_base_de_datos(lab):
    c, _ = lab()
    run = make_run(c, endpoint_ready(c))
    resp = c.get(f"/api/runs/pack?runs={run['id']}")
    assert resp.status_code == 200 and "attachment" in resp.headers["content-disposition"]
    data = resp.json()
    assert data["format"] == "arena-pack" and data["version"] == 1 and len(data["runs"]) == 1
    text = resp.text
    assert "host_pk" not in text and "endpoint_id" not in text
    assert "127.0.0.1" not in text  # sin URLs del equipo
    assert "\\\\" not in json.dumps(data["runs"][0]["params"])  # ni rutas de Windows

    other = Database(":memory:")
    out = pack.import_pack(other, data)
    assert len(out["imported"]) == 1 and out["duplicates"] == []
    new = other.get_run(out["imported"][0])
    assert new["origin"] == "importado" and new["tags"] == ["importado"]
    assert new["host_pk"] is None and new["endpoint_id"] is None
    assert new["suite_version"] == run["suite_version"] and new["suite_hash"] == run["suite_hash"]
    assert [i["response"] for i in other.list_items(new["id"])] == [i["response"] for i in run["items"]]
    assert len(other.list_samples(new["id"])) == len(run["samples"])
    # Las métricas comparables salen iguales
    assert compare.run_metrics(new)["tps"] == compare.run_metrics(run)["tps"]
    assert compare.run_metrics(new)["energy"] == compare.run_metrics(run)["energy"]
    # Y se puede comparar con el original
    out2 = compare.build([new, new], {new["id"]: other.list_items(new["id"])}, {}, {}, {})
    assert out2["comparability"]["level"] == "si"


def test_importar_dos_veces_o_lo_propio_es_duplicado(lab):
    c, _ = lab()
    run = make_run(c, endpoint_ready(c))
    data = c.get(f"/api/runs/pack?runs={run['id']}").json()
    first = c.post("/api/runs/import", content=json.dumps(data))
    assert first.status_code == 201 and first.json() == {"imported": [], "duplicates": [run["id"]]}
    other = Database(":memory:")
    assert len(pack.import_pack(other, data)["imported"]) == 1
    again = pack.import_pack(other, data)
    assert again["imported"] == [] and len(again["duplicates"]) == 1


def test_importado_aparece_en_el_historial_y_en_comparar(lab):
    c, _ = lab()
    run = make_run(c, endpoint_ready(c))
    data = c.get(f"/api/runs/pack?runs={run['id']}").json()
    data["runs"][0]["items"][0]["response"] = "otra respuesta"  # otro contenido ⇒ no es duplicado
    r = c.post("/api/runs/import", content=json.dumps(data))
    assert r.status_code == 201, r.text
    new_id = r.json()["imported"][0]
    row = next(x for x in c.get("/api/runs").json() if x["id"] == new_id)
    assert row["origin"] == "importado" and "importado" in row["tags"]
    cmp = c.get(f"/api/compare?runs={run['id']},{new_id}").json()
    assert len(cmp["runs"]) == 2


def test_otra_version_de_prueba_importada_no_es_comparable(lab):
    c, _ = lab()
    run = make_run(c, endpoint_ready(c))
    data = c.get(f"/api/runs/pack?runs={run['id']}").json()
    data["runs"][0]["suite_version"] = "99"
    data["runs"][0]["suite_hash"] = "otro"
    new_id = c.post("/api/runs/import", content=json.dumps(data)).json()["imported"][0]
    cmp = c.get(f"/api/compare?runs={run['id']},{new_id}").json()
    assert cmp["comparability"]["level"] == "no"


def test_paquetes_invalidos(lab):
    c, _ = lab()
    run = make_run(c, endpoint_ready(c))
    good = c.get(f"/api/runs/pack?runs={run['id']}").json()
    post = lambda body: c.post("/api/runs/import", content=body)  # noqa: E731
    assert post("no es json").status_code == 422
    assert post(json.dumps({"format": "otro"})).status_code == 422
    assert post(json.dumps({**good, "version": 2})).status_code == 422
    assert post(json.dumps({**good, "runs": []})).status_code == 422
    bad = copy.deepcopy(good)
    bad["runs"][0]["status"] = "running"
    assert post(json.dumps(bad)).status_code == 422
    bad = copy.deepcopy(good)
    del bad["runs"][0]["suite"]
    assert post(json.dumps(bad)).status_code == 422
    assert c.get("/api/runs/pack?runs=99999").status_code == 404
    assert c.get("/api/runs/pack?runs=abc").status_code == 422
