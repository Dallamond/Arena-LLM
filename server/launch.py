"""Comando de `llama-server` propuesto para un GGUF a partir de la calculadora de encaje.

Arena no lanza servidores (la GUI detecta, no controla): solo compone el comando
para copiarlo. Todo sale de lo detectado (equipo, GPU, binario, servidores en
marcha) y del veredicto ESTIMADO de `server.fit`; nada es específico de un PC.

Orden de dispositivos: con `CUDA_DEVICE_ORDER=PCI_BUS_ID`, `CUDA0, CUDA1…` coinciden
con el índice de `nvidia-smi`, que es el que guarda el agente. Por eso el comando
fija esa variable siempre que usa `-dev` o `-ts`.
"""

import shlex
from typing import Any
from urllib.parse import urlsplit

#: Prefijo de dispositivo de llama.cpp por proveedor de telemetría. Un proveedor que no
#: esté aquí no recibe `-dev`/`-ts` (se deja el reparto automático y se avisa).
BACKEND_PREFIX = {"nvidia": "CUDA"}
DEVICE_ORDER_ENV = {"CUDA_DEVICE_ORDER": "PCI_BUS_ID"}
STOPPED = ("detenido",)
FIRST_PORT = 8080  # el de llama-server por defecto; se sube hasta encontrar uno sin usar
MIB = 1024 * 1024


def _port_of(url: str) -> int | None:
    try:
        return urlsplit(url).port
    except ValueError:
        return None


def free_port(used: set[int]) -> int:
    port = FIRST_PORT
    while port in used:
        port += 1
    return port


def pick_exe(tools: dict[str, Any] | None, endpoints: list[dict[str, Any]], windows: bool) -> tuple[str, str]:
    """(ruta, origen): el configurado en el agente, el de un llama-server detectado o el del PATH."""
    configured = (tools or {}).get("llama_server")
    if configured:
        return configured, "configurado"
    for e in sorted(endpoints, key=lambda e: e.get("last_seen_at") or 0, reverse=True):
        exe = (e.get("snapshot") or {}).get("exe")
        if exe and "llama-server" in exe.replace("\\", "/").rsplit("/", 1)[-1]:
            return exe, "detectado"
    return ("llama-server.exe" if windows else "llama-server"), "supuesto"


def _ts_values(gpus: list[dict[str, Any]], reserve: int, compute: int) -> list[str]:
    """Proporción de `-ts` por memoria aprovechable de cada GPU (GiB con un decimal)."""
    out = []
    for g in gpus:
        usable = max((g.get("free_mib") or 0) * MIB - reserve - compute, 0)
        out.append(f"{usable / 1024**3:.1f}".removesuffix(".0"))
    return out


