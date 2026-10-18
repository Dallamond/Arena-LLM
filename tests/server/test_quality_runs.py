"""Suites de calidad de punta a punta, sin GPU: el llama-server simulado contesta de verdad."""

import re

from server.quality import datasets
from tests.server.test_quality import REFERENCE
from tests.server.test_runs import endpoint_ready, run_finished

QA_ANSWERS = {q["q"]: q["a"] for q in datasets.QA_QUESTIONS}


def answerer(prompt: str) -> str:
    """Un «modelo» que acierta casi todo: falla la pregunta del bate y la última del código."""
    for q, a in QA_ANSWERS.items():
        if q in prompt:
            return "Pienso un poco.\nRESPUESTA: 0,10" if "bate" in q else f"Pienso un poco.\nRESPUESTA: {a}"
    for p in datasets.CODE_PROBLEMS:
        if f"`{p['entry']}" in prompt or f"class {p['entry']}" in prompt:
            code = REFERENCE[p["id"]]
            if p["id"] == "islas":
                code = "def contar_islas(grid):\n    return 0\n"
            return f"```python\n{code}\n```"
    m = re.search(r"El código secreto es ([0-9A-F-]+)\.", prompt)
    if m:
        return f"El código es {m.group(1)}"
    return "no sé"


def start(c, ep, suite, params):
    r = c.post("/api/runs", json={"suite": suite, "endpoint_id": ep["id"], "params": {"baseline_s": 0, **params}})
    assert r.status_code == 201, r.text
    return run_finished(c, r.json()["id"], timeout=60)


def test_las_cuatro_suites_aparecen_con_sus_campos(lab):
    c, _ = lab()
    suites = {s["id"]: s for s in c.get("/api/suites").json()}
    for sid in ("qa", "codigo", "contexto", "concurrencia"):
        assert sid in suites and suites[sid]["fields"]
    assert len(suites["qa"]["cases"]) == 12 and len(suites["codigo"]["cases"]) == 10
    assert suites["contexto"]["cases"][0] == "2048 tok · 10 %"
    assert suites["qa"]["graded"] and not suites["concurrencia"]["graded"]


def test_qa_corrige_y_resume(lab):
    c, fake = lab(responder=answerer, tps=2000.0)
    run = start(c, endpoint_ready(c), "qa", {"max_tokens": 64})
    assert run["status"] == "done"
    q = run["summary"]["quality"]
    assert (q["total"], q["correct"]) == (12, 11)
    assert q["accuracy_pct"] == 100 * 11 / 12 and q["format_ok_pct"] == 100
    items = {i["name"]: i for i in c.get(f"/api/runs/{run['id']}").json()["items"]}
    assert items["bate"]["eval"]["correct"] is False and items["bate"]["eval"]["got"] == "0,10"
    assert items["producto"]["eval"]["correct"] is True
    # mismas semillas ⇒ mismos prompts, y el servidor recibió el formato pedido
    assert all("RESPUESTA:" in b["messages"][-1]["content"] for b in fake.bodies)
    assert all(b["temperature"] == 0 and b["seed"] == 42 and b["cache_prompt"] is False for b in fake.bodies)


def test_qa_acepta_preguntas_propias_y_subconjunto(lab):
    c, _ = lab(responder=lambda p: "RESPUESTA: azul" if "color" in p else "RESPUESTA: 408", tps=2000.0)
    run = start(
        c,
        endpoint_ready(c),
        "qa",
        {"include": ["producto"], "custom": [{"pregunta": "¿De qué color es el cielo?", "respuesta": "Azul"}]},
    )
    q = run["summary"]["quality"]
    assert (q["total"], q["correct"]) == (2, 2)


def test_qa_sin_formato_es_incorrecto(lab):
    c, _ = lab(responder=lambda p: "creo que 408", tps=2000.0)
    run = start(c, endpoint_ready(c), "qa", {"include": ["producto"]})
    q = run["summary"]["quality"]
    assert q["correct"] == 0 and q["format_ok_pct"] == 0


