"""Asistente: barrido de modelos × GPU.

Para cada pareja (modelo, destino) hace lo que Lucas haría a mano: calcula el encaje con la memoria libre de
ese momento, arranca `llama-server` desde el agente, espera a que esté listo, lanza la prueba elegida, y lo para
antes de pasar al siguiente. Al terminar quedan los runs listos para abrir en Comparar.

Solo para los servidores que lanzó él mismo: no toca los que ya estaban en marcha. Si algo no cabe con la memoria
libre de ese momento, el paso queda como «no cabe» y el barrido sigue.
"""

import asyncio
import logging
import time
from typing import Any

from server.agents import AgentError, AgentMonitor
from server.db import Database
from server.fit import FitParams
from server.fitting import HostError, fit_model
from server.hub import EventHub
from server.runs.manager import RunError, RunManager, validate
from server.runs.suites import SUITES

log = logging.getLogger(__name__)

MAX_MODELS = 12
MAX_TARGETS = 6
MAX_STEPS = 36
LOAD_TIMEOUT_S = (30, 3600)
POLL_S = 1.0
STOP_WAIT_S = 20.0
#: Pruebas que acepta el asistente (la de estrés y las de rendimiento tienen su propia pantalla).
SWEEP_SUITES = ("libre", "qa", "codigo", "contexto", "concurrencia")
#: Pasos que ya no cambian.
FINAL = ("hecho", "error", "no cabe", "omitido", "detenido")


