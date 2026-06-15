"""tree-sitter scanner (Tier 2, default) — SCN-003 + NET-022 + URL-SCAN + TSD-045.

Scanner genérico que recibe una grammar como parámetro. Un único módulo
cubre PHP, JS, TS, HTML, CSS, etc.

Tier 2 es el scanner de PREFERENCIA (default) para estos lenguajes cuando
el binding tree-sitter está instalado: el dispatcher lo intenta PRIMERO,
vía `tree_sitter_language_pack.get_language(lang)` (loader primario). Sin
binding, cae automáticamente a Tier 3 (regex_fallback) sin cambios de
resultado — promesa zero-install intacta. No es un fallback ni una opción
secundaria: es el tier por defecto cuando hay binding.

Carga de grammar (TSD-045 D1) — dos fuentes, en orden, una vez por run
(memoizado por el `_SCANNER_CACHE` del dispatcher):

  1. `tree_sitter_language_pack.get_language(lang)` + `tree_sitter.Parser`
     — fuente primaria. Una sola dep opcional cubre php/js/ts/html/css (y
     futuros Go/Rust/Ruby sin tocar código). Se usa `get_language` (no
     `get_parser`, que devuelve el Parser del binding Rust con API
     incompatible) y se construye el Parser con la API Python, igual que
     la Fuente 2. Detección defensiva con `getattr` (R2: si una 2.x cambia
     la API, se cae a regex en vez de romper).
  2. Módulo de grammar individual (`tree_sitter_php`, ...) — loader
     secundario que prueba candidatos de entry point: `language()`, luego
     `language_<lang>()` (corrige el fallo silencioso de php/ts, cuyos
     repos upstream exponen `language_php()` / `language_typescript()` en
     vez de `language()`).

Si ninguna fuente carga, el constructor levanta ImportError y el
dispatcher cae a Tier 3 (regex_fallback). Promesa zero-install intacta:
sin binding instalado, comportamiento idéntico al actual.

EDG-023 — JS/TS extracción field-aware (D3): se emite el SPECIFIER del
import (texto del string source), no el statement completo. El walk plano
anterior emitía `import { x } from './m';` entero, que `_resolve_js`
descartaba como bare specifier → 0 edges internos. Ahora se navega por
`child_by_field_name("source")` y se emite `./m`.

PHP — se conserva la captura de `*_expression` completa (el resolver ya
digiere literales de la expresión); además se porta PHP-018b
(`require $var` con asignación previa) vía el helper compartido de
regex_fallback (D4): una implementación, dos consumidores.

NET-022 / URL-SCAN / SEM-020 loader_calls — passes regex post-AST, ya en
paridad con Tier 3. No los toca el switch de tier.
"""

import importlib
import re

from compass.scanners.base import (
    Scanner as _BaseScanner,
    DEFAULT_EDGE_TYPE,
    build_http_loader_regex,
    build_loader_call_regex,
)
from compass.path_resolver import encode_loader_raw
from compass.scanners.regex_fallback import (
    _expand_loader_body,
    php_require_var_sentinels,
)
from compass.comment_filter import strip_comments

# URL-SCAN — regex para capturar URL literals en source text.
# Captura strings entre comillas simples o dobles que empiezan con http(s)://.
_URL_LITERAL_RE = re.compile(r'''["'](https?://[^"'\s)]+)["']''')


# EDG-023 — mapping node_type → edge_type por lenguaje (solo PHP usa el
# walk plano por node.type). JS/TS usan extracción field-aware dedicada
# (ver `_walk_js`), no este mapping.
_NODE_TYPE_EDGE = {
    "php": {
        "include_expression":      "include",
        "include_once_expression": "include",
        "require_expression":      "require",
        "require_once_expression": "require",
    },
}


# Tipos de nodo del árbol AST tree-sitter por lenguaje (derivado del mapping).
_NODE_TYPES_BY_LANGUAGE = {
    lang: tuple(mapping.keys()) for lang, mapping in _NODE_TYPE_EDGE.items()
}

# D3 — lenguajes con extractor field-aware dedicado (JS/TS family).
_JS_FAMILY = {"javascript", "typescript", "tsx", "jsx"}

