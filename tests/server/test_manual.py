"""Alta manual de endpoints: un llama-server que el agente no ve como proceso."""

import pytest

from server.detect import normalize_base_url
from server.fakes.fake_llama import FakeLlama, create_fake_app
from tests.conftest import run_uvicorn
from tests.server.test_runs import endpoint_ready, run_finished, wait


@pytest.mark.parametrize(
    "raw, url",
    [
        ("http://localhost:8080/", "http://127.0.0.1:8080"),
        (" http://LOCALHOST:8080/v1 ", "http://127.0.0.1:8080"),
        ("https://gpu-box.lan:9000", "https://gpu-box.lan:9000"),
        ("http://[::1]:8080", "http://[::1]:8080"),
    ],
)
def test_normaliza_url(raw, url):
    assert normalize_base_url(raw) == url


@pytest.mark.parametrize("raw", ["127.0.0.1:8080", "ftp://x:1", "http://x:8080/completion", "http://x:99999"])
def test_url_invalida(raw):
    with pytest.raises(ValueError):
        normalize_base_url(raw)


def extra_llama(stoppers, **kw):
    """llama-server simulado que el agente NO detecta (no está en su lista de procesos)."""
    fake = FakeLlama(**{"tps": 200.0, "pp_tps": 5000.0, **kw})
    url, stop = run_uvicorn(create_fake_app(fake))
    return fake, url, stop


def test_alta_manual_sondeo_y_gpu(lab, stoppers):
    c, _ = lab()
    endpoint_ready(c)  # el detectado por proceso
    fake, url, stop = extra_llama(stoppers)
    host = c.get("/api/hosts").json()[0]
    gpu_ids = [d["device_id"] for d in host["devices"] if d["kind"] == "gpu"]
    port = url.rsplit(":", 1)[1]

    r = c.post(
        "/api/endpoints", json={"host_id": host["id"], "base_url": f"http://localhost:{port}/v1", "alias": " caja "}
    )
    assert r.status_code == 201
    ep = r.json()
    assert ep["manual"] and ep["base_url"] == f"http://127.0.0.1:{port}" and ep["alias"] == "caja"
    assert c.post("/api/endpoints", json={"host_id": host["id"], "base_url": url}).status_code == 409
    assert c.post("/api/endpoints", json={"host_id": host["id"], "base_url": "sin-esquema"}).status_code == 422
    assert c.post("/api/endpoints", json={"host_id": 99, "base_url": "http://x:1"}).status_code == 404

    ready = wait(
        lambda: (
            (e := c.get("/api/endpoints").json())
            and next((x for x in e if x["id"] == ep["id"] and x["status"] == "listo"), None)
        )
    )
    snap = ready["snapshot"]
    assert snap["source"] == "manual" and snap["pid"] is None and snap["devices"] == []
    assert snap["derived"]["n_ctx_total"] == 8192 and snap["model_file"]
    kinds = lambda: [x["kind"] for x in reversed(c.get(f"/api/changes?endpoint={ep['id']}").json())]  # noqa: E731
    assert kinds() == ["manual", "listo"]

    # GPU asociada a mano: manda sobre la detección y queda como cambio de configuración
    assert c.patch(f"/api/endpoints/{ep['id']}", json={"device_ids": ["nvidia:no-existe"]}).status_code == 422
    r = c.patch(f"/api/endpoints/{ep['id']}", json={"device_ids": [gpu_ids[1]]})
    assert r.status_code == 200 and r.json()["device_ids"] == [gpu_ids[1]] and r.json()["alias"] == "caja"
    ch = wait(
        lambda: next((x for x in c.get(f"/api/changes?endpoint={ep['id']}").json() if x["kind"] == "cambio"), None)
    )
    assert ch["diff"]["gpus"] == [[], [gpu_ids[1]]]
    snap = c.get("/api/endpoints").json()
    snap = next(x for x in snap if x["id"] == ep["id"])["snapshot"]
    assert snap["gpu_link"] == "manual" and snap["devices"][0]["device_id"] == gpu_ids[1]

    # Se puede probar como cualquier otro, y la telemetría vigila la GPU asociada
    run = c.post(
        "/api/runs", json={"suite": "libre", "endpoint_id": ep["id"], "params": {"prompt": "hola", "max_tokens": 8}}
    )
    assert run.status_code == 201, run.text
    done = run_finished(c, run.json()["id"])
    assert done["status"] == "done"
    assert list(done["host_snapshot"]["thresholds"]) == [gpu_ids[1]]

    # Parado: queda "sin respuesta" (no desaparece) y se anota
    stop()
    wait(lambda: next(x for x in c.get("/api/endpoints").json() if x["id"] == ep["id"])["status"] == "sin respuesta")
    assert kinds()[-1] == "detenido"


def test_baja(lab, stoppers):
    c, _ = lab()
    detected = endpoint_ready(c)
    assert c.delete(f"/api/endpoints/{detected['id']}").status_code == 409  # volvería a aparecer
    host = c.get("/api/hosts").json()[0]
    ep = c.post("/api/endpoints", json={"host_id": host["id"], "base_url": "http://127.0.0.1:1"}).json()
    assert c.delete(f"/api/endpoints/{ep['id']}").status_code == 204
    assert all(x["id"] != ep["id"] for x in c.get("/api/endpoints").json())
    assert c.get(f"/api/changes?endpoint={ep['id']}").json() == []
    assert c.delete(f"/api/endpoints/{ep['id']}").status_code == 404


def test_alta_manual_de_uno_ya_detectado(lab):
    c, _ = lab()
    detected = endpoint_ready(c)
    host = c.get("/api/hosts").json()[0]
    ep = c.post("/api/endpoints", json={"host_id": host["id"], "base_url": detected["base_url"]}).json()
    assert ep["id"] == detected["id"] and ep["manual"]
    # Sigue viéndose como proceso: conserva pid y flags
    snap = wait(lambda: next(x for x in c.get("/api/endpoints").json() if x["id"] == ep["id"])["snapshot"])
    assert snap["source"] == "proceso" and snap["pid"] is not None
