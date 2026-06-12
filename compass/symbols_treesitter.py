"""Symbol extractors tree-sitter (TSD-047, D8) — JS/TS/PHP enriquecidos.

Módulo opt-in: solo activo si el binding tree-sitter está instalado
(reusa el loader D1 de `compass/scanners/treesitter.py`). Sin binding,
`extract_symbols()` devuelve None y `architect_symbols.extract_file` cae a
los extractores regex actuales — comportamiento idéntico al de hoy.

Devuelve el MISMO shape que los extractores regex de `architect_symbols`
(`{"language", "functions", "classes", "constants"}`) con campos
ADITIVOS, emitidos solo cuando hay dato (criterio anti context-blow,
`feedback_llm_compact_no_internal_sentinels`: cero campos vacíos):

  - `kind`: function | method | class | interface | trait | property | arrow
  - `range`: [line_start, line_end]  (1-based, exacto por node positions)
  - `signature`: texto de la declaración hasta el cuerpo, trimmed, cap ~120

No engorda `architect_symbols.py` (REF-034 pendiente); este módulo nace
listo para la futura migración a `compass/symbols.py`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Reusa el loader D1 — una sola fuente de verdad para la carga de grammars.
from compass.scanners.treesitter import _load_parser

_SIG_CAP = 120

# Parsers memoizados por lenguaje (un intento por proceso).
_PARSER_CACHE: Dict[str, Any] = {}
_PARSER_TRIED: set = set()

# language → (grammar_module_name para el loader secundario).
_GRAMMAR_MODULE = {
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "tsx": "tree_sitter_typescript",
    "php": "tree_sitter_php",
}


def reset_parser_cache() -> None:
    """Limpia la memoización de parsers — usado por tests/smoke."""
    _PARSER_CACHE.clear()
    _PARSER_TRIED.clear()


def _get_parser(language: str):
    """Devuelve un parser tree-sitter para `language`, o None si el binding
    no está disponible. Memoizado por lenguaje."""
    lang = (language or "").lower()
    if lang in _PARSER_TRIED:
        return _PARSER_CACHE.get(lang)
    _PARSER_TRIED.add(lang)
    grammar = _GRAMMAR_MODULE.get(lang)
    if grammar is None:
        return None
    try:
        parser, _tier = _load_parser(grammar, lang)
    except ImportError:
        return None
    except Exception:
        return None
    _PARSER_CACHE[lang] = parser
    return parser


def available_for(language: str) -> bool:
    """True si hay parser tree-sitter para `language` en este proceso."""
    return _get_parser(language) is not None


# ---------------------------------------------------------------------------
# Helpers de nodo
# ---------------------------------------------------------------------------

def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")


def _range(node) -> List[int]:
    # tree-sitter row es 0-based; symbols.json usa 1-based.
    return [node.start_point[0] + 1, node.end_point[0] + 1]


def _line(node) -> int:
    return node.start_point[0] + 1


def _signature(node, src: bytes) -> Optional[str]:
    """Texto de la declaración hasta el inicio del cuerpo, una línea,
    trimmed, cap ~120 chars. None si no hay nada útil."""
    body = node.child_by_field_name("body")
    end = body.start_byte if body is not None else node.end_byte
    raw = src[node.start_byte:end].decode("utf-8", errors="ignore")
    sig = " ".join(raw.split()).strip().rstrip("{").strip()
    if not sig:
        return None
    if len(sig) > _SIG_CAP:
        sig = sig[:_SIG_CAP].rstrip() + "…"
    return sig


def _name_of(node, src: bytes) -> Optional[str]:
    n = node.child_by_field_name("name")
    if n is not None:
        return _text(n, src).strip() or None
    return None


def _params(node, src: bytes) -> List[str]:
    """Lista de nombres de parámetros (JS/TS/PHP) desde el nodo de params."""
    params_node = node.child_by_field_name("parameters")
    if params_node is None:
        return []
    out: List[str] = []
    for child in params_node.named_children:
        # JS: identifier / required_parameter / optional_parameter / etc.
        # PHP: simple_parameter con field `name` ($var).
        nm = child.child_by_field_name("name")
        if nm is not None:
            out.append(_text(nm, src).strip())
            continue
        txt = _text(child, src).strip()
        if txt:
            out.append(txt)
    return out


# ---------------------------------------------------------------------------
# JS / TS
# ---------------------------------------------------------------------------

_JS_FUNC_TYPES = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "method_definition": "method",
}
_JS_CLASS_TYPES = {
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
}


def _is_exported(node) -> bool:
    p = node.parent
    return p is not None and p.type == "export_statement"


def _is_async(node, src: bytes) -> bool:
    for child in node.children:
        if child.type == "async":
            return True
    # Fallback textual para variantes de grammar.
    head = src[node.start_byte:node.start_byte + 16].decode(
        "utf-8", errors="ignore"
    )
    return head.lstrip().startswith("async")


def _extract_js(parser, source: str, language: str) -> Dict[str, Any]:
    data = source.encode("utf-8")
    tree = parser.parse(data)
    functions: List[Dict[str, Any]] = []
    classes: List[Dict[str, Any]] = []
    constants: List[Dict[str, Any]] = []

    def visit(node):
        ntype = node.type

        if ntype in _JS_CLASS_TYPES:
            name = _name_of(node, data)
            if name:
                methods: List[Dict[str, Any]] = []
                body = node.child_by_field_name("body")
                if body is not None:
                    for m in body.named_children:
                        if m.type == "method_definition":
                            mname = _name_of(m, data)
                            if mname:
                                methods.append(_clean({
                                    "name": mname,
                                    "args": _params(m, data),
                                    "line": _line(m),
                                    "range": _range(m),
                                    "kind": "method",
                                    "async": _is_async(m, data),
                                    "signature": _signature(m, data),
                                }))
                classes.append(_clean({
                    "name": name,
                    "bases": _js_bases(node, data),
                    "decorators": [],
                    "methods": methods,
                    "line": _line(node),
                    "range": _range(node),
                    "kind": _JS_CLASS_TYPES[ntype],
                    "exported": _is_exported(node),
                }))
            # No descender al cuerpo de la clase (métodos ya capturados).
            return

        if ntype in _JS_FUNC_TYPES and ntype != "method_definition":
            name = _name_of(node, data)
            if name:
                functions.append(_clean({
                    "name": name,
                    "args": _params(node, data),
                    "decorators": [],
                    "line": _line(node),
                    "range": _range(node),
                    "kind": "function",
                    "async": _is_async(node, data),
                    "exported": _is_exported(node),
                    "signature": _signature(node, data),
                }))

        elif ntype in ("lexical_declaration", "variable_declaration"):
            _js_var_declaration(node, data, functions, constants)

        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return {
        "language": language,
        "functions": functions,
        "classes": classes,
        "constants": constants,
    }


def _js_bases(node, src: bytes) -> List[str]:
    """extends/implements de una clase JS/TS."""
    bases: List[str] = []
    heritage = None
    for child in node.children:
        if child.type in ("class_heritage", "extends_clause"):
            heritage = child
            break
    if heritage is None:
        return bases
    for child in heritage.named_children:
        txt = _text(child, src).strip().lstrip("extends").lstrip("implements").strip()
        if txt:
            bases.append(txt)
    return bases


def _js_var_declaration(node, src: bytes, functions, constants) -> None:
    """`const x = () => …` / `const x = function(){}` → arrow/expression;
    `const FOO = literal` → constante."""
    exported = _is_exported(node)
    for decl in node.named_children:
        if decl.type != "variable_declarator":
            continue
        name = _name_of(decl, src)
        if not name:
            continue
        value = decl.child_by_field_name("value")
        if value is None:
            continue
        vtype = value.type
        if vtype == "arrow_function":
            functions.append(_clean({
                "name": name,
                "args": _params(value, src),
                "decorators": [],
                "line": _line(decl),
                "range": _range(decl),
                "kind": "arrow",
                "async": _is_async(value, src),
                "exported": exported,
                "signature": _signature(value, src),
            }))
        elif vtype in ("function", "function_expression"):
            functions.append(_clean({
                "name": name,
                "args": _params(value, src),
                "decorators": [],
                "line": _line(decl),
                "range": _range(decl),
                "kind": "expression",
                "async": _is_async(value, src),
                "exported": exported,
                "signature": _signature(value, src),
            }))
        else:
            constants.append(_clean({
                "name": name,
                "kind": _js_literal_kind(value),
                "line": _line(decl),
                "range": _range(decl),
            }))


def _js_literal_kind(value) -> Optional[str]:
    t = value.type
    mapping = {
        "string": "str", "template_string": "str", "number": "num",
        "true": "bool", "false": "bool", "null": "null",
        "array": "list", "object": "dict",
    }
    return mapping.get(t)


# ---------------------------------------------------------------------------
# PHP
# ---------------------------------------------------------------------------

_PHP_CLASS_TYPES = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "trait_declaration": "trait",
    "enum_declaration": "class",
}


def _extract_php(parser, source: str) -> Dict[str, Any]:
    data = source.encode("utf-8")
    tree = parser.parse(data)
    functions: List[Dict[str, Any]] = []
    classes: List[Dict[str, Any]] = []
    constants: List[Dict[str, Any]] = []

    def visit(node):
        ntype = node.type

        if ntype in _PHP_CLASS_TYPES:
            name = _name_of(node, data)
            if name:
                methods: List[Dict[str, Any]] = []
                body = node.child_by_field_name("body")
                if body is not None:
                    for m in body.named_children:
                        if m.type == "method_declaration":
                            mname = _name_of(m, data)
                            if mname:
                                methods.append(_clean({
                                    "name": mname,
                                    "args": _params(m, data),
                                    "line": _line(m),
                                    "range": _range(m),
                                    "kind": "method",
                                    "signature": _signature(m, data),
                                }))
                classes.append(_clean({
                    "name": name,
                    "kind": _PHP_CLASS_TYPES[ntype],
                    "bases": _php_bases(node, data),
                    "implements": _php_implements(node, data),
                    "methods": methods,
                    "line": _line(node),
                    "range": _range(node),
                }))
            return

        if ntype == "function_definition":
            name = _name_of(node, data)
            if name:
                functions.append(_clean({
                    "name": name,
                    "args": _params(node, data),
                    "decorators": [],
                    "line": _line(node),
                    "range": _range(node),
                    "kind": "function",
                    "signature": _signature(node, data),
                }))

        elif ntype == "const_declaration":
            for el in node.named_children:
                if el.type == "const_element":
                    cname = None
                    nm = el.child_by_field_name("name")
                    if nm is not None:
                        cname = _text(nm, data).strip()
                    else:
                        # const_element: primer hijo identifier.
                        for c in el.named_children:
                            if c.type == "name":
                                cname = _text(c, data).strip()
                                break
                    if cname:
                        constants.append(_clean({
                            "name": cname,
                            "kind": None,
                            "line": _line(el),
                            "range": _range(el),
                        }))

        for child in node.children:
            visit(child)

    visit(tree.root_node)
    return {
        "language": "php",
        "functions": functions,
        "classes": classes,
        "constants": constants,
    }


def _php_bases(node, src: bytes) -> List[str]:
    for child in node.children:
        if child.type == "base_clause":
            return [
                _text(c, src).strip()
                for c in child.named_children
                if _text(c, src).strip()
            ]
    return []


def _php_implements(node, src: bytes) -> List[str]:
    for child in node.children:
        if child.type == "class_interface_clause":
            return [
                _text(c, src).strip()
                for c in child.named_children
                if _text(c, src).strip()
            ]
    return []


# ---------------------------------------------------------------------------
# Limpieza anti context-blow + entry point
# ---------------------------------------------------------------------------

def _clean(d: Dict[str, Any]) -> Dict[str, Any]:
    """Quita claves con valor None / "" / [] vacíos para no inflar el JSON.
    Conserva `False` (async/exported) y `0` por ser datos válidos."""
    out = {}
    for k, v in d.items():
        if v is None:
            continue
        if v == "" or v == []:
            # decorators/bases/args/methods vacíos: omitir (aditivo).
            continue
        out[k] = v
    return out


def extract_symbols(source: str, rel_path: str, language: str) -> Optional[Dict[str, Any]]:
    """Punto de entrada — devuelve el dict de símbolos enriquecido para
    `language`, o None si el binding no está disponible (→ caller cae a
    regex). Levanta excepción solo si el parse explota (lo maneja el
    caller como warning).

    `language` ∈ {javascript, typescript, php}. Para tsx/jsx el caller
    pasa el lenguaje base correspondiente.
    """
    lang = (language or "").lower()
    parser = _get_parser(lang)
    if parser is None:
        return None
    if lang == "php":
        return _extract_php(parser, source)
    if lang in ("javascript", "typescript", "tsx", "jsx"):
        out_lang = "typescript" if lang in ("typescript", "tsx") else "javascript"
        return _extract_js(parser, source, out_lang)
    return None
