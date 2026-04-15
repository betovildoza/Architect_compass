"""Architect's Compass — paquete principal.

Este paquete agrupa la lógica de auditoría estructural que antes vivía en
el archivo monolítico `architect_compass.py`. El archivo raíz queda como
entry point delgado e importa `compass.core`.

Submódulos:
    core            — clase ArchitectCompass (analyze, run_audit, finalize)
    stack_detector  — placeholder; llenado en sesión STK-001
    path_resolver   — placeholder; llenado en sesión RES-002
    scanners/       — placeholders; llenado en sesión SCN-003
"""

from compass.core import ArchitectCompass

__all__ = ["ArchitectCompass"]