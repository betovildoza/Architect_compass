"""Regex fallback scanner (Tier 3) — SCN-003 + EDG-023 + NET-022 + URL-SCAN.

Config-driven. Recibe un dict con patterns (`inbound` / `outbound`) y aplica
`re.findall` sobre el contenido del archivo. Devuelve sólo los matches de
`outbound` (los imports/dependencias). Los `inbound` los sigue consumiendo
core.py para scoring de identidades.

EDG-023 — shape extendido de patterns:
    Cada entry en `patterns.outbound` puede ser:
      - `str` (legacy) — regex sola, edge_type default "use".
      - `dict` con `{"regex": "...", "edge_type": "require"|"import"|...}`.
    El scanner devuelve tuples `(target, edge_type)` consumidas por core.py.

NET-022 — opcionalmente recibe un `http_regex` compilado. Si presente,
ejecuta un segundo pass sobre el source para capturar URLs literales en
llamadas HTTP (edge_type `"fetch"`). El regex lo compila el dispatcher
desde `http_loaders[language]` del config.

URL-SCAN — tercer pass: regex sobre todo el source para capturar TODAS las
URL literals (http:// o https://) independientemente del contexto.
Deduplicado contra URLs ya capturadas por NET-022.

Equivalente funcional al scanning regex que vivía embebido en
compass/core.py::analyze() antes de SCN-003.
"""

import re

from compass.scanners.base import Scanner as _BaseScanner, DEFAULT_EDGE_TYPE
from compass.path_resolver import encode_loader_raw

# URL-SCAN — regex para capturar URL literals en source text.
_URL_LITERAL_RE = re.compile(r'''["'](https?://[^"'\s)]+)["']''')


class RegexFallbackScanner(_BaseScanner):
    """Scanner Tier 3 basado en patrones del config.

    Parámetros:
        patterns: dict con clave `outbound`. Items pueden ser str (legacy)
            o `{"regex": "...", "edge_type": "..."}` (EDG-023). Si viene
            `inbound` se ignora — ese tier se maneja aparte.
        http_regex: compiled regex de NET-022 http_loaders (opcional).
    """

    def __init__(self, patterns, http_regex=None, loader_regex=None, loader_edge_map=None):
        self._http_regex = http_regex
        # SEM-020 — regex de loader_calls + dict fn_name → edge_type.
        self._loader_regex = loader_regex
        self._loader_edge_map = loader_edge_map or {}
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
        # URL-SCAN removed the early return — even without compiled patterns
        # or http_regex, we still scan for URL literals.
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

        # SEM-020 — loader_calls: emitir sentinel por cada call matcheada
        # con su edge_type configurado. El PathResolver resuelve el arg.
        if self._loader_regex:
            for match in self._loader_regex.finditer(content):
                fn = match.group(1)
                body = match.group(2) or ""
                edge_type = self._loader_edge_map.get(fn, DEFAULT_EDGE_TYPE)
                out.append((encode_loader_raw(fn, body), edge_type))

        # NET-022 — segundo pass: URLs literales en llamadas HTTP.
        if self._http_regex:
            for match in self._http_regex.finditer(content):
                url = match.group(1)
                if url:
                    out.append((url, "fetch"))

        # URL-SCAN — broad URL literal scan over source text.
        # Catch URLs regardless of calling function. Dedup against URLs
        # already captured by the http_loaders pass above.
        seen_urls = {t for t, et in out if et == "fetch"}
        for match in _URL_LITERAL_RE.finditer(content):
            url = match.group(1).strip()
            if len(url) > 10 and url not in seen_urls:
                seen_urls.add(url)
                out.append((url, "fetch"))

        return out