"""Architect's Compass — root dispatcher (CLI-015).

Entry point principal de la CLI. Todos los subcomandos viven en
`compass/cli.py`. Este archivo es el target del .bat local y de cualquier
script externo que quiera invocar compass uniformemente.

Uso:
    python compass.py scan [path] [flags]
    python compass.py symbols [path] [flags]
    python compass.py init [path]
    python compass.py graph [path]
    python compass.py --help

Backward-compat:
    Los archivos `architect_compass.py` y `architect_symbols.py` siguen
    funcionando como wrappers delgados — invocan al mismo main() de abajo.
"""

import sys

# Asegurar stdout UTF-8 en Windows (preservado del entry point legacy).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from compass.cli import main


if __name__ == "__main__":
    sys.exit(main())