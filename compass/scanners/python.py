"""Python scanner (Tier 1) — SCN-003.

Usa `ast` (stdlib) para extraer imports de archivos .py. Cero dependencias.

Formato de salida — string normalizado que entiende PathResolver._resolve_python:

    'pkg.sub.mod'       ← import pkg.sub.mod
    'pkg.sub:name'      ← from pkg.sub import name
    '.relmod'           ← from . import relmod
    '..pkg:name'        ← from ..pkg import name
    '.:name'            ← from . import name   (dots = 1, module vacío)

El ':' separa el path del módulo del símbolo importado. PathResolver sólo
usa la parte izquierda (el path del módulo) para resolver el archivo.
"""

import ast

from compass.scanners.base import Scanner as _BaseScanner


class PythonScanner(_BaseScanner):
    def extract_imports(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
            tree = ast.parse(source, filename=str(file_path))
        except (OSError, SyntaxError, ValueError):
            return []

        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name:
                        out.append(alias.name)
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
                    out.append(f"{left}:{name}" if name else left)
        return out

