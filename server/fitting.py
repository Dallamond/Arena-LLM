"""Encaje de un GGUF frente a la memoria libre de un equipo, usado por la API y por el asistente.

Junta lo que hacen por separado `fit.py` (cálculo) y `launch.py` (opciones de arranque) con los datos
del agente: cabecera del GGUF, GPU y RAM libres ahora, servidores detectados y puertos reservados.
"""

from typing import Any

from server import launch
from server.agents import AgentError, AgentMonitor
from server.db import Database
from server.fit import FitError, FitParams, estimate, fit, gpus_from_state, ram_free_from_metrics

GGUF_TIMEOUT_S = 30.0  # leer la cabecera de un GGUF grande en un disco lento tarda unos segundos
#: Resumen del modelo que acompaña al encaje (la lista de modelos los muestra).
MODEL_SUMMARY_KEYS = ("name", "architecture", "general_type", "file_type", "size_label", "n_params",
                      "context_length", "expert_count", "file_size")  # fmt: skip


class HostError(Exception):
    """Fallo al consultar al equipo o parámetros de encaje no válidos."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


async def fit_model(
    monitor: AgentMonitor,
    db: Database,
    host_id: int,
    path: str,
    params: FitParams,
    reserved_ports: set[int],
) -> dict[str, Any]:
    try:
        params.validate()
    except FitError as exc:
        raise HostError(422, str(exc)) from exc
    state = monitor.states.get(host_id)
    if state is None:
        raise HostError(404, "Equipo no registrado")
    try:
        g = (await monitor.agent.get(state, "/gguf", {"path": path}, timeout=GGUF_TIMEOUT_S))["gguf"]
    except AgentError as exc:
        raise HostError(403 if exc.status == "unauthorized" else 502, exc.message) from exc
    est = estimate(g, params)
    gpus = gpus_from_state(state.info, state.metrics)
    verdict = fit(est, gpus, ram_free_from_metrics(state.metrics))
    model = {k: g.get(k) for k in MODEL_SUMMARY_KEYS}
    command = launch.build(
        path=path,
        est=est,
        verdict=verdict,
        model=model,
        host_info=state.info,
        gpus=gpus,
        endpoints=db.list_endpoints(host_id),
        reserved_ports=reserved_ports,
    )
    est.pop("layer_cost", None)
    return {"path": path, "estimated": True, "model": model, "estimate": est, "fit": verdict, "command": command}
