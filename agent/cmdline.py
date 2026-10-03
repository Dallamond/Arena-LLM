"""Parser tolerante de la línea de comandos de `llama-server`.

Los flags cambian entre builds de llama.cpp: se reconocen los conocidos (con
sus alias cortos y largos) y el resto se guarda tal cual en `unknown`, sin
perder nada. Los secretos (`--api-key`) se ocultan.
"""

import re
from dataclasses import dataclass, field
from typing import Any

# kind: str | int | float | bool (sin valor) | optbool (valor opcional on/off/auto) | list (repetible)
FLAG_SPECS: dict[str, tuple[tuple[str, ...], str]] = {
    "model": (("-m", "--model"), "str"),
    "alias": (("-a", "--alias"), "str"),
    "hf_repo": (("-hf", "-hfr", "--hf-repo"), "str"),
    "mmproj": (("-mm", "--mmproj"), "str"),
    "model_draft": (("-md", "--model-draft"), "str"),
    "lora": (("--lora",), "list"),
    "ctx": (("-c", "--ctx-size"), "int"),
    "n_predict": (("-n", "--n-predict", "--predict"), "int"),
    "ngl": (("-ngl", "--gpu-layers", "--n-gpu-layers"), "str"),
    "tensor_split": (("-ts", "--tensor-split"), "str"),
    "split_mode": (("-sm", "--split-mode"), "str"),
    "main_gpu": (("-mg", "--main-gpu"), "int"),
    "device": (("-dev", "--device"), "str"),
    "parallel": (("-np", "--parallel"), "int"),
    "flash_attn": (("-fa", "--flash-attn"), "optbool"),
    "batch": (("-b", "--batch-size"), "int"),
    "ubatch": (("-ub", "--ubatch-size"), "int"),
    "cache_type_k": (("-ctk", "--cache-type-k"), "str"),
    "cache_type_v": (("-ctv", "--cache-type-v"), "str"),
    "threads": (("-t", "--threads"), "int"),
    "threads_batch": (("-tb", "--threads-batch"), "int"),
    "host": (("--host",), "str"),
    "port": (("--port",), "int"),
    "override_tensor": (("-ot", "--override-tensor"), "list"),
    "n_cpu_moe": (("-ncmoe", "--n-cpu-moe"), "int"),
    "cpu_moe": (("-cmoe", "--cpu-moe"), "bool"),
    "mlock": (("--mlock",), "bool"),
    "no_mmap": (("--no-mmap",), "bool"),
    "cont_batching": (("-cb", "--cont-batching"), "bool"),
    "no_cont_batching": (("-nocb", "--no-cont-batching"), "bool"),
    "kv_unified": (("-kvu", "--kv-unified"), "bool"),
    "no_kv_unified": (("-no-kvu", "--no-kv-unified"), "bool"),
    "jinja": (("--jinja",), "bool"),
    "no_jinja": (("--no-jinja",), "bool"),
    "cache_prompt": (("--cache-prompt",), "bool"),
    "no_cache_prompt": (("--no-cache-prompt",), "bool"),
    "mmproj_device": (("-mmdev", "--mmproj-device"), "str"),
    "model_url": (("-mu", "--model-url"), "str"),
    "chat_template": (("--chat-template",), "str"),
    "chat_template_file": (("--chat-template-file",), "str"),
    "reasoning_format": (("--reasoning-format",), "str"),
    "reasoning_budget": (("--reasoning-budget",), "int"),
    "slots": (("--slots",), "bool"),
    "no_slots": (("--no-slots",), "bool"),
    "metrics": (("--metrics",), "bool"),
    "props": (("--props",), "bool"),
    "embeddings": (("--embedding", "--embeddings"), "bool"),
    "seed": (("-s", "--seed"), "int"),
    "temp": (("--temp",), "float"),
    "rope_scaling": (("--rope-scaling",), "str"),
    "rope_freq_base": (("--rope-freq-base",), "float"),
    "api_key": (("--api-key",), "secret"),
    "api_key_file": (("--api-key-file",), "str"),
}

SECRET_FLAGS = {"--api-key"}
REDACTED = "***"
OPT_BOOL_VALUES = {"on", "off", "auto", "true", "false", "1", "0", "enabled", "disabled"}
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")

_ALIASES = {alias: key for key, (aliases, _) in FLAG_SPECS.items() for alias in aliases}


