"""Regex fallback scanner (Tier 3) — SCN-003.

Config-driven. Recibe un dict con patterns (`inbound` / `outbound`) y aplica
`re.findall` sobre el contenido del archivo. Devuelve sólo los matches de
`outbound` (los imports/dependencias). Los `inbound` los sigue consumiendo
core.py para scoring de identidades.

Equivalente funcional al scanning regex que vivía embebido en
compass/core.py::analyze() antes de SCN-003.
"""

import re

from compass.scanners.base import Scanner as _BaseScanner


class RegexFallbackScanner(_BaseScanner):
    """Scanner Tier 3 basado en patrones del config.

    Parámetros:
        patterns: dict con clave `outbound` (lista de regex strings). Si
            viene `inbound` se ignora — ese tier se maneja aparte.
    """

    def __init__(self, patterns):
        patterns = patterns or {}
        raw_outbound = patterns.get("outbound", []) or []
        self._compiled = []
        for pat in raw_outbound:
            try:
                self._compiled.append(re.compile(pat, re.I))
            except re.error:
                # Patrón inválido: lo saltamos silenciosamente para no
                # abortar el run completo.
                continue

    def extract_imports(self, file_path):
        if not self._compiled:
            return []
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            return []

        out = []
        for regex in self._compiled:
            for match in regex.findall(content):
                if isinstance(match, tuple):
                    # Primer grupo no vacío gana (mismo criterio que el
                    # core viejo). Si todos vacíos, descartamos.
                    match = next((g for g in match if g), "")
                if match:
                    out.append(str(match).strip())
        return out