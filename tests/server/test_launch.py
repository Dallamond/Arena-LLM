"""Comando de llama-server propuesto desde la calculadora de encaje (sin GPU real)."""

import shlex

from server import launch

GIB = 1024**3


def est(n_layers=28, ctx=8192, parallel=1, kv_type="f16", ubatch=512):
    return {
        "kind": "model",
        "n_layers": n_layers,
        "compute": 300 * 1024 * 1024,
        "params": {"ctx": ctx, "parallel": parallel, "kv_type": kv_type, "ubatch": ubatch, "reserve_mib": 512},
    }


def info(os_name="windows", gpus=(("nvidia:A", 0, "nvidia"), ("nvidia:B", 1, "nvidia")), tools=None):
    return {
        "host": {"os": os_name},
        "devices": [{"device_id": d, "index": i, "provider": pr, "kind": "gpu"} for d, i, pr in gpus],
        "tools": tools or {},
    }


def gpus(*frees):
    return [{"device_id": f"nvidia:{'AB'[i]}", "name": f"GPU {'AB'[i]}", "free_mib": f, "total_mib": 24576} for i, f in enumerate(frees)]


def build(verdict, *, e=None, inf=None, g=None, endpoints=(), model=None, **kw):
    return launch.build(
        path=r"D:\modelos\Qwen 7B\q8.gguf",
        est=e or est(),
        verdict=verdict,
        model=model or {"context_length": 32768},
        host_info=inf if inf is not None else info(),
        gpus=g if g is not None else gpus(11000, 20000),
        endpoints=list(endpoints),
        **kw,
    )


def gpu_verdict(*fits):
    return {
        "verdict": "gpu",
        "ngl": 29,
        "gpus": [{"device_id": f"nvidia:{'AB'[i]}", "name": f"GPU {'AB'[i]}", "fits": f, "free": (i + 1) * GIB} for i, f in enumerate(fits)],
    }


def test_una_gpu_de_varias_usa_dev_y_orden_pci():
    out = build(gpu_verdict(True, False))
    assert out["available"] and len(out["options"]) == 1
    opt = out["options"][0]
    assert opt["args"][opt["args"].index("-dev") + 1] == "CUDA0"
    assert opt["args"][opt["args"].index("-ngl") + 1] == "29"
    assert opt["env"] == {"CUDA_DEVICE_ORDER": "PCI_BUS_ID"}
    assert opt["shells"]["cmd"].startswith("set CUDA_DEVICE_ORDER=PCI_BUS_ID\n")
    assert '"D:\\modelos\\Qwen 7B\\q8.gguf"' in opt["shells"]["cmd"]
    assert "'D:\\modelos\\Qwen 7B\\q8.gguf'" in opt["shells"]["powershell"]
    assert opt["shells"]["powershell"].splitlines()[-1].startswith("& ")


def test_cabe_en_dos_gpu_ofrece_ambas_con_la_mas_libre_primero():
    out = build(gpu_verdict(True, True))
    assert [o["id"] for o in out["options"]] == ["CUDA1", "CUDA0"]
    assert any("varias GPU" in n for n in out["notes"])


def test_una_sola_gpu_no_pone_dev():
    out = build(gpu_verdict(True), inf=info(gpus=(("nvidia:A", 0, "nvidia"),)), g=gpus(11000))
    args = out["options"][0]["args"]
    assert "-dev" not in args and out["options"][0]["env"] == {}


def test_reparto_con_ts_en_orden_de_indice():
    inf = info(gpus=(("nvidia:B", 1, "nvidia"), ("nvidia:A", 0, "nvidia")))
    out = build({"verdict": "split", "ngl": 29, "gpus": []}, inf=inf, g=gpus(11000, 21000))
    args = out["options"][0]["args"]
    ts = args[args.index("-ts") + 1].split(",")
    assert len(ts) == 2 and float(ts[0]) < float(ts[1])  # CUDA0 = A (menos libre), CUDA1 = B
    assert out["options"][0]["env"] == {"CUDA_DEVICE_ORDER": "PCI_BUS_ID"}


def test_parcial_en_ram_lleva_ngl_sugerido():
    out = build({"verdict": "ram", "ngl": 20, "gpus": []}, inf=info(gpus=(("nvidia:A", 0, "nvidia"),)), g=gpus(8000))
    args = out["options"][0]["args"]
    assert args[args.index("-ngl") + 1] == "20" and "-ts" not in args
    assert "20 de 28 capas" in out["options"][0]["label"]


