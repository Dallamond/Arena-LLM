"""Muestreo periódico en segundo plano.

`/metrics` devuelve siempre el último `Snapshot` en caché: así una petición no
lanza herramientas externas (p. ej. `nvidia-smi`) y varios clientes no
multiplican el coste.
"""

import logging
import threading
import time

from agent.model import DeviceInfo, Snapshot
from agent.providers.base import TelemetryProvider

log = logging.getLogger(__name__)


class Sampler:
    def __init__(self, providers: list[TelemetryProvider], interval_s: float = 1.0):
        if interval_s <= 0:
            raise ValueError("interval_s debe ser > 0")
        self.providers = providers
        self.interval_s = interval_s
        self._lock = threading.Lock()
        self._snapshot = Snapshot(interval_s=interval_s)
        self._devices: list[DeviceInfo] = []
        self._device_errors: dict[str, str] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def refresh_devices(self) -> list[DeviceInfo]:
        devices: list[DeviceInfo] = []
        errors: dict[str, str] = {}
        for p in self.providers:
            try:
                devices.extend(p.devices())
            except Exception as exc:  # un proveedor roto no tumba a los demás
                log.exception("Proveedor %s: fallo al detectar dispositivos", p.name)
                errors[p.name] = f"{type(exc).__name__}: {exc}"
        with self._lock:
            self._devices = devices
            self._device_errors = errors
        return devices

    def devices(self) -> tuple[list[DeviceInfo], dict[str, str]]:
        with self._lock:
            return list(self._devices), dict(self._device_errors)

    def sample_once(self) -> Snapshot:
        snap = Snapshot(t=time.time(), interval_s=self.interval_s)
        for p in self.providers:
            try:
                snap.devices.update(p.sample())
                ram = p.ram()
                if ram is not None:
                    snap.ram = ram
            except Exception as exc:
                log.exception("Proveedor %s: fallo al muestrear", p.name)
                snap.errors[p.name] = f"{type(exc).__name__}: {exc}"
        with self._lock:
            self._snapshot = snap
        return snap

    def latest(self) -> Snapshot:
        with self._lock:
            return self._snapshot

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="arena-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        next_t = time.monotonic()
        while not self._stop.is_set():
            self.sample_once()
            next_t += self.interval_s
            delay = next_t - time.monotonic()
            if delay < 0:  # el muestreo tardó más que el intervalo: no acumular retraso
                next_t = time.monotonic()
                delay = 0
            self._stop.wait(delay)
