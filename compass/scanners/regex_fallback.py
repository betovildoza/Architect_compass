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
from pathlib import Path

from compass.scanners.base import Scanner as _BaseScanner, DEFAULT_EDGE_TYPE
from compass.path_resolver import encode_loader_raw

# URL-SCAN — regex para capturar URL literals en source text.
_URL_LITERAL_RE = re.compile(r'''["'](https?://[^"'\s)]+)["']''')

# PHP-018b — detección de `require`/`include` con variable PHP asignada
# previamente a una expresión resoluble estáticamente.
#
# Patrón común en bootstraps PHP:
#     $config_path = dirname(__DIR__, 2) . '/etca_config.php';
#     require_once $config_path;
#
# El scanner regex normal no captura esto porque el `require_once` usa
# variable, no literal. Este pass hace dos sub-pases:
#   1. Detectar asignaciones `$var = dirname(__DIR__[, N]) . 'literal'` o
#      `$var = __DIR__ . 'literal'` — acumula candidatos por varname.
#   2. Detectar `require|require_once|include|include_once $var;` — emite
#      un edge por cada candidato asociado al varname, usando el source_file
#      para resolver `dirname(__DIR__, N)` a un path absoluto.
#
# Reasignaciones condicionales (pattern fallback típico: primero prueba
# path A, si no existe prueba B) acumulan ambos candidatos. Los que no
# resuelvan a un archivo real los descartará el PathResolver.
_PHP_VAR_ASSIGN_RE = re.compile(
    r"""\$([A-Za-z_]\w*)\s*=\s*"""      # $varname =
    r"""(dirname\s*\(\s*__DIR__(?:\s*,\s*(\d+))?\s*\)|__DIR__)"""  # dirname(__DIR__[, N]) | __DIR__
    r"""\s*\.\s*['"]([^'"]+)['"]""",    # . 'literal' o . "literal"
    re.IGNORECASE,
)

_PHP_REQUIRE_VAR_RE = re.compile(
    r"""\b(?:require|require_once|include|include_once)\s+\$([A-Za-z_]\w*)""",
    re.IGNORECASE,
)


def _collect_php_var_assignments(content):
    """PHP-018b — Extrae asignaciones a variables con expresiones path-like.

    Devuelve dict `{varname: [(levels_up, literal), ...]}` donde levels_up es
    el argumento de dirname (0 = __DIR__ sin dirname, 1 = dirname(__DIR__),
    2 = dirname(__DIR__, 2), etc.). Múltiples asignaciones al mismo var
    acumulan en la lista (maneja el patrón de fallback condicional).
    """
    assigns = {}
    for m in _PHP_VAR_ASSIGN_RE.finditer(content):
        var = m.group(1)
        base_expr = m.group(2).lower().replace(" ", "")
        levels_str = m.group(3)
        literal = m.group(4)
        if base_expr.startswith("dirname"):
            levels = int(levels_str) if levels_str else 1
        else:
            levels = 0
        assigns.setdefault(var, []).append((levels, literal))
    return assigns


def _resolve_dirname_levels(source_file, levels):
    """PHP-018b — Resuelve `dirname(__DIR__, levels)` a path absoluto posix.

    __DIR__ = source_file.parent. dirname() sube un nivel por cada unidad.
    levels=0 → __DIR__ (sin dirname), levels=1 → dirname(__DIR__), etc.
    """
    if source_file is None:
        return None
    base = Path(source_file).resolve().parent
    for _ in range(levels):
        base = base.parent
    return base


def _php_require_var_sentinels(content, file_path):
    """PHP-018b — Genera candidatos resueltos para `require $var` con
    asignación previa.

    Args:
        content: source PHP crudo.
        file_path: ruta absoluta del archivo fuente (para resolver __DIR__).

    Yields:
        tuples `(target, "require")` con el path candidato como string.
        Los paths son absolutos posix; el PathResolver los valida contra
        el proyecto y descarta los que no existan.
    """
    assigns = _collect_php_var_assignments(content)
    if not assigns:
        return
    for m in _PHP_REQUIRE_VAR_RE.finditer(content):
        var = m.group(1)
        candidates = assigns.get(var)
        if not candidates:
            continue
        for levels, literal in candidates:
            base = _resolve_dirname_levels(file_path, levels)
            if base is None:
                continue
            literal_clean = literal.lstrip("/\\")
            candidate_path = (base / literal_clean).as_posix()
            yield candidate_path, "require"

