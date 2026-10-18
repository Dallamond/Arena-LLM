"""Corrección automática, sandbox y datasets de las pruebas de calidad (sin GPU)."""

import os
from pathlib import Path

import pytest

from server.quality import datasets, grading
from server.quality.sandbox import run_python
from server.quality.summary import quality_summary

# --------------------------------------------------------------- normalización


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0,05", "0.05"),
        ("0.050", "0.05"),
        ("**0.05 €**", "0.05"),
        ("408.0", "408"),
        ("9.000", "9000"),
        ("9,000", "9000"),
        ("  Sí. ", "si"),
        ("\\boxed{42}", "42"),
        ('"Canberra"', "canberra"),
        ("3 minutos", "3"),
        ("-1,5", "-1.5"),
    ],
)
def test_normaliza_respuestas(raw, expected):
    assert grading.normalize_answer(raw) == expected


def test_extrae_la_ultima_linea_respuesta():
    text = "Pienso...\nRESPUESTA: 1\nme equivoqué\n**Respuesta:** 12\n"
    assert grading.extract_answer(text) == "12"
    assert grading.extract_answer("sin formato 12") is None


def test_qa_acierta_con_variantes_y_exige_el_formato():
    case = {"expected": "0.05", "alt": ["5 centimos"]}
    assert grading.grade_qa(case, "x\nRESPUESTA: 0,05")["correct"]
    assert grading.grade_qa(case, "x\nRESPUESTA: 5 céntimos")["correct"]
    assert not grading.grade_qa(case, "x\nRESPUESTA: 0,10")["correct"]
    sin = grading.grade_qa(case, "la respuesta es 0,05")
    assert not sin["correct"] and sin["format_ok"] is False


def test_aguja_encuentra_el_codigo_aunque_cambie_el_formato():
    case = {"expected": "AB12-CD34-EF56", "size": 2048, "depth": 50}
    assert grading.grade_needle(case, "El código es ab12 cd34 ef56.")["correct"]
    assert not grading.grade_needle(case, "No lo sé")["correct"]


def test_aguja_es_determinista_y_coloca_el_codigo_a_su_profundidad():
    p1, c1 = datasets.build_needle_prompt(42, 2048, 50, 3.5)
    p2, c2 = datasets.build_needle_prompt(42, 2048, 50, 3.5)
    assert (p1, c1) == (p2, c2)
    assert datasets.build_needle_prompt(43, 2048, 50, 3.5)[1] != c1
    assert abs(len(p1) - 2048 * 3.5) < 400
    assert c1 in p1
    # a 10 % aparece mucho antes que a 90 %
    early = datasets.build_needle_prompt(42, 4096, 10, 3.5)
    late = datasets.build_needle_prompt(42, 4096, 90, 3.5)
    assert early[0].index(early[1]) < late[0].index(late[1])


def test_extrae_codigo_de_la_respuesta():
    text = "Aquí:\n```python\ndef a():\n    return 1\n```\ny otra\n```python\ndef b():\n    return 2\n```"
    assert "def b" in grading.extract_code(text)
    assert grading.extract_code("```\nx = 1\n```") is not None
    assert grading.extract_code("no hay nada") is None


# ------------------------------------------------------------------- sandbox


def test_sandbox_pasa_y_falla():
    ok = run_python("def f():\n    return 2", "assert f() == 2")
    assert ok.passed and ok.status == "ok"
    bad = run_python("def f():\n    return 3", "assert f() == 2")
    assert not bad.passed and bad.status == "fallo" and "AssertionError" in bad.stderr


def test_sandbox_bucle_infinito_no_bloquea():
    res = run_python("while True:\n    pass", "assert True", timeout_s=1.5)
    assert not res.passed and res.status == "timeout"
    assert res.seconds < 8


def test_sandbox_sin_stdin():
    res = run_python("x = input()", "assert True", timeout_s=5)
    assert not res.passed  # EOFError: stdin cerrado, no se queda esperando


def test_sandbox_no_puede_escribir_fuera_del_directorio_temporal(tmp_path):
    target = tmp_path / "no_debe_existir.txt"
    code = f"open({str(target)!r}, 'w').write('x')\n"
    res = run_python(code, "assert True", timeout_s=5)
    assert not res.passed and not target.exists()
    assert "PermissionError" in res.stderr or "Arena" in res.stderr


def test_sandbox_no_puede_borrar_ni_abrir_red_ni_procesos(tmp_path):
    victim = tmp_path / "importante.txt"
    victim.write_text("datos")
    for code in (
        f"import os\nos.remove({str(victim)!r})",
        "import socket\nsocket.socket()",
        "import subprocess\nsubprocess.run(['python', '-c', 'pass'])",
        "import os\nos.system('echo hola')",
    ):
        res = run_python(code, "assert True", timeout_s=5)
        assert not res.passed, code
    assert victim.read_text() == "datos"


def test_sandbox_puede_escribir_en_su_propio_directorio():
    code = "open('local.txt', 'w').write('hola')\nassert open('local.txt').read() == 'hola'"
    assert run_python(code, "assert True", timeout_s=5).passed