# TSD-045 (D1) — memoización a nivel módulo del intento de import del
# language-pack (un intento por proceso, patrón `_TS_AVAILABLE`). Se limpia
# en `reset_pack_cache()` para tests.
_PACK_MODULE = None        # módulo importado, o None si no disponible
_PACK_RESOLVED = False     # True una vez intentado el import


def _get_language_pack():
    """Importa `tree_sitter_language_pack` una vez por proceso.

    Devuelve el módulo si expone `get_language` (R2: detección defensiva),
    o None si no está instalado / la API no es la esperada.
    """
    global _PACK_MODULE, _PACK_RESOLVED
    if _PACK_RESOLVED:
        return _PACK_MODULE
    _PACK_RESOLVED = True
    try:
        mod = importlib.import_module("tree_sitter_language_pack")
    except ImportError:
        _PACK_MODULE = None
        return None
    # R2 — pin <2.0 + detección defensiva. Si una 2.x cambió la API
    # (rewrite kreuzberg-dev con `process()`), `get_language` no existe →
    # tratamos el pack como no disponible y caemos al loader secundario.
    # Usamos `get_language` (no `get_parser`): `get_parser` devuelve el
    # Parser del binding Rust (builtins.Parser), cuya API es incompatible
    # con la API Python de tree_sitter (`.parse(bytes)` lanza TypeError).
    # `get_language` devuelve un `tree_sitter.Language` legítimo que sí
    # construye un `tree_sitter.Parser` Python funcional.
    if getattr(mod, "get_language", None) is None:
        _PACK_MODULE = None
        return None
    _PACK_MODULE = mod
    return mod


def reset_pack_cache():
    """Limpia la memoización del language-pack — usado por tests/smoke."""
    global _PACK_MODULE, _PACK_RESOLVED
    _PACK_MODULE = None
    _PACK_RESOLVED = False


# D1 — nombre del lenguaje del pack. Para "javascript"/"typescript" el
# pack usa esos mismos nombres; para tsx usa "tsx" (R4).
_PACK_LANG_ALIAS = {
    "javascript": "javascript",
    "typescript": "typescript",
    "tsx": "tsx",
    "jsx": "javascript",   # jsx lo parsea la grammar javascript del pack
    "php": "php",
    "html": "html",
    "css": "css",
}


def _load_parser(grammar_module_name, language):
    """TSD-045 (D1) — carga un `Parser` para `language`.

    Devuelve `(parser, tier_name)` donde tier_name ∈
    {"tree-sitter-pack", "tree-sitter"}. Levanta ImportError si ninguna
    fuente carga.

    `grammar_module_name`:
        - "@pack" → solo intentar el language-pack (html/css).
        - otro string → intentar pack primero, luego el módulo individual.
    """
    lang = (language or "").lower()

    # Fuente 1 — language-pack.
    pack = _get_language_pack()
    if pack is not None:
        pack_lang = _PACK_LANG_ALIAS.get(lang, lang)
        try:
            # `pack.get_language()` devuelve un `tree_sitter.Language` —
            # NO usar `pack.get_parser()`, que devuelve el Parser del
            # binding Rust (builtins.Parser) con API incompatible
            # (`.parse(bytes)` lanza TypeError). Construimos el Parser con
            # la API Python de tree_sitter, igual que la Fuente 2.
            ts_core = importlib.import_module("tree_sitter")
            lang_obj = pack.get_language(pack_lang)
            if lang_obj is not None:
                parser = ts_core.Parser(lang_obj)
                return parser, "tree-sitter-pack"
        except Exception:
            # Lenguaje no soportado por el pack o error de carga → seguir.
            pass

    # "@pack" significa: SOLO pack. Si falló, no hay loader secundario.
    if grammar_module_name == "@pack":
        raise ImportError(
            f"language '{lang}' no disponible en tree-sitter-language-pack."
        )

    # Fuente 2 — módulo de grammar individual.
    try:
        ts_core = importlib.import_module("tree_sitter")
        grammar_mod = importlib.import_module(grammar_module_name)
    except ImportError as e:
        raise ImportError(
            f"tree-sitter o la grammar '{grammar_module_name}' no están "
            f"instaladas: {e}"
        )

    Parser = getattr(ts_core, "Parser", None)
    Language = getattr(ts_core, "Language", None)
    if Parser is None or Language is None:
        raise ImportError(
            "tree-sitter instalado pero incompatible (falta Parser/Language)."
        )

    # D1 — candidatos de entry point. tree_sitter_javascript expone
    # `language()`; tree_sitter_php expone `language_php()`; tree_sitter_
    # typescript expone `language_typescript()` / `language_tsx()`.
    candidates = ["language", f"language_{lang}"]
    if lang in ("typescript", "tsx"):
        candidates = [f"language_{lang}", "language_typescript", "language"]
    elif lang == "php":
        candidates = ["language_php", "language", "language_php_only"]

    language_fn = None
    for attr in candidates:
        fn = getattr(grammar_mod, attr, None)
        if fn is not None:
            language_fn = fn
            break
    if language_fn is None:
        raise ImportError(
            f"El módulo '{grammar_module_name}' no expone ningún entry point "
            f"de grammar conocido (probados: {candidates})."
        )

    lang_obj = Language(language_fn())
    parser = Parser(lang_obj)
    return parser, "tree-sitter"


