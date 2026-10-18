"""Resumen de calidad de un run a partir de la nota (`eval`) de cada ítem.

Funciones puras. Un valor sin datos es None, nunca 0. Un ítem que falló por un error del servidor
(p. ej. contexto excedido) cuenta como no acertado y queda anotado, porque en `contexto` eso es
justo el límite que se quiere conocer.
"""

import bisect
import statistics
from collections.abc import Sequence
from typing import Any

from server.runs.stats import CUT_MSG, describe

GRADED_KINDS = ("qa", "code", "needle")


def _pct(num: int, den: int) -> float | None:
    return 100.0 * num / den if den else None


def _vram_by_item(items: Sequence[dict[str, Any]], samples: Sequence[dict[str, Any]]) -> dict[int, float | None]:
    """VRAM máxima usada (MiB, la mayor entre las GPU) mientras duró cada ítem."""
    gpu = [s for s in samples if isinstance(s["data"].get("mem_used_mib"), (int, float))]
    times = [s["t"] for s in gpu]
    out: dict[int, float | None] = {}
    for it in items:
        t0, t1 = it.get("started_at"), it.get("finished_at")
        if t0 is None or t1 is None or not gpu:
            out[it["idx"]] = None
            continue
        lo, hi = bisect.bisect_left(times, t0), bisect.bisect_right(times, t1)
        window = gpu[lo:hi] or gpu[max(0, hi - 1) : hi]  # sin lectura dentro: la última anterior
        out[it["idx"]] = max((s["data"]["mem_used_mib"] for s in window), default=None)
    return out


def _baseline_vram(samples: Sequence[dict[str, Any]]) -> float | None:
    vals = [
        s["data"]["mem_used_mib"]
        for s in samples
        if s["phase"] == "reposo" and isinstance(s["data"].get("mem_used_mib"), (int, float))
    ]
    return min(vals) if vals else None


def _graded(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        i for i in items if (i.get("eval") or {}).get("kind") in GRADED_KINDS and i.get("error") != CUT_MSG
    ]