@dataclass
class ParsedCommand:
    flags: dict[str, Any] = field(default_factory=dict)
    unknown: dict[str, Any] = field(default_factory=dict)
    positional: list[str] = field(default_factory=list)
    argv_redacted: list[str] = field(default_factory=list)


def _looks_like_value(token: str) -> bool:
    return not token.startswith("-") or bool(_NUMBER_RE.match(token))


def _convert(value: str, kind: str) -> Any:
    if kind == "int":
        try:
            return int(value)
        except ValueError:
            return value  # se guarda tal cual; no se inventa un número
    if kind == "float":
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _ngl(value: Any) -> Any:
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
        return int(value)
    return value  # "all", "auto"… de builds recientes


def parse_llama_server_args(argv: list[str]) -> ParsedCommand:
    """`argv` sin el ejecutable (argv[1:])."""
    out = ParsedCommand()
    i = 0
    while i < len(argv):
        start = i
        tok = argv[i]
        i += 1
        if not tok.startswith("-") or tok in ("-", "--") or _NUMBER_RE.match(tok):
            out.positional.append(tok)
            out.argv_redacted.append(tok)
            continue
        name, eq, inline = tok.partition("=")
        key = _ALIASES.get(name)
        kind = FLAG_SPECS[key][1] if key else None
        value: str | None
        if kind == "bool":
            value = None
        elif kind == "optbool":
            if eq:
                value = inline
            elif i < len(argv) and argv[i].lower() in OPT_BOOL_VALUES:
                value = argv[i]
                i += 1
            else:
                value = "on"  # forma antigua: -fa sin valor
        elif eq:
            value = inline
        elif i < len(argv) and _looks_like_value(argv[i]):
            value = argv[i]
            i += 1
        else:
            value = None

        if name in SECRET_FLAGS and value is not None:
            out.argv_redacted += [f"{name}={REDACTED}"] if eq else [name, REDACTED]
        else:
            out.argv_redacted += argv[start:i]

        if key is None:
            v: Any = True if value is None else value
            prev = out.unknown.get(name)
            out.unknown[name] = v if prev is None else ([*prev, v] if isinstance(prev, list) else [prev, v])
        elif kind == "bool":
            out.flags[key] = True
        elif value is None:
            out.unknown[name] = True  # flag conocido sin su valor: se registra, no se inventa
        elif kind == "optbool":
            out.flags[key] = value.lower()
        elif kind == "secret":
            out.flags[key] = REDACTED
        elif kind == "list":
            out.flags.setdefault(key, []).append(value)
        else:
            out.flags[key] = _convert(value, kind)
    if "ngl" in out.flags:
        out.flags["ngl"] = _ngl(out.flags["ngl"])
    return out


def split_windows_cmdline(cmdline: str) -> list[str]:
    """Divide una línea de comandos de Windows con las reglas de CommandLineToArgvW."""
    args: list[str] = []
    buf: list[str] = []
    in_quotes = False
    has_arg = False
    i = 0
    n = len(cmdline)
    # argv[0]: hasta el siguiente espacio fuera de comillas, sin tratar barras
    while i < n and cmdline[i] in " \t":
        i += 1
    while i < n:
        c = cmdline[i]
        if c == '"':
            in_quotes = not in_quotes
        elif c in " \t" and not in_quotes:
            break
        else:
            buf.append(c)
        i += 1
    if buf or i > 0:
        args.append("".join(buf))
    buf = []
    in_quotes = False
    while i < n:
        c = cmdline[i]
        if c == "\\":
            j = i
            while j < n and cmdline[j] == "\\":
                j += 1
            count = j - i
            if j < n and cmdline[j] == '"':
                buf.append("\\" * (count // 2))
                if count % 2:
                    buf.append('"')
                    i = j + 1
                else:
                    i = j
                has_arg = True
                continue
            buf.append("\\" * count)
            i = j
            has_arg = True
            continue
        if c == '"':
            if in_quotes and i + 1 < n and cmdline[i + 1] == '"':
                buf.append('"')
                i += 2
                has_arg = True
                continue
            in_quotes = not in_quotes
            has_arg = True
            i += 1
            continue
        if c in " \t" and not in_quotes:
            if has_arg or buf:
                args.append("".join(buf))
                buf = []
                has_arg = False
            i += 1
            continue
        buf.append(c)
        has_arg = True
        i += 1
    if has_arg or buf:
        args.append("".join(buf))
    return args
