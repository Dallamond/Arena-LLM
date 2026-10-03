from agent.model import DeviceInfo, DeviceSample
from agent.providers.base import TelemetryProvider


class NullProvider(TelemetryProvider):
    """Proveedor vacío: equipos sin GPU soportada. No inventa dispositivos ni datos."""

    name = "null"

    def devices(self) -> list[DeviceInfo]:
        return []

    def sample(self) -> dict[str, DeviceSample]:
        return {}