class TreeSitterScanner(_BaseScanner):
    """Scanner Tier 2. Carga una grammar dinámicamente (D1).

    Parámetros:
        grammar_module_name: nombre del módulo Python de la grammar
            (ej: 'tree_sitter_php') o "@pack" (solo language-pack).
        language: string del lenguaje ('php', 'javascript', ...) — se usa
            para elegir los tipos de nodo relevantes y el alias del pack.
        config: dict de config completo (opcional). NET-022/SEM-020 lo usan.

    Atributo público `tier_name` (D5): "tree-sitter" | "tree-sitter-pack".
    """

    def __init__(self, grammar_module_name, language, config=None):
        self._parser, self.tier_name = _load_parser(
            grammar_module_name, language,
        )
        self._language = (language or "").lower()
        self._is_js = self._language in _JS_FAMILY
        self._edge_map = dict(_NODE_TYPE_EDGE.get(self._language, {}))
        self._node_types = set(self._edge_map.keys())

        # NET-022 — regex para URLs literales en llamadas HTTP.
        self._http_regex = None
        self._loader_regex = None
        self._loader_edge_map = {}
        self._loader_specs = {}
        if config and isinstance(config, dict):
            loaders = (config.get("http_loaders") or {}).get(self._language) or []
            self._http_regex = build_http_loader_regex(loaders)
            # SEM-020 — loader_calls filtradas por lenguaje.
            loader_calls = config.get("loader_calls") or {}
            lang_loaders = {
                name: spec for name, spec in loader_calls.items()
                if isinstance(spec, dict)
                and (spec.get("language") or "").lower() == self._language
            }
            if lang_loaders:
                self._loader_regex = build_loader_call_regex(lang_loaders.keys())
                self._loader_edge_map = {
                    name: spec.get("edge_type") or DEFAULT_EDGE_TYPE
                    for name, spec in lang_loaders.items()
                }
                # Mini-S10.5 — spec completa para accepts_array.
                self._loader_specs = lang_loaders

    def extract_imports(self, file_path):
        try:
            with open(file_path, "rb") as f:
                data = f.read()
        except OSError:
            return []

        try:
            tree = self._parser.parse(data)
        except Exception:
            return []

        out = []
        if self._is_js:
            # D3 — extracción field-aware del specifier (no el statement).
            self._walk_js(tree.root_node, data, out)
        elif self._node_types:
            # PHP — walk plano por node.type (el resolver digiere la
            # expresión completa).
            self._walk(tree.root_node, data, out)

        source_text = data.decode("utf-8", errors="ignore")
        # MARKUP-061 II — filtrar comentarios ANTES de los passes regex
        # post-AST (PHP-018b/SEM-020/NET-022/URL-SCAN). El AST (_walk/_walk_js)
        # ya es inmune por construcción y usa `data`/`tree` originales (no se
        # toca, filtrar bytes del árbol rompería offsets). Paridad con Tier 3.
        source_text = strip_comments(source_text, self._language)

        # PHP-018b (D4) — `require|include $var` con asignación previa.
        # Misma implementación que Tier 3, vía helper compartido.
        if self._language == "php":
            for target, edge_type in php_require_var_sentinels(
                source_text, file_path,
            ):
                out.append((target, edge_type))

        # SEM-020 — loader_calls.
        # Mini-S10.5 — expand array literals (accepts_array).
        if self._loader_regex:
            for match in self._loader_regex.finditer(source_text):
                fn = match.group(1)
                body = match.group(2) or ""
                edge_type = self._loader_edge_map.get(fn, DEFAULT_EDGE_TYPE)
                for emitted_body in _expand_loader_body(
                    fn, body, self._loader_specs,
                ):
                    out.append((encode_loader_raw(fn, emitted_body), edge_type))

        # NET-022 — extraer URLs literales de llamadas HTTP.
        if self._http_regex:
            for match in self._http_regex.finditer(source_text):
                url = match.group(1)
                if url:
                    out.append((url, "fetch"))

        # URL-SCAN — broad URL literal scan over source text.
        # Catch URLs regardless of calling function. Dedup against URLs
        # already captured by the http_loaders pass above.
        seen_urls = {t for t, et in out if et == "fetch"}
        for match in _URL_LITERAL_RE.finditer(source_text):
            url = match.group(1).strip()
            if len(url) > 10 and url not in seen_urls:
                seen_urls.add(url)
                out.append((url, "fetch"))

        return out

    def _walk(self, node, source_bytes, out):
        """PHP — walk plano: emite el texto del nodo include/require."""
        if node.type in self._node_types:
            text = source_bytes[node.start_byte:node.end_byte].decode(
                "utf-8", errors="ignore"
            )
            # EDG-023 — edge_type según node_type; fallback a DEFAULT.
            edge_type = self._edge_map.get(node.type, DEFAULT_EDGE_TYPE)
            out.append((text, edge_type))
        for child in node.children:
            self._walk(child, source_bytes, out)

    def _walk_js(self, node, source_bytes, out):
        """D3 — JS/TS: emite el SPECIFIER (texto del string source), no el
        statement completo.

        Cubre:
          - import_statement / export_statement con campo `source` (string)
            → edge "import".  Incluye `export ... from '...'`.
          - call_expression cuyo callee es `require` o `import` (dynamic)
            con primer arg string → edge "require" / "import".

        Elimina el ruido del antiguo `call_expression → "use"`: las
        llamadas HTTP / wrappers ya las cubren NET-022 + URL-SCAN +
        loader_calls.
        """
        ntype = node.type
        if ntype in ("import_statement", "export_statement"):
            spec = self._js_string_specifier(node, source_bytes)
            if spec is not None:
                out.append((spec, "import"))
        elif ntype == "call_expression":
            edge = self._js_call_edge(node, source_bytes)
            if edge is not None:
                spec, edge_type = edge
                out.append((spec, edge_type))
        for child in node.children:
            self._walk_js(child, source_bytes, out)

    @staticmethod
    def _node_text(node, source_bytes):
        return source_bytes[node.start_byte:node.end_byte].decode(
            "utf-8", errors="ignore"
        )

    @staticmethod
    def _strip_quotes(text):
        text = text.strip()
        if len(text) >= 2 and text[0] in "'\"`" and text[-1] == text[0]:
            return text[1:-1]
        return text

    def _js_string_specifier(self, node, source_bytes):
        """Extrae el specifier del campo `source` de un import/export.

        Si el statement no tiene `source` (ej: `export const x = ...`),
        devuelve None — no es un re-export desde módulo.
        """
        src = node.child_by_field_name("source")
        if src is None:
            return None
        spec = self._strip_quotes(self._node_text(src, source_bytes))
        return spec or None

    def _js_call_edge(self, node, source_bytes):
        """`require('x')` / `import('x')` (dynamic) → (specifier, edge_type).

        Solo emite cuando el callee es exactamente `require` o `import` y
        el primer argumento es un string literal. Cualquier otra call
        (fetch, axios, etc.) la ignora — esas las cubren los passes regex.
        """
        callee = node.child_by_field_name("function")
        if callee is None:
            return None
        callee_text = self._node_text(callee, source_bytes).strip()
        if callee_text == "require":
            edge_type = "require"
        elif callee_text == "import":
            edge_type = "import"
        else:
            return None
        args = node.child_by_field_name("arguments")
        if args is None:
            return None
        for child in args.named_children:
            if child.type in ("string", "template_string"):
                spec = self._strip_quotes(self._node_text(child, source_bytes))
                return (spec, edge_type) if spec else None
            # Primer arg no-string (variable, expresión) → no resoluble.
            return None
        return None