def test_solo_cpu_desactiva_gpu():
    out = build({"verdict": "cpu", "ngl": 0, "gpus": []})
    args = out["options"][0]["args"]
    assert args[args.index("-ngl") + 1] == "0" and args[args.index("-dev") + 1] == "none"


def test_no_cabe_o_sin_datos_no_propone():
    assert build({"verdict": "no", "gpus": []})["available"] is False
    assert build({"verdict": "unknown", "gpus": []})["available"] is False
    assert launch.build(path="x", est={"kind": "mmproj"}, verdict={"verdict": "mmproj"}, model={}, host_info={}, gpus=[], endpoints=[])["available"] is False


def test_parametros_no_por_defecto():
    out = build(gpu_verdict(True, False), e=est(ctx=16384, parallel=2, kv_type="q8_0", ubatch=1024))
    args = out["options"][0]["args"]
    for flag, val in (("-c", "16384"), ("-np", "2"), ("-ctk", "q8_0"), ("-ctv", "q8_0"), ("-ub", "1024"), ("-fa", "on")):
        assert args[args.index(flag) + 1] == val
    plain = build(gpu_verdict(True, False))["options"][0]["args"]
    assert "-np" not in plain and "-ctk" not in plain and "-ub" not in plain


def test_puerto_libre_salta_los_ocupados_y_los_reservados():
    eps = [
        {"base_url": "http://127.0.0.1:8080", "status": "listo"},
        {"base_url": "http://127.0.0.1:8081", "status": "cargando"},
        {"base_url": "http://127.0.0.1:8082", "status": "detenido"},
    ]
    assert build(gpu_verdict(True, False), endpoints=eps)["port"] == 8082
    assert build(gpu_verdict(True, False), endpoints=eps, reserved_ports={8082})["port"] == 8083


def test_binario_configurado_detectado_o_supuesto():
    assert build(gpu_verdict(True, False), inf=info(tools={"llama_server": r"D:\ll\llama-server.exe"}))["exe_source"] == "configurado"
    eps = [
        {"base_url": "http://127.0.0.1:8080", "status": "listo", "last_seen_at": 1, "snapshot": {"exe": r"C:\viejo\llama-server.exe"}},
        {"base_url": "http://127.0.0.1:8081", "status": "listo", "last_seen_at": 2, "snapshot": {"exe": r"D:\nuevo\llama-server.exe"}},
        {"base_url": "http://127.0.0.1:9931", "status": "listo", "last_seen_at": 3, "snapshot": {"exe": r"C:\LlamaApp.exe"}},
    ]
    out = build(gpu_verdict(True, False), endpoints=eps)
    assert (out["exe"], out["exe_source"]) == (r"D:\nuevo\llama-server.exe", "detectado")
    out = build(gpu_verdict(True, False))
    assert (out["exe"], out["exe_source"]) == ("llama-server.exe", "supuesto")
    assert any("llama_server" in n for n in out["notes"])


def test_linux_da_bash_con_variable_en_linea():
    out = build(gpu_verdict(True, False), inf=info(os_name="linux"))
    sh = out["options"][0]["shells"]
    assert set(sh) == {"bash"}
    parts = shlex.split(sh["bash"])
    assert parts[0] == "CUDA_DEVICE_ORDER=PCI_BUS_ID" and parts[1] == "llama-server"
    assert r"D:\modelos\Qwen 7B\q8.gguf" in parts


def test_gpu_sin_backend_conocido_deja_reparto_automatico():
    inf = info(gpus=(("nvidia:A", 0, "nvidia"), ("nvidia:B", 1, "otro")))
    out = build({"verdict": "split", "ngl": 29, "gpus": []}, inf=inf)
    assert "-ts" not in out["options"][0]["args"]
    assert any("reparto automático" in n for n in out["notes"])


def test_aviso_si_el_contexto_por_slot_supera_el_entrenado():
    out = build(gpu_verdict(True, False), e=est(ctx=131072), model={"context_length": 32768})
    assert any("supera el de entrenamiento" in n and "131.072" in n for n in out["notes"])
    out = build(gpu_verdict(True, False), e=est(ctx=65536, parallel=2), model={"context_length": 32768})
    assert not any("entrenamiento" in n for n in out["notes"])
