"""Comparar runs: comparabilidad, diff de configuración, métricas, veredictos y matriz de respuestas."""

from server import compare

GPU_A, GPU_B = "nvidia:A", "nvidia:B"


def run(
    rid,
    *,
    suite="libre",
    version="1",
    status="done",
    model="m7b.gguf",
    quant="Q8_0",
    gpu=GPU_A,
    build="b1",
    ctx=4096,
    params=None,
    tps=30.0,
    ttft=0.5,
    temp=60.0,
    energy=1.0,
    tokens=1000,
    side=None,
):
    params = {
        "prompts": ["p1", "p2"],
        "temperature": 0,
        "seed": 42,
        "max_tokens": 256,
        "baseline_s": 5,
        **(params or {}),
    }
    return {
        "id": rid,
        "kind": "free",
        "suite": suite,
        "suite_version": version,
        "suite_hash": "h",
        "status": status,
        "label": None,
        "side": side,
        "battle_id": None,
        "started_at": 100.0,
        "params": params,
        "servers_snapshot": {
            "base_url": "http://127.0.0.1:8080",
            "model_file": model,
            "derived": {
                "model_path": f"/m/{model}",
                "model_ftype": quant,
                "build_info": build,
                "n_ctx_slot": ctx,
                "total_slots": 1,
            },
            "flags": {"ngl": 99, "port": 8080},
            "devices": [{"device_id": gpu}],
        },
        "host_snapshot": {
            "name": "pc",
            "devices": [{"device_id": GPU_A, "name": "RTX 3060"}, {"device_id": GPU_B, "name": "M40"}],
            "thresholds": {gpu: {"warn": 80, "crit": 90}},
        },
        "summary": {
            "completion_tokens": tokens,
            "requests_ok": 2,
            "tps_client": {"median": tps},
            "tps_server": {"median": tps},
            "pp_server": {"median": 900.0},
            "ttft_s": {"median": ttft},
            "degradation_pct": None,
            "duration_s": 30.0,
            "thresholds": {gpu: {"warn": 80, "crit": 90}},
            "phases": {"load_start": 105.0, "load_end": 135.0},
            "devices": {
                gpu: {
                    "temp_max_c": temp,
                    "temp_rise_c": 10.0,
                    "power_mean_w": 150.0,
                    "throttle_pct": 0.0,
                    "vram_peak_mib": 8000,
                    "energy_wh": energy,
                },
                # la otra GPU del equipo no cuenta para este run
                (GPU_B if gpu == GPU_A else GPU_A): {"temp_max_c": 99.0, "energy_wh": 50.0},
            },
        },
    }


def items_for(*runs, responses=None):
    out = {}
    for r in runs:
        out[r["id"]] = [
            {
                "idx": i,
                "prompt": p,
                "name": f"prompt {i + 1}",
                "response": (responses or {}).get((r["id"], p), f"resp {r['id']} {p}"),
                "metrics": {"completion_tokens": 10, "tps_client": 20.0, "ttft_s": 0.3, "finish_reason": "stop"},
                "error": None,
            }
            for i, p in enumerate(r["params"]["prompts"])
        ]
    return out


def build(*runs):
    return compare.build(list(runs), items_for(*runs), {}, {})


def test_un_solo_factor_es_comparable():
    out = build(run(1), run(2, model="m14b.gguf", quant="Q4_K_M"))
    assert out["comparability"]["level"] == "si"
    assert out["comparability"]["changes"] == ["modelo"]


def test_misma_configuracion_es_comparable_sin_cambios():
    out = build(run(1), run(2))
    assert out["comparability"]["level"] == "si" and out["comparability"]["changes"] == []


def test_varios_factores_a_la_vez_es_parcial():
    out = build(run(1), run(2, model="m14b.gguf", gpu=GPU_B))
    c = out["comparability"]
    assert c["level"] == "parcial"
    assert "modelo" in c["changes"] and "equipo/GPU" in c["changes"]
    assert any("varias cosas" in r for r in c["reasons"])


