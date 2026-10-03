import json
import sys

import pytest

from agent.cmdline import REDACTED, parse_llama_server_args, split_windows_cmdline
from agent.model import ProcessGpuUse
from agent.processes import (
    LinuxProcessSource,
    RawProcess,
    ServerDetector,
    describe,
    parse_cim_json,
)
from agent.simulate import SimProcessSource


def parse(line: str):
    return parse_llama_server_args(line.split())


def test_flags_habituales_con_alias_cortos_y_largos():
    p = parse(
        "-m modelos/q.gguf -ngl 99 -c 8192 -ts 3,2 --parallel 4 -fa on -b 2048 -ub 512 "
        "--cache-type-k q8_0 -ctv q8_0 -t 6 --port 8081 --host 0.0.0.0 --mlock"
    )
    f = p.flags
    assert f["model"] == "modelos/q.gguf"
    assert (f["ngl"], f["ctx"], f["tensor_split"], f["parallel"]) == (99, 8192, "3,2", 4)
    assert (f["flash_attn"], f["batch"], f["ubatch"]) == ("on", 2048, 512)
    assert (f["cache_type_k"], f["cache_type_v"], f["threads"]) == ("q8_0", "q8_0", 6)
    assert (f["port"], f["host"], f["mlock"]) == (8081, "0.0.0.0", True)
    assert p.unknown == {}


def test_flash_attn_forma_antigua_sin_valor():
    p = parse("-fa -c 4096")
    assert p.flags["flash_attn"] == "on"
    assert p.flags["ctx"] == 4096


def test_forma_con_igual_y_ngl_textual():
    p = parse_llama_server_args(["--ctx-size=16384", "--n-gpu-layers=all", "--flash-attn=auto"])
    assert p.flags == {"ctx": 16384, "ngl": "all", "flash_attn": "auto"}


def test_override_tensor_repetible():
    p = parse(r"-ot blk\.1[0-9]\.ffn_.*=CPU -ot exps=CPU --n-cpu-moe 12")
    assert p.flags["override_tensor"] == [r"blk\.1[0-9]\.ffn_.*=CPU", "exps=CPU"]
    assert p.flags["n_cpu_moe"] == 12


def test_flags_desconocidos_se_guardan_tal_cual():
    p = parse("--rara 1 --otra --rope-scaling yarn --nueva x --nueva y")
    assert p.unknown == {"--rara": "1", "--otra": True, "--nueva": ["x", "y"]}
    assert p.flags["rope_scaling"] == "yarn"


def test_valor_negativo_no_es_un_flag():
    p = parse("--seed -1 -n -1")
    assert p.flags["seed"] == -1 and p.flags["n_predict"] == -1


def test_valor_no_numerico_no_se_inventa():
    p = parse("-c mucho")
    assert p.flags["ctx"] == "mucho"


def test_flag_conocido_sin_valor():
    p = parse("--port")
    assert "port" not in p.flags and p.unknown == {"--port": True}


def test_api_key_oculta():
    p = parse_llama_server_args(["--api-key", "s3creto", "--port", "8081", "--api-key=otro"])
    assert p.flags["api_key"] == REDACTED
    assert "s3creto" not in p.argv_redacted and "otro" not in " ".join(p.argv_redacted)
    assert p.argv_redacted == ["--api-key", REDACTED, "--port", "8081", f"--api-key={REDACTED}"]


def test_argv_redactado_conserva_el_resto():
    argv = ["-m", "a.gguf", "-fa", "-c", "4096", "--jinja"]
    assert parse_llama_server_args(argv).argv_redacted == argv


WIN_CASES = [
    (
        r'"C:\Program Files\llama\llama-server.exe" -m "D:\mis modelos\a b.gguf" --port 8081',
        [r"C:\Program Files\llama\llama-server.exe", "-m", r"D:\mis modelos\a b.gguf", "--port", "8081"],
    ),
    (r"llama-server.exe -m D:\m\x.gguf  -c   4096", ["llama-server.exe", "-m", r"D:\m\x.gguf", "-c", "4096"]),
    (r'a.exe "x\"y" "z\\" w', ["a.exe", 'x"y', "z\\", "w"]),
    (r'a.exe "" b', ["a.exe", "", "b"]),
    (r'a.exe -ot "blk\.[0-9]=CPU"', ["a.exe", "-ot", r"blk\.[0-9]=CPU"]),
]


@pytest.mark.parametrize("line,expected", WIN_CASES)
def test_split_windows(line, expected):
    assert split_windows_cmdline(line) == expected