def build(
    *,
    path: str,
    est: dict[str, Any],
    verdict: dict[str, Any],
    model: dict[str, Any],
    host_info: dict[str, Any] | None,
    gpus: list[dict[str, Any]],
    endpoints: list[dict[str, Any]],
    reserved_ports: set[int] | None = None,
) -> dict[str, Any]:
    info = host_info or {}
    os_name = (info.get("host") or {}).get("os") or ""
    windows = os_name == "windows"
    v = verdict.get("verdict")
    if est.get("kind") != "model" or v not in ("gpu", "split", "ram", "cpu"):
        reason = {
            "no": "No cabe con la memoria libre ahora: no se propone comando.",
            "unknown": "Faltan datos para el veredicto: no se propone comando.",
        }.get(v, "Este GGUF no se carga como modelo.")
        return {"available": False, "reason": reason}

    p = est["params"]
    devices = {d["device_id"]: d for d in info.get("devices", [])}
    # GPU con índice y backend conocido, en el orden de llama.cpp (índice PCI)
    mapped = []
    for g in gpus:
        d = devices.get(g["device_id"]) or {}
        prefix = BACKEND_PREFIX.get(d.get("provider") or "")
        if prefix and d.get("index") is not None:
            mapped.append({**g, "dev": f"{prefix}{d['index']}", "index": d["index"]})
    mapped.sort(key=lambda g: g["index"])
    all_mapped = len(mapped) == len(gpus)
    notes: list[str] = []
    if gpus and not all_mapped:
        notes.append("Hay GPU de un tipo sin correspondencia con llama.cpp: se deja el reparto automático.")

    # Puertos ocupados: los de servidores que siguen vivos (un detenido ya lo ha soltado)
    live_eps = [e for e in endpoints if e.get("status") not in STOPPED]
    used = {pt for e in live_eps if (pt := _port_of(e.get("base_url") or "")) is not None}
    port = free_port(used | (reserved_ports or set()))
    exe, exe_source = pick_exe(info.get("tools"), endpoints, windows)
    if exe_source == "supuesto":
        notes.append(
            "Ruta de llama-server sin detectar: pon `llama_server` (o `llama_bench`) en la configuración del agente, "
            "o lanza un llama-server una vez para que Arena la vea."
        )

    base = ["-m", path, "-c", str(p["ctx"])]
    if p["parallel"] > 1:
        base += ["-np", str(p["parallel"])]
    if p["kv_type"] != "f16":
        base += ["-ctk", p["kv_type"], "-ctv", p["kv_type"]]
    if p["ubatch"] != 512:
        base += ["-ub", str(p["ubatch"])]
    tail = ["-fa", "on", "--port", str(port)]

    reserve = p["reserve_mib"] * MIB
    compute = est.get("compute") or 0
    ngl = verdict.get("ngl")
    options: list[dict[str, Any]] = []

    def option(oid: str, label: str, extra: list[str], env: dict[str, str] | None = None) -> None:
        args = [*base, *extra, *tail]
        options.append({"id": oid, "label": label, "args": args, "env": env or {}, **render(exe, args, env or {}, windows)})

    if v == "gpu":
        fitting = [g for g in verdict.get("gpus", []) if g.get("fits")]
        fitting.sort(key=lambda g: g.get("free") or 0, reverse=True)
        for g in fitting:
            m = next((x for x in mapped if x["device_id"] == g["device_id"]), None)
            name = g.get("name") or g["device_id"]
            if len(gpus) > 1 and m:
                option(m["dev"], f"Solo en {name}", ["-ngl", str(ngl), "-dev", m["dev"]], DEVICE_ORDER_ENV)
            else:
                option(g["device_id"], f"En {name}", ["-ngl", str(ngl)])
        if len(fitting) > 1:
            notes.append("Cabe en varias GPU: elige cuál; la de más memoria libre va primero, no necesariamente la más rápida.")
    elif v in ("split", "ram"):
        label = "Repartido entre GPU" if v == "split" else f"{ngl} de {est['n_layers']} capas en GPU, el resto en RAM"
        if len(mapped) > 1 and all_mapped:
            option(v, label, ["-ngl", str(ngl), "-ts", ",".join(_ts_values(mapped, reserve, compute))], DEVICE_ORDER_ENV)
            notes.append("`-ts` reparte según la memoria libre ahora (ESTIMADO); ajústalo si cambia lo que hay cargado.")
        else:
            option(v, label, ["-ngl", str(ngl)])
    else:  # cpu
        option("cpu", "Solo CPU", ["-ngl", "0", *(["-dev", "none"] if gpus else [])])

    ctx_train = model.get("context_length")
    if isinstance(ctx_train, int) and p["ctx"] // max(p["parallel"], 1) > ctx_train:
        notes.append(
            f"El contexto por slot ({p['ctx'] // max(p['parallel'], 1):,} tokens) supera el de entrenamiento "
            f"({ctx_train:,}): la calidad puede caer sin RoPE scaling.".replace(",", ".")
        )
    notes.append(f"Puerto {port}: libre entre los servidores detectados; otro programa podría estar usándolo.")
    return {
        "available": True,
        "exe": exe,
        "exe_source": exe_source,
        "os": os_name or None,
        "port": port,
        "options": options,
        "notes": notes,
        "estimated": True,
    }


def _cmd_quote(arg: str) -> str:
    return f'"{arg}"' if any(c in arg for c in ' &()^|<>,;=%!"') or not arg else arg


def _ps_quote(arg: str) -> str:
    if arg and all(c.isalnum() or c in "-_./:\\" for c in arg):
        return arg
    return "'" + arg.replace("'", "''") + "'"


def render(exe: str, args: list[str], env: dict[str, str], windows: bool) -> dict[str, Any]:
    """El mismo comando para cada shell del sistema del equipo."""
    if windows:
        cmd = [f"set {k}={v}" for k, v in env.items()]
        cmd.append(" ".join([_cmd_quote(exe), *(_cmd_quote(a) for a in args)]))
        ps = [f'$env:{k} = "{v}"' for k, v in env.items()]
        ps.append(" ".join(["&", _ps_quote(exe), *(_ps_quote(a) for a in args)]))
        return {"shells": {"cmd": "\n".join(cmd), "powershell": "\n".join(ps)}}
    prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
    line = " ".join([shlex.quote(exe), *(shlex.quote(a) for a in args)])
    return {"shells": {"bash": f"{prefix} {line}" if prefix else line}}