def _name(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def step_option(command: dict[str, Any], target: str) -> tuple[dict[str, Any] | None, str]:
    """Opción de arranque que corresponde al destino pedido, o el motivo de que no haya."""
    if not command.get("available"):
        return None, command.get("reason") or "No se puede lanzar este modelo"
    options = command.get("options") or []
    if target == "auto":
        return (options[0], "") if options else (None, "Sin opciones de arranque")
    if target == "reparto":
        opt = next((o for o in options if o["id"] in ("split", "ram")), None)
        return (opt, "") if opt else (None, "No necesita (o no puede) repartirse entre GPU")
    opt = next((o for o in options if o.get("device_id") == target), None)
    return (opt, "") if opt else (None, "No cabe entero en esa GPU con la memoria libre de ahora")


class SweepManager:
    def __init__(
        self, db: Database, hub: EventHub, monitor: AgentMonitor, runs: RunManager, reserved_ports: set[int]
    ):
        self.db = db
        self.hub = hub
        self.monitor = monitor
        self.runs = runs
        self.reserved_ports = reserved_ports
        self.tasks: dict[int, asyncio.Task] = {}
        self.cancelled: set[int] = set()

    # --- API ---------------------------------------------------------------

    async def start(
        self,
        host_id: int,
        models: list[str],
        targets: list[str],
        fit_params: dict[str, Any],
        suite: str,
        suite_params: dict[str, Any],
        label: str | None,
        load_timeout_s: int = 600,
    ) -> dict[str, Any]:
        state = self.monitor.states.get(host_id)
        if state is None:
            raise RunError(404, "Equipo no registrado")
        if state.status != "online":
            raise RunError(409, "El agente del equipo no está en línea")
        models = list(dict.fromkeys(m for m in models if isinstance(m, str) and m.strip()))
        targets = list(dict.fromkeys(t for t in targets if isinstance(t, str) and t.strip())) or ["auto"]
        if not 1 <= len(models) <= MAX_MODELS:
            raise RunError(422, f"Elige entre 1 y {MAX_MODELS} modelos")
        if len(targets) > MAX_TARGETS or len(models) * len(targets) > MAX_STEPS:
            raise RunError(422, f"Demasiados pasos (máximo {MAX_STEPS}): reduce modelos o destinos")
        if suite not in SWEEP_SUITES:
            raise RunError(422, f"Prueba no disponible en el asistente: {suite}")
        if not LOAD_TIMEOUT_S[0] <= load_timeout_s <= LOAD_TIMEOUT_S[1]:
            raise RunError(422, f"'load_timeout_s' entre {LOAD_TIMEOUT_S[0]} y {LOAD_TIMEOUT_S[1]}")
        try:
            fp = FitParams(**fit_params)
            fp.validate()
        except (TypeError, ValueError) as exc:
            raise RunError(422, f"Parámetros de arranque no válidos: {exc}") from exc
        # Se validan ya las opciones de la prueba: es mejor fallar aquí que a mitad del barrido
        validate(SUITES[suite], SUITES[suite].params(dict(suite_params)))

        steps = [
            {
                "i": i,
                "model_path": m,
                "model_name": _name(m),
                "target": t,
                "state": "pendiente",
                "message": None,
                "pid": None,
                "port": None,
                "run_id": None,
                "option": None,
                "started_at": None,
                "finished_at": None,
            }
            for i, (m, t) in enumerate((m, t) for m in models for t in targets)
        ]
        sweep = self.db.create_sweep(
            label=(label or "").strip() or None,
            status="running",
            params={
                "host_id": host_id,
                "models": models,
                "targets": targets,
                "fit": fp.__dict__,
                "suite": suite,
                "suite_params": suite_params,
                "load_timeout_s": load_timeout_s,
            },
            steps=steps,
        )
        sid = sweep["id"]
        self.tasks[sid] = asyncio.create_task(self._execute(sid), name=f"sweep-{sid}")
        self._publish(sid)
        return self.public(sid)

    async def cancel(self, sid: int) -> None:
        if self.db.get_sweep(sid) is None:
            raise RunError(404, "Barrido no encontrado")
        if sid not in self.tasks:
            raise RunError(409, "El barrido no está en marcha")
        self.cancelled.add(sid)
        sweep = self.db.get_sweep(sid)
        for st in sweep["steps"]:
            if st["state"] == "midiendo" and st.get("run_id") and self.runs.is_active(st["run_id"]):
                await self.runs.cancel(st["run_id"])

    async def shutdown(self) -> None:
        for sid in list(self.tasks):
            self.cancelled.add(sid)
        for t in list(self.tasks.values()):
            t.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    def public(self, sid: int) -> dict[str, Any]:
        sweep = self.db.get_sweep(sid)
        if sweep is None:
            raise RunError(404, "Barrido no encontrado")
        ids = [s["run_id"] for s in sweep["steps"] if s.get("run_id")]
        runs = {r["id"]: r for r in self.db.get_runs(ids)} if ids else {}
        light = {
            rid: {k: r.get(k) for k in ("id", "status", "summary", "suite", "error", "started_at", "finished_at")}
            for rid, r in runs.items()
        }
        return {**sweep, "runs": light}

    # --- ejecución ---------------------------------------------------------

    def _publish(self, sid: int) -> None:
        sweep = self.db.get_sweep(sid)
        if sweep:
            self.hub.publish("sweep", sweep)

    def _set(self, sid: int, step: dict[str, Any], steps: list[dict[str, Any]], **fields: Any) -> None:
        step.update(fields)
        self.db.update_sweep(sid, steps=steps)
        self._publish(sid)

    async def _execute(self, sid: int) -> None:
        sweep = self.db.get_sweep(sid)
        params, steps = sweep["params"], sweep["steps"]
        error = None
        try:
            for step in steps:
                if sid in self.cancelled:
                    self._set(sid, step, steps, state="omitido", message="Barrido cancelado")
                    continue
                await self._step(sid, params, step, steps)
        except asyncio.CancelledError:
            error = "Servidor detenido durante el barrido"
        except Exception as exc:  # el barrido queda como error; el servidor sigue
            log.exception("Barrido %s falló", sid)
            error = f"{type(exc).__name__}: {exc}"
        finally:
            for st in steps:
                if st["state"] not in FINAL:
                    st["state"] = "omitido" if st["state"] == "pendiente" else "detenido"
            states = [s["state"] for s in steps]
            if sid in self.cancelled:
                status = "cancelled"
            elif error:
                status = "error"
            elif "hecho" in states:
                status = "done"
            else:
                status = "error"
                error = "Ningún paso pudo medirse (mira el motivo de cada uno)"
            self.db.update_sweep(sid, steps=steps, status=status, error=error, finished_at=time.time())
            self.tasks.pop(sid, None)
            self.cancelled.discard(sid)
            self._publish(sid)

    async def _step(self, sid: int, params: dict[str, Any], step: dict[str, Any], steps: list[dict[str, Any]]) -> None:
        host_id = params["host_id"]
        state = self.monitor.states.get(host_id)
        step["started_at"] = time.time()
        pid = None
        try:
            if state is None or state.status != "online":
                raise _StepError("error", "El agente del equipo no está en línea")
            self._set(sid, step, steps, state="comprobando", message="Calculando el encaje con la memoria libre")
            try:
                fitted = await fit_model(
                    self.monitor, self.db, host_id, step["model_path"], FitParams(**params["fit"]), self.reserved_ports
                )
            except HostError as exc:
                raise _StepError("error", exc.message) from exc
            option, why = step_option(fitted["command"], step["target"])
            if option is None:
                raise _StepError("no cabe", why)

            self._set(sid, step, steps, state="arrancando", option=option["label"], message=None)
            try:
                out = await self.monitor.agent.post(state, "/launch", option["spec"])
            except AgentError as exc:
                raise _StepError("error", f"El agente no pudo lanzar llama-server: {exc.message}") from exc
            pid, port = out["pid"], out["port"]
            self._set(sid, step, steps, pid=pid, port=port)

            endpoint = await self._wait_ready(sid, state, params, pid, port)
            self._set(sid, step, steps, state="midiendo", message=None)
            run = await self.runs.start(
                params["suite"],
                endpoint["id"],
                dict(params["suite_params"]),
                f"Asistente #{sid} · {step['model_name']} · {option['label']}",
                sweep_id=sid,
            )
            self._set(sid, step, steps, run_id=run["id"])
            await self.runs.wait(run["id"])
            final = self.db.get_run(run["id"]) or {}
            if sid in self.cancelled or final.get("status") == "cancelled":
                raise _StepError("detenido", "Cancelado durante la medición")
            if final.get("status") in ("error", "aborted"):
                reason = final.get("abort_reason") or final.get("error") or "La prueba falló"
                raise _StepError("error", reason)
            self._set(sid, step, steps, state="hecho", message=None)
        except _StepError as exc:
            self._set(sid, step, steps, state=exc.state, message=exc.message)
        except RunError as exc:
            self._set(sid, step, steps, state="error", message=exc.message)
        finally:
            if pid is not None:
                await self._stop(sid, state, step, pid)
            step["finished_at"] = time.time()
            self.db.update_sweep(sid, steps=steps)
            self._publish(sid)

    async def _wait_ready(self, sid: int, state: Any, params: dict[str, Any], pid: int, port: int) -> dict[str, Any]:
        deadline = time.monotonic() + params["load_timeout_s"]
        suffix = f":{port}"
        while time.monotonic() < deadline:
            if sid in self.cancelled:
                raise _StepError("detenido", "Cancelado mientras cargaba el modelo")
            for ep in self.db.list_endpoints(state.pk):
                if ep["base_url"].rstrip("/").endswith(suffix) and ep["status"] == "listo":
                    return ep
            try:
                launched = (await self.monitor.agent.get(state, "/launched")).get("launched", [])
            except AgentError:
                launched = []
            mine = next((x for x in launched if x.get("pid") == pid), None)
            if mine is not None and not mine.get("alive"):
                tail = " | ".join((mine.get("log_tail") or [])[-3:])
                raise _StepError("error", f"llama-server terminó al arrancar (código {mine.get('returncode')}): {tail}")
            await asyncio.sleep(POLL_S)
        raise _StepError("error", f"El modelo no estuvo listo en {params['load_timeout_s']} s")

    async def _stop(self, sid: int, state: Any, step: dict[str, Any], pid: int) -> None:
        """Para el servidor que lanzó este paso y espera a que suelte la memoria."""
        if state is None:
            return
        try:
            await self.monitor.agent.post(state, "/launch/stop", {"pid": pid})
        except AgentError as exc:
            log.warning("No se pudo parar el servidor %s del barrido %s: %s", pid, sid, exc.message)
        end = time.monotonic() + STOP_WAIT_S
        port = step.get("port")
        while port and time.monotonic() < end:
            alive = [
                e
                for e in self.db.list_endpoints(state.pk)
                if e["base_url"].rstrip("/").endswith(f":{port}") and e["status"] != "detenido"
            ]
            if not alive:
                break
            await asyncio.sleep(0.5)


class _StepError(Exception):
    def __init__(self, state: str, message: str):
        super().__init__(message)
        self.state = state
        self.message = message
