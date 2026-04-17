"""Architect's Compass — Symbol Tool (SYM-004).

Tool paralela al pipeline principal de `architect_compass.py`. Extrae
funciones, clases, firmas y constantes por archivo y los serializa en
`.map/symbols.json` — formato pensado para contexto LLM.

No toca `compass/core.py`, `analyze()` ni `finalize()`. Es un pipeline
independiente que solo comparte helpers de carga de config.

Uso:
    python architect_symbols.py            # escanea el cwd
    python architect_symbols.py --root X   # escanea X
    python architect_symbols.py --help

Lenguajes cubiertos:
    Python → stdlib `ast`.
    JavaScript/TypeScript → regex fallback (tree-sitter opcional).
    PHP → regex fallback (tree-sitter opcional).
    HTML / CSS / JSON → skip (no tienen símbolos).

Shape del output (`.map/symbols.json`):
    {
      "version": "1.0",
      "generated_at": "ISO-8601",
      "project_name": "basename del root (solo identificador, nunca path absoluto)",
      "stats": {"files_scanned": N, "functions": N, "classes": N, "warnings": N},
      "files": {
        "relative/path.py": {
          "language": "python",
          "functions": [{"name": "...", "args": [...], "decorators": [...], "line": N}],
          "classes":   [{"name": "...", "bases": [...], "methods": [...], "line": N}],
          "constants": [{"name": "...", "kind": "str", "line": N}]
        }
      },
      "warnings": [{"path": "...", "error": "..."}]
    }

Config:
    Respeta `basal_rules.{ignore_folders, ignore_files, ignore_patterns,
    text_extensions}` del `mapper_config.json` global + `compass.local.json`
    del proyecto, usando `ArchitectCompass.load_config_hierarchy()` sin
    ejecutar `analyze()`.

Performance esperada:
    <10s para proyectos chicos (~hasta 1k archivos scannables).
    <30s para proyectos medianos (~hasta 5k archivos scannables).
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# MEDIO — VERSION del shape de symbols.json. Si el formato cambia a 1.1,
# actualizar también el docstring arriba. Default razonable: pocos bumps
# esperados en el año; no justifica hoy un config externo.
VERSION = "1.0"

# FUENTE ÚNICA de extensiones manejadas por cada extractor. Los archivos
# cuya extensión no aparece en este mapa son ignorados (aunque estén en
# text_extensions del config). Cambios requieren tocar extractores.
_HANDLED_EXTENSIONS_BY_LANGUAGE: Dict[str, set] = {
    "python": {".py"},
    "javascript": {".js", ".mjs", ".jsx"},
    "typescript": {".ts", ".tsx"},
    "php": {".php"},
}
_PYTHON_EXTS = _HANDLED_EXTENSIONS_BY_LANGUAGE["python"]
_JS_EXTS = _HANDLED_EXTENSIONS_BY_LANGUAGE["javascript"] | _HANDLED_EXTENSIONS_BY_LANGUAGE["typescript"]
_PHP_EXTS = _HANDLED_EXTENSIONS_BY_LANGUAGE["php"]
_HANDLED_EXTS: set = set().union(*_HANDLED_EXTENSIONS_BY_LANGUAGE.values())

# FALLBACK — Si `mapper_config.json` no carga (tool invocada fuera del repo
# Compass o config corrupto), usar estos defaults. Se mantiene sincronizado
# manualmente con `basal_rules.ignore_folders` del config global. Si el
# config sí carga, los valores del config tienen prioridad (ver
# _collect_files, donde hoy ambos se unionan — comportamiento histórico).
_DEFAULT_IGNORE_FOLDERS = {
    "__pycache__", "node_modules", "dist", "build", "venv", ".venv",
    ".git", ".map", ".claude", "_archivo", "out", ".next",
    "src-tauri/target", "target", "gen", "bin", "obj", "vendor",
    ".quarantine",
}
# FALLBACK — intersecta luego contra _HANDLED_EXTS en _collect_files.
_DEFAULT_TEXT_EXTS = _HANDLED_EXTS


# ---------------------------------------------------------------------------
# Config loading — intenta reutilizar compass.core.load_config_hierarchy.
# Si no está disponible (tool invocada fuera del repo Compass) cae a
# defaults razonables.
# ---------------------------------------------------------------------------

def _load_compass_config(project_root: Path) -> Dict[str, Any]:
    """Carga config basal + local sin instanciar ArchitectCompass.

    Reusa los helpers internos de core.py pero sin ejecutar `__init__`
    completo (que haría detección de stack, indexado de files, etc.).

    Devuelve un dict con el shape que produce `load_config_hierarchy()`.
    Nunca levanta — ante cualquier error devuelve un config mínimo con
    defaults seguros.
    """
    script_dir = Path(__file__).parent.absolute()

    # Inyectar el repo al sys.path para poder importar compass.*
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    try:
        # Evitar ejecutar analyze(): creamos un dummy con cwd cambiado
        # brevemente — load_config_hierarchy() solo usa paths basados en
        # project_root vía __init__. Como eso es pesado, replicamos la
        # lógica a mano leyendo los JSON directamente.
        # MEDIO — `mapper_config.json` es el nombre canonical del basal
        # del proyecto; no se parametriza por diseño (si alguien quiere
        # overrides locales usa `.map/compass.local.json`).
        global_cfg_path = script_dir / "mapper_config.json"
        # MEDIO — `.map/compass.local.json` sigue la convención del proyecto:
        # `.map/` es el directorio canonical de outputs y overrides locales.
        local_cfg_path = project_root / ".map" / "compass.local.json"
        legacy_local = project_root / ".map" / "mapper_config.json"

        config: Dict[str, Any] = {}
        if global_cfg_path.exists():
            config = json.loads(global_cfg_path.read_text(encoding="utf-8"))

        local_cfg: Optional[Dict[str, Any]] = None
        if local_cfg_path.exists():
            try:
                local_cfg = json.loads(local_cfg_path.read_text(encoding="utf-8"))
            except Exception as e:  # pragma: no cover - tolerante
                print(f"[symbols] WARN local config ilegible: {e}")
        elif legacy_local.exists():
            try:
                local_cfg = json.loads(legacy_local.read_text(encoding="utf-8"))
            except Exception as e:  # pragma: no cover
                print(f"[symbols] WARN legacy local config ilegible: {e}")

        if local_cfg:
            _merge_local_basal(config, local_cfg)
        return config
    except Exception as e:  # pragma: no cover
        print(f"[symbols] WARN fallback a defaults — {e}")
        return {}


def _merge_local_basal(config: Dict[str, Any], local_cfg: Dict[str, Any]) -> None:
    """Merge parcial de `basal_rules` — extiende listas del global con las del local.

    Refleja el comportamiento de `_merge_local_into` de core.py para las
    únicas 3 claves que este tool consume (ignore_folders/files/patterns +
    text_extensions). Las claves `*_remove` del local restan entries.
    """
    global_basal = config.setdefault("basal_rules", {})
    local_basal = local_cfg.get("basal_rules") or {}
    if not isinstance(local_basal, dict):
        return

    list_keys = ("ignore_folders", "ignore_files", "ignore_patterns", "text_extensions")
    for key in list_keys:
        local_vals = local_basal.get(key)
        if isinstance(local_vals, list) and local_vals:
            base = global_basal.setdefault(key, [])
            if isinstance(base, list):
                for v in local_vals:
                    if v not in base:
                        base.append(v)

    # Removal directives (`<list>_remove`)
    for key in ("ignore_folders", "ignore_files", "ignore_patterns"):
        remove = local_basal.get(f"{key}_remove")
        if isinstance(remove, list) and remove:
            current = global_basal.get(key) or []
            if isinstance(current, list):
                rem = {str(r) for r in remove if r}
                global_basal[key] = [x for x in current if x not in rem]


# ---------------------------------------------------------------------------
# File walker
# ---------------------------------------------------------------------------

def _collect_files(project_root: Path, rules: Dict[str, Any]) -> List[Tuple[Path, str]]:
    """Walk del project_root respetando ignore_* y text_extensions.

    Devuelve lista de tuples `(abs_path, rel_posix)`.
    """
    ignore_folders = set(rules.get("ignore_folders") or []) | _DEFAULT_IGNORE_FOLDERS
    ignore_files = set(rules.get("ignore_files") or [])
    ignore_patterns = list(rules.get("ignore_patterns") or [])
    text_extensions = set(rules.get("text_extensions") or []) or _DEFAULT_TEXT_EXTS

    # Solo nos interesan extensiones con extractor — fuente única _HANDLED_EXTS.
    text_extensions = text_extensions & _HANDLED_EXTS
    if not text_extensions:
        # Si el config no declara ninguna handled extension, usar defaults.
        text_extensions = _HANDLED_EXTS

    collected: List[Tuple[Path, str]] = []
    root_str = str(project_root)
    for dirpath, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in ignore_folders]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in text_extensions:
                continue
            abs_path = Path(dirpath) / fname
            rel_posix = abs_path.relative_to(project_root).as_posix()
            if rel_posix in ignore_files:
                continue
            if any(
                fnmatch.fnmatch(fname, pat) or fnmatch.fnmatch(rel_posix, pat)
                for pat in ignore_patterns
            ):
                continue
            collected.append((abs_path, rel_posix))
    return collected


# ---------------------------------------------------------------------------
# Python extractor (stdlib ast)
# ---------------------------------------------------------------------------

def _format_decorator(node: ast.AST) -> str:
    """Representación compacta de un decorator (sin argumentos completos)."""
    try:
        return "@" + ast.unparse(node)  # type: ignore[attr-defined]
    except Exception:
        # Fallback muy básico
        if isinstance(node, ast.Name):
            return "@" + node.id
        if isinstance(node, ast.Attribute):
            parts = []
            cur: Any = node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            return "@" + ".".join(reversed(parts))
        if isinstance(node, ast.Call):
            return _format_decorator(node.func) + "(...)"
        return "@<expr>"


def _python_args(func: ast.AST) -> List[str]:
    """Lista compacta de nombres de argumentos de una función AST."""
    if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    args: List[str] = []
    a = func.args
    for param in a.posonlyargs + a.args:
        args.append(param.arg)
    if a.vararg:
        args.append("*" + a.vararg.arg)
    for param in a.kwonlyargs:
        args.append(param.arg)
    if a.kwarg:
        args.append("**" + a.kwarg.arg)
    return args


def _python_base(node: ast.expr) -> str:
    try:
        return ast.unparse(node)  # type: ignore[attr-defined]
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return _python_base(node.value) + "." + node.attr
        return "<expr>"


def _python_literal_kind(node: ast.expr) -> Optional[str]:
    """Devuelve `str`, `int`, `float`, `bool`, `list`, `dict`, `tuple`, `None` — o None."""
    if isinstance(node, ast.Constant):
        v = node.value
        if v is None:
            return "NoneType"
        if isinstance(v, bool):
            return "bool"
        if isinstance(v, int):
            return "int"
        if isinstance(v, float):
            return "float"
        if isinstance(v, str):
            return "str"
        if isinstance(v, bytes):
            return "bytes"
        return type(v).__name__
    if isinstance(node, ast.List):
        return "list"
    if isinstance(node, ast.Dict):
        return "dict"
    if isinstance(node, ast.Tuple):
        return "tuple"
    if isinstance(node, ast.Set):
        return "set"
    return None


def extract_python(source: str, rel_path: str) -> Dict[str, Any]:
    """Extrae símbolos de un archivo Python con AST stdlib."""
    tree = ast.parse(source, filename=rel_path)

    functions: List[Dict[str, Any]] = []
    classes: List[Dict[str, Any]] = []
    constants: List[Dict[str, Any]] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append({
                "name": node.name,
                "args": _python_args(node),
                "decorators": [_format_decorator(d) for d in node.decorator_list],
                "line": node.lineno,
                "async": isinstance(node, ast.AsyncFunctionDef),
            })
        elif isinstance(node, ast.ClassDef):
            methods: List[Dict[str, Any]] = []
            init_args: List[str] = []
            for inner in node.body:
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    m_args = _python_args(inner)
                    methods.append({
                        "name": inner.name,
                        "args": m_args,
                        "decorators": [_format_decorator(d) for d in inner.decorator_list],
                        "line": inner.lineno,
                        "async": isinstance(inner, ast.AsyncFunctionDef),
                    })
                    if inner.name == "__init__":
                        init_args = [a for a in m_args if a != "self"]
            classes.append({
                "name": node.name,
                "bases": [_python_base(b) for b in node.bases],
                "decorators": [_format_decorator(d) for d in node.decorator_list],
                "methods": methods,
                "init_args": init_args,
                "line": node.lineno,
            })
        elif isinstance(node, ast.Assign):
            # Constantes top-level con nombre UPPER_SNAKE o similar.
            kind = _python_literal_kind(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants.append({
                        "name": target.id,
                        "kind": kind,
                        "line": node.lineno,
                    })
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            kind = _python_literal_kind(node.value) if node.value is not None else None
            constants.append({
                "name": node.target.id,
                "kind": kind,
                "line": node.lineno,
            })

    return {
        "language": "python",
        "functions": functions,
        "classes": classes,
        "constants": constants,
    }


# ---------------------------------------------------------------------------
# JS/TS extractor (regex fallback)
#
# Cubre:
#   - function name(...) { ... }          → function declaration
#   - async function name(...) { ... }    → async function
#   - const name = (args) => ...          → arrow assigned to const/let/var
#   - const name = function(args) { ... } → function expression assigned
#   - class Name extends Base { ... }     → class declaration
#   - export (default)? function name(...) / class Name
# ---------------------------------------------------------------------------

_JS_STRIP_COMMENTS = re.compile(
    r"/\*.*?\*/"          # block comment
    r"|//[^\n]*",         # line comment
    flags=re.DOTALL,
)

_JS_FUNC_RE = re.compile(
    r"""
    (?P<export>export\s+(?:default\s+)?)?
    (?P<async>async\s+)?
    function\s*\*?\s*
    (?P<name>[A-Za-z_$][\w$]*)
    \s*\((?P<args>[^)]*)\)
    """,
    re.VERBOSE,
)

_JS_ARROW_RE = re.compile(
    r"""
    (?P<export>export\s+(?:default\s+)?)?
    (?:const|let|var)\s+
    (?P<name>[A-Za-z_$][\w$]*)
    \s*(?::[^=]+?)?=\s*
    (?P<async>async\s+)?
    (?:
        \((?P<args>[^)]*)\)
        |
        (?P<single>[A-Za-z_$][\w$]*)
    )
    \s*=>
    """,
    re.VERBOSE,
)

_JS_FUNC_EXPR_RE = re.compile(
    r"""
    (?P<export>export\s+(?:default\s+)?)?
    (?:const|let|var)\s+
    (?P<name>[A-Za-z_$][\w$]*)
    \s*=\s*
    (?P<async>async\s+)?
    function\s*\*?\s*(?:[A-Za-z_$][\w$]*)?
    \s*\((?P<args>[^)]*)\)
    """,
    re.VERBOSE,
)

_JS_CLASS_RE = re.compile(
    r"""
    (?P<export>export\s+(?:default\s+)?)?
    class\s+
    (?P<name>[A-Za-z_$][\w$]*)
    (?:\s+extends\s+(?P<base>[A-Za-z_$][\w$.]*))?
    """,
    re.VERBOSE,
)

# Constantes top-level: heurística UPPER_SNAKE asignadas con = literal.
_JS_CONST_RE = re.compile(
    r"""
    ^\s*(?:export\s+)?(?:const|let)\s+
    (?P<name>[A-Z][A-Z0-9_]*)
    \s*=\s*
    (?P<value>.+?)\s*;?\s*$
    """,
    re.VERBOSE | re.MULTILINE,
)


def _split_js_args(raw: str) -> List[str]:
    raw = raw.strip()
    if not raw:
        return []
    # Muy básico: split por coma de nivel 0 (ignorando paréntesis/braces).
    depth = 0
    buf = ""
    out: List[str] = []
    for ch in raw:
        if ch in "([{":
            depth += 1
            buf += ch
        elif ch in ")]}":
            depth -= 1
            buf += ch
        elif ch == "," and depth == 0:
            out.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(buf.strip())
    # Limpiar type annotations TS y defaults — quedarse con nombre.
    cleaned: List[str] = []
    for a in out:
        # remover default: `x = 5` → `x`
        a = a.split("=", 1)[0].strip()
        # remover anotación TS: `x: Foo` → `x`
        a = a.split(":", 1)[0].strip()
        if a:
            cleaned.append(a)
    return cleaned


def _js_line_of(source: str, index: int) -> int:
    return source.count("\n", 0, index) + 1


def _kind_of_js_literal(val: str) -> Optional[str]:
    v = val.strip().rstrip(";").strip()
    if not v:
        return None
    if v[0] in "\"'`":
        return "str"
    if v in ("true", "false"):
        return "bool"
    if v == "null":
        return "null"
    if v == "undefined":
        return "undefined"
    if v.startswith("["):
        return "array"
    if v.startswith("{"):
        return "object"
    try:
        float(v)
        return "number"
    except ValueError:
        return None


def extract_js(source: str, rel_path: str) -> Dict[str, Any]:
    """Extrae símbolos de un archivo JS/TS con regex."""
    # Quitar comentarios para evitar falsos positivos. Esto rompe posiciones
    # originales — compensamos manteniendo una version paralela para lineno.
    clean = _JS_STRIP_COMMENTS.sub(lambda m: " " * len(m.group(0)), source)

    functions: List[Dict[str, Any]] = []
    classes: List[Dict[str, Any]] = []
    constants: List[Dict[str, Any]] = []
    seen_names = set()

    ext = os.path.splitext(rel_path)[1].lower()
    language = "typescript" if ext in (".ts", ".tsx") else "javascript"

    for m in _JS_FUNC_RE.finditer(clean):
        name = m.group("name")
        exported = bool(m.group("export"))
        is_async = bool(m.group("async"))
        line = _js_line_of(source, m.start())
        key = ("func", name, line)
        if key in seen_names:
            continue
        seen_names.add(key)
        functions.append({
            "name": name,
            "args": _split_js_args(m.group("args") or ""),
            "decorators": [],
            "line": line,
            "async": is_async,
            "exported": exported,
        })

    for m in _JS_ARROW_RE.finditer(clean):
        name = m.group("name")
        exported = bool(m.group("export"))
        is_async = bool(m.group("async"))
        args_raw = m.group("args")
        if args_raw is None:
            single = m.group("single")
            args = [single] if single else []
        else:
            args = _split_js_args(args_raw or "")
        line = _js_line_of(source, m.start())
        key = ("arrow", name, line)
        if key in seen_names:
            continue
        seen_names.add(key)
        functions.append({
            "name": name,
            "args": args,
            "decorators": [],
            "line": line,
            "async": is_async,
            "exported": exported,
            "kind": "arrow",
        })

    for m in _JS_FUNC_EXPR_RE.finditer(clean):
        name = m.group("name")
        exported = bool(m.group("export"))
        is_async = bool(m.group("async"))
        line = _js_line_of(source, m.start())
        key = ("fexpr", name, line)
        if key in seen_names:
            continue
        seen_names.add(key)
        functions.append({
            "name": name,
            "args": _split_js_args(m.group("args") or ""),
            "decorators": [],
            "line": line,
            "async": is_async,
            "exported": exported,
            "kind": "expression",
        })

    for m in _JS_CLASS_RE.finditer(clean):
        name = m.group("name")
        base = m.group("base")
        exported = bool(m.group("export"))
        line = _js_line_of(source, m.start())
        # Métodos: buscar `name(args)` en el bloque siguiente. Rudimentario
        # pero suficiente como señal para contexto LLM.
        body_start = clean.find("{", m.end())
        methods: List[Dict[str, Any]] = []
        if body_start != -1:
            depth = 0
            end = -1
            for i in range(body_start, len(clean)):
                c = clean[i]
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end != -1:
                body = clean[body_start + 1:end]
                # Método: (async )?name(args) { (sin keyword function).
                for mm in re.finditer(
                    r"(?:^|\n)\s*(?P<async>async\s+)?(?P<name>[A-Za-z_$][\w$]*)\s*\((?P<args>[^)]*)\)\s*\{",
                    body,
                ):
                    mname = mm.group("name")
                    if mname in ("if", "for", "while", "switch", "catch", "return"):
                        continue
                    methods.append({
                        "name": mname,
                        "args": _split_js_args(mm.group("args") or ""),
                        "async": bool(mm.group("async")),
                        "line": line + body[:mm.start()].count("\n"),
                    })
        classes.append({
            "name": name,
            "bases": [base] if base else [],
            "decorators": [],
            "methods": methods,
            "line": line,
            "exported": exported,
        })

    for m in _JS_CONST_RE.finditer(clean):
        name = m.group("name")
        value = m.group("value")
        line = _js_line_of(source, m.start())
        constants.append({
            "name": name,
            "kind": _kind_of_js_literal(value),
            "line": line,
        })

    return {
        "language": language,
        "functions": functions,
        "classes": classes,
        "constants": constants,
    }


# ---------------------------------------------------------------------------
# PHP extractor (regex fallback)
# ---------------------------------------------------------------------------

_PHP_STRIP_COMMENTS = re.compile(
    r"/\*.*?\*/|//[^\n]*|\#[^\n]*",
    flags=re.DOTALL,
)

_PHP_FUNC_RE = re.compile(
    r"""
    (?P<visibility>(?:public|protected|private|static|final|abstract)\s+){0,4}
    function\s+
    (?P<name>[A-Za-z_\x80-\xff][\w\x80-\xff]*)
    \s*\((?P<args>[^)]*)\)
    """,
    re.VERBOSE,
)

_PHP_CLASS_RE = re.compile(
    r"""
    (?:(?P<abstract>abstract|final)\s+)?
    (?P<kind>class|interface|trait)\s+
    (?P<name>[A-Za-z_\x80-\xff][\w\x80-\xff]*)
    (?:\s+extends\s+(?P<base>[A-Za-z_\x80-\xff\\][\w\x80-\xff\\,\s]*?))?
    (?:\s+implements\s+(?P<impl>[A-Za-z_\x80-\xff\\][\w\x80-\xff\\,\s]*?))?
    \s*\{
    """,
    re.VERBOSE,
)

_PHP_CONST_RE = re.compile(
    r"""
    (?:^|\s)
    (?:const\s+(?P<name1>[A-Z][A-Z0-9_]*)\s*=\s*(?P<val1>[^;]+);
       |define\s*\(\s*['"](?P<name2>[A-Z][A-Z0-9_]*)['"]\s*,\s*(?P<val2>[^)]+)\))
    """,
    re.VERBOSE,
)


def _split_php_args(raw: str) -> List[str]:
    raw = raw.strip()
    if not raw:
        return []
    out: List[str] = []
    depth = 0
    buf = ""
    for ch in raw:
        if ch in "([{":
            depth += 1
            buf += ch
        elif ch in ")]}":
            depth -= 1
            buf += ch
        elif ch == "," and depth == 0:
            out.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(buf.strip())
    cleaned: List[str] = []
    for a in out:
        a = a.split("=", 1)[0].strip()
        # Remover type hints: `Foo $bar` → `$bar`; `?Foo $bar` → `$bar`.
        parts = a.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].startswith("$"):
            a = parts[1]
        if a:
            cleaned.append(a.lstrip("&"))
    return cleaned


def _php_line_of(source: str, index: int) -> int:
    return source.count("\n", 0, index) + 1


def _kind_of_php_literal(val: str) -> Optional[str]:
    v = val.strip().rstrip(";").strip()
    if not v:
        return None
    if v[0] in "\"'":
        return "str"
    low = v.lower()
    if low in ("true", "false"):
        return "bool"
    if low == "null":
        return "null"
    if v.startswith("["):
        return "array"
    if v.startswith("array("):
        return "array"
    try:
        float(v)
        return "number"
    except ValueError:
        return None


def _keep_only_php_blocks(source: str) -> str:
    """Reemplaza todo lo que NO esté entre `<?php` y `?>` con espacios.

    Preserva offsets (línea / columna) para que los regex reporten línea
    correcta. Archivos PHP puros sin `<?php` explícito (raro) se tratan
    como todo-PHP.
    """
    if "<?php" not in source and "<?=" not in source:
        return source  # assume pure-PHP file
    out = list(" " * len(source))
    i = 0
    n = len(source)
    while i < n:
        # Buscar apertura
        open_idx = source.find("<?", i)
        if open_idx == -1:
            break
        # Saltar el tag de apertura
        if source.startswith("<?php", open_idx):
            tag_end = open_idx + 5
        elif source.startswith("<?=", open_idx):
            tag_end = open_idx + 3
        else:
            tag_end = open_idx + 2
        # Buscar cierre
        close_idx = source.find("?>", tag_end)
        if close_idx == -1:
            close_idx = n
        # Copiar bloque PHP preservando offset
        for j in range(tag_end, close_idx):
            out[j] = source[j]
        i = close_idx + 2
    return "".join(out)


def extract_php(source: str, rel_path: str) -> Dict[str, Any]:
    """Extrae símbolos de un archivo PHP con regex básico."""
    php_only = _keep_only_php_blocks(source)
    clean = _PHP_STRIP_COMMENTS.sub(lambda m: " " * len(m.group(0)), php_only)

    functions: List[Dict[str, Any]] = []
    classes: List[Dict[str, Any]] = []
    constants: List[Dict[str, Any]] = []

    # Clases primero — así podemos atribuir métodos a la clase contenedora.
    # Estrategia: localizar cada clase y su bloque balanced `{...}`.
    class_spans: List[Tuple[int, int, Dict[str, Any]]] = []
    for m in _PHP_CLASS_RE.finditer(clean):
        name = m.group("name")
        base = m.group("base")
        kind = m.group("kind")
        impl = m.group("impl")
        brace_start = clean.find("{", m.start())
        if brace_start == -1:
            continue
        depth = 0
        end = -1
        for i in range(brace_start, len(clean)):
            c = clean[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            end = len(clean)
        cls_entry = {
            "name": name,
            "kind": kind,
            "bases": [b.strip() for b in (base or "").split(",") if b.strip()],
            "implements": [i.strip() for i in (impl or "").split(",") if i.strip()],
            "methods": [],
            "line": _php_line_of(source, m.start()),
        }
        class_spans.append((brace_start, end, cls_entry))
        classes.append(cls_entry)

    # Funciones: asignar a clase si cae dentro de un span, sino top-level.
    for m in _PHP_FUNC_RE.finditer(clean):
        name = m.group("name")
        args = _split_php_args(m.group("args") or "")
        line = _php_line_of(source, m.start())
        containing = None
        for start, end, entry in class_spans:
            if start < m.start() < end:
                containing = entry
                break
        if containing is not None:
            containing["methods"].append({
                "name": name,
                "args": args,
                "line": line,
            })
        else:
            functions.append({
                "name": name,
                "args": args,
                "decorators": [],
                "line": line,
            })

    # Constantes top-level (const FOO = X; o define('FOO', X))
    for m in _PHP_CONST_RE.finditer(clean):
        name = m.group("name1") or m.group("name2")
        val = m.group("val1") or m.group("val2") or ""
        if not name:
            continue
        constants.append({
            "name": name,
            "kind": _kind_of_php_literal(val),
            "line": _php_line_of(source, m.start()),
        })

    return {
        "language": "php",
        "functions": functions,
        "classes": classes,
        "constants": constants,
    }


# ---------------------------------------------------------------------------
# Dispatcher + main loop
# ---------------------------------------------------------------------------

def extract_file(abs_path: Path, rel_posix: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Devuelve (symbols_dict, error_or_none) para un archivo dado.

    Ante error de parsing devuelve `(None, mensaje)` — el archivo se
    registra en `warnings` del output.
    """
    ext = abs_path.suffix.lower()
    try:
        source = abs_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return None, f"read-error: {e}"

    try:
        if ext in _PYTHON_EXTS:
            return extract_python(source, rel_posix), None
        if ext in _JS_EXTS:
            return extract_js(source, rel_posix), None
        if ext in _PHP_EXTS:
            return extract_php(source, rel_posix), None
    except SyntaxError as e:
        return None, f"syntax-error L{e.lineno}: {e.msg}"
    except Exception as e:
        return None, f"parse-error: {type(e).__name__}: {e}"
    return None, None  # extensión sin extractor


def build_symbols(project_root: Path, verbose: bool = False) -> Dict[str, Any]:
    """Genera el dict completo de símbolos para `.map/symbols.json`."""
    config = _load_compass_config(project_root)
    rules = (config.get("basal_rules") or {})

    files = _collect_files(project_root, rules)
    if verbose:
        print(f"[symbols] {len(files)} archivos scannables bajo {project_root}")

    files_out: Dict[str, Dict[str, Any]] = {}
    warnings: List[Dict[str, str]] = []
    total_funcs = 0
    total_classes = 0

    for abs_path, rel_posix in files:
        symbols, err = extract_file(abs_path, rel_posix)
        if err is not None:
            warnings.append({"path": rel_posix, "error": err})
            continue
        if symbols is None:
            continue
        # Skip archivos sin nada util (reduce ruido en el JSON).
        if not (symbols["functions"] or symbols["classes"] or symbols["constants"]):
            continue
        files_out[rel_posix] = symbols
        total_funcs += len(symbols["functions"])
        total_classes += len(symbols["classes"])
        # Métodos cuentan aparte pero suman señal.
        for cls in symbols["classes"]:
            total_funcs += len(cls.get("methods") or [])

    return {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # NO emitir paths absolutos — solo el basename como identificador.
        # Regla dura del proyecto: cero hardcoded paths en outputs.
        "project_name": project_root.name,
        "stats": {
            "files_scanned": len(files),
            "files_with_symbols": len(files_out),
            "functions": total_funcs,
            "classes": total_classes,
            "warnings": len(warnings),
        },
        "files": files_out,
        "warnings": warnings,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="architect_symbols",
        description=(
            "Extrae funciones/clases/firmas por archivo (SYM-004). "
            "Output: <root>/.map/symbols.json."
        ),
    )
    parser.add_argument(
        "--root", default=None,
        help="Directorio raíz del proyecto a escanear (default: cwd).",
    )
    parser.add_argument(
        "--output", default=None,
        help="Ruta del archivo de salida (default: <root>/.map/symbols.json).",
    )
    parser.add_argument(
        "--stdout", action="store_true",
        help="Imprimir el JSON a stdout en vez de escribirlo a disco.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Mostrar progreso.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path.cwd().resolve()
    if not root.is_dir():
        print(f"[symbols] ERROR root no es un directorio: {root}", file=sys.stderr)
        return 2

    t0 = time.time()
    result = build_symbols(root, verbose=args.verbose)
    elapsed = time.time() - t0
    result["elapsed_seconds"] = round(elapsed, 3)

    if args.stdout:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        out_path = Path(args.output) if args.output else (root / ".map" / "symbols.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        stats = result["stats"]
        print(
            f"[symbols] OK — {stats['files_with_symbols']}/{stats['files_scanned']} "
            f"archivos · {stats['functions']} funciones · {stats['classes']} clases "
            f"· {stats['warnings']} warnings · {elapsed:.2f}s"
        )
        print(f"[symbols] Escrito: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
