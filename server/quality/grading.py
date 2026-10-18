"""Corrección automática de las respuestas (funciones puras, con tests).

Nunca se da por buena una respuesta ambigua: si el modelo no sigue el formato pedido
(`RESPUESTA: <valor>`), el ítem se marca incorrecto y se anota que faltó el formato.
"""

import re
import unicodedata
from typing import Any

from server.quality.sandbox import run_python

_ANSWER_RE = re.compile(r"^[\s>*_#`-]*respuesta[\s*_]*[:：][\s*_]*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
# «9.000» y «9,000» son miles; «0.050» no (un grupo de miles no empieza por 0).
_THOUSANDS_RE = re.compile(r"^-?[1-9]\d{0,2}([.,]\d{3})+$")
_NUMBER_RE = re.compile(r"^-?\d+([.,]\d+)?$")
_FENCE_RE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize_answer(text: str) -> str:
    """Forma canónica para comparar: sin acentos, minúsculas, sin marcas de formato y números limpios.

    «0,05», «0.050» y «**0.05 €**» → «0.05». «9.000» y «9,000» (miles) → «9000».
    """
    s = _strip_accents(str(text)).lower().replace("\\boxed", "")
    s = re.sub(r"[*_`${}\\]", "", s).strip()
    s = s.strip(" .;:!¡?¿\"'«»()[]")
    s = re.sub(r"\s*(eur|euros|€|segundos|minutos|dias|días|letras|veces)\s*$", "", s).strip()
    if _THOUSANDS_RE.match(s):
        s = re.sub(r"[.,]", "", s)
    elif _NUMBER_RE.match(s):
        s = s.replace(",", ".")
        if "." in s:
            s = s.rstrip("0").rstrip(".") or "0"
    return re.sub(r"\s+", " ", s)


def extract_answer(text: str) -> str | None:
    """Valor de la última línea «RESPUESTA: …» (None si el modelo no la escribió)."""
    found = _ANSWER_RE.findall(text or "")
    return found[-1] if found else None


def grade_qa(case: dict[str, Any], text: str) -> dict[str, Any]:
    got_raw = extract_answer(text)
    expected = case["expected"]
    accepted = {normalize_answer(expected), *(normalize_answer(a) for a in case.get("alt", []))}
    if got_raw is None:
        return {"kind": "qa", "correct": False, "expected": expected, "got": None, "format_ok": False,
                "note": "No escribió la línea «RESPUESTA: …»."}  # fmt: skip
    got = normalize_answer(got_raw)
    return {"kind": "qa", "correct": got in accepted, "expected": expected, "got": got_raw.strip(), "format_ok": True}


def grade_needle(case: dict[str, Any], text: str) -> dict[str, Any]:
    code = case["expected"]
    squash = lambda s: re.sub(r"[^A-Z0-9]", "", s.upper())  # noqa: E731
    correct = squash(code) in squash(text or "")
    return {"kind": "needle", "correct": correct, "expected": code, "got": (text or "").strip()[:80] or None,
            "size": case.get("size"), "depth": case.get("depth")}  # fmt: skip


def extract_code(text: str) -> str | None:
    """Código Python de la respuesta: el último bloque ``` con `def`/`class`, o cualquier bloque."""
    blocks = [(lang.lower(), body) for lang, body in _FENCE_RE.findall(text or "")]
    py = [b for lang, b in blocks if lang in ("python", "py", "python3", "")]
    for body in reversed(py):
        if re.search(r"^\s*(def|class)\s", body, re.MULTILINE):
            return body
    if py:
        return py[-1]
    if re.search(r"^\s*(def|class)\s", text or "", re.MULTILINE):  # sin vallas: texto con código suelto
        return text
    return None


def grade_code(case: dict[str, Any], text: str, timeout_s: float = 10.0) -> dict[str, Any]:
    code = extract_code(text)
    if code is None:
        return {"kind": "code", "correct": False, "status": "sin código", "note": "No hay ningún bloque de código."}
    res = run_python(code, case["tests"], timeout_s=timeout_s)
    out: dict[str, Any] = {
        "kind": "code",
        "correct": res.passed,
        "status": res.status,
        "seconds": round(res.seconds, 3),
    }
    if not res.passed:
        tail = (res.stderr or res.stdout).strip().splitlines()[-6:]
        out["note"] = "\n".join(tail) if tail else {"timeout": f"Superó {timeout_s:g} s"}.get(res.status, "Falló")
    out["code"] = code
    return out
