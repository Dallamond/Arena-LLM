"""Suites de prueba con versión y hash de contenido (reproducibles y comparables).

Cambiar prompts, semillas o valores por defecto de una suite exige subir su
VERSION: el hash lo delata igualmente y el comparador lo marcará.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from server.quality import datasets

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


#: Opciones propias de las suites que cuentan para el hash de contenido.
SUITE_PARAM_KEYS = ("levels", "code_timeout_s")


class SuiteParamError(ValueError):
    """Parámetro de una suite fuera de rango o con forma incorrecta."""


@dataclass(frozen=True)
class Case:
    """Un ítem de una suite con evaluación: el prompt y lo que necesita el corrector."""

    name: str
    prompt: str
    spec: dict[str, Any]  # kind + esperado/tests/nivel…
    stored_prompt: str | None = None  # versión recortada para guardar (prompts enormes)

    def public(self) -> dict[str, Any]:
        return {"name": self.name, "prompt": self.stored_prompt or self.prompt, "spec": self.spec}


@dataclass(frozen=True)
class Suite:
    id: str
    name: str
    version: str
    # "items" (lista de prompts) | "duration" (bucle durante X s) | "concurrency" (niveles de paralelismo)
    mode: str
    description: str
    defaults: dict[str, Any]
    prompts: tuple[str, ...] = field(default=())
    #: Suites con evaluación: genera los ítems a partir de los parámetros. Sin él, mode "items" usa `prompts`.
    cases: Callable[[dict[str, Any]], list[Case]] | None = None
    #: Campos del formulario de la GUI: {key, label, type, help, choices?}.
    fields: tuple[dict[str, Any], ...] = ()
    graded: bool = False

    def params(self, user: dict[str, Any] | None) -> dict[str, Any]:
        merged = {**COMMON_DEFAULTS, **self.defaults}
        for k, v in (user or {}).items():
            if v is not None:
                merged[k] = v
        return merged

    def content_hash(self, params: dict[str, Any]) -> str:
        """Hash de lo que define la prueba: suite, versión, prompts y parámetros de generación."""
        if self.cases is not None:
            prompts = [c.public() for c in self.cases(params)]
        elif self.mode == "concurrency":
            prompts = [params.get("prompt")]
        else:
            prompts = params.get("prompts") if self.mode == "items" else list(self.prompts)
        keyed = {
            k: params.get(k)
            for k in (*SAMPLING_KEYS, "system", "extra", "repeats", "duration_s", "parallel", *SUITE_PARAM_KEYS)
        }
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
            "graded": self.graded,
            "fields": list(self.fields),
            "cases": [c.name for c in self.cases(self.params(None))] if self.cases else None,
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

def _int_list(params: dict[str, Any], key: str, lo: int, hi: int, label: str) -> list[int]:
    raw = params.get(key)
    if not isinstance(raw, list) or not raw:
        raise SuiteParamError(f"'{label}': lista de enteros entre {lo} y {hi}")
    out = []
    for v in raw:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v or not lo <= v <= hi:
            raise SuiteParamError(f"'{label}': cada valor debe ser un entero entre {lo} y {hi}")
        out.append(int(v))
    return list(dict.fromkeys(out))


def _id_list(params: dict[str, Any], valid: set[str]) -> list[str] | None:
    raw = params.get("include")
    if raw in (None, []):
        return None
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise SuiteParamError("'include' debe ser una lista de identificadores")
    unknown = sorted(set(raw) - valid)
    if unknown:
        raise SuiteParamError(f"Identificadores desconocidos: {', '.join(unknown)}")
    return raw


def qa_cases(params: dict[str, Any]) -> list[Case]:
    include = _id_list(params, {q["id"] for q in datasets.QA_QUESTIONS})
    custom = params.get("custom") or []
    if not isinstance(custom, list) or not all(isinstance(c, dict) for c in custom):
        raise SuiteParamError("'custom' debe ser una lista de {pregunta, respuesta}")
    cases = [
        Case(c["name"], c["prompt"], {"kind": "qa", "expected": c["expected"], "alt": c["alt"]})
        for c in datasets.qa_cases(include, custom)
    ]
    if not cases:
        raise SuiteParamError("Hace falta al menos una pregunta")
    return cases


def code_cases(params: dict[str, Any]) -> list[Case]:
    include = _id_list(params, {p["id"] for p in datasets.CODE_PROBLEMS})
    cases = [
        Case(c["name"], c["prompt"], {"kind": "code", "tests": c["tests"], "level": c["level"]})
        for c in datasets.code_cases(include)
    ]
    if not cases:
        raise SuiteParamError("Hace falta al menos un problema")
    try:
        timeout = float(params.get("code_timeout_s") or 10)
    except (TypeError, ValueError) as exc:
        raise SuiteParamError("'code_timeout_s' debe ser un número") from exc
    if not 1 <= timeout <= 120:
        raise SuiteParamError("'code_timeout_s' entre 1 y 120")
    return cases


def context_cases(params: dict[str, Any]) -> list[Case]:
    sizes = _int_list(params, "sizes", 256, 1_048_576, "tamaños de contexto")
    depths = _int_list(params, "depths", 0, 100, "profundidades")
    cpt = float(params.get("chars_per_token") or 3.5)
    if not 1 <= cpt <= 8:
        raise SuiteParamError("'chars_per_token' entre 1 y 8")
    seed = int(params.get("seed") or 0)
    cases = []
    for size in sorted(sizes):
        for depth in sorted(depths):
            prompt, code = datasets.build_needle_prompt(seed, size, depth, cpt)
            head = f"[relleno de ≈{size} tokens con el código a {depth} % de profundidad] "
            cases.append(
                Case(
                    f"{size} tok · {depth} %",
                    prompt,
                    {"kind": "needle", "expected": code, "size": size, "depth": depth},
                    stored_prompt=head + datasets.NEEDLE_QUESTION.strip(),
                )
            )
    return cases


def concurrency_levels(params: dict[str, Any]) -> list[int]:
    return sorted(_int_list(params, "levels", 1, 64, "niveles de concurrencia"))


def _choices(items: tuple[dict[str, Any], ...], label_key: str) -> list[dict[str, str]]:
    return [{"value": i["id"], "label": f"{i['id']} · {i[label_key][:60]}"} for i in items]


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
    "qa": Suite(
        id="qa",
        name="Preguntas con respuesta (QA)",
        version="1",
        mode="items",
        graded=True,
        description=(
            "12 preguntas de razonamiento y cultura con respuesta conocida. El modelo debe acabar con "
            "«RESPUESTA: valor»; se compara normalizando acentos, mayúsculas y números."
        ),
        defaults={"include": None, "custom": [], "repeats": 1, "max_tokens": 1024, "baseline_s": 3},
        cases=qa_cases,
        fields=(
            {"key": "include", "label": "Preguntas", "type": "choices", "choices": _choices(datasets.QA_QUESTIONS, "q"),
             "help": "Sin marcar = todas."},
            {"key": "custom", "label": "Preguntas propias", "type": "pairs",
             "help": "Una por línea: pregunta | respuesta esperada."},
            {"key": "repeats", "label": "Repeticiones", "type": "number"},
            {"key": "max_tokens", "label": "Tokens máximos", "type": "number",
             "help": "Los modelos que razonan necesitan bastantes."},
        ),
    ),
    "codigo": Suite(
        id="codigo",
        name="Calidad de código",
        version="1",
        mode="items",
        graded=True,
        description=(
            "10 problemas de Python en 3 niveles. Arena extrae el bloque de código, lo ejecuta aislado "
            "(subproceso, sin red, sin stdin, directorio temporal) con los tests y calcula el pass@1."
        ),
        defaults={"include": None, "repeats": 1, "max_tokens": 2048, "code_timeout_s": 10, "baseline_s": 3},
        cases=code_cases,
        fields=(
            {"key": "include", "label": "Problemas", "type": "choices",
             "choices": _choices(datasets.CODE_PROBLEMS, "desc"), "help": "Sin marcar = todos."},
            {"key": "repeats", "label": "Repeticiones", "type": "number"},
            {"key": "max_tokens", "label": "Tokens máximos", "type": "number"},
            {"key": "code_timeout_s", "label": "Tiempo máximo del código (s)", "type": "number"},
        ),
    ),
    "contexto": Suite(
        id="contexto",
        name="Contexto largo (aguja en un pajar)",
        version="1",
        mode="items",
        graded=True,
        description=(
            "Texto de relleno determinista con un código secreto a distintas profundidades y tamaños. "
            "Mide si lo encuentra, la velocidad de procesado del prompt, el TTFT y la VRAM frente al contexto. "
            "Si un tamaño no cabe, queda como resultado (así se conoce el límite)."
        ),
        defaults={"sizes": [2048, 4096, 8192], "depths": [10, 50, 90], "chars_per_token": 3.5, "max_tokens": 64,
                  "repeats": 1, "baseline_s": 3},
        cases=context_cases,
        fields=(
            {"key": "sizes", "label": "Tamaños (tokens)", "type": "numlist", "help": "Separados por comas."},
            {"key": "depths", "label": "Profundidades (%)", "type": "numlist", "help": "Dónde se esconde el código."},
            {"key": "chars_per_token", "label": "Caracteres por token", "type": "number",
             "help": "Solo orientativo: los tokens reales salen del servidor."},
            {"key": "max_tokens", "label": "Tokens máximos", "type": "number"},
        ),
    ),
    "concurrencia": Suite(
        id="concurrencia",
        name="Concurrencia",
        version="1",
        mode="concurrency",
        description=(
            "El mismo prompt con 1, 2, 4… peticiones a la vez (cada nivel tras el anterior). Mide los t/s "
            "agregados, los t/s por petición y el TTFT por nivel: cuánto escala el servidor con los slots."
        ),
        defaults={"levels": [1, 2, 4], "max_tokens": 128, "prompt": datasets.CONCURRENCY_PROMPT, "baseline_s": 3},
        fields=(
            {"key": "levels", "label": "Niveles de concurrencia", "type": "numlist",
             "help": "Necesitas al menos tantos slots (-np) como el nivel mayor."},
            {"key": "max_tokens", "label": "Tokens por petición", "type": "number"},
            {"key": "prompt", "label": "Prompt", "type": "text"},
        ),
    ),
}
