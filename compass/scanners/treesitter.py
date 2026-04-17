"""tree-sitter scanner (Tier 2) — SCN-003 + NET-022 + URL-SCAN.

Scanner genérico que recibe una grammar como parámetro (string tipo
`tree_sitter_php`). Un único módulo cubre PHP, JS, TS, Ruby, Go, etc.

Opt-in: si el módulo de grammar no está instalado, el constructor levanta
ImportError y el dispatcher cae a Tier 3 (regex_fallback).

Hoy el módulo trae queries triviales para PHP y JS. El resto de lenguajes
se dejan sin query explícita — caen a Tier 3 aunque la grammar esté
instalada. Agregar una query es una edición local de `_QUERIES_BY_LANGUAGE`.

NET-022 — Después del walk AST, si `http_loaders` en config tiene entries
para el lenguaje, se ejecuta un regex pass sobre el source text para
capturar URLs literales en llamadas HTTP con edge_type `"fetch"`.

URL-SCAN — Después de NET-022, un pass adicional busca TODOS los string
literals que sean URLs (http:// o https://) en el tree-sitter AST. Emite
con edge_type "fetch", deduplicado contra URLs ya capturadas por NET-022.

Nota: tree-sitter Python tiene dos APIs históricas (pre y post 0.22).
Este módulo implementa la más conservadora: cargar el language object y
recorrer el árbol manualmente buscando nodos por tipo. Si la librería no
está disponible, el scanner ni siquiera se construye.
"""

import importlib
import re

from compass.scanners.base import (
    Scanner as _BaseScanner,
    DEFAULT_EDGE_TYPE,
    build_http_loader_regex,
)

# URL-SCAN — regex para capturar URL literals en source text.
# Captura strings entre comillas simples o dobles que empiezan con http(s)://.
_URL_LITERAL_RE = re.compile(r'''["'](https?://[^"'\s)]+)["']''')


# EDG-023 — mapping node_type → edge_type por lenguaje. Lista acumulable.
# Conservador: si un node type no aparece acá, cae al DEFAULT_EDGE_TYPE.
_NODE_TYPE_EDGE = {
    "php": {
        "include_expression":      "include",
        "include_once_expression": "include",
        "require_expression":      "require",
        "require_once_expression": "require",
    },
    "javascript": {
        "import_statement": "import",
        "call_expression":  "use",   # fetch/axios se capturan pero el AST no distingue sin lookup
    },
    "typescript": {
        "import_statement": "import",
        "call_expression":  "use",
    },
}


# Tipos de nodo del árbol AST tree-sitter por lenguaje (derivado del mapping).
_NODE_TYPES_BY_LANGUAGE = {
    lang: tuple(mapping.keys()) for lang, mapping in _NODE_TYPE_EDGE.items()
}


class TreeSitterScanner(_BaseScanner):
    """Scanner Tier 2. Carga una grammar dinámicamente.

    Parámetros:
        grammar_module_name: nombre del módulo Python de la grammar
            (ej: 'tree_sitter_php').
        language: string del lenguaje ('php', 'javascript', ...) — se usa
            para elegir los tipos de nodo relevantes.
        config: dict de config completo (opcional). NET-022 lo usa para
            extraer `http_loaders[language]` y compilar el regex de URLs.
    """

    def __init__(self, grammar_module_name, language, config=None):
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

        # Cada grammar expone `language()` que retorna el puntero.
        language_fn = getattr(grammar_mod, "language", None)
        if language_fn is None:
            raise ImportError(
                f"El módulo '{grammar_module_name}' no expone language()."
            )

        lang_obj = Language(language_fn())
        self._parser = Parser(lang_obj)
        self._language = (language or "").lower()
        self._edge_map = dict(_NODE_TYPE_EDGE.get(self._language, {}))
        self._node_types = set(self._edge_map.keys())

        # NET-022 — regex para URLs literales en llamadas HTTP.
        self._http_regex = None
        if config and isinstance(config, dict):
            loaders = (config.get("http_loaders") or {}).get(self._language) or []
            self._http_regex = build_http_loader_regex(loaders)

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
        if self._node_types:
            self._walk(tree.root_node, data, out)

        # NET-022 — segundo pass: extraer URLs literales de llamadas HTTP.
        source_text = data.decode("utf-8", errors="ignore")
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
        if node.type in self._node_types:
            text = source_bytes[node.start_byte:node.end_byte].decode(
                "utf-8", errors="ignore"
            )
            # EDG-023 — edge_type según node_type; fallback a DEFAULT.
            edge_type = self._edge_map.get(node.type, DEFAULT_EDGE_TYPE)
            out.append((text, edge_type))
        for child in node.children:
            self._walk(child, source_bytes, out)