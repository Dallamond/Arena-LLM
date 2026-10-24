"""Nota de 0 a 100 por run para que una batalla tenga un resultado claro (funciones puras).

Cuatro dimensiones, cada una de 0 a 100 o `None` si no hay datos:
- **calidad**: aciertos (%) de las pruebas que se corrigen solas. Es una cifra *absoluta*: vale
  entre batallas. Lo que no se puede evaluar (prompts libres) no cuenta: la dimensión se omite.
- **velocidad**: t/s y TTFT *relativos* al mejor lado de la batalla (el mejor saca 100).
- **eficiencia**: tokens por Wh (o t/s por GiB de VRAM si no hay potencia) *relativos* al mejor.
- **estabilidad**: 100 menos el tiempo en throttling y la degradación de t/s. Absoluta.

Las dimensiones sin datos no puntúan 0: se omiten y sus pesos se reparten entre las demás.
La velocidad y la eficiencia necesitan al menos dos lados con dato (sin rival no hay referencia).
La nota global solo es comparable dentro de su batalla; la calidad, en cualquier sitio.
"""

from typing import Any

DIMENSIONS = ("quality", "speed", "efficiency", "stability")
LABELS = {"quality": "Calidad", "speed": "Velocidad", "efficiency": "Eficiencia", "stability": "Estabilidad"}
DEFAULT_WEIGHTS = {"quality": 50.0, "speed": 25.0, "efficiency": 15.0, "stability": 10.0}
#: Dentro de la velocidad: generación (t/s) y respuesta inicial (TTFT).
SPEED_MIX = {"tps": 0.7, "ttft": 0.3}
#: Dos notas a menos de esto son un empate (ruido de medida).
TIE_POINTS = 1.0


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def clean_weights(weights: dict[str, Any] | None) -> dict[str, float]:
    """Pesos válidos (solo las cuatro dimensiones, no negativos); sin nada útil, los de por defecto."""
    if not weights:
        return dict(DEFAULT_WEIGHTS)
    out = {k: w for k in DIMENSIONS if (w := _num(weights.get(k))) is not None and w >= 0}
    return out if sum(out.values()) > 0 else dict(DEFAULT_WEIGHTS)


def weights_error(weights: dict[str, Any]) -> str | None:
    """Motivo por el que unos pesos enviados por el usuario no valen, o None. Estricto: no corrige en silencio."""
    unknown = sorted(set(weights) - set(DIMENSIONS))
    if unknown:
        return f"Dimensiones desconocidas: {', '.join(unknown)} (valen {', '.join(DIMENSIONS)})"
    nums = {k: _num(v) for k, v in weights.items()}
    if any(v is None or v < 0 for v in nums.values()):
        return "Los pesos deben ser números no negativos"
    if not sum(nums.values()) > 0:
        return "Al menos un peso debe ser mayor que 0"
    return None


def _relative_high(values: list[float | None]) -> list[float | None]:
    """100·v/máximo; `None` si hay menos de dos valores o el máximo no es positivo."""
    nums = [v for v in values if v is not None]
    top = max(nums, default=0)
    if len(nums) < 2 or top <= 0:
        return [None] * len(values)
    return [None if v is None else 100.0 * max(v, 0) / top for v in values]


def _relative_low(values: list[float | None]) -> list[float | None]:
    """100·mínimo/v (menos es mejor); `None` si hay menos de dos valores o alguno no es positivo."""
    nums = [v for v in values if v is not None and v > 0]
    if len(nums) < 2:
        return [None] * len(values)
    low = min(nums)
    return [100.0 * low / v if v is not None and v > 0 else None for v in values]


def _weighted(parts: list[tuple[float | None, float]]) -> float | None:
    got = [(v, w) for v, w in parts if v is not None and w > 0]
    total = sum(w for _, w in got)
    return sum(v * w for v, w in got) / total if total else None


