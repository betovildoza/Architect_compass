"""Scanners — dispatcher placeholder.

TODO (SCN-003, NIVEL 4 del PLAN.md):
    Implementar función dispatcher:
        get_scanner(language, config) -> Scanner

    Orden de preferencia:
        1. python       → Tier 1 (ast stdlib)
        2. treesitter   → Tier 2 (si grammar instalada)
        3. regex_fallback → Tier 3 (config-driven)

    Invocado desde compass/core.py::analyze() con el lenguaje detectado por STK-001.
"""