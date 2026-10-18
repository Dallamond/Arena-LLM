"""Ejecución aislada del código que escriben los modelos.

Nunca se usa `exec()` en el servidor: el código va a un subproceso de Python propio con
- entorno mínimo (sin variables heredadas), directorio temporal propio y `stdin` cerrado;
- tiempo máximo, tras el cual se mata el árbol de procesos;
- un gancho de auditoría (`sys.addaudithook`, no se puede quitar desde el código) que prohíbe
  red, procesos, escritura fuera del directorio temporal y librerías nativas;
- en Linux, además, límites de CPU, memoria y tamaño de fichero (`resource`).

Es defensa en profundidad contra errores y descuidos del código generado (bucles infinitos,
borrar ficheros, abrir sockets), no una frontera de seguridad frente a un atacante decidido.
"""

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

OUTPUT_MAX = 4000  # caracteres que se guardan de la salida y de los errores
MEMORY_LIMIT_MB = 1024
CPU_LIMIT_S = 60

# Se ejecuta dentro del subproceso. Recibe por argv: marca secreta, ruta de la solución, ruta de los tests.
_RUNNER = r'''
import os, sys, builtins, runpy

MARK, SOLUTION, TESTS = sys.argv[1], sys.argv[2], sys.argv[3]
SANDBOX = os.path.realpath(os.getcwd())

def _inside(path):
    try:
        return os.path.realpath(os.fspath(path)).startswith(SANDBOX)
    except Exception:
        return False

_BLOCKED = (
    "socket.", "subprocess.", "os.system", "os.exec", "os.spawn", "os.fork", "os.posix_spawn",
    "os.kill", "os.killpg", "ctypes.", "winreg.", "msvcrt.", "webbrowser.", "pty.",
    "shutil.rmtree",
)
_WRITE_PATH_EVENTS = ("os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.chmod", "os.truncate",
                      "os.symlink", "os.link", "os.utime", "shutil.copyfile", "shutil.move")

def _hook(event, args):
    if event == "open":
        path, mode, flags = args
        writes = isinstance(mode, str) and any(c in mode for c in "wax+") or (isinstance(flags, int) and flags & 0o3)
        if writes and isinstance(path, (str, bytes, os.PathLike)) and not _inside(path):
            raise PermissionError("Arena: escritura fuera del directorio temporal")
        return
    if any(event.startswith(b) for b in _BLOCKED):
        raise PermissionError("Arena: operación no permitida en la prueba (" + event + ")")
    if event in _WRITE_PATH_EVENTS:
        for a in args:
            if isinstance(a, (str, bytes, os.PathLike)) and not _inside(a):
                raise PermissionError("Arena: modificar ficheros fuera del directorio temporal")

with open(SOLUTION, encoding="utf-8") as f:
    solution_src = f.read()
with open(TESTS, encoding="utf-8") as f:
    tests_src = f.read()

sys.addaudithook(_hook)
ns = {"__name__": "solucion"}
try:
    exec(compile(solution_src, "solucion.py", "exec"), ns)
except SystemExit:
    print("FALLO: la solución llamó a exit() al cargarse", file=sys.stderr)
    os._exit(3)
try:
    exec(compile(tests_src, "tests.py", "exec"), ns)
except SystemExit:
    print("FALLO: la solución llamó a exit() durante los tests", file=sys.stderr)
    os._exit(3)
sys.stdout.flush()
os.write(1, ("\n" + MARK + "\n").encode())
os._exit(0)
'''


@dataclass
class SandboxResult:
    passed: bool
    status: str  # "ok" | "fallo" | "timeout" | "error"
    stdout: str
    stderr: str
    seconds: float
    returncode: int | None

    def public(self) -> dict:
        return {
            "passed": self.passed,
            "status": self.status,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "seconds": round(self.seconds, 3),
            "returncode": self.returncode,
        }


def _posix_limits() -> None:  # pragma: no cover - solo Linux
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_MB * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT_S, CPU_LIMIT_S))
    resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024,) * 2)
    os.setsid()  # grupo propio para matarlo entero


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:  # pragma: no cover - solo Linux
        import signal

        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
    try:
        proc.kill()
    except OSError:
        pass


def _clip(text: str) -> str:
    return text if len(text) <= OUTPUT_MAX else text[:OUTPUT_MAX] + "\n… (recortado)"


def _env() -> dict[str, str]:
    keep = ("SYSTEMROOT", "SYSTEMDRIVE", "PATH") if os.name == "nt" else ("PATH",)
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0")
    return env


def run_python(solution: str, tests: str, timeout_s: float = 10.0) -> SandboxResult:
    """Ejecuta `solution` y después `tests` (aserciones) en un subproceso aislado."""
    import time

    mark = "ARENA-OK-" + secrets.token_hex(12)
    tmp = Path(tempfile.mkdtemp(prefix="arena-sbx-"))
    t0 = time.perf_counter()
    try:
        (tmp / "runner.py").write_text(_RUNNER, encoding="utf-8")
        (tmp / "solucion.py").write_text(solution, encoding="utf-8")
        (tmp / "tests.py").write_text(tests, encoding="utf-8")
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:  # pragma: no cover - solo Linux
            kwargs["preexec_fn"] = _posix_limits
        try:
            proc = subprocess.Popen(
                [sys.executable, "-I", "runner.py", mark, "solucion.py", "tests.py"],
                cwd=tmp,
                env=_env(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **kwargs,
            )
        except OSError as exc:
            return SandboxResult(False, "error", "", f"No se pudo lanzar Python: {exc}", 0.0, None)
        try:
            out, err = proc.communicate(timeout=timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            out, err = proc.communicate()
            timed_out = True
        seconds = time.perf_counter() - t0
        sout = out.decode("utf-8", "replace")
        serr = err.decode("utf-8", "replace")
        if timed_out:
            return SandboxResult(False, "timeout", _clip(sout), _clip(serr), seconds, None)
        passed = proc.returncode == 0 and mark in sout
        sout = sout.replace(mark, "").rstrip()
        return SandboxResult(passed, "ok" if passed else "fallo", _clip(sout), _clip(serr), seconds, proc.returncode)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def public_json(res: SandboxResult) -> str:
    return json.dumps(res.public(), ensure_ascii=False)
