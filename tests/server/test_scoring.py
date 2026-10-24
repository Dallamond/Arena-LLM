"""Nota 0-100 por run: calidad absoluta, velocidad/eficiencia relativas, sin inventar datos."""

import pytest

from server.scoring import DEFAULT_WEIGHTS, clean_weights, score_runs


def m(**kw):
    base = {
        "accuracy": None,
        "tps": None,
        "ttft": None,
        "tokens_per_wh": None,
        "tps_per_gib": None,
        "throttle": None,
        "degradation": None,
    }
    return {**base, **kw}


def test_un_solo_run_no_puntua():
    out = score_runs([m(tps=30)])
    assert out["scores"] == [] and out["winner"] is None


def test_calidad_absoluta_y_velocidad_relativa():
    out = score_runs(
        [m(accuracy=80, tps=40, ttft=0.5, tokens_per_wh=800), m(accuracy=60, tps=20, ttft=1.0, tokens_per_wh=400)]
    )
    a, b = out["scores"]
    assert a["dims"]["quality"] == 80 and b["dims"]["quality"] == 60  # absoluta
    assert a["dims"]["speed"] == pytest.approx(100) and b["dims"]["speed"] == pytest.approx(50)
    assert a["dims"]["efficiency"] == pytest.approx(100) and b["dims"]["efficiency"] == pytest.approx(50)
    assert a["rank"] == 1 and b["rank"] == 2 and out["winner"] == 0
    assert out["has_quality"] is True


def test_sin_calidad_se_omite_y_los_pesos_se_reparten():
    out = score_runs([m(tps=40, ttft=0.5), m(tps=20, ttft=1.0)])
    a = out["scores"][0]
    assert a["dims"]["quality"] is None and out["has_quality"] is False
    assert "quality" not in a["weights"]
    assert sum(a["weights"].values()) == pytest.approx(100)
    assert a["score"] == pytest.approx(100)  # solo cuenta la velocidad: no se penaliza lo no evaluable


def test_dato_en_un_solo_lado_no_da_referencia():
    out = score_runs([m(accuracy=70, tps=40), m(accuracy=50)])
    assert out["scores"][0]["dims"]["speed"] is None  # sin rival con dato no hay referencia
    assert out["scores"][1]["dims"]["speed"] is None


def test_eficiencia_cae_a_tps_por_gib_sin_potencia():
    out = score_runs([m(tps_per_gib=4.0), m(tps_per_gib=2.0)])
    assert [s["dims"]["efficiency"] for s in out["scores"]] == [pytest.approx(100), pytest.approx(50)]


def test_estabilidad_penaliza_throttling_y_degradacion():
    out = score_runs([m(throttle=22, degradation=5), m(throttle=0, degradation=-3)])
    assert out["scores"][0]["dims"]["stability"] == pytest.approx(73)
    assert out["scores"][1]["dims"]["stability"] == pytest.approx(100)  # mejorar no suma por encima de 100


def test_nunca_inventa_ceros():
    out = score_runs([m(), m()])
    assert all(s["score"] is None and s["rank"] is None for s in out["scores"])
    assert out["winner"] is None and out["dimensions"] == []


def test_empate_en_cabeza_sin_ganador_unico():
    out = score_runs([m(accuracy=70.0), m(accuracy=70.4), m(accuracy=40)])
    assert out["scores"][0]["rank"] == 1 and out["scores"][1]["rank"] == 1 and out["scores"][2]["rank"] == 3
    assert out["winner"] is None and out["tied"] == [0, 1]


def test_empate_no_se_encadena():
    out = score_runs([m(accuracy=70.0), m(accuracy=69.2), m(accuracy=68.4)])
    assert [s["rank"] for s in out["scores"]] == [1, 1, 3]  # 70→68,4 son 1,6 puntos: no es empate con el líder


def test_run_incompleto_se_marca_partial():
    out = score_runs([m(accuracy=70), m(accuracy=60)], ["done", "cancelled"])
    assert [s["partial"] for s in out["scores"]] == [False, True]


def test_pesos_personalizados():
    runs = [m(accuracy=100, tps=10), m(accuracy=0, tps=20)]
    calidad = score_runs(runs, weights={"quality": 100, "speed": 0})
    assert calidad["winner"] == 0
    velocidad = score_runs(runs, weights={"quality": 0, "speed": 100})
    assert velocidad["winner"] == 1


def test_pesos_invalidos_vuelven_a_los_de_por_defecto():
    assert clean_weights(None) == DEFAULT_WEIGHTS
    assert clean_weights({"quality": -5, "x": 3}) == DEFAULT_WEIGHTS
    assert clean_weights({"quality": 0, "speed": 0}) == DEFAULT_WEIGHTS
    assert clean_weights({"quality": 2, "speed": "a"}) == {"quality": 2.0}
