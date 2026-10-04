"""Comparar runs: insignia de comparabilidad, métricas, veredictos, diff de configuración,
respuestas por prompt y series superpuestas. Funciones puras sobre lo guardado en la BD.

Comparabilidad (la insignia habla de si la comparación es justa):
- **No comparables**: pruebas distintas (suite o versión).
- **Parcialmente**: prompts distintos, runs incompletos (detenidos, abortados, con error)
  o cambian varias cosas a la vez (p. ej. modelo y GPU): la diferencia no se puede
  atribuir a una sola causa.
- **Comparables**: misma prueba y cambia como mucho un factor, que es justo lo que se compara.

Las métricas de dispositivo se calculan solo con las GPU del propio run (las vigiladas):
en una batalla en paralelo en el mismo equipo cada lado se queda con su tarjeta.
"""

from typing import Any

from server.detect import config_view

LEVELS = {"si": "Comparables", "parcial": "Parcialmente comparables", "no": "No comparables"}
STATUS_TEXT = {"cancelled": "detenido", "aborted": "abortado", "error": "con error", "running": "en marcha"}
#: Parámetros que no cambian el resultado medido (fases y límites).
PARAMS_IGNORED = {"prompts", "baseline_s", "cooldown_s", "timeout_s", "model", "device_ids", "force"}
#: Factores de configuración: cada uno agrupa claves de `config_view` o del equipo.
FACTOR_LABEL = {
    "modelo": "modelo",
    "hardware": "equipo/GPU",
    "build": "build de llama.cpp",
    "contexto": "contexto/slots",
    "flags": "flags del servidor",
    "parametros": "parámetros de la prueba",
}
MAX_POINTS = 240
#: Diferencia por debajo de la cual un veredicto es empate (ruido de medida).
TIE_PCT = 1.0


def _title(run: dict[str, Any]) -> str:
    snap = run.get("servers_snapshot") or {}
    model = snap.get("model_file") or _file((run.get("params") or {}).get("model"))
    parts = [f"#{run['id']}"]
    if run.get("side"):
        parts.append(f"lado {run['side']}")
    if model:
        parts.append(model)
    return " · ".join(parts)


def _file(path: Any) -> str | None:
    if not isinstance(path, str) or not path:
        return None
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _gpu_ids(run: dict[str, Any]) -> list[str]:
    """GPU del run: las vigiladas (umbral térmico) o, si no hay, las del servidor."""
    watch = ((run.get("summary") or {}).get("thresholds") or {}) or (
        (run.get("host_snapshot") or {}).get("thresholds") or {}
    )
    if watch:
        return sorted(watch)
    snap = run.get("servers_snapshot") or {}
    return sorted(d["device_id"] for d in snap.get("devices") or [] if d.get("device_id"))


def _device_names(run: dict[str, Any]) -> dict[str, str]:
    devs = (run.get("host_snapshot") or {}).get("devices") or []
    return {d["device_id"]: d.get("name") or d["device_id"] for d in devs if d.get("device_id")}


def run_config(run: dict[str, Any]) -> dict[str, Any]:
    """Configuración comparable de un run (servidor + equipo + parámetros)."""
    snap = run.get("servers_snapshot") or {}
    host = (run.get("host_snapshot") or {}).get("host") or {}
    names = _device_names(run)
    view = config_view(snap) if snap else {}
    params = run.get("params") or {}
    cfg: dict[str, Any] = {
        "equipo": (run.get("host_snapshot") or {}).get("name") or host.get("hostname"),
        "gpus": [names.get(g, g) for g in _gpu_ids(run)],
        "modelo": _file(view.get("modelo")) or _file(params.get("model")),
        "cuantizacion": view.get("cuantizacion"),
        "build": view.get("build"),
        "ctx_por_slot": view.get("ctx_por_slot"),
        "slots": view.get("slots"),
    }
    for k, v in view.items():
        if k.startswith("flag:") and k not in ("flag:model", "flag:ctx_size", "flag:parallel"):
            cfg[k] = v
    for k, v in sorted(params.items()):
        if k not in PARAMS_IGNORED:
            cfg[f"param:{k}"] = v
    return cfg