def test_codigo_ejecuta_en_el_sandbox_y_calcula_pass_at_1(lab):
    c, _ = lab(responder=answerer, tps=3000.0)
    run = start(c, endpoint_ready(c), "codigo", {"max_tokens": 4000})
    q = run["summary"]["quality"]
    assert (q["total"], q["correct"]) == (10, 9)
    assert q["pass_at_1_pct"] == 90.0
    items = {i["name"]: i for i in c.get(f"/api/runs/{run['id']}").json()["items"]}
    assert items["islas"]["eval"]["correct"] is False and "AssertionError" in items["islas"]["eval"]["note"]
    assert items["lru"]["eval"]["correct"] is True and "def " in items["lru"]["eval"]["code"]


def test_codigo_malicioso_o_infinito_no_bloquea_el_servidor(lab, tmp_path):
    victim = tmp_path / "intocable.txt"
    victim.write_text("datos")
    bad = {
        "palindromo": "def es_palindromo(s):\n    while True:\n        pass",
        "dos_suma": f"import os\nos.remove({str(victim)!r})\ndef dos_suma(n, o):\n    return (0, 1)",
        "romano": f"open({str(tmp_path / 'nuevo.txt')!r}, 'w').write('x')\ndef romano_a_entero(s):\n    return 1",
    }

    def responder(prompt):
        for p in datasets.CODE_PROBLEMS:
            if f"`{p['entry']}" in prompt and p["id"] in bad:
                return f"```python\n{bad[p['id']]}\n```"
        return "nada"

    c, _ = lab(responder=responder, tps=3000.0)
    run = start(c, endpoint_ready(c), "codigo", {"include": list(bad), "code_timeout_s": 2})
    assert run["status"] == "done"
    q = run["summary"]["quality"]
    assert q["correct"] == 0 and q["timeouts"] == 1
    assert victim.read_text() == "datos" and not (tmp_path / "nuevo.txt").exists()
    assert c.get("/api/health").status_code == 200  # el servidor sigue vivo


def test_contexto_aguja_con_limite_y_vram(lab):
    # El servidor simulado rechaza los prompts de más de ~3000 palabras como «contexto excedido»
    c, fake = lab(responder=answerer, tps=3000.0, fail_prompt="__no_existe__")
    ep = endpoint_ready(c)
    run = start(c, ep, "contexto", {"sizes": [512, 1024], "depths": [10, 90], "max_tokens": 32})
    q = run["summary"]["quality"]
    assert (q["total"], q["correct"]) == (4, 4)
    assert q["max_size_ok"] == 1024 and q["first_failed_size"] is None
    assert [d["size"] for d in q["by_size"]] == [512, 1024]
    assert all(d["prompt_tokens"] for d in q["by_size"])
    items = c.get(f"/api/runs/{run['id']}").json()["items"]
    assert all(len(i["prompt"]) < 600 for i in items)  # el prompt enorme no se guarda entero
    assert fake.bodies and any(len(b["messages"][-1]["content"]) > 1500 for b in fake.bodies)


def test_contexto_excedido_queda_como_resultado(lab):
    c, _ = lab(responder=answerer, tps=3000.0, fail_prompt="secreto")
    run = start(c, endpoint_ready(c), "contexto", {"sizes": [512], "depths": [50]})
    assert run["status"] == "error"  # todas fallaron
    q = run["summary"]["quality"]
    assert q["failed"] == 1 and q["correct"] == 0 and q["first_failed_size"] == 512


def test_concurrencia_mide_agregado_por_nivel(lab):
    # tps bajo: el temporizador de Windows no distingue bien esperas de 10 ms
    c, fake = lab(tps=20.0)
    run = start(c, endpoint_ready(c), "concurrencia", {"levels": [1, 2], "max_tokens": 10})
    assert run["status"] == "done"
    q = run["summary"]["quality"]
    one, two = q["levels"]
    assert (one["requests"], two["requests"]) == (1, 2)
    assert one["tps_aggregate"] and two["tps_aggregate"] > one["tps_aggregate"] * 1.4
    assert two["scaling"] > 1.4 and q["best_level"] == 2
    assert fake.requests == 3


def test_validacion_de_opciones(lab):
    c, _ = lab()
    ep = endpoint_ready(c)
    for suite, params in (
        ("qa", {"include": ["no_existe"]}),
        ("codigo", {"code_timeout_s": 9999}),
        ("contexto", {"sizes": []}),
        ("contexto", {"depths": [150]}),
        ("concurrencia", {"levels": [0]}),
        ("concurrencia", {"levels": [1], "prompt": " "}),
    ):
        r = c.post("/api/runs", json={"suite": suite, "endpoint_id": ep["id"], "params": params})
        assert r.status_code == 422, (suite, params, r.text)