def _speed(metrics: list[dict[str, Any]]) -> list[float | None]:
    tps = _relative_high([_num(m.get("tps")) for m in metrics])
    ttft = _relative_low([_num(m.get("ttft")) for m in metrics])
    return [_weighted([(a, SPEED_MIX["tps"]), (b, SPEED_MIX["ttft"])]) for a, b in zip(tps, ttft, strict=True)]


def _efficiency(metrics: list[dict[str, Any]]) -> list[float | None]:
    per_wh = _relative_high([_num(m.get("tokens_per_wh")) for m in metrics])
    if sum(v is not None for v in per_wh) >= 2:
        return per_wh
    return _relative_high([_num(m.get("tps_per_gib")) for m in metrics])  # sin potencia: t/s por GiB


def _stability(m: dict[str, Any]) -> float | None:
    # Sin el límite de potencia por software: en su tope de potencia una GPU rinde con normalidad.
    # Un run guardado antes de separarlo solo trae el total.
    throttle = _num(m.get("throttle_hard"))
    if throttle is None:
        throttle = _num(m.get("throttle"))
    degradation = _num(m.get("degradation"))
    if throttle is None and degradation is None:
        return None
    penalty = (throttle or 0.0) + max(degradation or 0.0, 0.0)
    return max(0.0, min(100.0, 100.0 - penalty))


def _quality(m: dict[str, Any]) -> float | None:
    acc = _num(m.get("accuracy"))
    return None if acc is None else max(0.0, min(100.0, acc))


def score_runs(
    metrics: list[dict[str, Any]],
    statuses: list[str | None] | None = None,
    weights: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Nota por run (mismo orden que `metrics`) y ranking.

    `metrics` son los `run_metrics` de cada run; `statuses` sus estados (un run cancelado o abortado
    puntúa igual pero queda marcado `partial`; uno en `error` no puntúa). Con menos de dos runs no
    hay batalla: sin notas.
    """
    w = clean_weights(weights)
    n = len(metrics)
    if n < 2:
        return {"weights": w, "dimensions": [], "scores": [], "winner": None, "has_quality": False}
    speed, eff = _speed(metrics), _efficiency(metrics)
    scores = []
    for i, m in enumerate(metrics):
        dims = {"quality": _quality(m), "speed": speed[i], "efficiency": eff[i], "stability": _stability(m)}
        used = {k: w.get(k, 0.0) for k, v in dims.items() if v is not None and w.get(k, 0.0) > 0}
        total = sum(used.values())
        failed = bool(statuses and statuses[i] == "error")  # sin respuestas válidas: ni puntúa ni gana
        score = _weighted([(dims[k], used[k]) for k in used]) if total and not failed else None
        scores.append(
            {
                "score": score,
                "dims": dims,
                "weights": {k: 100.0 * v / total for k, v in used.items()} if total else {},
                "partial": bool(statuses and statuses[i] not in (None, "done")),
                "quality_correct": m.get("quality_correct"),
                "quality_total": m.get("quality_total"),
            }
        )
    ranked = sorted((i for i, s in enumerate(scores) if s["score"] is not None), key=lambda i: -scores[i]["score"])
    place, anchor = 0, 0.0
    for pos, i in enumerate(ranked):
        if pos == 0 or anchor - scores[i]["score"] >= TIE_POINTS:  # contra el primero del grupo: sin empates en cadena
            place, anchor = pos + 1, scores[i]["score"]
        scores[i]["rank"] = place
    for s in scores:
        s.setdefault("rank", None)
    top = sorted(i for i in ranked if scores[i]["rank"] == 1)
    return {
        "weights": w,
        "dimensions": [d for d in DIMENSIONS if any(s["dims"][d] is not None for s in scores)],
        "scores": scores,
        "winner": top[0] if len(top) == 1 else None,  # empate en cabeza: sin ganador único
        "has_quality": any(s["dims"]["quality"] is not None for s in scores),
        "tied": top if len(top) > 1 else [],
    }
