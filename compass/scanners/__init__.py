"""Scanners dispatcher — SCN-003.

`get_scanner(language, config) -> Scanner`

Orden de preferencia:
    1. Python → PythonScanner (Tier 1, stdlib ast).
    2. Language con entrada en `language_grammars` del config →
       TreeSitterScanner (Tier 2). Si la grammar no está instalada cae a 3.
    3. Lenguaje con definitions[].patterns en el config →
       RegexFallbackScanner (Tier 3).
    4. Nada disponible → NullScanner (devuelve []; se anota como aviso).

El scanner se cachea por (language, id(config)) para no re-construirlo por
archivo en cada run.
"""

from compass.scanners.base import Scanner, NullScanner
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
        return PythonScanner()

    grammars = (config.get("language_grammars") or {}) if config else {}
    grammar_name = grammars.get(language)

    if grammar_name and grammar_name != "stdlib_ast" and _TS_AVAILABLE:
        try:
            return TreeSitterScanner(grammar_name, language)
        except ImportError:
            # La grammar no está instalada — caemos a Tier 3.
            pass

    # Tier 3: recoger patterns de las definitions aplicables.
    patterns = _collect_regex_patterns(language, config)
    if patterns.get("outbound"):
        return RegexFallbackScanner(patterns)

    # Nada aplicable.
    if language not in _FEEDBACK_NO_SCANNER:
        _FEEDBACK_NO_SCANNER.add(language)
    return NullScanner()


def _collect_regex_patterns(language, config):
    """Junta outbound patterns de todas las definitions del config.

    El schema v2 no asocia definitions a un language directo (sino a un
    stack). Para mantener retrocompatibilidad con el scanner viejo,
    incluimos TODAS las outbound patterns de definitions con
    tier == 'regex_fallback'. Si en el futuro se quiere filtrar por
    lenguaje, agregar un campo `language` a definitions[].
    """
    merged = {"inbound": [], "outbound": []}
    if not config:
        return merged
    for df in config.get("definitions", []) or []:
        if df.get("tier") and df["tier"] != "regex_fallback":
            continue
        patterns = df.get("patterns", {}) or {}
        for key in ("inbound", "outbound"):
            for pat in patterns.get(key, []) or []:
                if pat and pat not in merged[key]:
                    merged[key].append(pat)
    return merged


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
    "PythonScanner",
    "RegexFallbackScanner",
    "get_scanner",
    "languages_without_scanner",
    "reset_cache",
]