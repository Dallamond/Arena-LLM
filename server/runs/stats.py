"""Cálculos del resumen de un run (funciones puras, con tests).

Regla: si no hay datos para una métrica, el resultado es None ("sin datos"),
nunca 0. La potencia es la de placa que reporta el driver, no la del enchufe.
"""

import math
import statistics
from collections.abc import Iterable, Sequence
from typing import Any

#: Bits de la máscara de clocks event reasons que cuentan como throttling
#: (potencia y térmico; no reposo ni ajustes de aplicación). Igual que agent/throttle.py.
THROTTLING_BITS = 0x004 | 0x008 | 0x020 | 0x040 | 0x080
DEGRADATION_MIN_S = 30.0
DEGRADATION_FRACTION = 0.2


def _nums(values: Iterable[Any]) -> list[float]:
    return [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]


def describe(values: Iterable[Any]) -> dict[str, float | None]:
    v = sorted(_nums(values))
    if not v:
        return {"n": 0, "mean": None, "median": None, "p10": None, "min": None, "max": None, "std": None}
    p10 = v[0] if len(v) == 1 else statistics.quantiles(v, n=10, method="inclusive")[0]
    return {
        "n": len(v),
        "mean": statistics.fmean(v),
        "median": statistics.median(v),
        "p10": p10,
        "min": v[0],
        "max": v[-1],
        "std": statistics.stdev(v) if len(v) > 1 else 0.0,
    }


def energy_wh(points: Sequence[tuple[float, Any]]) -> float | None:
    """Integral trapezoidal de la potencia (W) en el tiempo (s) → Wh. Huecos (None) cortan la integral."""
    total = 0.0
    used = False
    for (t0, p0), (t1, p1) in zip(points, points[1:], strict=False):
        if not _nums([p0, p1]) or len(_nums([p0, p1])) < 2 or t1 <= t0:
            continue
        total += (float(p0) + float(p1)) / 2 * (t1 - t0)
        used = True
    return total / 3600 if used else None


def throttle_pct(masks: Iterable[Any]) -> float | None:
    vals = [int(m) for m in masks if isinstance(m, int) and not isinstance(m, bool)]
    if not vals:
        return None
    return 100.0 * sum(1 for m in vals if m & THROTTLING_BITS) / len(vals)


def degradation_pct(series: Sequence[tuple[float, float]]) -> float | None:
    """Caída de t/s entre el primer 20 % y el último 20 % del tiempo (runs ≥ 30 s).

    Positivo = más lento al final. Solo cuentan los segundos con tokens.
    """
    pts = [(t, v) for t, v in series if isinstance(v, (int, float)) and v > 0]
    if len(pts) < 5:
        return None
    t0, t1 = pts[0][0], pts[-1][0]
    span = t1 - t0
    if span < DEGRADATION_MIN_S:
        return None
    first = [v for t, v in pts if t <= t0 + span * DEGRADATION_FRACTION]
    last = [v for t, v in pts if t >= t1 - span * DEGRADATION_FRACTION]
    if not first or not last:
        return None
    a, b = statistics.fmean(first), statistics.fmean(last)
    return 100.0 * (a - b) / a if a > 0 else None


def device_summary(samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Resumen de un dispositivo a partir de sus muestras [{t, phase, data}]."""
    base = [s for s in samples if s["phase"] == "reposo"]
    load = [s for s in samples if s["phase"] == "carga"]

    def series(rows, key):
        return [(s["t"], s["data"].get(key)) for s in rows]

    def vals(rows, key):
        return _nums(s["data"].get(key) for s in rows)

    temps_load = vals(load, "temp_c")
    temp_idle = statistics.fmean(vals(base, "temp_c")) if vals(base, "temp_c") else None
    temp_max = max(temps_load) if temps_load else None
    power_load = vals(load, "power_w")
    clocks = vals(load, "clock_sm_mhz")
    return {
        "temp_idle_c": temp_idle,
        "temp_mean_c": statistics.fmean(temps_load) if temps_load else None,
        "temp_max_c": temp_max,
        "temp_rise_c": temp_max - temp_idle if temp_max is not None and temp_idle is not None else None,
        "power_idle_w": statistics.fmean(vals(base, "power_w")) if vals(base, "power_w") else None,
        "power_mean_w": statistics.fmean(power_load) if power_load else None,
        "power_max_w": max(power_load) if power_load else None,
        "energy_wh": energy_wh(series(load, "power_w")),
        "util_mean_pct": statistics.fmean(vals(load, "util_gpu_pct")) if vals(load, "util_gpu_pct") else None,
        "vram_peak_mib": max(vals(load + base, "mem_used_mib")) if vals(load + base, "mem_used_mib") else None,
        "clock_sm_mean_mhz": statistics.fmean(clocks) if clocks else None,
        "clock_sm_min_mhz": min(clocks) if clocks else None,
        "throttle_pct": throttle_pct(s["data"].get("throttle_mask") for s in load),
        "cpu_util_mean_pct": statistics.fmean(vals(load, "util_pct")) if vals(load, "util_pct") else None,
        "n_samples": len(load),
    }


def run_summary(
    items: Sequence[dict[str, Any]],
    tps_series: Sequence[dict[str, Any]],
    samples: Sequence[dict[str, Any]],
    load_window: tuple[float | None, float | None],
) -> dict[str, Any]:
    ok = [i for i in items if not i.get("error")]
    m = [i.get("metrics") or {} for i in ok]
    tokens = sum(int(x.get("completion_tokens") or 0) for x in m)
    by_dev: dict[str, list[dict[str, Any]]] = {}
    for s in samples:
        by_dev.setdefault(s["device_id"], []).append(s)
    devices = {d: device_summary(rows) for d, rows in by_dev.items()}
    energy = [v["energy_wh"] for v in devices.values() if v.get("energy_wh") is not None]
    total_energy = sum(energy) if energy else None
    t0, t1 = load_window
    series = [(p["t"], p["tps"]) for p in tps_series]
    agg = [p["tps"] for p in tps_series if p["tps"] > 0]
    return {
        "requests": len(items),
        "requests_ok": len(ok),
        "requests_error": len(items) - len(ok),
        "completion_tokens": tokens,
        "prompt_tokens": sum(int(x.get("prompt_tokens") or 0) for x in m),
        "duration_s": (t1 - t0) if t0 is not None and t1 is not None else None,
        "tps_client": describe(x.get("tps_client") for x in m),
        "tps_server": describe(x.get("tps_server") for x in m),
        "pp_server": describe(x.get("pp_server") for x in m),
        "ttft_s": describe(x.get("ttft_s") for x in m),
        "latency_s": describe(x.get("latency_s") for x in m),
        "tps_aggregate": describe(agg),
        "degradation_pct": degradation_pct(series),
        "energy_wh": total_energy,
        "tokens_per_wh": tokens / total_energy if total_energy else None,
        "wh_per_1000_tokens": 1000 * total_energy / tokens if total_energy and tokens else None,
        "devices": devices,
    }