def test_el_hash_cambia_con_las_preguntas_y_es_estable(lab):
    c, _ = lab(responder=answerer, tps=3000.0)
    ep = endpoint_ready(c)
    a = start(c, ep, "qa", {"include": ["producto"]})
    b = start(c, ep, "qa", {"include": ["producto"]})
    d = start(c, ep, "qa", {"include": ["producto", "letras"]})
    assert a["suite_hash"] == b["suite_hash"] != d["suite_hash"]


# ---------------------------------------------------- batalla con corrección automática

import httpx  # noqa: E402
import pytest  # noqa: E402

from server.app import create_app  # noqa: E402
from server.fakes.fake_llama import FakeLlama, create_fake_app  # noqa: E402
from server.settings import Settings  # noqa: E402
from tests.conftest import run_uvicorn, start_agent  # noqa: E402
from tests.server.test_runs import wait  # noqa: E402


@pytest.fixture
def duel(tmp_path, stoppers):
    """Dos servidores simulados: A acierta todo en QA y B falla las dos primeras."""

    def weak(prompt):
        return "RESPUESTA: 0" if any(q in prompt for q in list(QA_ANSWERS)[:2]) else answerer(prompt)

    fakes = [FakeLlama(tps=3000.0, pp_tps=5000.0, responder=answerer),
             FakeLlama(tps=3000.0, pp_tps=5000.0, responder=weak, model="/m/otro-14b-Q4_K_M.gguf")]  # fmt: skip
    ports = []
    for f in fakes:
        url, stop = run_uvicorn(create_fake_app(f))
        stoppers.append(stop)
        ports.append(int(url.rsplit(":", 1)[1]))
    agent_url, stop_agent, _ = start_agent("nvidia2", servers=list(zip((4201, 4202), ports, strict=True)))
    stoppers.append(stop_agent)
    settings = Settings(data_dir=tmp_path, agents=[agent_url], poll_interval_s=0.1, web_dist=tmp_path / "no")
    api_url, stop_api = run_uvicorn(create_app(settings))
    stoppers.append(stop_api)
    c = httpx.Client(base_url=api_url, timeout=15)
    stoppers.append(c.close)
    eps = wait(lambda: len(ls := [e for e in c.get("/api/endpoints").json() if e["status"] == "listo"]) == 2 and ls)
    return c, sorted(eps, key=lambda e: e["base_url"] != f"http://127.0.0.1:{ports[0]}")


def test_batalla_de_qa_puntua_aciertos_por_lado(duel):
    c, eps = duel
    r = c.post(
        "/api/battles",
        json={
            "mode": "paralelo",
            "suite": "qa",
            "common": {"baseline_s": 0, "max_tokens": 64, "include": ["maquinas", "producto", "manzanas", "letras"]},
            "sides": [{"endpoint_id": eps[0]["id"]}, {"endpoint_id": eps[1]["id"], "params": {"temperature": 0.5}}],
        },
    )
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    b = wait(lambda: (x := c.get(f"/api/battles/{bid}").json())["status"] not in ("running", "pending") and x, 30)
    assert b["status"] == "done" and b["params"]["suite"] == "qa"
    score = [(run["summary"]["quality"]["correct"], run["summary"]["quality"]["total"]) for run in b["runs"]]
    assert score == [(4, 4), (2, 4)]
    assert {run["suite"] for run in b["runs"]} == {"qa"}
    # las preguntas son las mismas en los dos lados (mismo hash de suite salvo la temperatura del lado B)
    assert [len(run["items"]) for run in b["runs"]] == [4, 4]


def test_batalla_rechaza_pruebas_no_soportadas_y_opciones_ajenas(duel):
    c, eps = duel
    sides = [{"endpoint_id": eps[0]["id"]}, {"endpoint_id": eps[1]["id"]}]
    assert c.post("/api/battles", json={"mode": "paralelo", "suite": "estres", "sides": sides}).status_code == 422
    assert c.post("/api/battles", json={"mode": "paralelo", "suite": "libre", "sides": sides}).status_code == 422
    bad = {"mode": "paralelo", "suite": "qa", "common": {"sizes": [1024]}, "sides": sides}
    assert c.post("/api/battles", json=bad).status_code == 422
