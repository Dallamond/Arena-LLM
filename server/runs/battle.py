"""Batalla: los mismos prompts contra varios servidores (lados), en paralelo o uno detrás de otro.

Cada lado es un run normal de la suite `libre` (con su telemetría, resumen y foto de
configuración) marcado con `battle_id` y `side`. Lo común a todos los lados (prompts,
repeticiones, semilla, fases) se fija una sola vez: así la comparación es justa por
construcción. Por lado solo cambian los parámetros de muestreo y el prompt de sistema.
"""

import asyncio
import logging
import string
import time
from typing import Any

from server.db import Database
from server.hub import EventHub
from server.runs.manager import RunError, RunManager

log = logging.getLogger(__name__)

MAX_SIDES = 6
MODES = ("paralelo", "secuencial")
#: Lo que puede cambiar un lado. La semilla, los prompts y las fases son comunes.
SIDE_KEYS = (
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "repeat_penalty",
    "presence_penalty",
    "frequency_penalty",
    "max_tokens",
    "cache_prompt",
    "system",
    "extra",
)
COMMON_KEYS = ("seed", "repeats", "baseline_s", "cooldown_s", "timeout_s", *SIDE_KEYS)


def side_names(n: int) -> list[str]:
    return list(string.ascii_uppercase[:n])


def side_params(prompts: list[str], common: dict[str, Any], own: dict[str, Any]) -> dict[str, Any]:
    """Parámetros del run de un lado: comunes + los propios del lado (solo SIDE_KEYS)."""
    bad = sorted(set(own) - set(SIDE_KEYS))
    if bad:
        raise RunError(422, f"Un lado no puede cambiar {', '.join(bad)}: es común a toda la batalla")
    return {**{k: v for k, v in common.items() if k in COMMON_KEYS}, **own, "prompts": prompts}


