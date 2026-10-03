"""Calculadora de encaje: modelos densos, híbridos, proyectores y veredictos."""

import pytest

from server.fit import MIB, FitError, FitParams, estimate, fit, gpus_from_state, ram_free_from_metrics

GIB = 1024 * MIB


def dense(n=4, layer=GIB, **kw):
    g = {
        "architecture": "llama",
        "general_type": "model",
        "embedding_length": 1024,
        "head_count": 8,
        "head_count_kv": 2,
        "vocab_size": 1000,
        "layout": {"blocks": [layer] * n, "token_embd": 100 * MIB, "output": 200 * MIB, "other": 0},
        "metadata": {"llama.feed_forward_length": 4096},
    }
    g.update(kw)
    return g


def test_kv_denso():
    est = estimate(dense(), FitParams(ctx=1000, ubatch=10))
    # 4 capas × 2 cabezas KV × (128 + 128) × 2 bytes × 1000 tokens
    assert est["kv"] == 4 * 2 * 256 * 2 * 1000
    assert est["kv_layers"] == 4 and est["recurrent"] == 0
    assert est["compute"] == 4 * 10 * (1000 + 4 * 1024 + 4096)
    assert est["weights"] == 4 * GIB + 300 * MIB


def test_kv_cuantizado_y_cabezas_por_capa():
    g = dense(head_count_kv=[2, 0, 2, 0])  # capas 1 y 3 sin atención
    est = estimate(g, FitParams(ctx=1000, kv_type="q8_0"))
    assert est["kv_layers"] == 2
    assert est["kv"] == int(2 * 256 * (34 / 32) * 1000) * 2


def test_hibrido_qwen35():
    meta = {
        "qwen35.full_attention_interval": 4,
        "qwen35.ssm.conv_kernel": 4,
        "qwen35.ssm.inner_size": 4096,
        "qwen35.ssm.state_size": 128,
        "qwen35.ssm.group_count": 16,
    }
    g = dense(n=8, architecture="qwen35", key_length=256, value_length=256, head_count_kv=4, metadata=meta)
    est = estimate(g, FitParams(ctx=1000, parallel=2))
    assert est["kv_layers"] == 2  # capas 3 y 7
    assert est["kv"] == 2 * 4 * 512 * 2 * 1000
    per_seq = (3 * (4096 + 2 * 16 * 128) + 128 * 4096) * 4
    assert est["recurrent"] == 6 * per_seq * 2
    assert any("híbrido" in n for n in est["notes"])


def test_proyector_y_sin_capas():
    assert estimate({"architecture": "clip", "general_type": "mmproj"}, FitParams())["kind"] == "mmproj"
    assert estimate({"architecture": "x", "layout": {}}, FitParams())["kind"] == "unsupported"
    assert fit({"kind": "mmproj"}, [], 1000)["verdict"] == "mmproj"


def test_dimensiones_ausentes_dan_sin_datos():
    est = estimate(dense(embedding_length=None), FitParams())
    assert est["kv"] is None and est["compute"] is None
    assert fit(est, [{"device_id": "g", "free_mib": 99999, "total_mib": 99999}], 99999)["verdict"] == "unknown"


def test_params_invalidos():
    with pytest.raises(FitError):
        estimate(dense(), FitParams(kv_type="q3"))


def _gpu(i, free, total=None):
    return {"device_id": f"g{i}", "name": f"GPU{i}", "free_mib": free, "total_mib": total or free}


P = FitParams(ctx=1000, ubatch=10, reserve_mib=100)


def test_veredicto_cabe_en_una():
    f = fit(estimate(dense(), P), [_gpu(0, 3000), _gpu(1, 6000)], 8000)
    assert f["verdict"] == "gpu" and f["label"] == "Cabe en GPU1" and f["ngl"] == 5
    assert [g["fits"] for g in f["gpus"]] == [False, True]


def test_veredicto_repartido():
    f = fit(estimate(dense(), P), [_gpu(0, 2800), _gpu(1, 2800)], 8000)
    assert f["verdict"] == "split"


def test_veredicto_desborda_a_ram_con_ngl():
    f = fit(estimate(dense(), P), [_gpu(0, 2600)], 8000)
    assert f["verdict"] == "ram" and f["ngl"] == 2  # caben las 2 últimas capas
    assert f["ram_need"] > 2 * GIB


def test_veredicto_no_cabe_y_pista_gpu_vacia():
    f = fit(estimate(dense(), P), [_gpu(0, 1000, total=8000)], 500)
    assert f["verdict"] == "no" and "vacía" in f["hint"]


def test_solo_cpu_y_ram_sin_datos():
    est = estimate(dense(), P)
    assert fit(est, [], 8000)["verdict"] == "cpu"
    assert fit(est, [], None)["verdict"] == "unknown"


def test_estado_del_equipo():
    info = {"devices": [{"device_id": "g0", "kind": "gpu", "name": "A"}, {"device_id": "c", "kind": "cpu"}]}
    metrics = {"devices": {"g0": {"mem_total_mib": 12000, "mem_used_mib": 2000}}, "ram": {"total_mib": 16000}}
    assert gpus_from_state(info, metrics) == [{"device_id": "g0", "name": "A", "total_mib": 12000, "free_mib": 10000}]
    assert ram_free_from_metrics(metrics) is None  # used ausente → sin datos, no 0
    metrics["devices"]["g0"]["mem_used_mib"] = None
    assert gpus_from_state(info, metrics)[0]["free_mib"] is None
