"""Lector de la cabecera de ficheros GGUF (solo biblioteca estándar).

Lee metadatos e información de tensores sin tocar los pesos. El hash de la
cabecera (`header_sha256`) identifica el modelo de forma estable y barata: dos
ficheros con la misma cabecera y tamaño son, a efectos prácticos, el mismo.
"""

import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

MAGIC = b"GGUF"

# Tipos de valor de metadatos
_SCALARS = {
    0: ("<B", 1),
    1: ("<b", 1),
    2: ("<H", 2),
    3: ("<h", 2),
    4: ("<I", 4),
    5: ("<i", 4),
    6: ("<f", 4),
    7: ("<?", 1),
    10: ("<Q", 8),
    11: ("<q", 8),
    12: ("<d", 8),
}
T_STRING, T_ARRAY = 8, 9

#: Arrays numéricos de hasta este tamaño se guardan completos (p. ej. cabezas KV por capa).
MAX_ARRAY_KEEP = 1024
MAX_STRING = 64 * 1024 * 1024
MAX_COUNT = 1 << 32

GGML_TYPES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 6: "Q5_0", 7: "Q5_1", 8: "Q8_0", 9: "Q8_1",
    10: "Q2_K", 11: "Q3_K", 12: "Q4_K", 13: "Q5_K", 14: "Q6_K", 15: "Q8_K", 16: "IQ2_XXS",
    17: "IQ2_XS", 18: "IQ3_XXS", 19: "IQ1_S", 20: "IQ4_NL", 21: "IQ3_S", 22: "IQ2_S", 23: "IQ4_XS",
    24: "I8", 25: "I16", 26: "I32", 27: "I64", 28: "F64", 29: "IQ1_M", 30: "BF16", 34: "TQ1_0",
    35: "TQ2_0", 39: "MXFP4",
}  # fmt: skip

#: `general.file_type` (enum llama_ftype de llama.cpp).
FILE_TYPES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K",
    11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S",
    17: "Q5_K_M", 18: "Q6_K", 19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S", 22: "IQ3_XS",
    23: "IQ3_XXS", 24: "IQ1_S", 25: "IQ4_NL", 26: "IQ3_S", 27: "IQ3_M", 28: "IQ2_S", 29: "IQ2_M",
    30: "IQ4_XS", 31: "IQ1_M", 32: "BF16", 36: "TQ1_0", 37: "TQ2_0", 38: "MXFP4_MOE",
}  # fmt: skip


class GgufError(ValueError):
    pass


@dataclass
class GgufInfo:
    path: str
    file_size: int
    version: int
    header_bytes: int
    header_sha256: str
    n_tensors: int
    n_params: int
    architecture: str | None = None
    general_type: str | None = None  # "model" | "mmproj" | "adapter"… (si el fichero lo declara)
    name: str | None = None
    size_label: str | None = None
    file_type: str | None = None
    block_count: int | None = None
    context_length: int | None = None
    embedding_length: int | None = None
    head_count: Any = None  # int o lista por capa
    head_count_kv: Any = None
    key_length: int | None = None
    value_length: int | None = None
    expert_count: int | None = None
    expert_used_count: int | None = None
    vocab_size: int | None = None
    split_count: int | None = None
    tensor_types: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class _HashingReader:
    def __init__(self, f: BinaryIO):
        self.f = f
        self.h = hashlib.sha256()
        self.pos = 0

    def read(self, n: int) -> bytes:
        data = self.f.read(n)
        if len(data) != n:
            raise GgufError(f"fichero truncado en el byte {self.pos}")
        self.h.update(data)
        self.pos += n
        return data

    def unpack(self, fmt: str, size: int):
        return struct.unpack(fmt, self.read(size))[0]

    def u32(self) -> int:
        return self.unpack("<I", 4)

    def u64(self) -> int:
        return self.unpack("<Q", 8)

    def string(self, len64: bool) -> str:
        n = self.u64() if len64 else self.u32()
        if n > MAX_STRING:
            raise GgufError(f"cadena demasiado larga ({n} bytes): fichero corrupto")
        return self.read(n).decode("utf-8", "replace")

    def skip(self, n: int) -> None:
        while n > 0:
            chunk = min(n, 1 << 20)
            self.read(chunk)
            n -= chunk


