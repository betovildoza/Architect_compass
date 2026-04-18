"""Architect's Compass — legacy entry point (CLI-015 wrapper).

La CLI real vive en `compass/cli.py` (subcomandos scan/symbols/init/graph).
Este archivo se conserva como wrapper delgado por backward-compat:
cualquier script externo, .bat, CI pipeline o cron que invoque
`python architect_compass.py [args]` sigue funcionando y es equivalente a
`compass scan [args]`.
"""

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from compass.cli import main_scan


if __name__ == "__main__":
    sys.exit(main_scan())