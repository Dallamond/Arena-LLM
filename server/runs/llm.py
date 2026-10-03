"""Cliente de streaming contra `/v1/chat/completions` (compatible con OpenAI).

Mide en el cliente (TTFT, t/s) y recoge `timings`/`usage` del servidor cuando
existen (propios de llama.cpp). Lo que falta queda como None.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class ChatResult:
    content: str = ""
    reasoning: str = ""
    t_start: float = 0.0
    t_first: float | None = None
    t_last: float | None = None
    t_end: float | None = None
    chunks: int = 0  # chunks con texto (≈ tokens en llama-server)
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    timings: dict[str, Any] | None = None
    error: str | None = None
    http_status: int | None = None
    token_times: list[float] = field(default_factory=list)

    def metrics(self) -> dict[str, Any]:
        usage = self.usage or {}
        tim = self.timings or {}
        n_gen = usage.get("completion_tokens") or tim.get("predicted_n") or (self.chunks or None)
        tps_client = None
        if self.t_first is not None and self.t_last is not None and self.chunks > 1 and self.t_last > self.t_first:
            tps_client = (self.chunks - 1) / (self.t_last - self.t_first)
        return {
            "ttft_s": self.t_first - self.t_start if self.t_first is not None else None,
            "latency_s": self.t_end - self.t_start if self.t_end is not None else None,
            "prompt_tokens": usage.get("prompt_tokens") or tim.get("prompt_n"),
            "completion_tokens": n_gen,
            "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", tim.get("cache_n")),
            "chunks": self.chunks,
            "tps_client": tps_client,
            "tps_server": tim.get("predicted_per_second"),
            "pp_server": tim.get("prompt_per_second"),
            "prompt_ms": tim.get("prompt_ms"),
            "predicted_ms": tim.get("predicted_ms"),
            "finish_reason": self.finish_reason,
            "reasoning_chars": len(self.reasoning) or None,
        }


async def stream_chat(
    client: httpx.AsyncClient,
    base_url: str,
    payload: dict[str, Any],
    on_text: Callable[[str, str], None] | None = None,
    timeout_s: float = 600.0,
) -> ChatResult:
    """Lanza una petición en streaming. `on_text(tipo, texto)` recibe 'content' o 'reasoning'."""
    body = {**payload, "stream": True, "stream_options": {"include_usage": True}}
    res = ChatResult(t_start=time.perf_counter())
    try:
        async with client.stream(
            "POST", base_url.rstrip("/") + "/v1/chat/completions", json=body, timeout=timeout_s
        ) as r:
            res.http_status = r.status_code
            if r.status_code != 200:
                raw = (await r.aread()).decode("utf-8", "replace")
                res.error = _error_message(raw, r.status_code)
                return res
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if "error" in chunk:
                    res.error = _error_message(json.dumps(chunk), r.status_code)
                    break
                if chunk.get("usage"):
                    res.usage = chunk["usage"]
                if chunk.get("timings"):
                    res.timings = chunk["timings"]
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    now = time.perf_counter()
                    for key, kind in (("reasoning_content", "reasoning"), ("content", "content")):
                        text = delta.get(key)
                        if text:
                            if res.t_first is None:
                                res.t_first = now
                            res.t_last = now
                            res.chunks += 1
                            res.token_times.append(now)
                            if kind == "content":
                                res.content += text
                            else:
                                res.reasoning += text
                            if on_text:
                                on_text(kind, text)
                    if choice.get("finish_reason"):
                        res.finish_reason = choice["finish_reason"]
    except httpx.TimeoutException:
        res.error = f"Tiempo agotado ({timeout_s:.0f} s)"
    except httpx.HTTPError as exc:
        res.error = f"Conexión con el servidor de inferencia: {type(exc).__name__}: {exc}"
    finally:
        res.t_end = time.perf_counter()
    return res


def _error_message(raw: str, status: int) -> str:
    try:
        err = json.loads(raw).get("error")
        if isinstance(err, dict):
            msg = err.get("message") or json.dumps(err)
            kind = err.get("type")
            return f"HTTP {status}: {msg}" + (f" ({kind})" if kind else "")
        if err:
            return f"HTTP {status}: {err}"
    except (ValueError, AttributeError):
        pass
    return f"HTTP {status}: {raw[:300]}"
