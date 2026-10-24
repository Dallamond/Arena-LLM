"""Ranking acumulado de un paquete de batalla: qué modelo rinde mejor en la misma prueba (funciones puras).

Solo cuentan las batallas del paquete con **el mismo hash** (misma prueba, mismas preguntas, mismas opciones):
así los aciertos son comparables entre batallas y entre días. Las de otra versión del paquete se cuentan
aparte y no se mezclan. El criterio principal es la calidad absoluta (aciertos); sin calidad (pruebas
libres) manda la velocidad. Un valor sin datos es `None`, nunca 0.
"""

import statistics
from typing import Any

from server.compare import run_metrics, run_origin


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _median(values: list[float | None]) -> float | None:
    nums = [v for v in values if v is not None]
    return statistics.median(nums) if nums else None


def _entry(battle: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    origin = run_origin(run)
    m = run_metrics(run)
    snap = run.get("servers_snapshot") or {}
    return {
        "model": origin["model_name"] or "modelo desconocido",
        "quant": (snap.get("derived") or {}).get("model_ftype"),
        "devices": " + ".join(origin["device_names"]) or None,
        "host": origin["host_name"],
        "battle_id": battle["id"],
        "when": run.get("started_at") or battle.get("created_at"),
        "accuracy": _num(m.get("accuracy")),
        "correct": m.get("quality_correct"),
        "total": m.get("quality_total"),
        "tps": _num(m.get("tps")),
        "ttft": _num(m.get("ttft")),
        "tokens_per_wh": _num(m.get("tokens_per_wh")),
    }


def pack_ranking(
    pack: dict[str, Any], battles: list[dict[str, Any]], runs: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    """Ranking por modelo (y equipo/GPU) de las batallas terminadas de `pack`.

    `battles` son las batallas guardadas; `runs`, los runs completos por id.
    """
    entries: list[dict[str, Any]] = []
    other_versions = 0
    for b in battles:
        meta = (b.get("params") or {}).get("pack") or {}
        if meta.get("id") != pack["id"] or b.get("status") != "done":
            continue
        if meta.get("hash") != pack["hash"]:
            other_versions += 1
            continue
        for side in b.get("sides") or []:
            run = runs.get(side.get("run_id"))
            if run and run.get("status") == "done":
                entries.append(_entry(b, run))

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for e in entries:
        groups.setdefault((e["model"], e["quant"], e["devices"], e["host"]), []).append(e)

    rows = []
    for (model, quant, devices, host), es in groups.items():
        graded = [e for e in es if e["accuracy"] is not None]
        best = max(graded, key=lambda e: e["accuracy"], default=None)
        rows.append(
            {
                "model": model,
                "quant": quant,
                "devices": devices,
                "host": host,
                "battles": len(es),
                "accuracy_best": best["accuracy"] if best else None,
                "accuracy_mean": statistics.fmean(e["accuracy"] for e in graded) if graded else None,
                "correct": best["correct"] if best else None,
                "total": best["total"] if best else None,
                "tps": _median([e["tps"] for e in es]),
                "ttft": _median([e["ttft"] for e in es]),
                "tokens_per_wh": _median([e["tokens_per_wh"] for e in es]),
                "last_battle_id": max(e["battle_id"] for e in es),
                "last_at": max((e["when"] or 0) for e in es) or None,
            }
        )
    # Calidad media primero (lo que no tiene calidad, por velocidad), con la velocidad como desempate
    rows.sort(
        key=lambda r: (
            r["accuracy_mean"] is None,
            -(r["accuracy_mean"] or 0),
            r["tps"] is None,
            -(r["tps"] or 0),
            r["model"],
        )
    )
    place, prev = 0, None
    for pos, r in enumerate(rows):
        key = (r["accuracy_mean"], r["tps"] if r["accuracy_mean"] is None else None)
        if pos == 0 or key != prev:
            place = pos + 1
        r["rank"], prev = place, key
    return {
        "pack": {k: pack[k] for k in ("id", "nombre", "hash", "suite", "graded")},
        "rows": rows,
        "battles": len({e["battle_id"] for e in entries}),
        "other_versions": other_versions,
        "by_quality": any(r["accuracy_mean"] is not None for r in rows),
    }
