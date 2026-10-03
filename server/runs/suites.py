"""Suites de prueba con versión y hash de contenido (reproducibles y comparables).

Cambiar prompts, semillas o valores por defecto de una suite exige subir su
VERSION: el hash lo delata igualmente y el comparador lo marcará.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

#: Parámetros de muestreo que se pasan tal cual a /v1/chat/completions.
SAMPLING_KEYS = (
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "repeat_penalty",
    "presence_penalty",
    "frequency_penalty",
    "seed",
    "max_tokens",
    "stop",
    "cache_prompt",
)

COMMON_DEFAULTS: dict[str, Any] = {
    "temperature": 0.0,
    "seed": 42,
    "cache_prompt": False,  # medir sin caché de prompt (equidad)
    "system": "",
    "extra": {},
    "baseline_s": 5,  # reposo antes de cargar (línea base de temperatura y potencia)
    "cooldown_s": 0,  # enfriamiento después (curva de enfriado)
    "timeout_s": 600,
}


@dataclass(frozen=True)
class Suite:
    id: str
    name: str
    version: str
    mode: str  # "items" (lista de prompts) | "duration" (bucle durante X s)
    description: str
    defaults: dict[str, Any]
    prompts: tuple[str, ...] = field(default=())

    def params(self, user: dict[str, Any] | None) -> dict[str, Any]:
        merged = {**COMMON_DEFAULTS, **self.defaults}
        for k, v in (user or {}).items():
            if v is not None:
                merged[k] = v
        return merged

    def content_hash(self, params: dict[str, Any]) -> str:
        """Hash de lo que define la prueba: suite, versión, prompts y parámetros de generación."""
        prompts = params.get("prompts") if self.mode == "items" else list(self.prompts)
        keyed = {k: params.get(k) for k in (*SAMPLING_KEYS, "system", "extra", "repeats", "duration_s", "parallel")}
        blob = json.dumps(
            {"suite": self.id, "version": self.version, "prompts": prompts, "params": keyed},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "mode": self.mode,
            "description": self.description,
            "defaults": {**COMMON_DEFAULTS, **self.defaults},
            "prompts": list(self.prompts),
        }


def payload_for(params: dict[str, Any], prompt: str) -> dict[str, Any]:
    messages = []
    if params.get("system"):
        messages.append({"role": "system", "content": params["system"]})
    messages.append({"role": "user", "content": prompt})
    body: dict[str, Any] = {"messages": messages}
    for k in SAMPLING_KEYS:
        if params.get(k) is not None:
            body[k] = params[k]
    extra = params.get("extra") or {}
    if isinstance(extra, dict):
        body.update(extra)
    return body


STRESS_TOPICS = (
    "Explica con detalle cómo funciona un motor de combustión interna de cuatro tiempos, fase por fase.",
    "Escribe un relato largo sobre un refugio de montaña durante una tormenta de nieve que dura tres días.",
    "Describe paso a paso cómo montar un servidor doméstico con Proxmox, almacenamiento y copias de seguridad.",
    "Redacta una guía extensa para empezar a correr desde cero hasta completar una media maratón.",
    "Explica la historia de la informática desde las máquinas de cálculo mecánicas hasta los modelos de lenguaje.",
    "Escribe un ensayo largo sobre las ventajas y los inconvenientes de vivir en el campo frente a la ciudad.",
    "Describe en detalle el ciclo del agua y su relación con el clima de la península ibérica.",
    "Explica cómo funciona una red neuronal, desde la neurona artificial hasta el entrenamiento con gradientes.",
    "Redacta un plan de negocio detallado para una pequeña tienda online de camisetas personalizadas.",
    "Cuenta la historia de la exploración espacial, desde el Sputnik hasta las misiones a Marte.",
    "Explica con ejemplos cómo funciona la criptografía de clave pública y por qué es segura.",
    "Describe una ruta de senderismo de una semana por la sierra de Guadarrama, etapa por etapa.",
)

SUITES: dict[str, Suite] = {
    "libre": Suite(
        id="libre",
        name="Prompt libre",
        version="1",
        mode="items",
        description="Uno o varios prompts propios (separados por ---), con repeticiones. Sin evaluación automática.",
        defaults={
            "prompts": ["Explica en tres párrafos qué es un modelo de lenguaje."],
            "repeats": 1,
            "max_tokens": 512,
        },
    ),
    "estres": Suite(
        id="estres",
        name="Estrés GPU/VRAM",
        version="1",
        mode="duration",
        description=(
            "Peticiones largas en bucle durante la duración elegida, rotando temas. Mide t/s a lo largo del tiempo, "
            "temperatura, potencia, reloj, throttling, degradación y energía."
        ),
        defaults={"duration_s": 120, "parallel": 1, "max_tokens": 512, "baseline_s": 10, "cooldown_s": 30},
        prompts=STRESS_TOPICS,
    ),
}
