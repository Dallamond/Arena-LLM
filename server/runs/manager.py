"""Gestor de runs: ejecuta suites, muestrea telemetría y aborta por temperatura.

Fases de un run: reposo (línea base) → carga → enfriamiento. Las muestras del
agente se guardan con su fase; la serie de t/s se registra cada segundo. Todo
run guarda su foto de configuración (servidor, equipo, umbrales, parámetros).
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from server.agents import AgentError, AgentMonitor, HostState
from server.db import Database
from server.fit import FitError, FitParams, estimate, fit, gpus_from_state
from server.hub import EventHub
from server.runs import stats
from server.runs.bench import (
    BENCH_SUITES,
    BenchSpecError,
    BenchSuite,
    bench_summary,
    build_spec,
    default_ngl,
    default_threads,
    default_ts,
    normalize_row,
)
from server.runs.llm import ChatResult, stream_chat
from server.runs.stats import CUT_MSG
from server.runs.suites import SUITES, Suite, payload_for
from server.thresholds import thresholds_for

log = logging.getLogger(__name__)

LIVE_TEXT_MAX = 4000  # caracteres de la respuesta en vivo que se reenvían a la GUI
BENCH_POLL_S = 0.5
BENCH_DEVICES_TIMEOUT_S = 90.0  # la primera vez llama-bench carga CUDA para listar dispositivos
GGUF_TIMEOUT_S = 30.0  # leer la cabecera de un GGUF grande en un disco lento tarda unos segundos
#: Resumen del modelo que se guarda con un run de llama-bench.
BENCH_MODEL_KEYS = ("path", "name", "architecture", "file_type", "size_label", "n_params", "file_size",
                    "block_count", "expert_count", "context_length", "header_sha256")  # fmt: skip

LIMITS = {
    "duration_s": (5, 7200),
    "parallel": (1, 64),
    "max_tokens": (1, 131072),
    "baseline_s": (0, 600),
    "cooldown_s": (0, 1800),
    "repeats": (1, 100),
    "timeout_s": (5, 3600),
}


class RunError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class ActiveRun:
    id: int
    suite: Suite | BenchSuite
    host_pk: int
    endpoint: dict[str, Any] | None
    params: dict[str, Any]
    watch: dict[str, dict[str, Any]]  # device_id → {name, warn, crit}
    bench_spec: dict[str, Any] | None = None
    bench_model: dict[str, Any] | None = None
    bench_rows: int = 0
    bench_error: str | None = None
    phase: str = "reposo"
    started: float = field(default_factory=time.time)
    load_start: float | None = None
    load_end: float | None = None
    tokens: int = 0
    tokens_at_tick: int = 0
    last_tick: float | None = None
    requests_done: int = 0
    requests_error: int = 0
    abort_reason: str | None = None
    user_cancel: bool = False
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    workers: list[asyncio.Task] = field(default_factory=list)
    task: asyncio.Task | None = None
    live_text: str = ""
    live_dirty: bool = False
    max_temp: dict[str, float] = field(default_factory=dict)


def validate(suite: Suite, params: dict[str, Any]) -> dict[str, Any]:
    for key, (lo, hi) in LIMITS.items():
        if key in params and params[key] is not None:
            try:
                v = float(params[key])
            except (TypeError, ValueError) as exc:
                raise RunError(422, f"'{key}' debe ser un número") from exc
            if not lo <= v <= hi:
                raise RunError(422, f"'{key}' fuera de rango ({lo}–{hi})")
            params[key] = int(v) if key != "duration_s" else v
    if suite.mode == "items":
        prompts = [p.strip() for p in params.get("prompts") or [] if isinstance(p, str) and p.strip()]
        if not prompts:
            raise RunError(422, "Hace falta al menos un prompt")
        params["prompts"] = prompts
    if not isinstance(params.get("extra") or {}, dict):
        raise RunError(422, "'extra' debe ser un objeto JSON")
    return params


class RunManager:
    def __init__(self, db: Database, hub: EventHub, monitor: AgentMonitor, client: httpx.AsyncClient):
        self.db = db
        self.hub = hub
        self.monitor = monitor
        self.client = client
        self.active: dict[int, ActiveRun] = {}
        monitor.listeners.append(self._on_metrics)

    # --- API ---------------------------------------------------------------

    async def start(
        self,
        suite_id: str,
        endpoint_id: int,
        user_params: dict[str, Any],
        label: str | None,
        battle_id: int | None = None,
        side: str | None = None,
    ) -> dict:
        suite = SUITES.get(suite_id)
        if suite is None:
            raise RunError(404, f"Suite desconocida: {suite_id}")
        ep = self.db.get_endpoint(endpoint_id)
        if ep is None:
            raise RunError(404, "Servidor no registrado")
        if ep["status"] != "listo":
            raise RunError(409, f"El servidor no está listo (estado: {ep['status']})")
        if any(a.endpoint and a.endpoint["id"] == endpoint_id for a in self.active.values()):
            raise RunError(409, "Ya hay una prueba en marcha en este servidor")
        state = self.monitor.states.get(ep["host_pk"])
        if state is None or state.status != "online":
            raise RunError(409, "El agente del equipo no está en línea: no habría telemetría")

        params = validate(suite, suite.params(user_params))
        overrides = self.db.get_setting("thresholds", {}) or {}
        watch = self._watch_devices(state, ep, overrides)
        host_snapshot = {**state.public(), "thresholds": watch}
        run = self.db.create_run(
            kind="stress" if suite.id == "estres" else "free",
            suite=suite.id,
            suite_version=suite.version,
            suite_hash=suite.content_hash(params),
            label=label or None,
            status="running",
            host_pk=state.pk,
            endpoint_id=ep["id"],
            params=params,
            servers_snapshot=ep["snapshot"],
            host_snapshot=host_snapshot,
            started_at=time.time(),
            battle_id=battle_id,
            side=side,
        )
        ar = ActiveRun(id=run["id"], suite=suite, host_pk=state.pk, endpoint=ep, params=params, watch=watch)
        self.active[ar.id] = ar
        ar.task = asyncio.create_task(self._execute(ar), name=f"run-{ar.id}")
        self._publish_run(ar.id)
        return self.db.get_run(ar.id)

    async def start_bench(
        self, suite_id: str, host_pk: int, user_params: dict[str, Any], label: str | None, force: bool = False
    ) -> dict:
        """Prueba de rendimiento por componente: el agente lanza llama-bench."""
        suite = BENCH_SUITES.get(suite_id)
        if suite is None:
            raise RunError(404, f"Prueba de rendimiento desconocida: {suite_id}")
        state = self.monitor.states.get(host_pk)
        if state is None:
            raise RunError(404, "Equipo no registrado")
        if state.status != "online":
            raise RunError(409, "El agente del equipo no está en línea")
        if any(a.host_pk == host_pk and a.bench_spec is not None for a in self.active.values()):
            raise RunError(409, "Ya hay un llama-bench en marcha en este equipo")
        params = suite.params(user_params)
        model_path = params.get("model")
        if not isinstance(model_path, str) or not model_path:
            raise RunError(422, "Elige un modelo (GGUF)")
        for key, lo, hi in (("n_prompt", 0, 65536), ("n_gen", 0, 8192)):
            vals = params.get(key)
            if not isinstance(vals, list) or not vals or not all(isinstance(v, int) and lo <= v <= hi for v in vals):
                raise RunError(422, f"'{key}': lista de enteros entre {lo} y {hi}")
        if not isinstance(params.get("repetitions"), int) or not 1 <= params["repetitions"] <= 50:
            raise RunError(422, "'repetitions' entre 1 y 50")
        for key in ("baseline_s", "cooldown_s", "timeout_s"):
            lo, hi = LIMITS[key]
            try:
                params[key] = int(float(params.get(key) or 0))
            except (TypeError, ValueError) as exc:
                raise RunError(422, f"'{key}' debe ser un número") from exc
            if not lo <= params[key] <= hi:
                raise RunError(422, f"'{key}' fuera de rango ({lo}–{hi})")

        try:
            g = (await self.monitor.agent.get(state, "/gguf", {"path": model_path}, timeout=GGUF_TIMEOUT_S))["gguf"]
            listed = await self.monitor.agent.get(state, "/bench/devices", timeout=BENCH_DEVICES_TIMEOUT_S)
        except AgentError as exc:
            raise RunError(409, f"Agente: {exc.message}") from exc
        if g.get("general_type") == "mmproj" or g.get("architecture") == "clip":
            raise RunError(422, "Es un proyector multimodal (mmproj), no un modelo")
        model = {k: g.get(k) for k in BENCH_MODEL_KEYS}
        by_id = {d["device_id"]: d for d in listed.get("devices", []) if d.get("device_id")}
        gpus_info = [d for d in (state.info or {}).get("devices", []) if d.get("kind") == "gpu"]

        raw_ids = params.get("device_ids") or []
        if not isinstance(raw_ids, list):
            raise RunError(422, "'device_ids' debe ser una lista")
        is_cpu = suite.id == "bench-cpu" or "cpu" in raw_ids
        gpu_ids = [] if is_cpu else [i for i in raw_ids if i != "cpu"]
        if suite.id == "bench-ts" and not gpu_ids:
            gpu_ids = list(by_id)
        if suite.id == "bench-dispositivo" and not is_cpu and len(gpu_ids) != 1:
            raise RunError(422, "Elige un único dispositivo")
        missing = [i for i in gpu_ids if i not in by_id]
        if missing:
            raise RunError(422, f"llama-bench no ve estas GPU: {', '.join(missing)}")
        if suite.min_gpus and len(gpu_ids) < suite.min_gpus:
            raise RunError(422, f"Hacen falta al menos {suite.min_gpus} GPU")
        names = [by_id[i]["name"] for i in gpu_ids]

        if suite.sweep and not params.get("sweep"):
            host = state.public().get("host") or {}
            if suite.sweep == "threads":
                params["sweep"] = default_threads(host.get("cpu_cores"), host.get("cpu_threads"))
            elif suite.sweep == "n_gpu_layers":
                params["sweep"] = default_ngl(g.get("block_count"))
            elif suite.sweep == "tensor_split":
                params["sweep"] = default_ts([float(by_id[i].get("total_mib") or 0) for i in gpu_ids])
        params.update(model=model_path, device_ids=["cpu"] if is_cpu else gpu_ids)
        try:
            spec = build_spec(suite, params, model_path, names, is_cpu)
        except BenchSpecError as exc:
            raise RunError(422, str(exc)) from exc

        if not force:
            self._bench_precheck(state, suite, g, params, gpu_ids, is_cpu)

        overrides = self.db.get_setting("thresholds", {}) or {}
        watch_ids = gpu_ids or ([] if is_cpu else [d["device_id"] for d in gpus_info])
        watch = {
            d["device_id"]: {"name": d.get("name"), **thresholds_for(d, overrides)}
            for d in gpus_info
            if d["device_id"] in watch_ids
        }
        snapshot = {
            "engine": "llama-bench",
            "exe": listed.get("exe"),
            "version": listed.get("version"),
            "simulated": listed.get("simulated"),
            "model": model,
            "model_file": model_path.replace("\\", "/").rsplit("/", 1)[-1],
            "devices": [{"device_id": i, "bench_name": by_id[i]["name"]} for i in gpu_ids],
            "cpu_only": is_cpu,
            "spec": spec,
        }
        run = self.db.create_run(
            kind="bench",
            suite=suite.id,
            suite_version=suite.version,
            suite_hash=suite.content_hash(params),
            label=label or None,
            status="running",
            host_pk=state.pk,
            endpoint_id=None,
            params=params,
            servers_snapshot=snapshot,
            host_snapshot={**state.public(), "thresholds": watch},
            started_at=time.time(),
        )
        ar = ActiveRun(id=run["id"], suite=suite, host_pk=state.pk, endpoint=None, params=params, watch=watch,
                       bench_spec=spec, bench_model=model)  # fmt: skip
        self.active[ar.id] = ar
        ar.task = asyncio.create_task(self._execute(ar), name=f"run-{ar.id}")
        self._publish_run(ar.id)
        return self.db.get_run(ar.id)

    def _bench_precheck(
        self, state: HostState, suite: BenchSuite, g: dict, params: dict, gpu_ids: list[str], is_cpu: bool
    ) -> None:
        """Avisos que se pueden saltar con `force`: servidor ocupando la tarjeta o modelo que no cabe."""
        busy = []
        for ep in self.db.list_endpoints(state.pk):
            if ep["status"] not in ("listo", "cargando"):
                continue
            derived = (ep.get("snapshot") or {}).get("derived") or {}
            if str(derived.get("model_path") or "none").lower() == "none" and not derived.get("n_ctx_slot"):
                continue  # responde pero sin modelo cargado (p. ej. modo router): no ocupa la tarjeta
            used = {u["device_id"] for u in (ep.get("snapshot") or {}).get("devices", [])}
            if is_cpu or not gpu_ids or not used or used & set(gpu_ids):
                busy.append(ep.get("alias") or ep["base_url"])
        if busy:
            raise RunError(
                409,
                f"Hay un servidor en marcha ({', '.join(busy)}): ocupa memoria y cómputo y falsearía el resultado. "
                "Páralo o lanza igualmente.",
            )
        if suite.id in ("bench-dispositivo", "bench-ts") and not is_cpu and gpu_ids:
            ctx = max(params["n_prompt"]) + max(params["n_gen"])
            try:
                est = estimate(g, FitParams(ctx=max(ctx, 1), kv_type=params.get("cache_type_k") or "f16"))
            except FitError:
                return
            if est.get("kind") != "model":
                return
            gpus = [x for x in gpus_from_state(state.info, state.metrics) if x["device_id"] in gpu_ids]
            verdict = fit(est, gpus, None)
            if verdict.get("verdict") not in ("gpu", "split", "unknown"):
                need = verdict.get("need_full_gpu") or 0
                free = sum(x["free_mib"] or 0 for x in gpus) * 1024 * 1024
                raise RunError(
                    409,
                    f"ESTIMADO: el modelo necesita {need / 1024**3:.1f} GiB y hay {free / 1024**3:.1f} GiB libres "
                    "en la GPU elegida. Prueba la curva -ngl o lanza igualmente.",
                )

    async def wait(self, run_id: int) -> None:
        """Espera a que termine un run en marcha (vuelve enseguida si ya terminó)."""
        ar = self.active.get(run_id)
        if ar and ar.task:
            await asyncio.shield(ar.task)

    def is_active(self, run_id: int) -> bool:
        return run_id in self.active

    async def cancel(self, run_id: int) -> None:
        ar = self.active.get(run_id)
        if ar is None:
            raise RunError(409, "La prueba no está en marcha")
        ar.user_cancel = True
        self._halt(ar)

    async def shutdown(self) -> None:
        for ar in list(self.active.values()):
            ar.user_cancel = True
            self._halt(ar)
            if ar.task:
                try:
                    await asyncio.wait_for(ar.task, timeout=5)
                except (TimeoutError, asyncio.CancelledError):
                    pass

    # --- ejecución ---------------------------------------------------------

    def _watch_devices(self, state: HostState, ep: dict, overrides: dict) -> dict[str, dict[str, Any]]:
        devices = (state.info or {}).get("devices", [])
        gpus = {d["device_id"]: d for d in devices if d.get("kind") == "gpu"}
        linked = [u["device_id"] for u in (ep["snapshot"] or {}).get("devices", []) if u["device_id"] in gpus]
        ids = linked or list(gpus)  # sin asociación conocida se vigilan todas las GPU del equipo
        return {i: {"name": gpus[i].get("name"), **thresholds_for(gpus[i], overrides)} for i in ids}

    def _halt(self, ar: ActiveRun) -> None:
        ar.stop.set()
        for w in ar.workers:
            w.cancel()

    async def _sleep_phase(self, ar: ActiveRun, phase: str, seconds: float) -> None:
        ar.phase = phase
        if phase == "reposo":
            self._boundary_sample(ar)  # lectura inicial en reposo
        self._publish_live(ar)
        if seconds > 0 and not ar.stop.is_set():
            try:
                await asyncio.wait_for(ar.stop.wait(), timeout=seconds)
            except TimeoutError:
                pass

    async def _execute(self, ar: ActiveRun) -> None:
        status, error = "done", None
        ticker = None
        try:
            await self._sleep_phase(ar, "reposo", float(ar.params.get("baseline_s") or 0))
            if not ar.stop.is_set():
                ar.phase = "carga"
                ar.load_start = time.time()
                if ar.suite.mode == "bench":
                    self._publish_live(ar)
                    await self._run_bench(ar)
                else:
                    ticker = asyncio.create_task(self._ticker(ar))
                    if ar.suite.mode == "items":
                        await self._run_items(ar)
                    else:
                        await self._run_duration(ar)
                ar.load_end = time.time()
                self._boundary_sample(ar)  # última lectura dentro de la carga
                if ticker:
                    ticker.cancel()
                    await self._tick(ar)  # último segundo parcial
            if not ar.user_cancel and not ar.abort_reason:
                await self._sleep_phase(ar, "enfriamiento", float(ar.params.get("cooldown_s") or 0))
        except Exception as exc:  # el run se guarda como error, el servidor sigue
            log.exception("Run %s falló", ar.id)
            status, error = "error", f"{type(exc).__name__}: {exc}"
        finally:
            if ticker:
                ticker.cancel()
            ar.load_end = ar.load_end or (time.time() if ar.load_start else None)
            if ar.abort_reason:
                status = "aborted"
            elif ar.user_cancel:
                status = "cancelled"
            elif status == "done" and ar.requests_done and ar.requests_error == ar.requests_done:
                status, error = "error", "Todas las peticiones fallaron (ver ítems)"
            elif status == "done" and ar.bench_error:
                status, error = "error", ar.bench_error
            summary = stats.run_summary(
                self.db.list_items(ar.id),
                self.db.list_tps(ar.id),
                self.db.list_samples(ar.id),
                (ar.load_start, ar.load_end),
            )
            summary["thresholds"] = ar.watch
            summary["phases"] = {"load_start": ar.load_start, "load_end": ar.load_end}
            if isinstance(ar.suite, BenchSuite):
                summary.update(bench_summary(ar.suite, self.db.list_bench_rows(ar.id)))
            self.db.update_run(
                ar.id,
                status=status,
                error=error,
                abort_reason=ar.abort_reason,
                finished_at=time.time(),
                summary=summary,
            )
            self.active.pop(ar.id, None)
            self._publish_run(ar.id)

    async def _run_items(self, ar: ActiveRun) -> None:
        prompts = ar.params["prompts"]
        repeats = int(ar.params.get("repeats") or 1)
        idx = 0
        for r in range(repeats):
            for i, prompt in enumerate(prompts):
                if ar.stop.is_set():
                    return
                name = f"prompt {i + 1}" + (f" · rep {r + 1}" if repeats > 1 else "")
                task = asyncio.create_task(self._request(ar, idx, name, prompt, live=True))
                ar.workers = [task]
                try:
                    await task
                except asyncio.CancelledError:
                    if not ar.stop.is_set():
                        raise
                    return
                idx += 1

    async def _run_bench(self, ar: ActiveRun) -> None:
        """Lanza llama-bench en el agente y recoge las filas según salen."""
        state = self.monitor.states.get(ar.host_pk)
        assert isinstance(ar.suite, BenchSuite)
        if state is None:
            ar.bench_error = "Equipo no registrado"
            return
        try:
            await self.monitor.agent.post(state, "/bench", ar.bench_spec)
        except AgentError as exc:
            ar.bench_error = f"El agente no pudo lanzar llama-bench: {exc.message}"
            return
        failures = 0
        while True:
            stopping = ar.stop.is_set()
            if stopping:  # cancelar y recoger lo que ya hubiera salido
                try:
                    await self.monitor.agent.post(state, "/bench/cancel")
                except AgentError:
                    pass
            try:
                body = await self.monitor.agent.get(state, "/bench", {"since": ar.bench_rows})
                failures = 0
            except AgentError as exc:
                failures += 1
                if stopping:
                    return
                if failures >= 10:
                    ar.bench_error = f"Se perdió el contacto con el agente: {exc.message}"
                    return
                await self._wait_stop(ar, BENCH_POLL_S)
                continue
            job = body.get("job") or {}
            for raw in job.get("rows") or []:
                row = normalize_row(ar.suite, raw, ar.bench_model or {})
                self.db.add_bench_row(ar.id, ar.bench_rows, row)
                public = {k: v for k, v in row.items() if k != "raw"}
                self.hub.publish("bench_row", {"run": ar.id, "idx": ar.bench_rows, **public})
                ar.bench_rows += 1
            if stopping:
                return
            if job.get("status") != "running":
                if job.get("status") == "error":
                    ar.bench_error = job.get("error") or "llama-bench falló"
                elif not ar.bench_rows:
                    ar.bench_error = "llama-bench terminó sin resultados"
                return
            self._publish_live(ar)
            await self._wait_stop(ar, BENCH_POLL_S)

    async def _wait_stop(self, ar: ActiveRun, seconds: float) -> None:
        try:
            await asyncio.wait_for(ar.stop.wait(), timeout=seconds)
        except TimeoutError:
            pass

    async def _run_duration(self, ar: ActiveRun) -> None:
        deadline = time.time() + float(ar.params["duration_s"])
        topics = ar.suite.prompts
        counter = {"n": 0}

        async def worker(slot: int) -> None:
            while not ar.stop.is_set() and time.time() < deadline:
                n = counter["n"]
                counter["n"] += 1
                prompt = topics[n % len(topics)]
                await self._request(ar, n, f"petición {n + 1} · slot {slot + 1}", prompt, live=slot == 0)

        ar.workers = [asyncio.create_task(worker(s)) for s in range(int(ar.params.get("parallel") or 1))]
        # Al llegar la hora no se lanzan más peticiones; las que están en curso se cortan
        remaining = max(0.0, deadline - time.time())
        try:
            await asyncio.wait_for(asyncio.gather(*ar.workers, return_exceptions=True), timeout=remaining + 0.5)
        except TimeoutError:
            for w in ar.workers:
                w.cancel()
            await asyncio.gather(*ar.workers, return_exceptions=True)

    async def _request(self, ar: ActiveRun, idx: int, name: str, prompt: str, live: bool) -> None:
        payload = payload_for(ar.params, prompt)
        started = time.time()
        if live:
            ar.live_text = ""

        def on_text(kind: str, text: str) -> None:
            ar.tokens += 1
            if live and kind == "content" and len(ar.live_text) < LIVE_TEXT_MAX:
                ar.live_text += text
                ar.live_dirty = True

        result: ChatResult | None = None
        try:
            result = await stream_chat(
                self.client, ar.endpoint["base_url"], payload, on_text, float(ar.params["timeout_s"])
            )
        except asyncio.CancelledError:
            self._save_item(ar, idx, name, prompt, None, started, CUT_MSG)
            raise
        self._save_item(ar, idx, name, prompt, result, started, result.error)

    def _save_item(
        self,
        ar: ActiveRun,
        idx: int,
        name: str,
        prompt: str,
        res: ChatResult | None,
        started: float,
        error: str | None,
    ) -> None:
        metrics = res.metrics() if res else {}
        ar.requests_done += 1
        if error and error != CUT_MSG:
            ar.requests_error += 1
        self.db.add_item(
            ar.id,
            idx,
            name=name,
            prompt=prompt,
            response=res.content if res else None,
            reasoning=(res.reasoning or None) if res else None,
            metrics=metrics,
            error=error,
            started_at=started,
            finished_at=time.time(),
        )
        self.hub.publish(
            "run_item",
            {"run": ar.id, "idx": idx, "name": name, "error": error, "metrics": metrics},
        )

    async def _ticker(self, ar: ActiveRun) -> None:
        while True:
            await asyncio.sleep(1.0)
            await self._tick(ar)

    async def _tick(self, ar: ActiveRun) -> None:
        now = time.time()
        delta = ar.tokens - ar.tokens_at_tick
        ar.tokens_at_tick = ar.tokens
        dt = max(1e-6, now - (ar.last_tick or ar.load_start or now))
        ar.last_tick = now
        if ar.load_start is not None:
            self.db.add_tps(ar.id, now, delta, delta / dt)
        self._publish_live(ar, tps=delta / dt)

    # --- telemetría ----------------------------------------------------------

    def _boundary_sample(self, ar: ActiveRun) -> None:
        """Guarda la última lectura conocida al cambiar de fase: cada fase tiene al menos una muestra."""
        state = self.monitor.states.get(ar.host_pk)
        if state is None or not state.metrics or state.status != "online":
            return
        devices = dict(state.metrics.get("devices") or {})
        if state.metrics.get("ram"):
            devices["ram"] = state.metrics["ram"]
        self.db.add_samples(ar.id, time.time(), ar.phase, devices)

    def _on_metrics(self, state: HostState, snap: dict[str, Any]) -> None:
        for ar in list(self.active.values()):
            if ar.host_pk != state.pk:
                continue
            devices = dict(snap.get("devices") or {})
            if snap.get("ram"):
                devices["ram"] = snap["ram"]
            self.db.add_samples(ar.id, time.time(), ar.phase, devices)
            for dev_id, lim in ar.watch.items():
                temp = (devices.get(dev_id) or {}).get("temp_c")
                if isinstance(temp, (int, float)):
                    ar.max_temp[dev_id] = max(ar.max_temp.get(dev_id, temp), temp)
                    if ar.phase == "carga" and temp >= lim["crit"] and not ar.abort_reason:
                        ar.abort_reason = (
                            f"{lim.get('name') or dev_id}: {temp:.0f} °C ≥ {lim['crit']} °C "
                            f"(umbral {lim.get('source')})"
                        )
                        log.warning("Run %s abortado: %s", ar.id, ar.abort_reason)
                        self._halt(ar)
            self._publish_live(ar)

    # --- eventos -------------------------------------------------------------

    def _publish_run(self, run_id: int) -> None:
        run = self.db.get_run(run_id)
        if run:
            self.hub.publish("run", _run_public(run))

    def _publish_live(self, ar: ActiveRun, tps: float | None = None) -> None:
        payload: dict[str, Any] = {
            "run": ar.id,
            "phase": ar.phase,
            "t": time.time(),
            "elapsed_s": time.time() - ar.started,
            "load_elapsed_s": time.time() - ar.load_start if ar.load_start else None,
            "tokens": ar.tokens,
            "requests_done": ar.requests_done,
            "requests_error": ar.requests_error,
            "max_temp": ar.max_temp,
            "abort_reason": ar.abort_reason,
            "bench_rows": ar.bench_rows if ar.bench_spec is not None else None,
        }
        if tps is not None:
            payload["tps"] = tps
        if ar.live_dirty:
            payload["text"] = ar.live_text
            ar.live_dirty = False
        self.hub.publish("run_live", payload)


def _run_public(run: dict[str, Any]) -> dict[str, Any]:
    """Run sin las fotos grandes (para listas y eventos)."""
    return {k: v for k, v in run.items() if k not in ("servers_snapshot", "host_snapshot")}
