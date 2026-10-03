"""Detección de servidores y runs de punta a punta, sin GPU:
llama-server simulado + agente simulado (nvidia2) + servidor Arena, todo por HTTP real."""

import time


def wait(fn, timeout=10.0, every=0.1):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        last = fn()
        if last:
            return last
        time.sleep(every)
    raise AssertionError(f"condición no alcanzada (último valor: {last!r})")


def endpoint_ready(c):
    return wait(lambda: next((e for e in c.get("/api/endpoints").json() if e["status"] == "listo"), None))


def run_finished(c, run_id, timeout=20.0):
    return wait(
        lambda: (r := c.get(f"/api/runs/{run_id}").json())["status"] not in ("running", "pending") and r,
        timeout=timeout,
    )


def test_detecta_el_servidor_y_su_configuracion(lab):
    c, _ = lab()
    ep = endpoint_ready(c)
    snap = ep["snapshot"]
    d = snap["derived"]
    assert (d["n_ctx_slot"], d["total_slots"], d["n_ctx_total"]) == (4096, 2, 8192)
    assert d["model_ftype"] == "Q4_K_M" and d["build_info"] == "b0000-simulado"
    assert snap["flags"]["ngl"] == 99 and snap["gpu_link"] == "compute-apps"
    assert "chat_template" not in snap["props"]  # se guarda solo su hash
    assert [ch["kind"] for ch in c.get("/api/changes").json()] == ["nuevo"]


def test_cambio_de_configuracion_registrado(lab):
    c, fake = lab()
    endpoint_ready(c)
    fake.n_ctx = 16384  # como relanzar con otro -c
    ch = wait(lambda: next((x for x in c.get("/api/changes").json() if x["kind"] == "cambio"), None))
    assert ch["diff"]["ctx_por_slot"] == [4096, 8192]


def test_servidor_cargando(lab):
    c, _ = lab(loading_s=1.5)
    ep = wait(lambda: next(iter(c.get("/api/endpoints").json()), None))
    assert ep["status"] == "cargando"
    r = c.post("/api/runs", json={"suite": "libre", "endpoint_id": ep["id"], "params": {}})
    assert r.status_code == 409 and "no está listo" in r.json()["detail"]
    endpoint_ready(c)
    time.sleep(0.6)
    # Detectado mientras cargaba: al quedar listo se registra "listo", no un cambio falso
    assert [ch["kind"] for ch in reversed(c.get("/api/changes").json())] == ["nuevo", "listo"]


def test_run_libre_guarda_todo(lab):
    c, _ = lab()
    ep = endpoint_ready(c)
    r = c.post(
        "/api/runs",
        json={"suite": "libre", "endpoint_id": ep["id"], "label": "prueba",
              "params": {"prompts": ["Hola, ¿qué tal?", "Dime algo"], "max_tokens": 20, "baseline_s": 1.0}},
    )  # fmt: skip
    assert r.status_code == 201, r.text
    run = run_finished(c, r.json()["id"])
    assert run["status"] == "done", run
    assert run["suite_version"] == "1" and len(run["suite_hash"]) == 16
    assert run["servers_snapshot"]["derived"]["n_ctx_slot"] == 4096
    assert run["host_snapshot"]["thresholds"]  # umbrales usados, guardados con el run
    assert [i["prompt"] for i in run["items"]] == ["Hola, ¿qué tal?", "Dime algo"]
    m = run["items"][0]["metrics"]
    assert m["completion_tokens"] == 20 and m["ttft_s"] > 0
    assert m["tps_client"] > 0 and m["tps_server"] > 0
    assert run["items"][0]["response"].strip()
    s = run["summary"]
    assert s["completion_tokens"] == 40 and s["requests_ok"] == 2
    assert {x["phase"] for x in run["samples"]} >= {"reposo", "carga"}


def test_estres_con_telemetria_y_paralelo(lab):
    c, fake = lab(tps=60.0)
    ep = endpoint_ready(c)
    params = {"duration_s": 5, "parallel": 2, "max_tokens": 30, "baseline_s": 1, "cooldown_s": 1}
    r = c.post("/api/runs", json={"suite": "estres", "endpoint_id": ep["id"], "params": params})
    assert r.status_code == 201, r.text
    run = run_finished(c, r.json()["id"], timeout=30)
    assert run["status"] == "done", run
    assert len(run["tps"]) >= 4
    assert {x["phase"] for x in run["samples"]} == {"reposo", "carga", "enfriamiento"}
    s = run["summary"]
    assert s["requests_ok"] >= 4 and s["tps_aggregate"]["mean"] > 0
    gpu = next(v for k, v in s["devices"].items() if k.startswith("nvidia:"))
    assert gpu["energy_wh"] and gpu["power_mean_w"] and gpu["temp_max_c"] is not None
    assert s["energy_wh"] and s["tokens_per_wh"]
    assert s["degradation_pct"] is None  # run < 30 s: no se calcula


def test_aborto_termico(lab):
    c, _ = lab()
    ep = endpoint_ready(c)
    gpu0 = ep["snapshot"]["devices"][0]["device_id"]
    assert c.put("/api/settings/thresholds", json={gpu0: {"warn": 0, "crit": 1}}).status_code == 200
    r = c.post(
        "/api/runs", json={"suite": "estres", "endpoint_id": ep["id"], "params": {"duration_s": 60, "baseline_s": 0}}
    )
    run = run_finished(c, r.json()["id"], timeout=15)
    assert run["status"] == "aborted"
    assert "≥ 1 °C" in run["abort_reason"] and "ajustes" in run["abort_reason"]


def test_error_del_servidor_se_guarda_como_resultado(lab):
    c, _ = lab(fail_prompt="REVENTAR")
    ep = endpoint_ready(c)
    r = c.post(
        "/api/runs",
        json={"suite": "libre", "endpoint_id": ep["id"], "params": {"prompts": ["REVENTAR"], "baseline_s": 0}},
    )
    run = run_finished(c, r.json()["id"])
    assert run["status"] == "error"
    assert "exceeds the available context size" in run["items"][0]["error"]


def test_cancelar_y_validacion(lab):
    c, _ = lab()
    ep = endpoint_ready(c)
    bad = c.post("/api/runs", json={"suite": "estres", "endpoint_id": ep["id"], "params": {"parallel": 999}})
    assert bad.status_code == 422
    assert c.post("/api/runs", json={"suite": "nada", "endpoint_id": ep["id"]}).status_code == 404
    r = c.post(
        "/api/runs", json={"suite": "estres", "endpoint_id": ep["id"], "params": {"duration_s": 60, "baseline_s": 0}}
    )
    run_id = r.json()["id"]
    dup = c.post("/api/runs", json={"suite": "libre", "endpoint_id": ep["id"]})
    assert dup.status_code == 409
    assert c.delete(f"/api/runs/{run_id}").status_code == 409
    time.sleep(1.0)
    assert c.post(f"/api/runs/{run_id}/cancel").status_code == 202
    run = run_finished(c, run_id)
    assert run["status"] == "cancelled"
    assert c.delete(f"/api/runs/{run_id}").status_code == 204


def test_ajustes(lab):
    c, _ = lab()
    assert c.put("/api/settings/appearance", json={"accent": "#ffaa00"}).status_code == 200
    assert c.get("/api/settings").json()["appearance"] == {"accent": "#ffaa00"}
    assert c.put("/api/settings/otra", json={}).status_code == 404
    assert c.put("/api/settings/appearance", json=[1, 2]).status_code == 422