def _factor(key: str) -> str:
    if key in ("modelo", "cuantizacion"):
        return "modelo"
    if key in ("equipo", "gpus"):
        return "hardware"
    if key == "build":
        return "build"
    if key in ("ctx_por_slot", "slots"):
        return "contexto"
    if key.startswith("param:"):
        return "parametros"
    return "flags"


def config_diff(configs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys: list[str] = []
    for c in configs:
        keys += [k for k in c if k not in keys]
    rows = []
    for k in keys:
        values = [c.get(k) for c in configs]
        rows.append({"key": k, "factor": _factor(k), "values": values, "same": all(v == values[0] for v in values)})
    return rows


def _prompt_sets(runs: list[dict[str, Any]], items: dict[int, list[dict[str, Any]]]) -> list[set[str]]:
    out = []
    for r in runs:
        ps = (r.get("params") or {}).get("prompts")
        if isinstance(ps, list):
            out.append(set(ps))
        else:
            out.append({i.get("prompt") for i in items.get(r["id"], []) if i.get("prompt")})
    return out


def comparability(
    runs: list[dict[str, Any]], diff: list[dict[str, Any]], items: dict[int, list[dict[str, Any]]]
) -> dict[str, Any]:
    if len(runs) < 2:
        return {"level": None, "label": "Un solo run", "reasons": [], "changes": []}
    reasons: list[str] = []
    level = "si"
    suites = sorted({r["suite"] for r in runs})
    versions = sorted({str(r.get("suite_version")) for r in runs})
    if len(suites) > 1:
        level = "no"
        reasons.append(f"Pruebas distintas: {', '.join(suites)}.")
    elif len(versions) > 1:
        level = "no"
        reasons.append(f"Versiones distintas de la prueba: {', '.join('v' + v for v in versions)}.")

    sets = _prompt_sets(runs, items)
    if any(sets) and level != "no":
        common = set.intersection(*sets) if all(sets) else set()
        union = set.union(*sets)
        if common != union:
            level = "parcial"
            reasons.append(f"Prompts distintos: {len(common)} en común de {len(union)}.")

    for r in runs:
        if r.get("status") != "done":
            if level == "si":
                level = "parcial"
            reasons.append(f"Run #{r['id']} {STATUS_TEXT.get(r.get('status'), r.get('status'))}: métricas incompletas.")

    changed = []
    for row in diff:
        if not row["same"] and row["factor"] not in changed:
            changed.append(row["factor"])
    if len(changed) >= 2 and level == "si":
        level = "parcial"
    if len(changed) >= 2:
        reasons.append(
            "Cambian varias cosas a la vez ("
            + ", ".join(FACTOR_LABEL[f] for f in changed)
            + "): la diferencia no se puede atribuir a una sola."
        )
    return {
        "level": level,
        "label": LEVELS[level],
        "reasons": reasons,
        "changes": [FACTOR_LABEL[f] for f in changed],
    }


# --- métricas -------------------------------------------------------------------


def _own_devices(run: dict[str, Any]) -> list[dict[str, Any]]:
    devs = ((run.get("summary") or {}).get("devices")) or {}
    ids = _gpu_ids(run)
    return [devs[d] for d in ids if d in devs]


def _max(vals: list[Any]) -> float | None:
    nums = [v for v in vals if isinstance(v, (int, float))]
    return max(nums) if nums else None


def _sum(vals: list[Any]) -> float | None:
    nums = [v for v in vals if isinstance(v, (int, float))]
    return sum(nums) if nums else None


def run_metrics(run: dict[str, Any]) -> dict[str, Any]:
    s = run.get("summary") or {}
    bench = s.get("bench") or {}
    own = _own_devices(run)
    energy = _sum([d.get("energy_wh") for d in own])
    tokens = s.get("completion_tokens")
    is_bench = run.get("kind") == "bench"
    return {
        "tps": (bench.get("best_tg") or {}).get("t_s") if is_bench else (s.get("tps_client") or {}).get("median"),
        "tps_server": None if is_bench else (s.get("tps_server") or {}).get("median"),
        "pp": (bench.get("best_pp") or {}).get("t_s") if is_bench else (s.get("pp_server") or {}).get("median"),
        "ttft": None if is_bench else (s.get("ttft_s") or {}).get("median"),
        "tokens": None if is_bench else tokens,
        "requests_ok": None if is_bench else s.get("requests_ok"),
        "degradation": s.get("degradation_pct"),
        "temp_max": _max([d.get("temp_max_c") for d in own]),
        "temp_rise": _max([d.get("temp_rise_c") for d in own]),
        "power_mean": _sum([d.get("power_mean_w") for d in own]),
        "throttle": _max([d.get("throttle_pct") for d in own]),
        "vram_peak": _sum([d.get("vram_peak_mib") for d in own]),
        "energy": energy,
        "tokens_per_wh": tokens / energy if isinstance(tokens, (int, float)) and tokens and energy else None,
        "duration": s.get("duration_s"),
    }


#: (clave, rótulo, unidad, mejor: "high" | "low" | None, decimales)
METRICS = (
    ("tps", "t/s generación (mediana; bench: mejor tg)", "t/s", "high", 1),
    ("tps_server", "t/s según el servidor (mediana)", "t/s", "high", 1),
    ("pp", "t/s procesado de prompt", "t/s", "high", 0),
    ("ttft", "TTFT (mediana)", "s", "low", 2),
    ("tokens", "tokens generados", "", None, 0),
    ("requests_ok", "peticiones correctas", "", None, 0),
    ("degradation", "degradación de t/s", "%", "low", 1),
    ("temp_max", "temperatura máxima", "°C", "low", 0),
    ("temp_rise", "subida de temperatura", "°C", "low", 0),
    ("power_mean", "potencia media de placa", "W", "low", 0),
    ("throttling", "throttling", "%", "low", 0),
    ("vram_peak", "VRAM pico", "MiB", None, 0),
    ("energy", "energía (GPU del run)", "Wh", None, 2),
    ("tokens_per_wh", "tokens por Wh", "tok/Wh", "high", 0),
    ("duration", "duración de la carga", "s", None, 0),
)


def metric_table(per_run: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for key, label, unit, better, digits in METRICS:
        src = "throttle" if key == "throttling" else key
        values = [m.get(src) for m in per_run]
        nums = [v for v in values if isinstance(v, (int, float))]
        best: list[int] = []
        if better and len(nums) >= 2 and len(set(nums)) > 1:
            target = max(nums) if better == "high" else min(nums)
            best = [i for i, v in enumerate(values) if v == target]
        if not nums:
            continue
        rows.append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "better": better,
                "digits": digits,
                "values": values,
                "best": best,
            }
        )
    return rows


