"""Python scanner (Tier 1) — SCN-003 + NET-022 + URL-SCAN + LOAD-038.

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

LOAD-038 — cuarto pass via AST para filesystem loaders (Python):
  - `open("path")` → sentinel con arg en posición 0
  - `Path("path").read_text()` → sentinel con arg en posición 0 (del constructor)
  - `json.load(open(...))` → nested: resuelve el open() interior
  - `Path().read_bytes()` → idem read_text()

Loaders universales (DEFAULT_PYTHON_LOADERS en defaults.py) se aplican siempre
salvo que sean sobreescritos en mapper_config.json (config extiende, nunca reemplaza).
"""

import ast

from compass.scanners.base import Scanner as _BaseScanner
from compass.path_resolver import encode_loader_raw
from compass.defaults import DEFAULT_PYTHON_LOADERS


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


def _constant_string_value(node):
    """Extrae el valor string de un ast.Constant, o None si no es string.

    Soporta Constant (Python 3.8+) y Str (legacy, Python <3.8).
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    # Legacy: ast.Str para versiones antiguas de Python
    if isinstance(node, ast.Str):
        return node.s
    return None


class PythonScanner(_BaseScanner):
    """Scanner Python Tier 1. Opcionalmente recibe config para NET-022 y LOAD-038."""

    def __init__(self, config=None):
        self._http_loaders = set()
        self._loader_calls = {}  # LOAD-038: loader_calls que aplican a Python
        self._loader_edge_map = {}

        # LOAD-038: inicializar con defaults universales (stdlib Python)
        # Los defaults se pueden sobreescribir/extender vía config (si existe)
        self._loader_calls.update(DEFAULT_PYTHON_LOADERS)
        for fn_name, spec in DEFAULT_PYTHON_LOADERS.items():
            self._loader_edge_map[fn_name] = spec.get("edge_type", "load")

        if config and isinstance(config, dict):
            loaders = (config.get("http_loaders") or {}).get("python") or []
            self._http_loaders = set(loaders)
            # LOAD-038: mergeear loader_calls de config (extiende/sobreescribe defaults)
            all_loaders = config.get("loader_calls") or {}
            for fn_name, spec in all_loaders.items():
                if isinstance(spec, dict) and spec.get("language") == "python":
                    self._loader_calls[fn_name] = spec
                    self._loader_edge_map[fn_name] = spec.get("edge_type", "load")

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

        # LOAD-038 — extraer filesystem loaders (open, Path.read_text, json.load, etc.)
        # via AST. Captura sentinels para que PathResolver los resuelva.
        if self._loader_calls:
            self._extract_filesystem_loaders(tree, out)

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

    def _extract_filesystem_loaders(self, tree, out):
        """LOAD-038 — Extrae loader calls de filesystem via AST y emite sentinels.

        Maneja:
          - `open("path")` → sentinel encode_loader_raw("open", "\"path\"")
          - `Path("path").read_text()` → emite como "read_text" con arg
          - `json.load(open(...))` → nested: resuelve el open interior
          - `Path("path").read_bytes()` → emite como "read_bytes" con arg
          - `VAR = path_expr / "literal.json"` → asignación Path division (extendido)
          - `with open(literal) as f: json.load(f)` → data flow resolver (nuevo 18A.1)

        Nota: los sentinels se configuran en mapper_config con arg: N apropiado
        para que PathResolver los resuelva.
        """
        # Primer pass: buscar asignaciones Path / "literal" para capturar JSONs, etc.
        # Esto permite capturar patrones como:
        #   MODELS_JSON = CERBERO_SETUP_DIR / "global_models.json"
        self._try_path_division_assignments(tree, out)

        # Segundo pass: detectar `with open(...) as var:` seguido de loader calls
        # con esa variable (18A.1 — data flow para context managers)
        self._try_with_open_loaders(tree, out)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            # Intentar case: `Path("path").read_text()` o `.read_bytes()`
            self._try_path_method_call(node, out)

            # Luego intentar: `open("path")` directo o `json.load(open(...))`
            self._try_direct_loader_call(node, out)

    def _try_path_method_call(self, node, out):
        """Intenta matchear Path().read_text() / Path().read_bytes()."""
        if not isinstance(node.func, ast.Attribute):
            return
        method_name = node.func.attr
        if method_name not in ("read_text", "read_bytes"):
            return
        if method_name not in self._loader_calls:
            return

        # Verificar que el objeto es una llamada a Path()
        if not isinstance(node.func.value, ast.Call):
            return
        constructor_call = node.func.value
        constructor_name = _callee_dotted_name(constructor_call.func)
        if constructor_name not in ("Path", "pathlib.Path"):
            return

        # Extraer primer argumento del constructor
        if not constructor_call.args:
            return
        arg_str = _constant_string_value(constructor_call.args[0])
        if not arg_str:
            return

        # Emitir sentinel
        edge_type = self._loader_edge_map.get(method_name, "load")
        sentinel = encode_loader_raw(method_name, f'"{arg_str}"')
        out.append((sentinel, edge_type))

    def _try_direct_loader_call(self, node, out):
        """Intenta matchear loaders registrados en self._loader_calls.

        Soporta patrones:
          - open("path") directo
          - json.load(open(...)) nested
          - send_from_directory("dir", "file") multi-arg
          - send_file("filepath")
          - Cualquier loader genérico registrado
        """
        callee_name = _callee_dotted_name(node.func)
        if not callee_name:
            return

        if callee_name == "open" and "open" in self._loader_calls:
            self._emit_loader_sentinel(node, "open", out, arg_position=0)
        elif callee_name == "json.load" and "json.load" in self._loader_calls:
            self._emit_loader_sentinel_nested(node, "json.load", out)
        elif callee_name in self._loader_calls:
            # Loader genérico: extraer arg según spec
            spec = self._loader_calls.get(callee_name, {})

            # Caso especial: send_from_directory(dir, filename) → combinar ambos
            if callee_name == "send_from_directory" and len(node.args) >= 2:
                dir_str = _constant_string_value(node.args[0])
                file_str = _constant_string_value(node.args[1])
                if dir_str and file_str:
                    combined = f"{dir_str}/{file_str}".replace("//", "/")
                    edge_type = self._loader_edge_map.get(callee_name, "load")
                    sentinel = encode_loader_raw(callee_name, f'"{combined}"')
                    out.append((sentinel, edge_type))
            else:
                # Loader genérico estándar
                arg_pos = spec.get("arg", 1) - 1  # spec usa 1-based, AST usa 0-based
                if 0 <= arg_pos < len(node.args):
                    self._emit_loader_sentinel(node, callee_name, out, arg_position=arg_pos)

    def _try_with_open_loaders(self, tree, out):
        """18A.1 — Detecta `with open(literal) as var:` seguido de consumidores.

        Patrón:
            with open("path.json") as f:
                data = json.load(f)
                ...

        Estrategia:
          1. Buscar ast.With nodes con context manager open(literal)
          2. Extraer el variable binding (ej: f)
          3. Dentro del body del with, buscar Calls que consuman ese variable
          4. Emitir sentinel si se detecta consumidor válido (json.load, yaml.load, etc.)

        Limitación: solo alcanza el scope del with (1 nivel). Si f se pasa a otra
        función, eso es límite teórico (no atacar).
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.With):
                continue

            # Recorrer contextos del with (puede haber múltiples)
            for item in node.items:
                if not isinstance(item.context_expr, ast.Call):
                    continue

                # Verificar que es open()
                callee = _callee_dotted_name(item.context_expr.func)
                if callee != "open":
                    continue

                # Extraer ruta literal del open()
                if not item.context_expr.args:
                    continue
                path_str = _constant_string_value(item.context_expr.args[0])
                if not path_str:
                    continue

                # Obtener el variable binding (var en `as var`)
                if not item.optional_vars:
                    continue
                if isinstance(item.optional_vars, ast.Name):
                    var_name = item.optional_vars.id
                else:
                    # Tuple unpacking u otros — no soportado
                    continue

                # Ahora buscar dentro del body del with si hay consumidores de var
                # Consumidores reconocidos: json.load(f), yaml.load(f), f.read(), etc.
                for body_node in ast.walk(node):
                    if isinstance(body_node, ast.Call):
                        # Case 1: json.load(f), yaml.load(f), etc.
                        callee_name = _callee_dotted_name(body_node.func)
                        if callee_name in self._loader_calls and body_node.args:
                            first_arg = body_node.args[0]
                            if isinstance(first_arg, ast.Name) and first_arg.id == var_name:
                                # Encontramos consumidor de esta variable
                                # Emitir sentinel
                                edge_type = self._loader_edge_map.get(callee_name, "load")
                                sentinel = encode_loader_raw(callee_name, f'"{path_str}"')
                                out.append((sentinel, edge_type))
                                break  # Solo registrar una vez por with block

                        # Case 2: f.read(), f.readlines(), etc. (metodos del file handle)
                        elif isinstance(body_node.func, ast.Attribute):
                            method_name = body_node.func.attr
                            if isinstance(body_node.func.value, ast.Name):
                                obj_name = body_node.func.value.id
                                if obj_name == var_name and method_name in ("read", "readlines", "readline"):
                                    # Consumidor de file handle detectado
                                    edge_type = "load"
                                    sentinel = encode_loader_raw("open", f'"{path_str}"')
                                    out.append((sentinel, edge_type))
                                    break

    def _emit_loader_sentinel(self, node, loader_name, out, arg_position=0):
        """Emite un sentinel para un loader directo como open().

        arg_position: índice del argumento que contiene el path (0-based).
        """
        if not node.args or len(node.args) <= arg_position:
            return
        arg_str = _constant_string_value(node.args[arg_position])
        if not arg_str:
            return
        edge_type = self._loader_edge_map.get(loader_name, "load")
        sentinel = encode_loader_raw(loader_name, f'"{arg_str}"')
        out.append((sentinel, edge_type))

    def _emit_loader_sentinel_nested(self, node, loader_name, out):
        """Emite un sentinel para json.load(open(...)) — resuelve el arg interior."""
        if not node.args:
            return
        first_arg = node.args[0]
        if not isinstance(first_arg, ast.Call):
            return
        inner_callee = _callee_dotted_name(first_arg.func)
        if inner_callee != "open":
            return
        # Recursivamente procesar el open() interior
        self._emit_loader_sentinel(first_arg, "json.load", out, arg_position=0)

    def _try_path_division_assignments(self, tree, out):
        """LOAD-038 extendido — Captura asignaciones Path / "literal".

        Patrón: VAR = path_expr / "nombre_archivo.ext" [/ "subdir" / ...]
        Ejemplos:
          - MODELS_JSON = CERBERO_SETUP_DIR / "global_models.json"
          - CONFIG_PATH = Path.cwd() / "config" / "settings.json"

        Emite sentinels para que el resolver capture estos archivos.
        Extrae TODA la cadena de divisiones (izquierda + derecha) para
        capturar paths como "config/settings.json" en vez de solo "settings.json".
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            # Solo procesar asignaciones simples (una target)
            if len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue

            # Verificar si el valor es una división Path
            # Patrón: BinOp con op = Div (el operador /)
            value = node.value
            if not isinstance(value, ast.BinOp):
                continue
            if not isinstance(value.op, ast.Div):
                continue

            # Navegar la cadena de BinOp para extraer TODOS los literales
            # Forma: ((a / b) / c) → extraer [b, c]
            # También maneja: a / "b" / "c" / "d.json" → [b, c, d.json]
            path_parts = []
            node_ptr = value
            while isinstance(node_ptr, ast.BinOp) and isinstance(node_ptr.op, ast.Div):
                right_lit = _constant_string_value(node_ptr.right)
                if right_lit:
                    path_parts.insert(0, right_lit)
                else:
                    # Si el lado derecho no es literal, parar aquí
                    break
                node_ptr = node_ptr.left

            if not path_parts:
                continue

            # Emitir como un "load" directo con el path literal
            # Si hay múltiples partes, usamos "/" para separarlas.
            full_path = "/".join(path_parts)
            edge_type = "load"
            sentinel = encode_loader_raw("path_literal", f'"{full_path}"')
            out.append((sentinel, edge_type))

