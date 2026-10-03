"""Registro de proveedores de telemetría.

Para añadir un fabricante: crear su módulo en este paquete y añadir la clase a
`GPU_PROVIDERS` (o a `SYSTEM_PROVIDERS` si mide CPU/RAM).
"""

from agent.providers.base import TelemetryProvider
from agent.providers.null import NullProvider

GPU_PROVIDERS: list[type[TelemetryProvider]] = []
SYSTEM_PROVIDERS: list[type[TelemetryProvider]] = []


def detect_providers() -> list[TelemetryProvider]:
    """Instancia los proveedores disponibles en este equipo.

    Si no hay ningún proveedor de GPU disponible se usa `NullProvider`, de modo
    que un equipo solo con CPU funciona igual.
    """
    gpus = [cls() for cls in GPU_PROVIDERS if cls.available()]
    system = [cls() for cls in SYSTEM_PROVIDERS if cls.available()]
    return (gpus or [NullProvider()]) + system


__all__ = ["TelemetryProvider", "NullProvider", "detect_providers", "GPU_PROVIDERS", "SYSTEM_PROVIDERS"]
