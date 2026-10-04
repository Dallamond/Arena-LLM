import http.client
import json
import struct
import threading

import pytest

from agent.api import AgentApp, make_server
from agent.config import AgentConfig, load_config
from agent.gguf import GgufError, read_header
from agent.model import HostInfo
from agent.providers import NullProvider
from agent.sampler import Sampler


def _s(text: str) -> bytes:
    b = text.encode("utf-8")
    return struct.pack("<Q", len(b)) + b


def _kv(key: str, vtype: int, payload: bytes) -> bytes:
    return _s(key) + struct.pack("<I", vtype) + payload


def write_gguf(path, *, magic=b"GGUF", version=3, tokens=5, truncate=None):
    """GGUF mínimo con metadatos de un modelo llama y dos tensores."""
    kvs = [
        _kv("general.architecture", 8, _s("llama")),
        _kv("general.name", 8, _s("Mini prueba")),
        _kv("general.file_type", 4, struct.pack("<I", 15)),  # Q4_K_M
        _kv("llama.block_count", 4, struct.pack("<I", 2)),
        _kv("llama.context_length", 4, struct.pack("<I", 4096)),
        _kv("llama.embedding_length", 4, struct.pack("<I", 64)),
        _kv("llama.attention.head_count", 4, struct.pack("<I", 8)),
        _kv("llama.attention.head_count_kv", 9, struct.pack("<IQ", 4, 2) + struct.pack("<2I", 2, 4)),
        _kv("llama.rope.freq_base", 6, struct.pack("<f", 10000.0)),
        _kv("general.flag", 7, struct.pack("<?", True)),
        _kv(
            "tokenizer.ggml.tokens",
            9,
            struct.pack("<IQ", 8, tokens) + b"".join(_s(f"t{i}") for i in range(tokens)),
        ),
    ]
    tensors = [
        _s("token_embd.weight") + struct.pack("<I", 2) + struct.pack("<2Q", 64, tokens) + struct.pack("<IQ", 12, 0),
        _s("output_norm.weight") + struct.pack("<I", 1) + struct.pack("<Q", 64) + struct.pack("<IQ", 0, 4096),
    ]
    head = magic + struct.pack("<I", version) + struct.pack("<QQ", len(tensors), len(kvs))
    data = head + b"".join(kvs) + b"".join(tensors)
    if truncate:
        data = data[:truncate]
    path.write_bytes(data + (b"\0" * 64 if not truncate else b""))
    return len(head + b"".join(kvs) + b"".join(tensors))


def test_cabecera_minima(tmp_path):
    f = tmp_path / "mini-Q4_K_M.gguf"
    header_len = write_gguf(f)
    g = read_header(f)
    assert (g.version, g.architecture, g.name, g.file_type) == (3, "llama", "Mini prueba", "Q4_K_M")
    assert (g.block_count, g.context_length, g.embedding_length, g.head_count) == (2, 4096, 64, 8)
    assert g.head_count_kv == [2, 4]  # array por capa conservado
    assert g.vocab_size == 5
    assert g.n_tensors == 2 and g.n_params == 64 * 5 + 64
    assert g.tensor_types == {"Q4_K": 1, "F32": 1}
    assert g.header_bytes == header_len
    assert "tokenizer.ggml.tokens" not in g.metadata
    assert g.metadata["general.flag"] is True


def test_hash_estable_e_independiente_de_los_pesos(tmp_path):
    a, b = tmp_path / "a.gguf", tmp_path / "b.gguf"
    write_gguf(a)
    write_gguf(b)
    with b.open("ab") as fh:
        fh.write(b"pesos distintos")
    assert read_header(a).header_sha256 == read_header(b).header_sha256
    c = tmp_path / "c.gguf"
    write_gguf(c, tokens=6)
    assert read_header(c).header_sha256 != read_header(a).header_sha256


@pytest.mark.parametrize(
    "kwargs,msg",
    [({"magic": b"NOPE"}, "magic"), ({"version": 9}, "versión"), ({"truncate": 60}, "truncado")],
)
def test_ficheros_invalidos(tmp_path, kwargs, msg):
    f = tmp_path / "x.gguf"
    write_gguf(f, **kwargs)
    with pytest.raises(GgufError, match=msg):
        read_header(f)


def test_config_rutas_permitidas(tmp_path):
    models = tmp_path / "modelos"
    (models / "sub").mkdir(parents=True)
    ok = models / "sub" / "m.gguf"
    write_gguf(ok)
    outside = tmp_path / "fuera.gguf"
    write_gguf(outside)
    (models / "nota.txt").write_text("x")
    cfg = AgentConfig(model_dirs=[models])
    assert cfg.allowed_model(str(ok)) == ok.resolve()
    assert cfg.allowed_model(str(outside)) is None
    assert cfg.allowed_model(str(models / "sub" / ".." / ".." / "fuera.gguf")) is None
    assert cfg.allowed_model(str(models / "nota.txt")) is None
    assert cfg.allowed_model(str(models / "no-existe.gguf")) is None
    assert cfg.allowed_model("") is None


def test_load_config(tmp_path):
    f = tmp_path / "agent.json"
    f.write_text(json.dumps({"model_dirs": ["/a"], "llama_bench": "/b/llama-bench"}), encoding="utf-8")
    cfg = load_config(f, ["/c"])
    assert [p.as_posix() for p in cfg.model_dirs][-1] == "/c"
    assert len(cfg.model_dirs) == 2 and cfg.source == f
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "no.json")