# Mini-S10.5 — detectar array literal PHP tipo `['a.php', 'b.php']` o
# `array('a.php', 'b.php')` como primer argumento. Solo match si TODOS los
# elementos son string literals (no variables ni concatenaciones). Extrae
# cada literal; si hay variables/arrays dinámicos, retorna lista vacía.
_PHP_ARRAY_LITERAL_RE = re.compile(
    r'''^\s*(?:\[|array\s*\()\s*(.+?)\s*(?:\]|\))\s*(?:,.*)?$''', re.DOTALL,
)
_PHP_STRING_ITEM_RE = re.compile(r'''['"]([^'"]+)['"]''')


def _expand_loader_body(fn_name, body, loader_specs):
    """Mini-S10.5 — Dada una call body cruda, devuelve una lista de
    cuerpos sintéticos a emitir como sentinels.

    Caso normal: devuelve `[body]` intacto.
    Caso `accepts_array: true` + primer arg = array literal con solo
    strings: devuelve `["'item1'", "'item2'", ...]` — un body por string,
    para que el resolver trate cada uno como call one-arg normal.
    Si el array tiene variables o no se puede parsear, retorna `[body]`
    (el resolver termina descartándolo, comportamiento pre-S10.5).
    """
    if not loader_specs:
        return [body]
    spec = loader_specs.get(fn_name) or {}
    if not spec.get("accepts_array"):
        return [body]
    # Extraer el primer arg del body a mano (split_call_args vive en el
    # resolver; acá replicamos muy chico: buscar `[` o `array(` al inicio).
    stripped = body.lstrip()
    if not (stripped.startswith("[") or stripped.lower().startswith("array")):
        return [body]
    m = _PHP_ARRAY_LITERAL_RE.match(body)
    if not m:
        return [body]
    inner = m.group(1)
    # Detectar presencia de variables o concatenaciones → bail out.
    # Quitamos primero los string literals para ver si queda ruido no-delim.
    residual = _PHP_STRING_ITEM_RE.sub("", inner)
    if re.search(r"[\$\.]", residual):
        return [body]
    items = _PHP_STRING_ITEM_RE.findall(inner)
    if not items:
        return [body]
    return [f"'{item}'" for item in items]


class RegexFallbackScanner(_BaseScanner):
    """Scanner Tier 3 basado en patrones del config.

    Parámetros:
        patterns: dict con clave `outbound`. Items pueden ser str (legacy)
            o `{"regex": "...", "edge_type": "..."}` (EDG-023). Si viene
            `inbound` se ignora — ese tier se maneja aparte.
        http_regex: compiled regex de NET-022 http_loaders (opcional).
    """

    def __init__(self, patterns, http_regex=None, loader_regex=None,
                 loader_edge_map=None, loader_specs=None):
        self._http_regex = http_regex
        # SEM-020 — regex de loader_calls + dict fn_name → edge_type.
        self._loader_regex = loader_regex
        self._loader_edge_map = loader_edge_map or {}
        # Mini-S10.5 — spec completa por fn_name (para accepts_array).
        self._loader_specs = loader_specs or {}
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
        # Mini-S10.5 — si spec declara `accepts_array`, expandir array literal
        # PHP en múltiples sentinels (uno por string) al vuelo.
        if self._loader_regex:
            for match in self._loader_regex.finditer(content):
                fn = match.group(1)
                body = match.group(2) or ""
                edge_type = self._loader_edge_map.get(fn, DEFAULT_EDGE_TYPE)
                for emitted_body in _expand_loader_body(
                    fn, body, self._loader_specs,
                ):
                    out.append((encode_loader_raw(fn, emitted_body), edge_type))

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

        # PHP-018b — `require|include $var` con asignación previa
        # `$var = dirname(__DIR__[, N]) . 'literal'`. Emite candidato ya
        # resuelto a path absoluto (sin sentinel) — PathResolver valida
        # existencia y descarta si no cae dentro del proyecto.
        if str(file_path).lower().endswith(".php"):
            for target, edge_type in _php_require_var_sentinels(content, file_path):
                out.append((target, edge_type))

        return out