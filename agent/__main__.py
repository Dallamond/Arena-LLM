import sys

from agent import __version__


def main() -> int:
    print(f"Agente Arena {__version__} — servidor HTTP pendiente (F1, paso 2)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
