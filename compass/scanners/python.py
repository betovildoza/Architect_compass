"""Python scanner (Tier 1) — SCN-003 + NET-022 + URL-SCAN.

Usa `ast` (stdlib) para extraer imports de archivos .py. Cero dependencias.

Formato de salida — string normalizado que entiende PathResolver._resolve_python:

    'pkg.sub.mod'       ← import pkg.sub.mod
    'pkg.sub:name'      ← from pkg.sub import name
    '.relmod'           ← from . import relmod
    '..pkg:name'        ← from ..pkg import name
    '.:name'            ← from . import name   (dots = 1, module vacío)

El ':' separa el path del módulo del símbolo importado. PathResolver sólo
usa la parte izquierda (el path del módulo) para resolver el archivo.

NET-022 — segundo pass via AST: si `http_loaders["python"]` existe en el
config, recorre el AST buscando `Call` nodes cuyo callee matchea algún
nombre de http_loader y cuyo primer argumento es un string literal (Constant
con valor str). Emite la URL literal con edge_type `"fetch"`.
Usar AST en vez de regex evita false positives en docstrings/comments.

URL-SCAN — tercer pass via AST: busca TODOS los string literals que sean
URLs (http:// o https://) independientemente del contexto (assignment,
argumento a función no listada en http_loaders, etc.). Deduplicado contra
URLs ya capturadas por NET-022 para evitar duplicados. Las URLs se emiten
con edge_type "fetch" y core.py las clasifica vía _classify_outbound.
"""

import ast

from compass.scanners.base import Scanner as _BaseScanner


def _callee_dotted_name(node):
    """Extrae el nombre punteado de un callee AST node.

    Soporta:
      - Name('fetch')         → 'fetch'
      - Attribute(Name('requests'), 'get') → 'requests.get'
      - Attribute(Attribute(Name('urllib'), 'request'), 'urlopen')
                              → 'urllib.request.urlopen'

    Retorna None si el nodo no es un callee simple (ej: subscript, call
    anidado, expresión compleja).
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _callee_dotted_name(node.value)
        if parent is not None:
            return parent + "." + node.attr
    return None


class PythonScanner(_BaseScanner):
    """Scanner Python Tier 1. Opcionalmente recibe config para NET-022."""

    def __init__(self, config=None):
        self._http_loaders = set()
        if config and isinstance(config, dict):
            loaders = (config.get("http_loaders") or {}).get("python") or []
            self._http_loaders = set(loaders)

    def extract_imports(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
            tree = ast.parse(source, filename=str(file_path))
        except (OSError, SyntaxError, ValueError):
            return []

        # EDG-023 — todas las edges de Python se etiquetan "import".
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name:
                        out.append((alias.name, "import"))
            elif isinstance(node, ast.ImportFrom):
                # level = 0 → import absoluto.
                # level = 1 → from . import x
                # level = 2 → from .. import x
                prefix = "." * (node.level or 0)
                module = node.module or ""
                for alias in node.names:
                    # `from x import y` → "x:y". Preservar el alias.name
                    # permite a PathResolver buscar el archivo "y.py" si
                    # "x.y" no existe como módulo (submódulo).
                    name = alias.name or ""
                    left = prefix + module
                    target = f"{left}:{name}" if name else left
                    out.append((target, "import"))

            # NET-022 — extraer URLs literales de llamadas HTTP via AST.
            # Busca Call nodes cuyo callee es un nombre que matchea algún
            # http_loader, y cuyo primer argumento es un string literal.
            # Usar AST (no regex) evita false positives en docstrings.
            elif isinstance(node, ast.Call) and self._http_loaders:
                callee_name = _callee_dotted_name(node.func)
                if callee_name and callee_name in self._http_loaders:
                    # Primer argumento posicional debe ser string literal.
                    if node.args:
                        first_arg = node.args[0]
                        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                            url = first_arg.value
                            if url:
                                out.append((url, "fetch"))

        # URL-SCAN — broad URL literal scan via AST.
        # Catch URLs regardless of calling function. Dedup against URLs
        # already captured by the http_loaders pass above.
        seen_urls = {t for t, et in out if et == "fetch"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value.strip()
                if len(val) > 10 and val.startswith(("http://", "https://")):
                    if val not in seen_urls:
                        seen_urls.add(val)
                        out.append((val, "fetch"))

        return out

