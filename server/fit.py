"""Calculadora de encaje de un GGUF (todas las cifras son ESTIMADAS).

Modelo de memoria (llama.cpp, reparto por capas):
- Pesos: bytes reales de cada capa (`layout.blocks`, deducidos de los offsets del GGUF).
  `token_embd` se queda siempre en RAM; `output` va a la GPU solo con todas las capas en GPU.
- KV: por capa de atención, `cabezas_kv × (dim_k + dim_v) × bytes(tipo) × ctx`. En modelos
  híbridos (p. ej. `qwen35`, `full_attention_interval`) solo algunas capas tienen KV; las demás
  guardan un estado recurrente de tamaño fijo por secuencia (F32).
- Búfer de cómputo: aproximación `4 × ubatch × (vocab + 4·embd + ff)` bytes por dispositivo,
  suponiendo flash attention.
- Reserva: contexto del runtime y margen por GPU (parámetro, no medido).

Si el modelo usa ventana deslizante el KV calculado es una cota superior, y se avisa.
"""

from dataclasses import dataclass
from typing import Any

#: Bytes por elemento de los tipos de caché KV que acepta llama.cpp (bloques de 32).
KV_TYPES: dict[str, float] = {
    "f32": 4.0,
    "f16": 2.0,
    "bf16": 2.0,
    "q8_0": 34 / 32,
    "q5_1": 24 / 32,
    "q5_0": 22 / 32,
    "q4_1": 20 / 32,
    "q4_0": 18 / 32,
    "iq4_nl": 18 / 32,
}

MIB = 1024 * 1024


class FitError(ValueError):
    pass


@dataclass
class FitParams:
    ctx: int = 8192  # contexto total (-c); se reparte entre los slots
    parallel: int = 1  # -np: secuencias (multiplica el estado recurrente)
    kv_type: str = "f16"
    ubatch: int = 512
    reserve_mib: int = 512  # por GPU: contexto CUDA/runtime y margen

    def validate(self) -> None:
        if self.kv_type not in KV_TYPES:
            raise FitError(f"Tipo de KV desconocido: {self.kv_type}")
        if not (1 <= self.ctx <= 10_000_000) or not (1 <= self.parallel <= 256):
            raise FitError("Contexto o paralelo fuera de rango")
        if not (1 <= self.ubatch <= 65536) or not (0 <= self.reserve_mib <= 65536):
            raise FitError("ubatch o reserva fuera de rango")


def _per_layer(value: Any, n: int) -> list[int] | None:
    if isinstance(value, list) and value:
        vals = [int(v) for v in value[:n]]
        return vals + [vals[-1]] * (n - len(vals))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [int(value)] * n
    return None


def _num(meta: dict[str, Any], key: str) -> int | None:
    v = meta.get(key)
    if isinstance(v, list) and v:
        v = max(v)
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def estimate(g: dict[str, Any], p: FitParams) -> dict[str, Any]:
    """Desglose de memoria de un modelo (bytes). `g` es el `gguf` que devuelve el agente."""
    p.validate()
    arch = g.get("architecture")
    if g.get("general_type") == "mmproj" or arch == "clip":
        return {"kind": "mmproj", "notes": ["Proyector multimodal: acompaña a un modelo, no se carga solo."]}
    layout = g.get("layout") or {}
    blocks: list[int] = layout.get("blocks") or []
    if not arch or not blocks:
        return {"kind": "unsupported", "notes": ["El GGUF no trae capas reconocibles (blk.N)."]}

    meta = g.get("metadata") or {}
    notes: list[str] = []
    n = len(blocks)
    n_embd = g.get("embedding_length")
    heads = _per_layer(g.get("head_count"), n)
    kv_heads = _per_layer(g.get("head_count_kv"), n) or heads
    interval = _num(meta, f"{arch}.full_attention_interval")
    d_conv = _num(meta, f"{arch}.ssm.conv_kernel")
    d_inner = _num(meta, f"{arch}.ssm.inner_size")
    d_state = _num(meta, f"{arch}.ssm.state_size")
    n_group = _num(meta, f"{arch}.ssm.group_count") or 0
    has_ssm = bool(d_inner and d_state)
    elt = KV_TYPES[p.kv_type]

    kv_bytes: list[int | None] = []
    rec_bytes: list[int] = []
    kv_unknown = False
    for il in range(n):
        attn = kv_heads is not None and kv_heads[il] > 0
        if interval:
            attn = attn and (il + 1) % interval == 0
        elif has_ssm and g.get("head_count_kv") is None:
            attn = False  # recurrente puro (Mamba): sin cabezas KV
        if attn:
            hd = n_embd // heads[il] if n_embd and heads and heads[il] else None
            k = g.get("key_length") or hd
            v = g.get("value_length") or hd
            if not k or not v:
                kv_unknown = True
                kv_bytes.append(None)
            else:
                kv_bytes.append(int(kv_heads[il] * (k + v) * elt * p.ctx))
            rec_bytes.append(0)
        else:
            kv_bytes.append(0)
            if has_ssm:
                conv = (d_conv - 1 if d_conv else 0) * (d_inner + 2 * n_group * d_state)
                rec_bytes.append((conv + d_state * d_inner) * 4 * p.parallel)
            else:
                rec_bytes.append(0)
    if kv_unknown:
        notes.append("Faltan dimensiones de atención en la cabecera: KV sin datos.")
    if any(rec_bytes):
        notes.append(f"Modelo híbrido/recurrente: estado fijo por secuencia ×{p.parallel} (F32).")
    if _num(meta, f"{arch}.attention.sliding_window"):
        notes.append("Usa ventana deslizante: el KV calculado es una cota superior.")
    if g.get("expert_count"):
        notes.append("MoE: se cuentan todos los expertos en GPU (sin --cpu-moe).")
    missing = layout.get("split_missing") or []
    if missing:
        notes.append(f"Faltan partes del modelo partido: {', '.join(missing)}.")

    vocab = g.get("vocab_size") or 0
    ff = _num(meta, f"{arch}.feed_forward_length") or 0
    compute = 4 * p.ubatch * (vocab + 4 * (n_embd or 0) + ff) if n_embd else None
    if compute is None:
        notes.append("Sin embedding_length: búfer de cómputo sin datos.")

    kv_total = None if kv_unknown else sum(int(k or 0) for k in kv_bytes)
    layer_cost = [
        blocks[i] + int(kv_bytes[i] or 0) + rec_bytes[i] for i in range(n)
    ]
    return {
        "kind": "model",
        "params": p.__dict__,
        "n_layers": n,
        "weights": sum(blocks) + layout.get("output", 0) + layout.get("token_embd", 0) + layout.get("other", 0),
        "weights_layers": sum(blocks),
        "token_embd": layout.get("token_embd", 0),
        "output": layout.get("output", 0) + layout.get("other", 0),
        "kv": kv_total,
        "kv_layers": sum(1 for k in kv_bytes if k),
        "recurrent": sum(rec_bytes),
        "compute": compute,
        "layer_cost": layer_cost,
        "notes": notes,
    }


