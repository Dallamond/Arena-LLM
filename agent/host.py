"""Identidad básica del equipo (sin datos de CPU/RAM: eso es del proveedor de sistema)."""

import hashlib
import platform
import socket
import sys
import uuid
from pathlib import Path

from agent.model import HostInfo


def _raw_machine_id() -> str | None:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
                return str(value)
        except OSError:
            return None
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            text = Path(path).read_text(encoding="ascii").strip()
        except OSError:
            continue
        if text:
            return text
    return None


def host_id() -> str:
    """Identificador estable del equipo.

    Se publica un hash, no el identificador de máquina crudo. Sin identificador
    del sistema se recurre a nombre + MAC (estable salvo cambio de red).
    """
    raw = _raw_machine_id() or f"{socket.gethostname()}|{uuid.getnode():012x}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def host_info() -> HostInfo:
    return HostInfo(
        host_id=host_id(),
        hostname=socket.gethostname(),
        os=sys.platform.replace("win32", "windows"),
        os_version=platform.platform() or None,
    )
