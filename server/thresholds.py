"""Umbrales térmicos por dispositivo (misma regla que web/src/lib/thresholds.ts).

Prioridad: valor que el usuario fija en Ajustes → derivado de la temperatura de
slowdown que reporta el dispositivo → valor por defecto del fabricante.
"""

from typing import Any

WARN_MARGIN_C = 10
CRIT_MARGIN_C = 5
PROVIDER_DEFAULTS = {"nvidia": {"warn": 80, "crit": 85}}
GENERIC_DEFAULT = {"warn": 80, "crit": 85}


def thresholds_for(device: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    o = (overrides or {}).get(device.get("device_id", ""), {}) or {}
    slowdown = device.get("temp_slowdown_c")
    if isinstance(slowdown, (int, float)):
        base = {"warn": slowdown - WARN_MARGIN_C, "crit": slowdown - CRIT_MARGIN_C, "source": "dispositivo"}
    else:
        base = {**PROVIDER_DEFAULTS.get(device.get("provider", ""), GENERIC_DEFAULT), "source": "por defecto"}
    if isinstance(o.get("warn"), (int, float)):
        base["warn"] = o["warn"]
        base["source"] = "ajustes"
    if isinstance(o.get("crit"), (int, float)):
        base["crit"] = o["crit"]
        base["source"] = "ajustes"
    return base
