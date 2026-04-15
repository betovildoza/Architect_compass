"""Architect's Compass — paquete principal.

Este paquete agrupa la lógica de auditoría estructural que antes vivía en
el archivo monolítico `architect_compass.py`. El archivo raíz queda como
entry point delgado e importa `compass.core`.

Submódulos:
    core            — clase ArchitectCompass (analyze, run_audit, finalize)
    stack_detector  — StackDetector + resolve_file_stack (STK-001 + MST-006)
    path_resolver   — PathResolver (RES-002)
    scanners/       — dispatcher get_scanner + Scanner base + tiers (SCN-003)
"""

from compass.core import ArchitectCompass
from compass.stack_detector import StackDetector, resolve_file_stack
from compass.path_resolver import PathResolver
from compass.scanners import get_scanner

__all__ = [
    "ArchitectCompass",
    "StackDetector",
    "resolve_file_stack",
    "PathResolver",
    "get_scanner",
]