def test_sandbox_no_acepta_un_exit_como_aprobado():
    assert not run_python("import sys\nsys.exit(0)", "assert False", timeout_s=5).passed
    assert not run_python("print('ARENA-OK')\nimport os\nos._exit(0)", "assert False", timeout_s=5).passed


def test_sandbox_no_hereda_el_entorno():
    os.environ["ARENA_SECRETO_PRUEBA"] = "hola"
    try:
        res = run_python("import os\nassert 'ARENA_SECRETO_PRUEBA' not in os.environ", "assert True", timeout_s=5)
    finally:
        del os.environ["ARENA_SECRETO_PRUEBA"]
    assert res.passed


def test_sandbox_limpia_su_directorio():
    before = {p.name for p in Path(os.environ.get("TEMP", "/tmp")).glob("arena-sbx-*")}
    run_python("x = 1", "assert x == 1")
    after = {p.name for p in Path(os.environ.get("TEMP", "/tmp")).glob("arena-sbx-*")}
    assert after <= before


# ------------------------------------------- los 10 problemas con su solución de referencia

REFERENCE = {
    "palindromo": """
def es_palindromo(s):
    t = [c.lower() for c in s if c.isalnum()]
    return t == t[::-1]
""",
    "dos_suma": """
def dos_suma(nums, objetivo):
    seen = {}
    for j, n in enumerate(nums):
        if objetivo - n in seen:
            return (seen[objetivo - n], j)
        seen[n] = j
""",
    "intervalos": """
def fusionar_intervalos(intervalos):
    out = []
    for a, b in sorted(intervalos):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out
""",
    "romano": """
def romano_a_entero(s):
    v = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    t = 0
    for i, c in enumerate(s):
        t += -v[c] if i + 1 < len(s) and v[c] < v[s[i + 1]] else v[c]
    return t
""",
    "aplanar": """
def aplanar(lista):
    out = []
    for x in lista:
        if isinstance(x, list):
            out.extend(aplanar(x))
        else:
            out.append(x)
    return out
""",
    "parentesis": """
def parentesis_validos(s):
    pares = {')': '(', ']': '[', '}': '{'}
    pila = []
    for c in s:
        if c in '([{':
            pila.append(c)
        elif c in pares:
            if not pila or pila.pop() != pares[c]:
                return False
    return not pila
""",
    "lru": """
from collections import OrderedDict
class LRUCache:
    def __init__(self, capacidad):
        self.c = capacidad
        self.d = OrderedDict()
    def get(self, k):
        if k not in self.d:
            return -1
        self.d.move_to_end(k)
        return self.d[k]
    def put(self, k, v):
        self.d[k] = v
        self.d.move_to_end(k)
        if len(self.d) > self.c:
            self.d.popitem(last=False)
""",
    "frecuencias": """
import re
from collections import Counter
def frecuencias_top(texto, k):
    c = Counter(re.findall(r'[a-z0-9]+', texto.lower()))
    return sorted(c.items(), key=lambda x: (-x[1], x[0]))[:k]
""",
    "fibonacci": """
def fibonacci_mod(n, m):
    def fd(k):
        if k == 0:
            return (0, 1)
        a, b = fd(k >> 1)
        c = a * ((2 * b - a) % m) % m
        d = (a * a + b * b) % m
        return (d, (c + d) % m) if k & 1 else (c, d)
    return fd(n)[0] % m
""",
    "islas": """
def contar_islas(grid):
    if not grid:
        return 0
    h, w = len(grid), len(grid[0])
    seen = set()
    def dfs(i, j):
        stack = [(i, j)]
        while stack:
            x, y = stack.pop()
            if (x, y) in seen or not (0 <= x < h and 0 <= y < w) or not grid[x][y]:
                continue
            seen.add((x, y))
            stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    n = 0
    for i in range(h):
        for j in range(w):
            if grid[i][j] and (i, j) not in seen:
                n += 1
                dfs(i, j)
    return n
""",
}


def test_hay_referencia_para_cada_problema():
    assert set(REFERENCE) == {p["id"] for p in datasets.CODE_PROBLEMS}
    assert len(datasets.CODE_PROBLEMS) == 10 and len(datasets.QA_QUESTIONS) == 12


@pytest.mark.parametrize("problem", datasets.CODE_PROBLEMS, ids=lambda p: p["id"])
def test_cada_problema_acepta_su_referencia_y_rechaza_una_solucion_vacia(problem):
    ok = run_python(REFERENCE[problem["id"]], problem["tests"], timeout_s=20)
    assert ok.passed, ok.stderr
    stub = f"def {problem['entry']}(*a, **k):\n    return None\n"
    if problem["entry"] == "LRUCache":
        stub = (
            "class LRUCache:\n"
            "    def __init__(self, c): pass\n"
            "    def get(self, k): return None\n"
            "    def put(self, k, v): pass\n"
        )
    assert not run_python(stub, problem["tests"], timeout_s=20).passed