def _accuracy_block(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    graded = _graded(items)
    correct = sum(1 for i in graded if i["eval"].get("correct"))
    failed = sum(1 for i in graded if i["eval"].get("failed"))
    return {
        "total": len(graded),
        "correct": correct,
        "failed": failed,  # errores del servidor (no cuentan como acierto)
        "accuracy_pct": _pct(correct, len(graded)),
        "truncated": sum(1 for i in graded if i["eval"].get("truncated")),
    }


def _qa(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out = _accuracy_block(items)
    graded = _graded(items)
    out["format_ok_pct"] = _pct(sum(1 for i in graded if i["eval"].get("format_ok")), len(graded))
    return out


def _code(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out = _accuracy_block(items)
    out["pass_at_1_pct"] = out["accuracy_pct"]  # una sola muestra por problema y repetición
    levels: dict[int, dict[str, int]] = {}
    for i in _graded(items):
        lv = int(i["eval"].get("level") or 0)
        d = levels.setdefault(lv, {"total": 0, "correct": 0})
        d["total"] += 1
        d["correct"] += 1 if i["eval"].get("correct") else 0
    out["by_level"] = {str(k): v for k, v in sorted(levels.items())}
    out["no_code"] = sum(1 for i in _graded(items) if i["eval"].get("status") == "sin código")
    out["timeouts"] = sum(1 for i in _graded(items) if i["eval"].get("status") == "timeout")
    return out


def _needle(items: Sequence[dict[str, Any]], samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out = _accuracy_block(items)
    vram = _vram_by_item(items, samples)
    base = _baseline_vram(samples)
    rows = []
    for i in _graded(items):
        ev, m = i["eval"], i.get("metrics") or {}
        peak = vram.get(i["idx"])
        rows.append(
            {
                "name": i.get("name"),
                "size": ev.get("size"),
                "depth": ev.get("depth"),
                "correct": bool(ev.get("correct")),
                "failed": bool(ev.get("failed")),
                "note": ev.get("note"),
                "prompt_tokens": m.get("prompt_tokens"),
                "ttft_s": m.get("ttft_s"),
                "pp_server": m.get("pp_server"),
                "vram_mib": peak,
                "vram_delta_mib": peak - base if peak is not None and base is not None else None,
            }
        )
    by_size: dict[int, dict[str, Any]] = {}
    for r in rows:
        size = int(r["size"])
        d = by_size.setdefault(size, {"size": size, "total": 0, "correct": 0, "failed": 0, "rows": []})
        d["total"] += 1
        d["correct"] += 1 if r["correct"] else 0
        d["failed"] += 1 if r["failed"] else 0
        d["rows"].append(r)
    sizes = []
    for size in sorted(by_size):
        d = by_size[size]
        rows_ok = [r for r in d.pop("rows") if not r["failed"]]
        d["prompt_tokens"] = statistics.median([r["prompt_tokens"] for r in rows_ok if r["prompt_tokens"]]) if any(
            r["prompt_tokens"] for r in rows_ok
        ) else None
        d["pp_server"] = describe(r["pp_server"] for r in rows_ok)["median"]
        d["ttft_s"] = describe(r["ttft_s"] for r in rows_ok)["median"]
        peaks = [r["vram_mib"] for r in rows_ok if r["vram_mib"] is not None]
        d["vram_mib"] = max(peaks) if peaks else None
        deltas = [r["vram_delta_mib"] for r in rows_ok if r["vram_delta_mib"] is not None]
        d["vram_delta_mib"] = max(deltas) if deltas else None
        d["accuracy_pct"] = _pct(d["correct"], d["total"])
        sizes.append(d)
    ok_sizes = [d["size"] for d in sizes if d["total"] and d["correct"] == d["total"]]
    failed_sizes = [d["size"] for d in sizes if d["failed"]]
    out.update(
        rows=rows,
        by_size=sizes,
        max_size_ok=max(ok_sizes) if ok_sizes else None,
        first_failed_size=min(failed_sizes) if failed_sizes else None,
    )
    return out


def _concurrency(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    levels: dict[int, list[dict[str, Any]]] = {}
    for i in items:
        lv = (i.get("eval") or {}).get("level")
        if isinstance(lv, int) and i.get("error") != CUT_MSG:
            levels.setdefault(lv, []).append(i)
    rows = []
    for lv in sorted(levels):
        its = levels[lv]
        ok = [i for i in its if not i.get("error")]
        starts = [i["started_at"] for i in its if i.get("started_at") is not None]
        ends = [i["finished_at"] for i in its if i.get("finished_at") is not None]
        wall = max(ends) - min(starts) if starts and ends else None
        tokens = sum(int((i.get("metrics") or {}).get("completion_tokens") or 0) for i in ok)
        per = describe((i.get("metrics") or {}).get("tps_client") for i in ok)
        rows.append(
            {
                "level": lv,
                "requests": len(its),
                "errors": len(its) - len(ok),
                "wall_s": wall,
                "tokens": tokens,
                "tps_aggregate": tokens / wall if wall and tokens else None,
                "tps_per_request": per["median"],
                "ttft_s": describe((i.get("metrics") or {}).get("ttft_s") for i in ok)["median"],
            }
        )
    single = next((r["tps_aggregate"] for r in rows if r["level"] == 1 and r["tps_aggregate"]), None)
    for r in rows:
        agg = r["tps_aggregate"]
        r["scaling"] = agg / single if agg and single else None  # ×1 = no escala
        r["efficiency_pct"] = 100.0 * agg / (single * r["level"]) if agg and single else None
    best = max((r for r in rows if r["tps_aggregate"]), key=lambda r: r["tps_aggregate"], default=None)
    return {"levels": rows, "best_level": best["level"] if best else None,
            "best_tps_aggregate": best["tps_aggregate"] if best else None}  # fmt: skip


def quality_summary(suite_id: str, items: Sequence[dict[str, Any]], samples: Sequence[dict[str, Any]]) -> dict | None:
    """Bloque `quality` del resumen; None si la suite no tiene evaluación."""
    if suite_id == "qa":
        return {"suite": suite_id, **_qa(items)}
    if suite_id == "codigo":
        return {"suite": suite_id, **_code(items)}
    if suite_id == "contexto":
        return {"suite": suite_id, **_needle(items, samples)}
    if suite_id == "concurrencia":
        return {"suite": suite_id, **_concurrency(items)}
    return None
