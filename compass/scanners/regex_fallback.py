"""Regex fallback scanner (Tier 3) — SCN-003 + EDG-023.

Config-driven. Recibe un dict con patterns (`inbound` / `outbound`) y aplica
`re.findall` sobre el contenido del archivo. Devuelve sólo los matches de
`outbound` (los imports/dependencias). Los `inbound` los sigue consumiendo
core.py para scoring de identidades.

EDG-023 — shape extendido de patterns:
    Cada entry en `patterns.outbound` puede ser:
      - `str` (legacy) — regex sola, edge_type default "use".
      - `dict` con `{"regex": "...", "edge_type": "require"|"import"|...}`.
    El scanner devuelve tuples `(target, edge_type)` consumidas por core.py.

Equivalente funcional al scanning regex que vivía embebido en
compass/core.py::analyze() antes de SCN-003.
"""

import re

from compass.scanners.base import Scanner as _BaseScanner, DEFAULT_EDGE_TYPE


class RegexFallbackScanner(_BaseScanner):
    """Scanner Tier 3 basado en patrones del config.

    Parámetros:
        patterns: dict con clave `outbound`. Items pueden ser str (legacy)
            o `{"regex": "...", "edge_type": "..."}` (EDG-023). Si viene
            `inbound` se ignora — ese tier se maneja aparte.
    """

    def __init__(self, patterns):
        patterns = patterns or {}
        raw_outbound = patterns.get("outbound", []) or []
        # EDG-023: guardamos (compiled, edge_type) por pattern.
        self._compiled = []
        for pat in raw_outbound:
            regex_str, edge_type = self._extract_pattern_fields(pat)
            if not regex_str:
                continue
            try:
                compiled = re.compile(regex_str, re.I)
            except re.error:
                # Patrón inválido: lo saltamos silenciosamente para no
                # abortar el run completo.
                continue
            # GRF-021 — ignorar patterns sin grupos de captura. Una regex
            # outbound sin `(...)` solo confirma que el pattern aparece en
            # el archivo, pero no extrae el path del target. Matchearlo
            # emite un nodo fantasma con el texto del pattern (ej.
            # `curl_exec`, `document.querySelector`). Mejor: descartar
            # silenciosamente; si el usuario quiere ver esas llamadas,
            # el `metadata.calls` del nodo fuente las va a listar.
            if compiled.groups < 1:
                continue
            self._compiled.append((compiled, edge_type))

    @staticmethod
    def _extract_pattern_fields(pat):
        """Normaliza un pattern de config a `(regex_str, edge_type)`.

        Acepta:
          - str  → `(pat, DEFAULT_EDGE_TYPE)`
          - dict → `(pat["regex"], pat.get("edge_type", DEFAULT_EDGE_TYPE))`
        """
        if pat is None:
            return None, DEFAULT_EDGE_TYPE
        if isinstance(pat, dict):
            regex_str = pat.get("regex") or pat.get("pattern")
            edge_type = pat.get("edge_type") or DEFAULT_EDGE_TYPE
            return (regex_str, str(edge_type)) if regex_str else (None, DEFAULT_EDGE_TYPE)
        return str(pat), DEFAULT_EDGE_TYPE

    def extract_imports(self, file_path):
        if not self._compiled:
            return []
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            return []

        out = []
        for regex, edge_type in self._compiled:
            for match in regex.findall(content):
                if isinstance(match, tuple):
                    # Primer grupo no vacío gana (mismo criterio que el
                    # core viejo). Si todos vacíos, descartamos.
                    match = next((g for g in match if g), "")
                if match:
                    out.append((str(match).strip(), edge_type))
        return out