@pytest.fixture
def agent(tmp_path):
    models = tmp_path / "modelos"
    models.mkdir()
    write_gguf(models / "a-Q4_K_M.gguf")
    write_gguf(models / "big-00001-of-00002.gguf")
    (models / "roto.gguf").write_bytes(b"GGUF\x09\0\0\0")
    write_gguf(tmp_path / "secreto.gguf")
    sampler = Sampler([NullProvider()])
    app = AgentApp(HostInfo("h", "x", "linux"), sampler, config=AgentConfig(model_dirs=[models]))
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], models, tmp_path
    server.shutdown()
    server.server_close()


def get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    r = conn.getresponse()
    body = json.loads(r.read())
    conn.close()
    return r.status, body


def test_ruta_models(agent):
    port, models, _ = agent
    status, body = get(port, "/models")
    assert status == 200
    files = {f["file"]: f for f in body["files"]}
    assert set(files) == {"a-Q4_K_M.gguf", "big-00001-of-00002.gguf", "roto.gguf"}
    assert (
        files["big-00001-of-00002.gguf"]["split_part"],
        files["big-00001-of-00002.gguf"]["split_total"],
    ) == (1, 2)


def test_ruta_gguf(agent):
    from urllib.parse import quote

    port, models, tmp = agent
    status, body = get(port, "/gguf?path=" + quote(str(models / "a-Q4_K_M.gguf")))
    assert status == 200 and body["gguf"]["file_type"] == "Q4_K_M"
    status, body = get(port, "/gguf?path=" + quote(str(tmp / "secreto.gguf")))
    assert status == 403 and body["error"]["code"] == "path"
    status, body = get(port, "/gguf?path=" + quote(str(models / "roto.gguf")))
    assert status == 422 and "versión" in body["error"]["message"]


def test_gguf_sin_carpetas_configuradas():
    app = AgentApp(HostInfo("h", "x", "linux"), Sampler([NullProvider()]))
    status, body = app.handle("GET", "/gguf?path=/x.gguf", {"Host": "localhost"})
    assert status == 403 and body["error"]["code"] == "no_model_dirs"


def write_layered(path, tensors, *, data_bytes, split=None):
    """GGUF con tensores `(nombre, offset)` de tipo F32 y `data_bytes` de datos alineados a 32."""
    kvs = [_kv("general.architecture", 8, _s("llama")), _kv("llama.block_count", 4, struct.pack("<I", 2))]
    if split:
        kvs.append(_kv("split.count", 2, struct.pack("<H", split)))
    infos = [_s(n) + struct.pack("<I", 1) + struct.pack("<Q", 4) + struct.pack("<IQ", 0, off) for n, off in tensors]
    head = b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", len(infos), len(kvs)) + b"".join(kvs) + b"".join(infos)
    pad = (-len(head)) % 32
    path.write_bytes(head + b"\0" * pad + b"\0" * data_bytes)


def test_layout_por_capas(tmp_path):
    f = tmp_path / "capas.gguf"
    write_layered(
        f,
        [("token_embd.weight", 0), ("blk.0.attn_q.weight", 100), ("blk.0.ffn.weight", 160),
         ("blk.1.attn_q.weight", 300), ("output_norm.weight", 520), ("output.weight", 540), ("rope_freqs", 900)],
        data_bytes=1000,
    )  # fmt: skip
    lay = read_header(f).layout
    assert lay == {"blocks": [200, 220], "token_embd": 100, "output": 380, "other": 100, "data_bytes": 1000}


def test_layout_modelo_partido(tmp_path):
    models = tmp_path / "m"
    models.mkdir()
    p1, p2 = models / "big-00001-of-00002.gguf", models / "big-00002-of-00002.gguf"
    write_layered(p1, [("token_embd.weight", 0), ("blk.0.w", 64)], data_bytes=128, split=2)
    write_layered(p2, [("blk.1.w", 0), ("output.weight", 96)], data_bytes=160)
    app = AgentApp(HostInfo("h", "x", "linux"), Sampler([NullProvider()]), config=AgentConfig(model_dirs=[models]))
    lay = app.gguf({"path": str(p1)})["gguf"].layout
    assert lay["blocks"] == [64, 96] and lay["token_embd"] == 64 and lay["output"] == 64
    assert lay["data_bytes"] == 288 and lay["split_missing"] == []
    p2.unlink()
    app._gguf_cache.clear()
    assert app.gguf({"path": str(p1)})["gguf"].layout["split_missing"] == [p2.name]


def test_llama_server_configurado_o_junto_a_llama_bench(tmp_path):
    bench = tmp_path / "llama-bench.exe"
    bench.write_bytes(b"")
    assert AgentConfig(llama_bench=bench).llama_server_path() is None  # no hay llama-server al lado
    (tmp_path / "llama-server.exe").write_bytes(b"")
    assert AgentConfig(llama_bench=bench).llama_server_path() == tmp_path / "llama-server.exe"
    other = tmp_path / "otro" / "llama-server"
    assert AgentConfig(llama_bench=bench, llama_server=other).llama_server_path() == other
    f = tmp_path / "agent.json"
    f.write_text(json.dumps({"llama_server": str(other)}), encoding="utf-8")
    assert load_config(f).llama_server == other
