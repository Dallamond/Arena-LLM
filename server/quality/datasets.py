"""Bancos de preguntas, problemas de código y generador de texto para las pruebas de calidad.

Son datos: cambiar cualquier cosa de aquí exige subir la VERSION de la suite que los usa
(el hash de contenido de la suite los incluye y el comparador marca el cambio).
"""

import hashlib
import random
from typing import Any

# --------------------------------------------------------------------- qa

QA_FORMAT = (
    "\n\nRazona brevemente y termina con una última línea exactamente así:\n"
    "RESPUESTA: <valor>\n"
    "Solo el valor, sin unidades ni explicaciones en esa línea."
)

#: id, pregunta, respuesta esperada y alternativas aceptadas.
QA_QUESTIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "maquinas",
        "q": "Si 3 máquinas hacen 3 piezas en 3 minutos, ¿cuántos minutos necesitan 100 máquinas para hacer 100 piezas?",
        "a": "3",
    },
    {"id": "producto", "q": "¿Cuánto es 17 × 24?", "a": "408"},
    {
        "id": "manzanas",
        "q": "Tengo 5 manzanas, me como 2 y luego compro el triple de las que me quedan. ¿Cuántas manzanas tengo ahora?",
        "a": "12",
    },
    {"id": "australia", "q": "¿Cuál es la capital de Australia?", "a": "Canberra"},
    {"id": "serie", "q": "Completa la serie: 2, 6, 12, 20, 30, ¿cuál es el siguiente número?", "a": "42"},
    {
        "id": "bate",
        "q": "Un bate y una pelota cuestan 1,10 € en total. El bate cuesta 1 € más que la pelota. ¿Cuánto cuesta la pelota, en euros?",
        "a": "0.05",
        "alt": ["5 centimos", "5 cent", "0.05 eur"],
    },
    {
        "id": "dias",
        "q": "En un año no bisiesto, ¿cuántos días suman febrero, marzo y abril juntos?",
        "a": "89",
    },
    {
        "id": "altura",
        "q": "Ana es más alta que Beto, Beto es más alto que Carla y Carla es más alta que Dani. ¿Quién es la segunda más baja?",
        "a": "Carla",
    },
    {"id": "segundos", "q": "¿Cuántos segundos hay en 2,5 horas?", "a": "9000"},
    {
        "id": "silogismo",
        "q": "Todos los bloops son razzies y todos los razzies son lazzies. ¿Son todos los bloops lazzies? Responde sí o no.",
        "a": "si",
        "alt": ["yes"],
    },
    {"id": "reves", "q": 'Escribe la palabra "linux" al revés.', "a": "xunil"},
    {"id": "letras", "q": 'Cuenta cuántas veces aparece la letra "r" en la palabra "carretera".', "a": "3"},
)


def qa_cases(include: list[str] | None, custom: list[dict[str, str]] | None) -> list[dict[str, Any]]:
    ids = set(include) if include else None
    cases = []
    for item in QA_QUESTIONS:
        if ids is not None and item["id"] not in ids:
            continue
        cases.append(
            {
                "name": f"{item['id']}",
                "prompt": item["q"] + QA_FORMAT,
                "expected": item["a"],
                "alt": list(item.get("alt", [])),
            }
        )
    for i, c in enumerate(custom or []):
        q, a = str(c.get("pregunta", "")).strip(), str(c.get("respuesta", "")).strip()
        if q and a:
            cases.append({"name": f"propia {i + 1}", "prompt": q + QA_FORMAT, "expected": a, "alt": []})
    return cases


# ----------------------------------------------------------------- código

CODE_FORMAT = (
    "\n\nEscribe la solución completa en Python dentro de UN solo bloque ```python. "
    "Sin ejemplos de uso ni llamadas a input(): solo el código de la función (o clase) y lo que necesite."
)

_FIB_REF = '''
def _ref_fib(n, m):
    def fd(k):
        if k == 0:
            return (0, 1)
        a, b = fd(k >> 1)
        c = a * ((2 * b - a) % m) % m
        d = (a * a + b * b) % m
        return (d, (c + d) % m) if k & 1 else (c, d)
    return fd(n)[0] % m
'''