@pytest.mark.skipif(sys.platform != "win32", reason="solo Windows")
@pytest.mark.parametrize("line,_", WIN_CASES)
def test_split_windows_igual_que_commandlinetoargvw(line, _):
    import ctypes
    from ctypes import wintypes

    shell32 = ctypes.WinDLL("shell32")
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    n = ctypes.c_int()
    ptr = shell32.CommandLineToArgvW(line, ctypes.byref(n))
    expected = [ptr[i] for i in range(n.value)]
    ctypes.windll.kernel32.LocalFree(ptr)
    assert split_windows_cmdline(line) == expected


def test_cim_json_un_objeto_y_filtrado():
    one = {
        "pid": 10,
        "exe": r"C:\l\llama-server.exe",
        "cmd": r'"C:\l\llama-server.exe" -c 2048',
        "start": "x",
    }
    assert [p.pid for p in parse_cim_json(json.dumps(one))] == [10]
    other = {"pid": 11, "exe": r"C:\l\llama-server-tool.exe", "cmd": "llama-server-tool.exe"}
    assert parse_cim_json(json.dumps([one, other]))[0].argv[1:] == ["-c", "2048"]
    assert [p.pid for p in parse_cim_json(json.dumps([one, other]))] == [10]
    assert parse_cim_json("") == []


def test_cim_sin_ruta_de_ejecutable_usa_argv0():
    item = {"pid": 12, "exe": None, "cmd": "llama-server -m x.gguf"}
    [p] = parse_cim_json(json.dumps(item))
    assert p.exe == "llama-server"


def test_fuente_linux_desde_proc_falso(tmp_path):
    (tmp_path / "stat").write_text("cpu 1 2 3 4\nbtime 1759000000\n")
    for pid, argv in [
        (100, ["/opt/llama-server", "-m", "a.gguf", "--port", "9000"]),
        (200, ["/usr/bin/bash"]),
    ]:
        d = tmp_path / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        (d / "stat").write_text(f"{pid} (proc) S " + " ".join(["0"] * 18) + " 500 0 0\n")
    (tmp_path / "300").mkdir()  # proceso terminado: sin cmdline
    [p] = LinuxProcessSource(tmp_path).list()
    assert p.pid == 100 and p.argv[-1] == "9000"
    assert p.started_at and p.started_at.startswith("2025-09-27")


def test_describe_puerto_por_defecto_y_gpu():
    proc = RawProcess(pid=7, exe="/x/llama-server", argv=["/x/llama-server", "-m", r"D:\m\q.gguf"])
    s = describe(proc, {7: [ProcessGpuUse("nvidia:GPU-1", None)]})
    assert (s.port, s.port_source, s.host) == (8080, "default", "127.0.0.1")
    assert s.model_file == "q.gguf"
    assert s.gpu_link == "compute-apps"
    s2 = describe(RawProcess(pid=8, exe=None, argv=["llama-server", "--port", "9001"]), {})
    assert (s2.port, s2.port_source, s2.gpu_link, s2.model_file) == (9001, "flag", None, None)


def test_detector_cachea_y_aisla_errores():
    class Boom(SimProcessSource):
        calls = 0

        def list(self):
            Boom.calls += 1
            raise PermissionError("denegado")

    det = ServerDetector(Boom([]), [], ttl_s=60)
    r1 = det.detect()
    r2 = det.detect()
    assert r1 is r2 and Boom.calls == 1
    assert r1["servers"] == [] and "denegado" in r1["errors"]["processes"]


def test_flags_negativos_de_builds_recientes():
    p = parse("-no-kvu --no-jinja --no-cache-prompt -mmdev none -sm tensor")
    assert p.flags["no_kv_unified"] and p.flags["no_jinja"] and p.flags["no_cache_prompt"]
    assert p.flags["mmproj_device"] == "none" and p.flags["split_mode"] == "tensor"
    assert p.unknown == {}


def test_linea_real_b11379():
    # Capturada del llama-server real (03/10/2026, build b11379, RTX 3060)
    line = r"D:\dev-tools\llama.cpp\b11379\llama-server.exe -m D:/ollama/models/Qwen/q.gguf -ngl 99 -c 8192 -np 2 -fa on --port 8081"
    argv = split_windows_cmdline(line)
    p = parse_llama_server_args(argv[1:])
    assert p.flags == {"model": "D:/ollama/models/Qwen/q.gguf", "ngl": 99, "ctx": 8192, "parallel": 2,
                       "flash_attn": "on", "port": 8081}  # fmt: skip