def _read_value(r: _HashingReader, vtype: int, len64: bool) -> Any:
    if vtype in _SCALARS:
        return r.unpack(*_SCALARS[vtype])
    if vtype == T_STRING:
        return r.string(len64)
    if vtype == T_ARRAY:
        etype = r.u32()
        count = r.u64() if len64 else r.u32()
        if count > MAX_COUNT:
            raise GgufError(f"array demasiado grande ({count}): fichero corrupto")
        if etype in _SCALARS:
            fmt, size = _SCALARS[etype]
            if count <= MAX_ARRAY_KEEP:
                data = r.read(size * count)
                return list(struct.unpack(f"<{count}{fmt[1]}", data))
            r.skip(size * count)
            return {"array_of": etype, "len": count}
        if etype == T_STRING:
            for _ in range(count):
                r.string(len64)
            return {"array_of": "string", "len": count}
        if etype == T_ARRAY:
            return {
                "array_of": "array",
                "len": count,
                "items": [_read_value(r, T_ARRAY, len64) for _ in range(count)],
            }
        raise GgufError(f"tipo de elemento desconocido en array: {etype}")
    raise GgufError(f"tipo de metadato desconocido: {vtype}")


def _int(v: Any) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def read_header(path: str | Path) -> GgufInfo:
    path = Path(path)
    size = path.stat().st_size
    with path.open("rb") as f:
        r = _HashingReader(f)
        if r.read(4) != MAGIC:
            raise GgufError("no es un fichero GGUF (magic incorrecto)")
        version = r.u32()
        if version not in (1, 2, 3):
            raise GgufError(f"versión GGUF no soportada: {version}")
        len64 = version >= 2
        n_tensors = r.u64() if len64 else r.u32()
        n_kv = r.u64() if len64 else r.u32()
        if n_kv > 1_000_000 or n_tensors > 10_000_000:
            raise GgufError("recuentos imposibles en la cabecera: fichero corrupto")
        meta: dict[str, Any] = {}
        for _ in range(n_kv):
            key = r.string(len64)
            meta[key] = _read_value(r, r.u32(), len64)
        n_params = 0
        types: dict[str, int] = {}
        for _ in range(n_tensors):
            r.string(len64)
            n_dims = r.u32()
            if n_dims > 8:
                raise GgufError(f"tensor con {n_dims} dimensiones: fichero corrupto")
            count = 1
            for _ in range(n_dims):
                count *= r.u64() if len64 else r.u32()
            ttype = r.u32()
            r.u64()  # offset
            n_params += count
            tname = GGML_TYPES.get(ttype, f"type_{ttype}")
            types[tname] = types.get(tname, 0) + 1

    arch = meta.get("general.architecture")
    arch = arch if isinstance(arch, str) else None

    def a(suffix: str) -> Any:
        return meta.get(f"{arch}.{suffix}") if arch else None

    ftype = meta.get("general.file_type")
    tokens = meta.get("tokenizer.ggml.tokens")
    head_kv = a("attention.head_count_kv")
    return GgufInfo(
        path=str(path),
        file_size=size,
        version=version,
        header_bytes=r.pos,
        header_sha256=r.h.hexdigest(),
        n_tensors=n_tensors,
        n_params=n_params,
        architecture=arch,
        general_type=meta.get("general.type") if isinstance(meta.get("general.type"), str) else None,
        name=meta.get("general.name") if isinstance(meta.get("general.name"), str) else None,
        size_label=meta.get("general.size_label")
        if isinstance(meta.get("general.size_label"), str)
        else None,
        file_type=FILE_TYPES.get(ftype, f"ftype_{ftype}") if isinstance(ftype, int) else None,
        block_count=_int(a("block_count")),
        context_length=_int(a("context_length")),
        embedding_length=_int(a("embedding_length")),
        head_count=a("attention.head_count"),
        head_count_kv=head_kv,
        key_length=_int(a("attention.key_length")),
        value_length=_int(a("attention.value_length")),
        expert_count=_int(a("expert_count")),
        expert_used_count=_int(a("expert_used_count")),
        vocab_size=tokens["len"]
        if isinstance(tokens, dict)
        else (len(tokens) if isinstance(tokens, list) else None),
        split_count=_int(meta.get("split.count")),
        tensor_types=dict(sorted(types.items(), key=lambda kv: -kv[1])),
        metadata={k: v for k, v in meta.items() if not k.startswith("tokenizer.ggml.")},
    )
