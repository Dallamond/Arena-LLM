"""llama-server simulado para tests y para desarrollar sin GPU.

Imita las respuestas reales de la build b11379 (03/10/2026): `/health` (503
mientras "carga"), `/props`, `/slots`, `/v1/models` y `/v1/chat/completions`
en streaming con `usage` y `timings` en el último chunk.

    python -m server.fakes.fake_llama --port 8085 --tps 40
"""

import argparse
import asyncio
import hashlib
import json
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

WORDS = (
    "el modelo genera texto de prueba para medir la velocidad del servidor con datos simulados "
    "y deterministas sin tarjeta gráfica ni pesos reales en esta máquina de desarrollo"
).split()


class FakeLlama:
    def __init__(
        self,
        tps: float = 40.0,
        pp_tps: float = 800.0,
        n_ctx: int = 8192,
        slots: int = 2,
        model: str = "/modelos/falso-7b-Q4_K_M.gguf",
        loading_s: float = 0.0,
        build: str = "b0000-simulado",
        fail_prompt: str | None = None,
    ):
        self.tps = tps
        self.pp_tps = pp_tps
        self.n_ctx = n_ctx
        self.slots = slots
        self.model = model
        self.ready_at = time.monotonic() + loading_s
        self.build = build
        self.fail_prompt = fail_prompt
        self.busy = 0
        self.requests = 0

    @property
    def loading(self) -> bool:
        return time.monotonic() < self.ready_at

    def props(self) -> dict[str, Any]:
        return {
            "default_generation_settings": {
                "params": {"seed": 4294967295, "temperature": 0.8, "top_k": 40, "top_p": 0.95, "n_predict": -1},
                "n_ctx": self.n_ctx // self.slots,
            },
            "total_slots": self.slots,
            "model_alias": self.model,
            "model_ftype": "Q4_K_M",
            "model_path": self.model,
            "modalities": {"vision": False, "video": False, "audio": False},
            "endpoint_slots": True,
            "endpoint_props": False,
            "endpoint_metrics": False,
            "chat_template": "{% for m in messages %}{{ m.content }}{% endfor %}",
            "build_info": self.build,
        }


def create_fake_app(fake: FakeLlama | None = None) -> FastAPI:
    fake = fake or FakeLlama()
    app = FastAPI(title="llama-server simulado")
    app.state.fake = fake

    def loading_response() -> JSONResponse:
        return JSONResponse(
            {"error": {"message": "Loading model", "type": "unavailable_error", "code": 503}}, status_code=503
        )

    @app.get("/health")
    def health():
        return loading_response() if fake.loading else {"status": "ok"}

    @app.get("/props")
    def props():
        return loading_response() if fake.loading else fake.props()

    @app.get("/slots")
    def slots():
        if fake.loading:
            return loading_response()
        return [
            {"id": i, "n_ctx": fake.n_ctx // fake.slots, "speculative": False, "is_processing": i < fake.busy}
            for i in range(fake.slots)
        ]

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": [{"id": fake.model, "object": "model", "created": 0}]}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        if fake.loading:
            return loading_response()
        body = await request.json()
        prompt = " ".join(str(m.get("content", "")) for m in body.get("messages", []))
        if fake.fail_prompt and fake.fail_prompt in prompt:
            return JSONResponse(
                {
                    "error": {
                        "code": 400,
                        "message": "the request exceeds the available context size",
                        "type": "exceed_context_size_error",
                    }
                },
                status_code=400,
            )
        max_tokens = int(body.get("max_tokens") or 64)
        seed = int(hashlib.sha256(f"{prompt}|{body.get('seed')}".encode()).hexdigest(), 16)
        prompt_n = max(1, len(prompt.split()))
        fake.requests += 1

        async def stream():
            fake.busy += 1
            try:
                created = int(time.time())
                base = {
                    "created": created,
                    "id": "chatcmpl-fake",
                    "model": fake.model,
                    "system_fingerprint": fake.build,
                    "object": "chat.completion.chunk",
                }
                yield _sse({**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": None}}]})
                t0 = time.perf_counter()
                await asyncio.sleep(prompt_n / fake.pp_tps)
                prompt_ms = (time.perf_counter() - t0) * 1000
                t1 = time.perf_counter()
                for i in range(max_tokens):
                    word = WORDS[(seed + i) % len(WORDS)]
                    yield _sse({**base, "choices": [{"index": 0, "delta": {"content": word + " "}}]})
                    await asyncio.sleep(1 / fake.tps)
                predicted_ms = (time.perf_counter() - t1) * 1000
                yield _sse({**base, "choices": [{"index": 0, "finish_reason": "length", "delta": {}}]})
                yield _sse({
                    **base,
                    "choices": [],
                    "usage": {"completion_tokens": max_tokens, "prompt_tokens": prompt_n,
                              "total_tokens": prompt_n + max_tokens, "prompt_tokens_details": {"cached_tokens": 0}},
                    "timings": {"cache_n": 0, "prompt_n": prompt_n, "prompt_ms": prompt_ms,
                                "prompt_per_second": prompt_n / (prompt_ms / 1000),
                                "predicted_n": max_tokens, "predicted_ms": predicted_ms,
                                "predicted_per_second": max_tokens / (predicted_ms / 1000)},
                })  # fmt: skip
                yield "data: [DONE]\n\n"
            finally:
                fake.busy -= 1

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def main() -> None:
    import uvicorn

    p = argparse.ArgumentParser(description="llama-server simulado")
    p.add_argument("--port", type=int, default=8085)
    p.add_argument("--tps", type=float, default=40.0)
    p.add_argument("--slots", type=int, default=2)
    p.add_argument("--ctx", type=int, default=8192)
    p.add_argument("--loading", type=float, default=0.0, help="segundos simulando la carga del modelo")
    a = p.parse_args()
    fake = FakeLlama(tps=a.tps, n_ctx=a.ctx, slots=a.slots, loading_s=a.loading)
    uvicorn.run(create_fake_app(fake), host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
