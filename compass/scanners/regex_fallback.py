"""Regex fallback scanner (Tier 3) — placeholder.

TODO (SCN-003, NIVEL 4 del PLAN.md):
    Scanner config-driven que usa `definitions[].patterns` del mapper_config.json
    para cualquier lenguaje sin grammar disponible.

    Hoy la lógica equivalente vive embebida en compass/core.py::analyze();
    migrarla a este módulo como implementación de la interfaz Scanner.
"""
