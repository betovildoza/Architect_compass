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
from compass.defaults import DEFAULT_LANGUAGE_GRAMMARS

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

# TSD-045 (D5) — registro positivo del tier que corrió por lenguaje.
# Valores: "ast" | "tree-sitter" | "tree-sitter-pack" | "regex" |
# "html-regex" | "none". Poblado en `_build_scanner` (una vez por lenguaje
# por run, gracias al cache). `analyze()` lo escribe en
# atlas["audit"]["scanner_tiers"].
_SCANNER_TIERS = {}

# TSD-045 (D6) — tier ACTIVO por lenguaje, consultado por el cache
# incremental para invalidar entries cuyo tier cacheado ya no coincide.
# Es el mismo dato que `_SCANNER_TIERS` pero expuesto vía helper estable.

# Valores que en config.language_grammars significan "opt-out" (forzar
# Tier 3 regex para ese lenguaje, aunque el binding esté instalado).
_OPT_OUT_GRAMMARS = {"regex", "regex_only", "stdlib_ast", "none"}


def _resolve_grammar(language, config):
    """TSD-045 (D2) — merge `DEFAULT_LANGUAGE_GRAMMARS <- config` (config
    gana). Devuelve el nombre de grammar a usar, o None si opt-out / sin
    entrada.
    """
    grammar = DEFAULT_LANGUAGE_GRAMMARS.get(language)
    config_grammars = (config.get("language_grammars") or {}) if config else {}
    if language in config_grammars:
        grammar = config_grammars[language]  # override explícito del proyecto
    if grammar is None:
        return None
    if isinstance(grammar, str) and grammar.lower() in _OPT_OUT_GRAMMARS:
        return None
    return grammar


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


def _record_tier(language, tier):
    """D5 — registra el tier resuelto para `language` (último gana; el
    cache garantiza una resolución por lenguaje por run)."""
    if language:
        _SCANNER_TIERS[language] = tier


def _build_scanner(language, config):
    if language == "python":
        _record_tier(language, "ast")
        return PythonScanner(config=config)

    if language in ("html", "htm"):
        # TSD-046 (D7) — intentar Tier 2 tree-sitter (vía language-pack)
        # primero; si no está disponible, fallback al HtmlScanner probado
        # (no-regresión). El default HTML pasa a tree-sitter solo cuando el
        # binding está instalado; el gate de paridad es TSD-048.
        # MARKUP-061 — la selección de tier HTML se factoriza en `_html_scanner`
        # (reusada por `get_markup_scanner` sin duplicar la decisión).
        scanner = _html_scanner(config)
        _record_tier(language, getattr(scanner, "tier_name", "html-regex"))
        return scanner

    if language == "css":
        # TSD-046 (D7) — CssScanner dual-tier. Reemplaza el NullScanner que
        # generaba el warning "Sin scanner disponible: css".
        if _resolve_grammar("css", config):
            from compass.scanners.css import CssScanner
            scanner = CssScanner(config=config)
            _record_tier(language, getattr(scanner, "tier_name", "regex"))
            return scanner

    grammar_name = _resolve_grammar(language, config)

    if grammar_name and _TS_AVAILABLE:
        try:
            scanner = TreeSitterScanner(grammar_name, language, config=config)
            _record_tier(language, getattr(scanner, "tier_name", "tree-sitter"))
            return scanner
        except ImportError:
            # La grammar no está instalada / no disponible — caemos a Tier 3.
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
        _record_tier(language, "regex")
        return RegexFallbackScanner(
            patterns,
            http_regex=http_regex,
            loader_regex=loader_regex,
            loader_edge_map=loader_edge_map,
            loader_specs=lang_loaders if loader_regex else None,
            language=language,  # MARKUP-061 II — filtrado de comentarios.
        )

    # Nada aplicable.
    _record_tier(language, "none")
    if language not in _FEEDBACK_NO_SCANNER:
        _FEEDBACK_NO_SCANNER.add(language)
    return NullScanner()


def _html_scanner(config):
    """MARKUP-061 — selección de scanner HTML por tier (factorizado del
    branch html/htm de `_build_scanner`). Intenta Tier 2 tree-sitter vía
    language-pack; si no está disponible, cae al `HtmlScanner` regex probado.
    NO registra tier (lo hace el caller que conoce el `language`)."""
    if _TS_AVAILABLE and _resolve_grammar("html", config):
        try:
            from compass.scanners.html_treesitter import TreeSitterHtmlScanner
            return TreeSitterHtmlScanner(config=config)
        except Exception:
            pass  # grammar html no disponible → HtmlScanner.
    return HtmlScanner(config=config)


def get_markup_scanner(config):
    """MARKUP-061 — scanner HTML para el markup-pass sobre templates
    server-side (.php/.twig/...). Cacheado aparte del dispatch por language
    (NO ensucia `_SCANNER_TIERS` del lenguaje del template).

    Usa SIEMPRE el `HtmlScanner` regex, NO el tier tree-sitter. Razón
    (verificada en ETCA): un template server-side NO es HTML AST-parseable —
    el PHP embebido (`<?php ?>`, `<?= ?>`) rompe la grammar HTML tree-sitter
    (sobre `tienda.php`: 1639 nodos ERROR, 0 `element` → 0 edges). El regex
    `HtmlScanner` es robusto a HTML+PHP mixto y extrae los `<link>/<script>`
    igual. El filtrado de comentarios (MARKUP-061 II) ya está en HtmlScanner
    regex (C4.3), así que el markup-pass lo hereda. La paridad de tier del
    ticket se refiere al scanner del TEMPLATE (php tree-sitter ↔ php regex),
    no al markup-scanner: ambos tiers de template usan este mismo markup-pass.
    """
    cache_key = ("__markup__", id(config))
    if cache_key in _SCANNER_CACHE:
        return _SCANNER_CACHE[cache_key]
    scanner = HtmlScanner(config=config)
    _SCANNER_CACHE[cache_key] = scanner
    return scanner


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


def active_scanner_tiers():
    """TSD-045 (D5) — devuelve `{language: tier}` con el tier que corrió en
    este run. Vacío al inicio de cada `analyze()` (lo limpia
    `reset_cache()`). `analyze()` lo escribe en
    atlas["audit"]["scanner_tiers"].
    """
    return dict(_SCANNER_TIERS)


def scanner_tier_for(language):
    """TSD-045 (D6) — tier activo para `language` (o None si aún no se
    resolvió en este run). Consultado por el cache incremental para
    invalidar entries con tier obsoleto.
    """
    return _SCANNER_TIERS.get((language or "").lower())


def reset_cache():
    """Limpia el cache — usado al inicio de cada analyze() y por tests."""
    _SCANNER_CACHE.clear()
    _FEEDBACK_NO_SCANNER.clear()
    _SCANNER_TIERS.clear()
    # D1 — re-evaluar disponibilidad del language-pack en el próximo build
    # (relevante para tests que instalan/desinstalan el binding en proceso).
    if _TS_AVAILABLE:
        try:
            from compass.scanners.treesitter import reset_pack_cache
            reset_pack_cache()
        except ImportError:
            pass


__all__ = [
    "Scanner",
    "NullScanner",
    "HtmlScanner",
    "PythonScanner",
    "RegexFallbackScanner",
    "get_scanner",
    "get_markup_scanner",
    "languages_without_scanner",
    "active_scanner_tiers",
    "scanner_tier_for",
    "reset_cache",
    "_definition_applies_to_language",
]