CODE_PROBLEMS: tuple[dict[str, Any], ...] = (
    {
        "id": "palindromo",
        "level": 1,
        "entry": "es_palindromo",
        "desc": "`es_palindromo(s)`: devuelve True si el texto es un palíndromo ignorando mayúsculas, espacios y signos de puntuación (solo cuentan letras y dígitos). La cadena vacía es palíndromo.",
        "tests": """
assert es_palindromo("Anita lava la tina") is True
assert es_palindromo("A man, a plan, a canal: Panama") is True
assert es_palindromo("hola") is False
assert es_palindromo("") is True
assert es_palindromo("12321") is True
assert es_palindromo("12345") is False
""",
    },
    {
        "id": "dos_suma",
        "level": 1,
        "entry": "dos_suma",
        "desc": "`dos_suma(nums, objetivo)`: devuelve una tupla (i, j) con i < j tal que nums[i] + nums[j] == objetivo. Hay exactamente una solución.",
        "tests": """
assert tuple(dos_suma([2, 7, 11, 15], 9)) == (0, 1)
assert tuple(dos_suma([3, 2, 4], 6)) == (1, 2)
assert tuple(dos_suma([3, 3], 6)) == (0, 1)
assert tuple(dos_suma([-1, -2, -3, -4, -5], -8)) == (2, 4)
""",
    },
    {
        "id": "intervalos",
        "level": 2,
        "entry": "fusionar_intervalos",
        "desc": "`fusionar_intervalos(intervalos)`: recibe una lista de pares [inicio, fin], posiblemente desordenada, y devuelve la lista de intervalos fusionados y ordenados (dos intervalos que se tocan en un extremo se fusionan). Lista vacía → lista vacía.",
        "tests": """
norm = lambda r: [list(x) for x in r]
assert norm(fusionar_intervalos([[1, 3], [2, 6], [8, 10], [15, 18]])) == [[1, 6], [8, 10], [15, 18]]
assert norm(fusionar_intervalos([[1, 4], [4, 5]])) == [[1, 5]]
assert norm(fusionar_intervalos([[5, 6], [1, 2]])) == [[1, 2], [5, 6]]
assert norm(fusionar_intervalos([])) == []
assert norm(fusionar_intervalos([[1, 10], [2, 3]])) == [[1, 10]]
""",
    },
    {
        "id": "romano",
        "level": 1,
        "entry": "romano_a_entero",
        "desc": "`romano_a_entero(s)`: convierte un número romano (1–3999) a entero.",
        "tests": """
assert romano_a_entero("III") == 3
assert romano_a_entero("LVIII") == 58
assert romano_a_entero("MCMXCIV") == 1994
assert romano_a_entero("IX") == 9
assert romano_a_entero("MMMCMXCIX") == 3999
""",
    },
    {
        "id": "aplanar",
        "level": 2,
        "entry": "aplanar",
        "desc": "`aplanar(lista)`: aplana una lista con anidamiento arbitrario de listas y devuelve una lista plana en el mismo orden. Las cadenas NO se desglosan (siguen siendo un elemento).",
        "tests": """
assert list(aplanar([1, [2, [3, [4]], 5]])) == [1, 2, 3, 4, 5]
assert list(aplanar([])) == []
assert list(aplanar(["ab", ["cd", ["e"]]])) == ["ab", "cd", "e"]
assert list(aplanar([[[]], 1])) == [1]
""",
    },
    {
        "id": "parentesis",
        "level": 2,
        "entry": "parentesis_validos",
        "desc": "`parentesis_validos(s)`: True si los paréntesis (), corchetes [] y llaves {} del texto están bien emparejados y anidados. Cadena vacía → True.",
        "tests": """
assert parentesis_validos("()[]{}") is True
assert parentesis_validos("(]") is False
assert parentesis_validos("((") is False
assert parentesis_validos("") is True
assert parentesis_validos("{[()]}") is True
assert parentesis_validos("([)]") is False
assert parentesis_validos("]") is False
""",
    },
    {
        "id": "lru",
        "level": 3,
        "entry": "LRUCache",
        "desc": "`class LRUCache` con `__init__(self, capacidad)`, `get(self, clave)` (devuelve el valor o -1 si no existe y marca la clave como usada) y `put(self, clave, valor)` (inserta o actualiza; si se supera la capacidad, expulsa la clave usada hace más tiempo).",
        "tests": """
c = LRUCache(2)
c.put(1, 1); c.put(2, 2)
assert c.get(1) == 1
c.put(3, 3)
assert c.get(2) == -1
c.put(4, 4)
assert c.get(1) == -1
assert c.get(3) == 3
assert c.get(4) == 4
d = LRUCache(1)
d.put(1, 1); d.put(1, 5)
assert d.get(1) == 5
d.put(2, 2)
assert d.get(1) == -1
""",
    },
    {
        "id": "frecuencias",
        "level": 2,
        "entry": "frecuencias_top",
        "desc": "`frecuencias_top(texto, k)`: devuelve la lista de las k palabras más frecuentes como tuplas (palabra, veces). Pasa el texto a minúsculas y quita la puntuación (solo cuentan letras y dígitos dentro de cada palabra). Desempate: orden alfabético.",
        "tests": """
t = "El perro y el gato. El PERRO ladra, el gato maulla; y el pez nada."
assert [tuple(x) for x in frecuencias_top(t, 3)] == [("el", 5), ("gato", 2), ("perro", 2)]
assert [tuple(x) for x in frecuencias_top("a b b c c", 2)] == [("b", 2), ("c", 2)]
assert frecuencias_top("", 3) == []
""",
    },
    {
        "id": "fibonacci",
        "level": 3,
        "entry": "fibonacci_mod",
        "desc": "`fibonacci_mod(n, m)`: devuelve F(n) mod m, con F(0)=0 y F(1)=1. n puede llegar a 10**18, así que hace falta un algoritmo rápido (no vale iterar n veces).",
        "tests": _FIB_REF
        + """
assert fibonacci_mod(10, 1000) == 55
assert fibonacci_mod(0, 7) == 0
assert fibonacci_mod(1, 7) == 1
for n, m in ((10**18, 10**9 + 7), (123456789012345678, 998244353), (10**15, 1000), (97, 10)):
    assert fibonacci_mod(n, m) == _ref_fib(n, m), (n, m)
""",
    },
    {
        "id": "islas",
        "level": 2,
        "entry": "contar_islas",
        "desc": "`contar_islas(grid)`: recibe una matriz de 0 y 1 (lista de listas) y devuelve el número de islas (grupos de 1 conectados en horizontal o vertical, no en diagonal). Matriz vacía o sin unos → 0.",
        "tests": """
assert contar_islas([[1, 1, 0, 0], [1, 0, 0, 1], [0, 0, 1, 1]]) == 2
assert contar_islas([]) == 0
assert contar_islas([[0, 0], [0, 0]]) == 0
assert contar_islas([[1, 0], [0, 1]]) == 2
assert contar_islas([[1]]) == 1
assert contar_islas([[1, 1, 1], [1, 1, 1]]) == 1
""",
    },
)