def _gpu_layers(costs: list[int], capacity: float) -> tuple[int, int]:
    """Máximo de capas finales (llama.cpp offloadea las últimas) que caben y sus bytes."""
    used, k = 0, 0
    for c in reversed(costs):
        if used + c > capacity:
            break
        used += c
        k += 1
    return k, used


def fit(est: dict[str, Any], gpus: list[dict[str, Any]], ram_free_mib: float | None) -> dict[str, Any]:
    """Veredicto frente a la memoria libre. `gpus`: [{device_id, name, free_mib, total_mib}]."""
    if est.get("kind") != "model":
        return {"verdict": est.get("kind"), "label": None, "gpus": []}
    reserve = est["params"]["reserve_mib"] * MIB
    compute = est["compute"] or 0
    costs = est["layer_cost"]
    full = sum(costs) + est["output"] + compute + reserve
    known = [g for g in gpus if g.get("free_mib") is not None]
    per_gpu = []
    for g in gpus:
        free = g["free_mib"] * MIB if g.get("free_mib") is not None else None
        total = g["total_mib"] * MIB if g.get("total_mib") is not None else None
        per_gpu.append(
            {
                "device_id": g["device_id"],
                "name": g.get("name"),
                "need": full,
                "free": free,
                "fits": free is not None and full <= free,
                "fits_if_empty": total is not None and full <= total,
            }
        )
    out: dict[str, Any] = {"need_full_gpu": full, "gpus": per_gpu, "ngl": None, "ram_need": None}
    if est["kv"] is None or est["compute"] is None:
        out.update(verdict="unknown", label="Sin datos suficientes")
        return out
    fitting = [g for g in per_gpu if g["fits"]]
    if fitting:
        names = " · ".join(g["name"] or g["device_id"] for g in fitting)
        out.update(verdict="gpu", label=f"Cabe en {names}", ngl=est["n_layers"] + 1, ram_need=est["token_embd"])
        return out
    # Varias GPUs: cada una paga su reserva y su búfer de cómputo.
    cap = sum(max(g["free_mib"] * MIB - reserve - compute, 0) for g in known)
    if len(known) >= 2 and sum(costs) + est["output"] <= cap:
        out.update(verdict="split", label="Cabe repartido entre GPUs", ngl=est["n_layers"] + 1, ram_need=est["token_embd"])
        return out
    k, _ = _gpu_layers(costs, cap)
    ram_need = est["token_embd"] + est["output"] + sum(costs[: len(costs) - k]) + compute
    out.update(ngl=k, ram_need=ram_need)
    ram_ok = ram_free_mib is not None and ram_need <= ram_free_mib * MIB
    if ram_free_mib is None:
        out.update(verdict="unknown", label="RAM sin datos")
    elif not ram_ok:
        out.update(verdict="no", label="No cabe")
    elif k == 0:
        out.update(verdict="cpu", label=f"Solo CPU · necesita {ram_need / 1024**3:.1f} GiB de RAM")
    else:
        out.update(verdict="ram", label=f"Necesita {ram_need / 1024**3:.1f} GiB de RAM")
    if out["verdict"] != "gpu" and any(g["fits_if_empty"] for g in per_gpu):
        out["hint"] = "Cabría en una GPU vacía: ahora hay memoria ocupada (¿otro servidor cargado?)."
    return out


def gpus_from_state(info: dict[str, Any] | None, metrics: dict[str, Any] | None) -> list[dict[str, Any]]:
    """GPUs del equipo con memoria libre según el último muestreo (null si no hay dato)."""
    devices = (metrics or {}).get("devices") or {}
    out = []
    for d in (info or {}).get("devices", []):
        if d.get("kind") != "gpu":
            continue
        s = devices.get(d["device_id"]) or {}
        total = s.get("mem_total_mib") or d.get("memory_total_mib")
        used = s.get("mem_used_mib")
        out.append(
            {
                "device_id": d["device_id"],
                "name": d.get("name"),
                "total_mib": total,
                "free_mib": total - used if total is not None and used is not None else None,
            }
        )
    return out


def ram_free_from_metrics(metrics: dict[str, Any] | None) -> float | None:
    ram = (metrics or {}).get("ram") or {}
    if ram.get("total_mib") is None or ram.get("used_mib") is None:
        return None
    return ram["total_mib"] - ram["used_mib"]
