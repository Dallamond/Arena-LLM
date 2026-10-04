"""Pruebas de rendimiento por componente con `llama-bench` (F6).

Cuatro perfiles, todos con versión y hash de contenido:

- `bench-dispositivo`: un único dispositivo (una GPU con todas las capas, o la CPU).
- `bench-cpu`: solo CPU/RAM con barrido de hilos.
- `bench-ngl`: híbrido, barrido de capas en GPU (la "curva de la RAM").
- `bench-ts`: reparto entre GPU, barrido de `-ts`.

El **perfil estándar** (mismos tamaños de prompt/generación y repeticiones en
cualquier equipo) es el valor por defecto; cambiarlo cambia el hash y el
comparador lo marcará. Los valores por defecto de los barridos se derivan del
equipo y del modelo (capas del GGUF, núcleos de la CPU, GPU detectadas): nada
cableado.

Métricas derivadas (funciones puras, con tests):
- % de capas en GPU = min(ngl, capas + 1) / (capas + 1). llama.cpp cuenta la
  capa de salida como una más.
- Ancho de banda efectivo ≈ tamaño del modelo × t/s de generación. Es una
  aproximación válida para modelos densos (ESTIMADO); en MoE no se calcula.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

#: Perfil estándar v1: idéntico en cualquier equipo.
STANDARD = {"n_prompt": [512], "n_gen": [128], "repetitions": 3}

BENCH_COMMON = {
    **STANDARD,
    "flash_attn": None,  # None = lo que decida la build (se guarda lo que reporta llama-bench)
    "cache_type_k": None,
    "cache_type_v": None,
    "baseline_s": 5,
    "cooldown_s": 0,
    "timeout_s": 3600,
}

#: Claves que definen el contenido de la prueba (entran en el hash).
HASH_KEYS = ("n_prompt", "n_gen", "repetitions", "flash_attn", "cache_type_k", "cache_type_v", "sweep")


@dataclass(frozen=True)
class BenchSuite:
    id: str
    name: str
    version: str
    sweep: str | None  # parámetro que se barre (None = un solo punto)
    sweep_label: str | None
    description: str
    min_gpus: int = 0

    mode = "bench"

    def params(self, user: dict[str, Any] | None) -> dict[str, Any]:
        merged = dict(BENCH_COMMON)
        for k, v in (user or {}).items():
            if v is not None:
                merged[k] = v
        return merged

    def content_hash(self, params: dict[str, Any]) -> str:
        keyed = {k: params.get(k) for k in HASH_KEYS}
        blob = json.dumps({"suite": self.id, "version": self.version, "params": keyed}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "mode": self.mode,
            "description": self.description,
            "defaults": dict(BENCH_COMMON),
            "sweep": self.sweep,
            "sweep_label": self.sweep_label,
            "min_gpus": self.min_gpus,
            "prompts": [],
        }


BENCH_SUITES: dict[str, BenchSuite] = {
    "bench-dispositivo": BenchSuite(
        id="bench-dispositivo",
        name="Un dispositivo",
        version="1",
        sweep=None,
        sweep_label=None,
        description="Cuánto da un dispositivo solo: una GPU con todas las capas, o la CPU sin GPU. Perfil estándar.",
    ),
    "bench-cpu": BenchSuite(
        id="bench-cpu",
        name="Solo CPU/RAM",
        version="1",
        sweep="threads",
        sweep_label="hilos",
        description="Sin GPU (-dev none, -ngl 0) con barrido de hilos: dónde deja de escalar la CPU con tu RAM.",
    ),
    "bench-ngl": BenchSuite(
        id="bench-ngl",
        name="Híbrido · curva de la RAM",
        version="1",
        sweep="n_gpu_layers",
        sweep_label="capas en GPU",
        description="Barrido de -ngl: cuánto se pierde por cada capa que pasa de la VRAM a la RAM.",
    ),
    "bench-ts": BenchSuite(
        id="bench-ts",
        name="Reparto entre GPU",
        version="1",
        sweep="tensor_split",
        sweep_label="reparto -ts",
        description="Barrido de -ts con todas las capas en GPU: cómo repartir un modelo entre varias tarjetas.",
        min_gpus=2,
    ),
}


class BenchSpecError(ValueError):
    pass


# --- valores por defecto derivados del equipo y del modelo ---------------------


def default_threads(cores: int | None, threads: int | None) -> list[int]:
    """Barrido de hilos: 1, 2, mitad de núcleos, núcleos y todos los hilos (sin repetir)."""
    c = cores or threads or 4
    t = threads or c
    vals = {1, 2, max(1, c // 2), c, t}
    return sorted(v for v in vals if 1 <= v <= t)


def default_ngl(n_layers: int | None) -> list[int]:
    """0, ¼, ½, ¾ y todas las capas (+1 de salida)."""
    if not n_layers:
        return [0, 8, 16, 24, 99]
    full = n_layers + 1
    return sorted({0, round(full * 0.25), round(full * 0.5), round(full * 0.75), full})


def default_ts(vram_mib: list[float]) -> list[str]:
    """Repartos para N GPU: igual, proporcional a la VRAM y, con dos, varios cocientes."""
    n = len(vram_mib)
    if n < 2:
        return []
    out = ["/".join(["1"] * n)]
    if all(v > 0 for v in vram_mib):
        low = min(vram_mib)
        prop = "/".join(f"{v / low:.2f}".rstrip("0").rstrip(".") for v in vram_mib)
        out.append(prop)
    if n == 2:
        out += ["3/1", "2/1", "1/2", "1/3"]
    seen: list[str] = []
    for ts in out:
        if ts not in seen:
            seen.append(ts)
    return seen


def build_spec(
    suite: BenchSuite,
    params: dict[str, Any],
    model_path: str,
    device_names: list[str],
    is_cpu: bool,
) -> dict[str, Any]:
    """Especificación para el agente. `device_names`: nombres de llama-bench ("CUDA0"…)."""
    spec: dict[str, Any] = {
        "model": model_path,
        "n_prompt": list(params["n_prompt"]),
        "n_gen": list(params["n_gen"]),
        "repetitions": int(params["repetitions"]),
        "timeout_s": int(params.get("timeout_s") or 3600),
    }
    for k in ("flash_attn", "cache_type_k", "cache_type_v"):
        if params.get(k):
            spec[k] = params[k]
    sweep = params.get("sweep") or []
    if suite.id == "bench-dispositivo":
        if is_cpu:
            spec.update(devices=["none"], n_gpu_layers=[0])
            if params.get("threads"):
                spec["threads"] = [int(params["threads"])]
        else:
            spec.update(devices=["/".join(device_names)], n_gpu_layers=[999])
    elif suite.id == "bench-cpu":
        spec.update(devices=["none"], n_gpu_layers=[0], threads=[int(v) for v in sweep])
    elif suite.id == "bench-ngl":
        spec.update(n_gpu_layers=[int(v) for v in sweep])
        if device_names:
            spec["devices"] = ["/".join(device_names)]
    elif suite.id == "bench-ts":
        if len(device_names) < 2:
            raise BenchSpecError("El reparto necesita al menos dos GPU")
        spec.update(devices=["/".join(device_names)], n_gpu_layers=[999], tensor_split=[str(v) for v in sweep])
    if suite.sweep and not sweep:
        raise BenchSpecError(f"Falta el barrido de {suite.sweep_label}")
    return spec


# --- filas y métricas derivadas ----------------------------------------------


def row_test(row: dict[str, Any]) -> str:
    p, n = int(row.get("n_prompt") or 0), int(row.get("n_gen") or 0)
    if p and not n:
        return "pp"
    if n and not p:
        return "tg"
    return "pg"


def layers_pct(ngl: Any, n_layers: int | None, cpu_only: bool) -> float | None:
    if cpu_only:
        return 0.0
    if not isinstance(ngl, int) or not n_layers:
        return None
    full = n_layers + 1
    return 100.0 * min(max(ngl, 0), full) / full


def bandwidth_gbs(model_size: Any, tg_ts: Any, is_moe: bool) -> float | None:
    """Ancho de banda efectivo (GB/s) ≈ bytes del modelo × tokens/s. ESTIMADO, solo modelos densos."""
    if is_moe or not isinstance(model_size, (int, float)) or not isinstance(tg_ts, (int, float)):
        return None
    if model_size <= 0 or tg_ts <= 0:
        return None
    return model_size * tg_ts / 1e9


def sweep_value(suite: BenchSuite, row: dict[str, Any]) -> Any:
    key = {"threads": "n_threads", "n_gpu_layers": "n_gpu_layers", "tensor_split": "tensor_split"}.get(
        suite.sweep or ""
    )
    return row.get(key) if key else None


def normalize_row(suite: BenchSuite, raw: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """Fila de llama-bench → fila guardada (columnas + parámetros + derivadas)."""
    n_layers = model.get("block_count")
    is_moe = bool(model.get("expert_count"))
    cpu_only = raw.get("devices") == "none"
    test = row_test(raw)
    params = {
        k: raw.get(k)
        for k in ("n_gpu_layers", "n_threads", "tensor_split", "devices", "flash_attn", "type_k", "type_v",
                  "n_batch", "n_ubatch", "n_cpu_moe", "split_mode", "main_gpu")  # fmt: skip
    }
    samples = raw.get("samples_ts") if isinstance(raw.get("samples_ts"), list) else None
    derived = {
        "layers_pct": layers_pct(raw.get("n_gpu_layers"), n_layers, cpu_only),
        "bandwidth_gbs": bandwidth_gbs(raw.get("model_size"), raw.get("avg_ts"), is_moe) if test == "tg" else None,
        "sweep": sweep_value(suite, raw),
    }
    return {
        "test": test,
        "n_prompt": raw.get("n_prompt"),
        "n_gen": raw.get("n_gen"),
        "n_depth": raw.get("n_depth"),
        "params": params,
        "t_s_mean": raw.get("avg_ts"),
        "t_s_std": raw.get("stddev_ts"),
        "reps": len(samples) if samples else None,
        "samples": samples,
        "t": raw.get("t"),
        "derived": derived,
        "raw": raw,
    }


def bench_summary(suite: BenchSuite, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Resumen: mejor pp/tg, info de la build y la curva (valor barrido → t/s)."""

    def best(test: str) -> dict[str, Any] | None:
        cand = [r for r in rows if r["test"] == test and isinstance(r.get("t_s_mean"), (int, float))]
        if not cand:
            return None
        top = max(cand, key=lambda r: r["t_s_mean"])
        return {"t_s": top["t_s_mean"], "std": top["t_s_std"], "sweep": top["derived"].get("sweep"),
                "params": top["params"], "bandwidth_gbs": top["derived"].get("bandwidth_gbs")}  # fmt: skip

    curve: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if suite.sweep is None:
            break
        curve.setdefault(r["test"], []).append(
            {"x": r["derived"].get("sweep"), "t_s": r["t_s_mean"], "std": r["t_s_std"],
             "layers_pct": r["derived"].get("layers_pct"),
             "bandwidth_gbs": r["derived"].get("bandwidth_gbs")}  # fmt: skip
        )
    first = rows[0]["raw"] if rows else {}
    return {
        "bench": {
            "rows": len(rows),
            "best_pp": best("pp"),
            "best_tg": best("tg"),
            "sweep": suite.sweep,
            "sweep_label": suite.sweep_label,
            "curve": curve,
            "build": {k: first.get(k) for k in ("build_commit", "build_number", "backends", "gpu_info", "cpu_info")},
            "model_type": first.get("model_type"),
            "model_size": first.get("model_size"),
            "model_n_params": first.get("model_n_params"),
        }
    }