def test_fibonacci_exige_algoritmo_rapido():
    slow = (
        "def fibonacci_mod(n, m):\n"
        "    a, b = 0, 1\n"
        "    for _ in range(n):\n"
        "        a, b = b, (a + b) % m\n"
        "    return a\n"
    )
    res = run_python(slow, next(p for p in datasets.CODE_PROBLEMS if p["id"] == "fibonacci")["tests"], timeout_s=2)
    assert not res.passed and res.status == "timeout"


def test_grade_code_de_extremo_a_extremo():
    case = {"tests": "assert suma(1, 2) == 3", "level": 1}
    good = grading.grade_code(case, "```python\ndef suma(a, b):\n    return a + b\n```")
    assert good["correct"] and good["level"] if "level" in good else good["correct"]
    bad = grading.grade_code(case, "```python\ndef suma(a, b):\n    return a - b\n```")
    assert not bad["correct"] and "AssertionError" in bad["note"]
    assert grading.grade_code(case, "no sé")["status"] == "sin código"


# --------------------------------------------------------------------- resumen


def _item(idx, name, ev, metrics=None, error=None, t0=0.0, t1=1.0):
    return {"idx": idx, "name": name, "eval": ev, "metrics": metrics or {}, "error": error,
            "started_at": t0, "finished_at": t1}  # fmt: skip


def test_resumen_qa_y_codigo():
    items = [
        _item(0, "a", {"kind": "qa", "correct": True, "format_ok": True}),
        _item(1, "b", {"kind": "qa", "correct": False, "format_ok": False}),
        _item(2, "c", {"kind": "qa", "correct": True, "format_ok": True, "truncated": True}),
    ]
    q = quality_summary("qa", items, [])
    assert (q["total"], q["correct"]) == (3, 2)
    assert q["accuracy_pct"] == pytest.approx(66.666, abs=0.01)
    assert q["format_ok_pct"] == pytest.approx(66.666, abs=0.01) and q["truncated"] == 1
    code = quality_summary(
        "codigo",
        [
            _item(0, "x", {"kind": "code", "correct": True, "level": 1}),
            _item(1, "y", {"kind": "code", "correct": False, "level": 3, "status": "timeout"}),
        ],
        [],
    )
    assert code["pass_at_1_pct"] == 50.0 and code["timeouts"] == 1
    assert code["by_level"] == {"1": {"total": 1, "correct": 1}, "3": {"total": 1, "correct": 0}}


def test_resumen_sin_items_no_inventa_cero():
    q = quality_summary("qa", [], [])
    assert q["total"] == 0 and q["accuracy_pct"] is None
    assert quality_summary("libre", [], []) is None


def test_resumen_contexto_con_vram_y_limite():
    def ev(size, depth, ok, failed=False):
        return {"kind": "needle", "correct": ok, "size": size, "depth": depth, "failed": failed}

    items = [
        _item(0, "2k", ev(2048, 50, True), {"prompt_tokens": 2100, "pp_server": 900, "ttft_s": 2.0}, t0=10, t1=12),
        _item(1, "4k", ev(4096, 50, True), {"prompt_tokens": 4200, "pp_server": 850, "ttft_s": 4.5}, t0=20, t1=25),
        _item(2, "8k", ev(8192, 50, False, True), {}, error="HTTP 400: exceed context", t0=30, t1=31),
    ]
    samples = [
        {"t": 5, "phase": "reposo", "device_id": "g0", "data": {"mem_used_mib": 1000}},
        {"t": 11, "phase": "carga", "device_id": "g0", "data": {"mem_used_mib": 5000}},
        {"t": 22, "phase": "carga", "device_id": "g0", "data": {"mem_used_mib": 6500}},
        {"t": 30.5, "phase": "carga", "device_id": "g0", "data": {"mem_used_mib": 5000}},
    ]
    q = quality_summary("contexto", items, samples)
    by = {d["size"]: d for d in q["by_size"]}
    assert by[2048]["vram_mib"] == 5000 and by[4096]["vram_mib"] == 6500
    assert by[4096]["vram_delta_mib"] == 5500
    assert q["max_size_ok"] == 4096 and q["first_failed_size"] == 8192
    assert by[8192]["failed"] == 1 and by[8192]["pp_server"] is None


def test_resumen_concurrencia_escala():
    def it(idx, level, t0, t1, tps, tokens=100):
        return _item(idx, f"n{level}", {"kind": "concurrency", "level": level},
                     {"completion_tokens": tokens, "tps_client": tps, "ttft_s": 0.2}, t0=t0, t1=t1)  # fmt: skip

    items = [it(0, 1, 0, 2, 50), it(1, 2, 10, 13, 33), it(2, 2, 10, 13, 33)]
    q = quality_summary("concurrencia", items, [])
    one, two = q["levels"]
    assert one["tps_aggregate"] == 50 and two["tps_aggregate"] == pytest.approx(200 / 3)
    assert two["scaling"] == pytest.approx(200 / 3 / 50) and two["efficiency_pct"] == pytest.approx(66.67, abs=0.01)
    assert q["best_level"] == 2