def test_parametro_distinto_cuenta_como_factor():
    out = build(run(1), run(2, params={"temperature": 0.7}))
    assert out["comparability"]["level"] == "si" and out["comparability"]["changes"] == ["parámetros de la prueba"]
    row = next(r for r in out["config_diff"] if r["key"] == "param:temperature")
    assert row["values"] == [0, 0.7] and not row["same"]
    # las fases no cuentan
    assert not any(r["key"] == "param:baseline_s" for r in out["config_diff"])


def test_otra_prueba_u_otra_version_no_es_comparable():
    assert build(run(1), run(2, suite="estres"))["comparability"]["level"] == "no"
    out = build(run(1), run(2, version="2"))
    assert out["comparability"]["level"] == "no" and "v1" in out["comparability"]["reasons"][0]


def test_prompts_distintos_o_run_incompleto_es_parcial():
    out = build(run(1), run(2, params={"prompts": ["p1", "otro"]}))
    assert out["comparability"]["level"] == "parcial"
    assert any("1 en común de 3" in r for r in out["comparability"]["reasons"])
    out = build(run(1), run(2, status="aborted"))
    assert out["comparability"]["level"] == "parcial"
    assert any("#2 abortado" in r for r in out["comparability"]["reasons"])


def test_metricas_solo_con_las_gpu_del_run_y_mejor_resaltado():
    out = build(run(1, tps=30, temp=60, energy=1.0), run(2, tps=45, temp=70, energy=2.0, gpu=GPU_B))
    rows = {r["key"]: r for r in out["metrics"]}
    assert rows["temp_max"]["values"] == [60, 70]  # no el 99 °C de la otra GPU
    assert rows["tps"]["best"] == [1] and rows["temp_max"]["best"] == [0]
    assert rows["tokens_per_wh"]["values"] == [1000.0, 500.0] and rows["tokens_per_wh"]["best"] == [0]
    assert rows["tokens"]["best"] == []  # sin "mejor" en las informativas


def test_veredictos_con_margen_y_sin_empates():
    out = build(run(1, tps=30, ttft=0.5), run(2, tps=45, ttft=0.5))
    v = {x["key"]: x for x in out["verdicts"]}
    assert v["tps"]["run_index"] == 1 and round(v["tps"]["margin_pct"]) == 50
    assert "ttft" not in v  # empate
    out = build(run(1, tps=30.0), run(2, tps=30.2))
    assert "tps" not in {x["key"] for x in out["verdicts"]}  # < 1 %: ruido, sin ganador


def test_matriz_de_respuestas_alinea_por_prompt_y_repeticion():
    a, b = run(1, params={"prompts": ["p1", "p2", "p1"]}), run(2, params={"prompts": ["p2", "p1"]})
    m = compare.item_matrix([a, b], items_for(a, b))
    assert [(r["prompt"], r["rep"]) for r in m] == [("p1", 0), ("p2", 0), ("p1", 1)]
    assert m[0]["cells"][0]["response"] == "resp 1 p1" and m[0]["cells"][1]["response"] == "resp 2 p1"
    assert m[2]["cells"][1] is None  # el run 2 no repitió p1


def test_un_solo_run_sirve_para_leer_respuestas():
    out = build(run(1))
    assert out["comparability"]["level"] is None and out["verdicts"] == []
    assert len(out["items"]) == 2 and out["items"][0]["cells"][0]["response"] == "resp 1 p1"


def test_series_desde_el_inicio_de_la_carga_y_de_la_gpu_del_run():
    r = run(1, gpu=GPU_B)
    tps = [{"t": 104.0, "tps": 0.0}, {"t": 106.0, "tps": 30.0}]
    samples = [
        {"t": 106.0, "device_id": GPU_A, "data": {"temp_c": 50}},
        {"t": 107.0, "device_id": GPU_B, "data": {"temp_c": 65, "power_w": 120}},
    ]
    s = compare.series(r, tps, samples)
    assert s["tps"] == [{"t": 1.0, "v": 30.0}]
    assert s["temp"] == [{"t": 2.0, "v": 65}] and s["device"] == "M40"