def code_cases(include: list[str] | None) -> list[dict[str, Any]]:
    ids = set(include) if include else None
    return [
        {
            "name": p["id"],
            "prompt": f"Implementa en Python lo siguiente:\n\n{p['desc']}{CODE_FORMAT}",
            "entry": p["entry"],
            "tests": p["tests"],
            "level": p["level"],
        }
        for p in CODE_PROBLEMS
        if ids is None or p["id"] in ids
    ]


# --------------------------------------------------------------- contexto

NEEDLE_QUESTION = (
    "\n\nEn el texto anterior hay una frase que dice cuál es el código secreto. "
    "¿Cuál es el código secreto? Responde solo con el código."
)

_FILLER_SENTENCES = (
    "El río atraviesa el valle despacio mientras las nubes cambian de forma sobre las montañas.",
    "En la plaza del pueblo, los vecinos comentan el precio del pan y el tiempo de la semana.",
    "La biblioteca abre a las nueve y cierra cuando el último lector termina su capítulo.",
    "Un tren de mercancías cruza el puente cada tarde sin que nadie levante la vista del campo.",
    "El taller huele a madera recién cortada y a barniz, y siempre suena una radio lejana.",
    "Al final del camino hay una fuente donde los caminantes rellenan sus botellas antes de subir.",
    "Las cuentas del trimestre mostraron pocas sorpresas y un ligero aumento en los gastos de envío.",
    "Cada otoño el bosque se llena de setas, y cada otoño alguien se pierde buscándolas.",
    "El técnico revisó los cables, apuntó los resultados en su cuaderno y volvió a cerrar el armario.",
    "La tormenta pasó de largo, dejando el aire limpio y las calles brillando bajo la farola.",
    "Los niños dibujaron un mapa del patio con tres tesoros y un río de tiza azul.",
    "Nadie recuerda quién plantó el nogal, pero todos saben a quién pertenece su sombra.",
)


def needle_code(seed: int, size: int, depth: int) -> str:
    """Código secreto determinista (no aparece en el relleno)."""
    h = hashlib.sha256(f"{seed}|{size}|{depth}".encode()).hexdigest().upper()
    return f"{h[:4]}-{h[4:8]}-{h[8:12]}"


def build_needle_prompt(seed: int, size_tokens: int, depth_pct: int, chars_per_token: float) -> tuple[str, str]:
    """Texto de relleno de ~size_tokens tokens con la frase secreta a depth_pct % de profundidad."""
    rng = random.Random(f"{seed}|{size_tokens}|{depth_pct}")
    target_chars = int(size_tokens * chars_per_token)
    code = needle_code(seed, size_tokens, depth_pct)
    needle = f"El código secreto es {code}."
    parts: list[str] = []
    total = 0
    while total < target_chars:
        s = rng.choice(_FILLER_SENTENCES)
        parts.append(s)
        total += len(s) + 1
    at = min(len(parts), max(0, round(len(parts) * depth_pct / 100)))
    parts.insert(at, needle)
    return " ".join(parts) + NEEDLE_QUESTION, code


# ------------------------------------------------------------ concurrencia

CONCURRENCY_PROMPT = (
    "Escribe un texto continuo y detallado sobre cómo organizar un viaje de una semana por la sierra, "
    "sin listas ni títulos."
)
