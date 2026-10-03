from pathlib import Path

import pytest

from agent import throttle
from agent.providers.nvidia import (
    INFO_FIELDS,
    SAMPLE_FIELDS,
    NvidiaProvider,
    NvidiaSmi,
    convert,
    normalize_bus_id,
    parse_temperature_limits,
)

FIX = Path(__file__).parent.parent / "fixtures" / "nvidia"
UUID_A = "GPU-00000000-0000-0000-0000-000000000001"
UUID_B = "GPU-00000000-0000-0000-0000-000000000002"

# Valores por campo de nvidia-smi para dos GPUs (A con todo, B pasiva y antigua).
VALUES = {
    "index": ["0", "1"],
    "uuid": [UUID_A, UUID_B],
    "name": ["Prueba A 12GB", "Prueba B 24GB"],
    "pci.bus_id": ["00000000:08:00.0", "00000000:09:00.0"],
    "memory.total": ["12288", "24576"],
    "driver_version": ["580.00", "580.00"],
    "power.limit": ["170.00", "250.00"],
    "power.max_limit": ["170.00", "250.00"],
    "compute_cap": ["8.6", "5.2"],
    "driver_model.current": ["WDDM", "[N/A]"],
    "temperature.gpu": ["48", "71"],
    "power.draw": ["25.09", "[N/A]"],
    "utilization.gpu": ["44", "97"],
    "utilization.memory": ["40", "88"],
    "memory.used": ["1937", "19000"],
    "clocks.sm": ["390", "1000"],
    "clocks.mem": ["405", "3004"],
    "fan.speed": ["0", "[N/A]"],
    "pstate": ["P8", "P0"],
    "clocks_event_reasons.active": ["0x0000000000000001", "0x0000000000000060"],
    "clocks_throttle_reasons.active": ["0x0000000000000001", "0x0000000000000060"],
    "pcie.link.gen.current": ["1", "3"],
    "pcie.link.width.current": ["16", "16"],
}

TEMP_Q = """
==============NVSMI LOG==============
Attached GPUs                                          : 2
GPU 00000000:08:00.0
    Temperature
        GPU Current Temp                               : 48 C
        GPU Shutdown Temp                              : 98 C
        GPU Slowdown Temp                              : 95 C
        GPU Target Temperature                         : 83 C

GPU 00000000:09:00.0
    Temperature
        GPU Current Temp                               : 71 C
        GPU Shutdown Temp                              : N/A
        GPU Slowdown Temp                              : N/A
"""


class FakeSmi:
    """Simula nvidia-smi: rechaza los campos de `invalid` como lo hace el driver real."""

    def __init__(self, invalid=(), apps="", fail=False):
        self.invalid = set(invalid)
        self.apps = apps
        self.fail = fail
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if self.fail:
            return 9, "", "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver."
        if args[1:] == ["-q", "-d", "TEMPERATURE"]:
            return 0, TEMP_Q, ""
        if args[1].startswith("--query-compute-apps"):
            return 0, self.apps, ""
        fields = args[1].removeprefix("--query-gpu=").split(",")
        for f in fields:
            if f in self.invalid or f not in VALUES:
                return 2, f'Field "{f}" is not a valid field to query.\n\n', ""
        rows = [", ".join(VALUES[f][i] for f in fields) for i in range(2)]
        return 0, "\n".join(rows) + "\n", ""


def provider(**kw):
    fake = FakeSmi(**kw)
    return NvidiaProvider(NvidiaSmi("nvidia-smi", runner=fake)), fake


def test_mensaje_real_de_campo_invalido():
    text = (FIX / "error_invalid_field.txt").read_text(encoding="utf-8")
    from agent.providers.nvidia import INVALID_FIELD_RE

    assert INVALID_FIELD_RE.search(text).group(1) == "campo.falso"


def test_dispositivos_y_limites_termicos():
    prov, _ = provider()
    a, b = prov.devices()
    assert a.device_id == f"nvidia:{UUID_A}"
    assert (a.index, a.memory_total_mib, a.compute_capability, a.driver_model) == (0, 12288, "8.6", "WDDM")
    assert (a.temp_slowdown_c, a.temp_shutdown_c) == (95.0, 98.0)
    assert b.temp_slowdown_c is None
    assert b.driver_model is None
    # La GPU pasiva declara lo que no expone, sin inventar ceros
    assert {"fan_pct", "power_w", "temp_slowdown_c", "driver_model"} <= set(b.fields_unavailable)
    assert "fan_pct" not in a.fields_unavailable  # 0 % es un dato real, no ausencia


