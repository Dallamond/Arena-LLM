"""Interfaz común de los proveedores de telemetría.

Cada fabricante (NVIDIA, AMD, Intel, Apple…) o recurso (CPU/RAM) implementa un
proveedor. El resto del agente solo habla con esta interfaz: añadir un
fabricante no debe tocar nada fuera de `providers/`.
"""

from abc import ABC, abstractmethod

from agent.model import DeviceInfo, DeviceSample, ProcessGpuUse, RamSample


class TelemetryProvider(ABC):
    #: Nombre corto y estable ("nvidia", "cpu", "null"…); prefijo de `device_id`.
    name: str = ""

    @classmethod
    def available(cls) -> bool:
        """¿Puede funcionar en este equipo? (herramienta presente, SO compatible…)."""
        return True

    @abstractmethod
    def devices(self) -> list[DeviceInfo]:
        """Dispositivos detectados con su ficha. Puede tardar; se llama al arrancar."""

    @abstractmethod
    def sample(self) -> dict[str, DeviceSample]:
        """Lectura actual por `device_id`. Debe ser rápida (se llama cada intervalo)."""

    def ram(self) -> RamSample | None:
        """Memoria del sistema, si este proveedor la mide. Solo uno debería hacerlo."""
        return None

    def processes(self) -> dict[int, list[ProcessGpuUse]]:
        """Qué procesos (pid) usan qué dispositivos, si el proveedor lo sabe."""
        return {}
