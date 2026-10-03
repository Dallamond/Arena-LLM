import shutil
import sys
from pathlib import Path

import pytest

from agent.host import enrich_host
from agent.model import DeviceInfo, HostInfo, RamSample
from agent.providers.cpu_ram import (
    CpuRamProvider,
    CpuTimes,
    _LinuxBackend,
    cpu_util,
    parse_cpuinfo,
    parse_meminfo,
    parse_proc_stat,
)

FIX = Path(__file__).parent.parent / "fixtures" / "linux"


def read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_uso_de_cpu_por_diferencia():
    a = parse_proc_stat(read("stat_1"))
    b = parse_proc_stat(read("stat_2"))
    assert cpu_util(a, b) == 60.0  # +500 ticks totales, +200 ociosos


def test_primera_lectura_no_inventa_uso():
    assert cpu_util(None, CpuTimes(idle=1, total=2)) is None


def test_sin_avance_de_tiempo_es_null():
    t = CpuTimes(idle=5, total=10)
    assert cpu_util(t, t) is None


def test_meminfo_usa_memavailable():
    ram = parse_meminfo(read("meminfo"))
    assert ram.total_mib == 32000.0
    assert ram.used_mib == 12000.0


def test_meminfo_kernel_antiguo_sin_memavailable():
    ram = parse_meminfo(read("meminfo_old_kernel"))
    assert ram.total_mib == 4000.0
    assert ram.used_mib == 2000.0  # total − (free + buffers + cached)


def test_meminfo_vacio_es_null():
    assert parse_meminfo("") == RamSample(used_mib=None, total_mib=None)


def test_cpuinfo_nucleos_hilos_y_frecuencia():
    static, freq = parse_cpuinfo(read("cpuinfo"))
    assert static.model == "CPU de prueba 2 nucleos"
    assert static.cores == 2
    assert static.threads == 4
    assert freq == 2150.0


def test_cpuinfo_arm_sin_modelo_ni_core_id():
    static, freq = parse_cpuinfo(read("cpuinfo_arm"))
    assert static.model is None
    assert static.cores is None
    assert static.threads == 2
    assert freq is None


def test_proveedor_con_backend_linux_de_fixtures(tmp_path):
    for src, dst in [("stat_1", "stat"), ("meminfo", "meminfo"), ("cpuinfo", "cpuinfo")]:
        shutil.copy(FIX / src, tmp_path / dst)
    prov = CpuRamProvider(backend=_LinuxBackend(tmp_path), device_id="cpu:prueba")
    [dev] = prov.devices()
    assert (dev.kind, dev.name, dev.cores, dev.threads) == ("cpu", "CPU de prueba 2 nucleos", 2, 4)
    first = prov.sample()["cpu:prueba"]
    assert first.util_pct is None
    shutil.copy(FIX / "stat_2", tmp_path / "stat")
    assert prov.sample()["cpu:prueba"].util_pct == 60.0
    assert prov.ram().total_mib == 32000.0


def test_enrich_host():
    host = HostInfo(host_id="h", hostname="x", os="linux")
    cpu = DeviceInfo(device_id="cpu:h", provider="cpu", kind="cpu", name="CPU X", cores=6, threads=12)
    enrich_host(host, [cpu], RamSample(used_mib=1, total_mib=16303.6))
    assert (host.cpu_model, host.cpu_cores, host.cpu_threads, host.ram_total_mib) == ("CPU X", 6, 12, 16304)


@pytest.mark.skipif(not CpuRamProvider.available(), reason="sin backend nativo")
def test_backend_nativo_de_este_equipo():
    prov = CpuRamProvider()
    [dev] = prov.devices()
    assert dev.threads and dev.threads >= 1
    if sys.platform == "win32":
        assert dev.cores and dev.cores <= dev.threads
    prov.sample()
    util = prov.sample()[prov.device_id].util_pct
    assert util is None or 0 <= util <= 100
    ram = prov.ram()
    assert ram.total_mib > 0 and 0 < ram.used_mib <= ram.total_mib
