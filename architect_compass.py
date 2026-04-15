"""Architect's Compass — entry point.

La lógica vive en el paquete `compass/`. Este archivo solo instancia la clase
principal y corre el flujo de auditoría. La CLI estructurada llega en CLI-015.
"""

import sys

sys.stdout.reconfigure(encoding="utf-8")

from compass.core import ArchitectCompass


if __name__ == "__main__":
    compass = ArchitectCompass()
    compass.analyze()
    compass.finalize()