class BattleManager:
    def __init__(self, db: Database, hub: EventHub, runs: RunManager):
        self.db = db
        self.hub = hub
        self.runs = runs
        self.tasks: dict[int, asyncio.Task] = {}
        self.cancelled: set[int] = set()

    async def start(
        self,
        mode: str,
        prompts: list[str],
        common: dict[str, Any],
        sides: list[dict[str, Any]],
        label: str | None,
    ) -> dict[str, Any]:
        if mode not in MODES:
            raise RunError(422, f"Modo desconocido: {mode}")
        prompts = [p.strip() for p in prompts if isinstance(p, str) and p.strip()]
        if not prompts:
            raise RunError(422, "Hace falta al menos un prompt")
        if not 2 <= len(sides) <= MAX_SIDES:
            raise RunError(422, f"Una batalla necesita entre 2 y {MAX_SIDES} lados")
        bad = sorted(set(common) - set(COMMON_KEYS))
        if bad:
            raise RunError(422, f"Parámetros comunes desconocidos: {', '.join(bad)}")
        endpoint_ids = [s.get("endpoint_id") for s in sides]
        if not all(isinstance(e, int) for e in endpoint_ids):
            raise RunError(422, "Cada lado necesita un servidor")
        if mode == "paralelo" and len(set(endpoint_ids)) < len(endpoint_ids):
            raise RunError(
                422, "En paralelo cada lado necesita su propio servidor; con el mismo servidor usa el modo secuencial"
            )
        for eid in set(endpoint_ids):
            ep = self.db.get_endpoint(eid)
            if ep is None:
                raise RunError(404, f"Servidor #{eid} no registrado")
            if ep["status"] != "listo":
                raise RunError(409, f"El servidor {ep['base_url']} no está listo (estado: {ep['status']})")
            if any(a.endpoint and a.endpoint["id"] == eid for a in self.runs.active.values()):
                raise RunError(409, f"Ya hay una prueba en marcha en {ep['base_url']}")
        names = side_names(len(sides))
        plan = []
        for name, s in zip(names, sides, strict=True):
            own = s.get("params") or {}
            if not isinstance(own, dict):
                raise RunError(422, f"Lado {name}: 'params' debe ser un objeto")
            plan.append(
                {
                    "side": name,
                    "endpoint_id": s["endpoint_id"],
                    "label": (s.get("label") or "").strip() or None,
                    "params": own,
                    "run_id": None,
                    "_full": side_params(prompts, common, own),
                }
            )

        battle = self.db.create_battle(
            label=(label or "").strip() or None,
            mode=mode,
            status="running",
            params={"prompts": prompts, "common": common},
            sides=[{k: v for k, v in p.items() if k != "_full"} for p in plan],
        )
        bid = battle["id"]
        try:
            if mode == "paralelo":
                for p in plan:
                    await self._start_side(bid, plan, p)
            else:
                await self._start_side(bid, plan, plan[0])  # el primero falla aquí, no en segundo plano
        except RunError:
            for p in plan:
                if p["run_id"] and self.runs.is_active(p["run_id"]):
                    await self.runs.cancel(p["run_id"])
            self.db.delete_battle(bid)
            raise
        self.tasks[bid] = asyncio.create_task(self._follow(bid, plan, mode), name=f"battle-{bid}")
        self._publish(bid)
        return self.public(bid)

    async def _start_side(self, bid: int, plan: list[dict[str, Any]], p: dict[str, Any]) -> None:
        battle_label = (self.db.get_battle(bid) or {}).get("label")
        # El run ya lleva battle_id y side: la etiqueta solo guarda los nombres que puso Lucas
        label = " · ".join(x for x in (p["label"], battle_label) if x) or None
        run = await self.runs.start("libre", p["endpoint_id"], p["_full"], label, battle_id=bid, side=p["side"])
        p["run_id"] = run["id"]
        self.db.update_battle(bid, sides=[{k: v for k, v in x.items() if k != "_full"} for x in plan])
        self._publish(bid)

    async def _follow(self, bid: int, plan: list[dict[str, Any]], mode: str) -> None:
        error = None
        try:
            if mode == "paralelo":
                await asyncio.gather(*(self.runs.wait(p["run_id"]) for p in plan if p["run_id"]))
            else:
                for i, p in enumerate(plan):
                    if i > 0:
                        if bid in self.cancelled:
                            break
                        try:
                            await self._start_side(bid, plan, p)
                        except RunError as exc:
                            error = f"Lado {p['side']}: {exc.message}"
                            break
                    await self.runs.wait(p["run_id"])
        except Exception as exc:  # la batalla queda como error; el servidor sigue
            log.exception("Batalla %s falló", bid)
            error = f"{type(exc).__name__}: {exc}"
        finally:
            statuses = [
                (self.db.get_run(p["run_id"]) or {}).get("status") if p["run_id"] else "no lanzado" for p in plan
            ]
            if bid in self.cancelled:
                status = "cancelled"
            elif error or "error" in statuses:
                status = "error"
            elif "aborted" in statuses:
                status = "aborted"
            elif "cancelled" in statuses or "no lanzado" in statuses:
                status = "cancelled"
            else:
                status = "done"
            self.db.update_battle(bid, status=status, error=error, finished_at=time.time())
            self.tasks.pop(bid, None)
            self.cancelled.discard(bid)
            self._publish(bid)

    async def cancel(self, bid: int) -> None:
        battle = self.db.get_battle(bid)
        if battle is None:
            raise RunError(404, "Batalla no encontrada")
        if bid not in self.tasks:
            raise RunError(409, "La batalla no está en marcha")
        self.cancelled.add(bid)
        for s in battle["sides"] or []:
            if s.get("run_id") and self.runs.is_active(s["run_id"]):
                await self.runs.cancel(s["run_id"])

    async def shutdown(self) -> None:
        for bid in list(self.tasks):
            self.cancelled.add(bid)
        for t in list(self.tasks.values()):
            t.cancel()

    def public(self, bid: int, with_items: bool = False) -> dict[str, Any]:
        battle = self.db.get_battle(bid)
        if battle is None:
            raise RunError(404, "Batalla no encontrada")
        runs = []
        for s in battle["sides"] or []:
            run = self.db.get_run(s["run_id"]) if s.get("run_id") else None
            if run is None:
                runs.append(None)
                continue
            pub = {k: v for k, v in run.items() if k != "host_snapshot"}
            if with_items:
                pub["items"] = self.db.list_items(run["id"])
            runs.append(pub)
        return {**battle, "runs": runs}

    def _publish(self, bid: int) -> None:
        battle = self.db.get_battle(bid)
        if battle:
            self.hub.publish("battle", battle)
