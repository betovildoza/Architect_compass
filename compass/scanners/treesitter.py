"""tree-sitter scanner (Tier 2) — SCN-003.

Scanner genérico que recibe una grammar como parámetro (string tipo
`tree_sitter_php`). Un único módulo cubre PHP, JS, TS, Ruby, Go, etc.

Opt-in: si el módulo de grammar no está instalado, el constructor levanta
ImportError y el dispatcher cae a Tier 3 (regex_fallback).

Hoy el módulo trae queries triviales para PHP y JS. El resto de lenguajes
se dejan sin query explícita — caen a Tier 3 aunque la grammar esté
instalada. Agregar una query es una edición local de `_QUERIES_BY_LANGUAGE`.

Nota: tree-sitter Python tiene dos APIs históricas (pre y post 0.22).
Este módulo implementa la más conservadora: cargar el language object y
recorrer el árbol manualmente buscando nodos por tipo. Si la librería no
está disponible, el scanner ni siquiera se construye.
"""

import importlib

from compass.scanners.base import Scanner as _BaseScanner


# Tipos de nodo del árbol AST tree-sitter por lenguaje. Lista acumulable a
# medida que se verifica el comportamiento sobre proyectos reales.
_NODE_TYPES_BY_LANGUAGE = {
    "php": ("include_expression", "require_expression",
            "include_once_expression", "require_once_expression"),
    "javascript": ("import_statement", "call_expression"),
    "typescript": ("import_statement", "call_expression"),
}


class TreeSitterScanner(_BaseScanner):
    """Scanner Tier 2. Carga una grammar dinámicamente.

    Parámetros:
        grammar_module_name: nombre del módulo Python de la grammar
            (ej: 'tree_sitter_php').
        language: string del lenguaje ('php', 'javascript', ...) — se usa
            para elegir los tipos de nodo relevantes.
    """

    def __init__(self, grammar_module_name, language):
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
        self._node_types = set(
            _NODE_TYPES_BY_LANGUAGE.get(self._language, ())
        )

    def extract_imports(self, file_path):
        if not self._node_types:
            return []
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
        self._walk(tree.root_node, data, out)
        return out

    def _walk(self, node, source_bytes, out):
        if node.type in self._node_types:
            text = source_bytes[node.start_byte:node.end_byte].decode(
                "utf-8", errors="ignore"
            )
            out.append(text)
        for child in node.children:
            self._walk(child, source_bytes, out)