VERDICTS = (
    ("tps", "Más rápido", "high"),
    ("ttft", "Responde antes", "low"),
    ("temp_max", "Más frío", "low"),
    ("tokens_per_wh", "Más eficiente", "high"),
)


def verdicts(per_run: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    if len(per_run) < 2:
        return out
    for key, title, better in VERDICTS:
        vals = [(i, m.get(key)) for i, m in enumerate(per_run) if isinstance(m.get(key), (int, float))]
        if len(vals) < 2:
            continue
        ordered = sorted(vals, key=lambda x: x[1], reverse=better == "high")
        (wi, wv), (_, second) = ordered[0], ordered[1]
        margin = abs(wv - second) / abs(second) * 100 if second else None
        if wv == second or (margin is not None and margin < TIE_PCT):
            continue  # empate (o diferencia dentro del ruido): sin ganador
        out.append(
            {"key": key, "title": title, "run_index": wi, "value": wv, "runner_up": second, "margin_pct": margin}
        )
    return out


# --- respuestas por prompt ----------------------------------------------------------


def item_matrix(runs: list[dict[str, Any]], items: dict[int, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Filas = (prompt, repetición), en el orden de aparición; columnas = runs."""
    order: list[tuple[str, int]] = []
    cells: dict[tuple[str, int], list[dict[str, Any] | None]] = {}
    for col, r in enumerate(runs):
        seen: dict[str, int] = {}
        for it in items.get(r["id"], []):
            prompt = it.get("prompt") or it.get("name") or f"#{it['idx']}"
            rep = seen.get(prompt, 0)
            seen[prompt] = rep + 1
            key = (prompt, rep)
            if key not in cells:
                order.append(key)
                cells[key] = [None] * len(runs)
            m = it.get("metrics") or {}
            cells[key][col] = {
                "response": it.get("response"),
                "reasoning": it.get("reasoning"),
                "error": it.get("error"),
                "tokens": m.get("completion_tokens"),
                "tps": m.get("tps_client"),
                "ttft": m.get("ttft_s"),
                "finish": m.get("finish_reason"),
            }
    return [{"prompt": p, "rep": rep, "cells": cells[(p, rep)]} for p, rep in order]


# --- series superpuestas --------------------------------------------------------------


def _downsample(points: list[dict[str, float]]) -> list[dict[str, float]]:
    if len(points) <= MAX_POINTS:
        return points
    step = len(points) / MAX_POINTS
    return [points[int(i * step)] for i in range(MAX_POINTS)]


def series(run: dict[str, Any], tps: list[dict[str, Any]], samples: list[dict[str, Any]]) -> dict[str, Any]:
    """t/s y, de la primera GPU del run, temperatura y potencia; tiempo desde el inicio de la carga."""
    phases = (run.get("summary") or {}).get("phases") or {}
    t0 = phases.get("load_start") or run.get("started_at") or 0
    out: dict[str, Any] = {"tps": _downsample([{"t": p["t"] - t0, "v": p["tps"]} for p in tps if p["t"] >= t0])}
    gpus = _gpu_ids(run)
    dev = gpus[0] if gpus else None
    for key, field in (("temp", "temp_c"), ("power", "power_w")):
        pts = [
            {"t": s["t"] - t0, "v": s["data"].get(field)}
            for s in samples
            if s["device_id"] == dev and isinstance((s.get("data") or {}).get(field), (int, float))
        ]
        out[key] = _downsample(pts)
    out["device"] = _device_names(run).get(dev, dev) if dev else None
    return out


def build(
    runs: list[dict[str, Any]],
    items: dict[int, list[dict[str, Any]]],
    tps: dict[int, list[dict[str, Any]]],
    samples: dict[int, list[dict[str, Any]]],
    bench_rows: dict[int, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    configs = [run_config(r) for r in runs]
    diff = config_diff(configs)
    per_run = [run_metrics(r) for r in runs]
    public = []
    for r, m in zip(runs, per_run, strict=True):
        public.append(
            {
                "id": r["id"],
                "title": _title(r),
                "label": r.get("label"),
                "kind": r.get("kind"),
                "suite": r.get("suite"),
                "suite_version": r.get("suite_version"),
                "suite_hash": r.get("suite_hash"),
                "status": r.get("status"),
                "battle_id": r.get("battle_id"),
                "side": r.get("side"),
                "started_at": r.get("started_at"),
                "base_url": (r.get("servers_snapshot") or {}).get("base_url"),
                "metrics": m,
                "bench_rows": len((bench_rows or {}).get(r["id"], [])),
            }
        )
    return {
        "runs": public,
        "comparability": comparability(runs, diff, items),
        "config_diff": diff,
        "metrics": metric_table(per_run),
        "verdicts": verdicts(per_run),
        "items": item_matrix(runs, items),
        "series": [series(r, tps.get(r["id"], []), samples.get(r["id"], [])) for r in runs],
    }
