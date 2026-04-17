"""Scanners dispatcher — SCN-003 + NET-022.

`get_scanner(language, config) -> Scanner`

Orden de preferencia:
    1. Python → PythonScanner (Tier 1, stdlib ast).
    2. Language con entrada en `language_grammars` del config →
       TreeSitterScanner (Tier 2). Si la grammar no está instalada cae a 3.
    3. Lenguaje con definitions[].patterns en el config →
       RegexFallbackScanner (Tier 3).
    4. Nada disponible → NullScanner (devuelve []; se anota como aviso).

NET-022: todos los tiers reciben `config` para compilar el `http_loaders`
regex y extraer URLs literales de llamadas HTTP con edge_type `"fetch"`.

El scanner se cachea por (language, id(config)) para no re-construirlo por
archivo en cada run.
"""

from compass.scanners.base import (
    Scanner, NullScanner, build_http_loader_regex, build_loader_call_regex,
    DEFAULT_EDGE_TYPE,
)
from compass.scanners.html import HtmlScanner
from compass.scanners.python import PythonScanner
from compass.scanners.regex_fallback import RegexFallbackScanner

# El import de treesitter es barato (no carga grammars); las grammars se
# cargan sólo al instanciar TreeSitterScanner. Pero aislamos por si el
# módulo tuviera algún side-effect pesado en el futuro.
try:
    from compass.scanners.treesitter import TreeSitterScanner
    _TS_AVAILABLE = True
except ImportError:
    _TS_AVAILABLE = False


_SCANNER_CACHE = {}
_FEEDBACK_NO_SCANNER = set()


def get_scanner(language, config):
    """Devuelve un Scanner para `language` usando `config`.

    El caller ya resolvió stack → language (o extensión → language) antes
    de llamar. `language` siempre es string (puede ser "" o "unknown").
    """
    key = (language or "").lower()
    cache_key = (key, id(config))
    if cache_key in _SCANNER_CACHE:
        return _SCANNER_CACHE[cache_key]

    scanner = _build_scanner(key, config)
    _SCANNER_CACHE[cache_key] = scanner
    return scanner


def _build_scanner(language, config):
    if language == "python":
        return PythonScanner(config=config)
    if language in ("html", "htm"):
        return HtmlScanner(config=config)

    grammars = (config.get("language_grammars") or {}) if config else {}
    grammar_name = grammars.get(language)

    if grammar_name and grammar_name != "stdlib_ast" and _TS_AVAILABLE:
        try:
            return TreeSitterScanner(grammar_name, language, config=config)
        except ImportError:
            # La grammar no está instalada — caemos a Tier 3.
            pass

    # Tier 3: recoger patterns de las definitions aplicables.
    patterns = _collect_regex_patterns(language, config)
    # NET-022: compilar http_loaders regex para el lenguaje.
    http_regex = None
    # SEM-020: compilar loader_calls regex para el lenguaje.
    loader_regex = None
    loader_edge_map = {}
    lang_loaders = {}
    if config and isinstance(config, dict):
        loaders = (config.get("http_loaders") or {}).get(language) or []
        http_regex = build_http_loader_regex(loaders)
        loader_calls = config.get("loader_calls") or {}
        lang_loaders = {
            name: spec for name, spec in loader_calls.items()
            if isinstance(spec, dict)
            and (spec.get("language") or "").lower() == (language or "").lower()
        }
        if lang_loaders:
            loader_regex = build_loader_call_regex(lang_loaders.keys())
            loader_edge_map = {
                name: spec.get("edge_type") or DEFAULT_EDGE_TYPE
                for name, spec in lang_loaders.items()
            }
    if patterns.get("outbound") or http_regex or loader_regex:
        return RegexFallbackScanner(
            patterns,
            http_regex=http_regex,
            loader_regex=loader_regex,
            loader_edge_map=loader_edge_map,
            loader_specs=lang_loaders if loader_regex else None,
        )

    # Nada aplicable.
    if language not in _FEEDBACK_NO_SCANNER:
        _FEEDBACK_NO_SCANNER.add(language)
    return NullScanner()


def _collect_regex_patterns(language, config):
    """Junta outbound patterns de las definitions aplicables al `language`.

    DEF-017 — language filter:
      Cada entry de `definitions[]` puede declarar un campo `language`
      (string) o `languages` (lista de strings). Si declara, sólo aplica
      cuando coincide con el lenguaje del archivo escaneado. Si la
      definition NO declara `language`/`languages`, se asume que aplica a
      todos los lenguajes (backward-compat con configs pre-DEF-017).

    Esto evita que una regex pensada para PHP matchee spuriamente sobre
    un .js (origen del hallazgo Sesión 4 #4 — ver SESSION_LOG.md).
    """
    merged = {"inbound": [], "outbound": []}
    if not config:
        return merged
    target_language = (language or "").lower()
    for df in config.get("definitions", []) or []:
        if df.get("tier") and df["tier"] != "regex_fallback":
            continue
        if not _definition_applies_to_language(df, target_language):
            continue
        patterns = df.get("patterns", {}) or {}
        for key in ("inbound", "outbound"):
            for pat in patterns.get(key, []) or []:
                if pat and pat not in merged[key]:
                    merged[key].append(pat)
    return merged


def _definition_applies_to_language(definition, target_language):
    """True si la definition aplica al `target_language`.

    Reglas:
      - Si no declara `language` ni `languages` → aplica a todos
        (backward-compat).
      - Si declara `language` (string) → match case-insensitive.
      - Si declara `languages` (lista) → cualquiera matchea.
      - Si target_language es vacío y la definition restringe lenguaje,
        no aplica (no podemos asegurar match).
    """
    declared_single = definition.get("language")
    declared_list = definition.get("languages")
    if not declared_single and not declared_list:
        return True
    declared = []
    if declared_single:
        declared.append(str(declared_single).lower())
    if declared_list:
        declared.extend(str(x).lower() for x in declared_list)
    if not target_language:
        return False
    return target_language in declared


def languages_without_scanner():
    """Devuelve set de lenguajes que cayeron al NullScanner.

    Útil para que core.py incluya esta info en feedback.log.
    """
    return set(_FEEDBACK_NO_SCANNER)


def reset_cache():
    """Limpia el cache — usado principalmente por tests/smoke."""
    _SCANNER_CACHE.clear()
    _FEEDBACK_NO_SCANNER.clear()


__all__ = [
    "Scanner",
    "NullScanner",
    "HtmlScanner",
    "PythonScanner",
    "RegexFallbackScanner",
    "get_scanner",
    "languages_without_scanner",
    "reset_cache",
    "_definition_applies_to_language",
]