def test_muestra_convierte_na_a_null_y_decodifica_throttle():
    prov, _ = provider()
    s = prov.sample()
    a, b = s[f"nvidia:{UUID_A}"], s[f"nvidia:{UUID_B}"]
    assert (a.temp_c, a.power_w, a.fan_pct, a.pstate, a.pcie_gen) == (48.0, 25.09, 0.0, "P8", 1)
    assert a.throttle == ["gpu_idle"]
    assert b.power_w is None and b.fan_pct is None
    assert b.throttle_mask == 0x60
    assert b.throttle == ["sw_thermal", "hw_thermal"]


def test_driver_antiguo_usa_el_alias_de_throttle():
    prov, fake = provider(invalid={"clocks_event_reasons.active"})
    s = prov.sample()
    assert s[f"nvidia:{UUID_B}"].throttle_mask == 0x60
    assert any("clocks_throttle_reasons.active" in c[1] for c in fake.calls)
    assert "throttle_mask" not in prov.smi.unavailable


def test_campo_sin_alias_se_descarta_y_se_reintenta():
    prov, _ = provider(invalid={"pcie.link.gen.current", "compute_cap"})
    [a, _] = prov.devices()
    s = prov.sample()[f"nvidia:{UUID_A}"]
    assert s.pcie_gen is None and s.temp_c == 48.0
    assert a.compute_capability is None
    assert {"pcie_gen", "compute_capability"} <= set(a.fields_unavailable)


def test_resolucion_se_cachea():
    prov, fake = provider(invalid={"fan.speed"})
    prov.sample()
    n = len(fake.calls)
    prov.sample()
    assert len(fake.calls) == n + 1  # una sola llamada por muestra tras resolver


def test_driver_caido_lanza_error_legible():
    prov, _ = provider(fail=True)
    with pytest.raises(RuntimeError, match="couldn't communicate"):
        prov.sample()


def test_procesos_wddm_sin_vram():
    apps = (FIX / "compute_apps_wddm.csv").read_text(encoding="utf-8")
    prov, _ = provider(apps=apps)
    procs = prov.processes()
    assert procs[2116][0].device_id == f"nvidia:{UUID_A}"
    assert procs[2116][0].mem_used_mib is None


def test_limites_desde_salida_real():
    text = (FIX / "q_temperature_rtx3060_591.txt").read_text(encoding="utf-8")
    lim = parse_temperature_limits(text)
    assert lim["08:00.0"] == {"shutdown": 98.0, "slowdown": 95.0, "max_operating": 93.0, "target": 83.0}


@pytest.mark.parametrize(
    "raw,kind,expected",
    [
        ("[N/A]", "float", None),
        ("[Not Supported]", "int", None),
        ("", "str", None),
        ("170.00", "float", 170.0),
        ("16", "int", 16),
        ("25.1 W", "float", 25.1),
        ("0x60", "mask", 0x60),
        ("abc", "float", None),
    ],
)
def test_convert(raw, kind, expected):
    assert convert(raw, kind) == expected


def test_normalize_bus_id():
    assert normalize_bus_id("00000000:08:00.0") == normalize_bus_id("0000:08:00.0") == "08:00.0"


def test_throttle():
    assert throttle.decode(0) == []
    assert throttle.decode(None) is None
    assert throttle.decode(0x1000 | 0x4) == ["sw_power_cap", "unknown_0x1000"]
    assert throttle.is_throttling(0x1) is False  # reposo no es throttling
    assert throttle.is_throttling(0x40) is True
    assert throttle.parse_mask("[N/A]") is None


def test_especificaciones_sin_claves_duplicadas():
    for specs in (INFO_FIELDS, SAMPLE_FIELDS):
        keys = [s.key for s in specs]
        assert len(keys) == len(set(keys))


@pytest.mark.skipif(not NvidiaProvider.available(), reason="sin nvidia-smi")
def test_nvidia_smi_real_de_este_equipo():
    prov = NvidiaProvider()
    devs = prov.devices()
    assert devs, "nvidia-smi presente pero sin GPUs"
    sample = prov.sample()
    for d in devs:
        assert d.device_id in sample
        assert d.memory_total_mib and d.memory_total_mib > 0
