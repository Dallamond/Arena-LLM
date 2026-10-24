"""Ranking acumulado por paquete: mismo hash, calidad absoluta primero, sin mezclar versiones."""

from server.ranking import pack_ranking
from tests.server.test_compare import GPU_B, run

PACK = {"id": "duelo", "nombre": "Duelo", "hash": "h1", "suite": "qa", "graded": True}


def qrun(rid, accuracy=None, correct=None, total=12, **kw):
    r = run(rid, **kw)
    if accuracy is not None:
        r["summary"]["quality"] = {"accuracy_pct": accuracy, "correct": correct, "total": total}
    return r


def battle(bid, runs, hash="h1", status="done", pack="duelo"):
    return {
        "id": bid,
        "status": status,
        "created_at": 1.0,
        "params": {"pack": {"id": pack, "hash": hash}},
        "sides": [{"side": "AB"[i], "run_id": r["id"]} for i, r in enumerate(runs)],
    }


def rank(battles, runs):
    return pack_ranking(PACK, battles, {r["id"]: r for r in runs})


def test_ordena_por_calidad_media_y_agrupa_por_modelo_y_equipo():
    rs = [
        qrun(1, 75, 9, model="a.gguf"),
        qrun(2, 50, 6, model="b.gguf"),
        qrun(3, 91.7, 11, model="a.gguf"),  # el mismo modelo en otra batalla
        qrun(4, 33, 4, model="c.gguf"),
    ]
    out = rank([battle(10, rs[:2]), battle(11, [rs[2], rs[3]])], rs)
    assert [r["model"] for r in out["rows"]] == ["a.gguf", "b.gguf", "c.gguf"]
    a = out["rows"][0]
    assert a["battles"] == 2 and a["accuracy_mean"] == (75 + 91.7) / 2
    assert (a["accuracy_best"], a["correct"], a["total"]) == (91.7, 11, 12)
    assert [r["rank"] for r in out["rows"]] == [1, 2, 3] and out["by_quality"] is True
    assert out["battles"] == 2 and a["last_battle_id"] == 11


def test_no_mezcla_versiones_ni_cuenta_batallas_sin_terminar():
    rs = [qrun(1, 80, 10, model="a.gguf"), qrun(2, 20, 2, model="b.gguf")]
    out = rank(
        [battle(1, rs, hash="viejo"), battle(2, rs, status="running"), battle(3, rs, pack="otro")],
        rs,
    )
    assert out["rows"] == [] and out["other_versions"] == 1 and out["battles"] == 0


def test_el_mismo_modelo_en_otra_gpu_es_otra_fila():
    rs = [qrun(1, 70, 8, model="a.gguf"), qrun(2, 60, 7, model="a.gguf", gpu=GPU_B)]
    out = rank([battle(1, rs)], rs)
    assert len(out["rows"]) == 2 and {r["devices"] for r in out["rows"]} == {"RTX 3060", "M40"}


def test_sin_calidad_manda_la_velocidad_y_no_se_inventan_aciertos():
    rs = [run(1, model="lento.gguf", tps=10.0), run(2, model="rapido.gguf", tps=50.0)]
    out = rank([battle(1, rs)], rs)
    assert [r["model"] for r in out["rows"]] == ["rapido.gguf", "lento.gguf"]
    assert out["by_quality"] is False
    assert all(r["accuracy_mean"] is None and r["correct"] is None for r in out["rows"])


def test_empate_comparte_puesto():
    rs = [
        qrun(1, 60, 7, model="a.gguf"),
        qrun(2, 60, 7, model="b.gguf", tps=5.0),
        qrun(3, 10, 1, model="c.gguf"),
    ]
    out = rank([battle(1, rs[:2]), battle(2, rs[2:])], rs)
    assert [r["rank"] for r in out["rows"]] == [1, 1, 3]  # a y b empatan en calidad: la velocidad solo ordena


def test_run_incompleto_no_cuenta():
    rs = [qrun(1, 80, 10, model="a.gguf"), qrun(2, 20, 2, model="b.gguf", status="cancelled")]
    out = rank([battle(1, rs)], rs)
    assert [r["model"] for r in out["rows"]] == ["a.gguf"]
