import pytest

from server.runs import stats


def test_describe():
    d = stats.describe([10, 20, 30, None, float("nan"), "x"])
    assert d["n"] == 3 and d["mean"] == 20 and d["median"] == 20 and d["min"] == 10 and d["max"] == 30
    assert stats.describe([])["mean"] is None
    assert stats.describe([5])["std"] == 0.0


def test_energia_trapezoidal():
    # 100 W constantes durante 36 s = 1 Wh
    pts = [(float(t), 100.0) for t in range(0, 37)]
    assert stats.energy_wh(pts) == pytest.approx(1.0)
    # rampa 0 → 200 W en 36 s = media 100 W → 1 Wh
    assert stats.energy_wh([(0.0, 0.0), (36.0, 200.0)]) == pytest.approx(1.0)


def test_energia_con_huecos_y_sin_datos():
    pts = [(0.0, 100.0), (18.0, 100.0), (19.0, None), (20.0, 100.0), (38.0, 100.0)]
    assert stats.energy_wh(pts) == pytest.approx(1.0)  # el hueco no se inventa
    assert stats.energy_wh([(0.0, None), (1.0, None)]) is None
    assert stats.energy_wh([]) is None


def test_throttling_ignora_reposo():
    assert stats.throttle_pct([0x1, 0x1, 0x20, 0x0]) == 25.0
    assert stats.throttle_pct([None, None]) is None


def test_degradacion():
    flat = [(float(t), 40.0) for t in range(60)]
    assert stats.degradation_pct(flat) == pytest.approx(0.0)
    falling = [(float(t), 40.0 if t < 30 else 30.0) for t in range(60)]
    assert stats.degradation_pct(falling) == pytest.approx(25.0)
    assert stats.degradation_pct([(float(t), 40.0) for t in range(20)]) is None  # < 30 s
    assert stats.degradation_pct([]) is None


def test_resumen_de_dispositivo():
    rows = [
        {"t": float(t), "phase": "reposo", "data": {"temp_c": 40, "power_w": 20, "mem_used_mib": 1000}}
        for t in range(5)
    ]
    rows += [
        {"t": 5.0 + t, "phase": "carga",
         "data": {"temp_c": 60 + t, "power_w": 150, "throttle_mask": 0x20 if t > 7 else 0,
                  "mem_used_mib": 8000, "clock_sm_mhz": 1800, "util_gpu_pct": 99}}
        for t in range(10)
    ]  # fmt: skip
    s = stats.device_summary(rows)
    assert s["temp_idle_c"] == 40 and s["temp_max_c"] == 69 and s["temp_rise_c"] == 29
    assert s["power_idle_w"] == 20 and s["power_mean_w"] == 150
    assert s["energy_wh"] == pytest.approx(150 * 9 / 3600)
    assert s["throttle_pct"] == 20.0
    assert s["vram_peak_mib"] == 8000
    assert s["n_samples"] == 10


def test_resumen_de_run():
    items = [
        {
            "metrics": {
                "completion_tokens": 100,
                "prompt_tokens": 10,
                "tps_client": 40.0,
                "tps_server": 41.0,
                "ttft_s": 0.2,
            }
        },
        {
            "metrics": {
                "completion_tokens": 100,
                "prompt_tokens": 10,
                "tps_client": 30.0,
                "tps_server": 31.0,
                "ttft_s": 0.4,
            }
        },
        {"metrics": {}, "error": "HTTP 400"},
    ]
    samples = [{"t": float(t), "phase": "carga", "device_id": "g", "data": {"power_w": 100.0}} for t in range(37)]
    tps = [{"t": float(t), "tokens": 40, "tps": 40.0} for t in range(5)]
    s = stats.run_summary(items, tps, samples, (0.0, 36.0))
    assert (s["requests"], s["requests_ok"], s["requests_error"]) == (3, 2, 1)
    assert s["completion_tokens"] == 200
    assert s["tps_client"]["mean"] == 35.0
    assert s["energy_wh"] == pytest.approx(1.0)
    assert s["tokens_per_wh"] == pytest.approx(200.0)
    assert s["wh_per_1000_tokens"] == pytest.approx(5.0)
    assert s["duration_s"] == 36.0


def test_resumen_sin_telemetria_no_inventa_energia():
    s = stats.run_summary([{"metrics": {"completion_tokens": 10}}], [], [], (None, None))
    assert s["energy_wh"] is None and s["tokens_per_wh"] is None and s["duration_s"] is None


def test_peticion_cortada_no_es_error():
    items = [
        {"metrics": {"completion_tokens": 50, "tps_client": 30.0}},
        {"metrics": {}, "error": stats.CUT_MSG},
    ]
    s = stats.run_summary(items, [], [], (0.0, 10.0))
    assert (s["requests_ok"], s["requests_error"], s["requests_cut"]) == (1, 0, 1)
    assert s["tps_client"]["n"] == 1


def test_pico_de_ram():
    rows = [{"t": float(t), "phase": "carga", "data": {"used_mib": 1000 + t}} for t in range(5)]
    assert stats.device_summary(rows)["ram_used_peak_mib"] == 1004
