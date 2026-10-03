"""Máscara de *clocks event reasons* (antes *throttle reasons*) de NVML/nvidia-smi."""

REASONS: dict[int, str] = {
    0x001: "gpu_idle",
    0x002: "applications_clocks",
    0x004: "sw_power_cap",
    0x008: "hw_slowdown",
    0x010: "sync_boost",
    0x020: "sw_thermal",
    0x040: "hw_thermal",
    0x080: "hw_power_brake",
    0x100: "display_clocks",
}

#: Bits que cuentan como *throttling* real (térmico o de potencia). Reposo y
#: ajustes de aplicación no cuentan.
THROTTLING_BITS = 0x004 | 0x008 | 0x020 | 0x040 | 0x080


def parse_mask(text: str | None) -> int | None:
    if text is None:
        return None
    text = text.strip()
    if not text or "N/A" in text or "Not Supported" in text:
        return None
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text)
    except ValueError:
        return None


def decode(mask: int | None) -> list[str] | None:
    if mask is None:
        return None
    names = [name for bit, name in REASONS.items() if mask & bit]
    unknown = mask & ~sum(REASONS)
    if unknown:
        names.append(f"unknown_0x{unknown:x}")
    return names


def is_throttling(mask: int | None) -> bool | None:
    return None if mask is None else bool(mask & THROTTLING_BITS)
