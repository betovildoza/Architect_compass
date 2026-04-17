"""Path resolver — RES-002 + SEM-020 + INIT-032.

Convierte un string crudo de import (ej: './utils', '__DIR__ . "/sub/file.php"',
'@alias/module', 'from .foo import bar') en el path absoluto del archivo
referenciado, usando reglas semánticas por lenguaje.

Retorna:
    - str (path absoluto posix) si el archivo resuelve a algo existente
      dentro del project_root.
    - None si el import es externo, dinámico, o no se puede resolver con
      certeza. No adivinar: emitir None es preferible a generar nodos
      fantasma (ver memory/feedback_resolve_identity.md).

Notas de diseño:
    - `raw` llega tal como lo capturó el scanner (regex o AST). El resolver
      NO hace limpieza agresiva de caracteres (ese era el bug viejo de
      _resolve_identity que inventaba nombres). Solo normaliza quotes y
      whitespace de borde.
    - NO usar `path_style = raw.replace('.', '/')` — esa trampa interna
      convertía extensiones en paths (ver memory/feedback_path_style_trampa.md).
      La separación por puntos vs. por barras se decide explícitamente por
      lenguaje.
    - Si un submétodo no puede resolver con la información disponible,
      retorna None. El caller (core.py) decide qué hacer con el raw (ej:
      tratarlo como nodo externo con el label crudo).

SEM-020 — Semantic Loader Resolution:
    - El resolver ahora acepta un `config` opcional con dos secciones:
      `path_functions` (función → template de path) y `loader_calls`
      (función → { arg, ext_default, base, ... }).
    - Cuando el raw capturado es una loader_call completa (ej.
      `wp_enqueue_script('main', get_template_directory_uri() . '/js/main.js')`)
      el resolver extrae el argumento configurado y lo evalúa.
    - Las funciones de `path_functions` se evalúan en expresiones tipo
      `fn() . 'literal'` (PHP) o interpolación `"$var/literal"` con
      aliasing (`$dir = get_template_directory_uri()` → capturamos el
      mapping en una pasada previa de "fuzzy eval" sobre los literales).
    - `theme_root` / `plugins_root` son paths absolutos detectados por
      core.py; si no están disponibles, fallback a `project_root`.

INIT-032 — Re-exports en __init__.py:
    - `_resolve_python` parsea `__init__.py` del paquete candidato cuando
      el import es `from pkg import X` (shape `pkg:X`). Si X está
      re-exportado desde un submódulo (`from .sub import X` en __init__),
      devuelve el path de ese submódulo en vez del __init__.
    - Resultado: `from engine import call_with_fallback` produce edge al
      archivo real que define `call_with_fallback` (típicamente
      `engine/api.py` o `engine/tools.py`), no sólo a `engine/__init__.py`
      (que además está en ignore_patterns).
"""

import ast
import os
import re
from pathlib import Path


# Constantes comunes que aparecen en imports PHP relativos al archivo fuente.
_PHP_FILE_CONSTANTS = ("__DIR__", "__FILE__")

# Extensiones que el resolver JS probará al hacer module resolution sin
# extensión explícita (orden = prioridad de búsqueda).
_JS_CANDIDATE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

# Extensiones Python candidatas para resolución.
_PY_CANDIDATE_EXTS = (".py", ".pyi")

# Schemes/atributos que nunca se resuelven contra el repo en HTML.
# `javascript:`/`data:` son código inline, `mailto:`/`tel:` son protocolos
# externos, `#anchor` es navegación intra-página.
_HTML_UNRESOLVABLE_PREFIXES = (
    "mailto:", "tel:", "javascript:", "data:", "sms:", "geo:",
    "file:", "ftp:", "ftps:", "ws:", "wss:",
)

# Extensiones que HTML prueba cuando una ruta no trae extensión explícita.
_HTML_EXTENSIONLESS_EXTS = (".html", ".htm", ".php")

# SEM-020 — sentinel prefix para loader_calls capturadas por el scanner.
# Formato: "@@LOADER@@<fn>@@<raw_call_body>". El scanner emite esto para
# que el resolver sepa que recibió una llamada entera, no un path ya
# limpio. Usamos doble-at para que no colisione con nada en un path real.
LOADER_SENTINEL = "@@LOADER@@"

# SEM-020 — extensiones "conocidas" que NO se auto-extienden con ext_default
# si el argumento ya termina en una de ellas.
_KNOWN_PATH_EXTENSIONS = {
    ".php", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".css", ".scss",
    ".html", ".htm", ".json", ".xml", ".svg", ".png", ".jpg", ".jpeg",
    ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp4", ".webm", ".mp3", ".wav", ".pdf", ".md",
}


def encode_loader_raw(fn_name, call_body):
    """Helper público para el scanner: empaqueta un loader call como sentinel."""
    return f"{LOADER_SENTINEL}{fn_name}{LOADER_SENTINEL}{call_body}"


class PathResolver:
    """Resuelve imports crudos a paths absolutos dentro del proyecto."""

    def __init__(self, project_root, config=None, theme_root=None, plugins_root=None):
        self.project_root = Path(project_root).resolve()
        self.config = config or {}
        # SEM-020 — roots para substitución de tokens en path_functions.
        self._theme_root = Path(theme_root).resolve() if theme_root else self.project_root
        self._plugins_root = (
            Path(plugins_root).resolve() if plugins_root else self.project_root
        )
        # Diccionarios de config SEM-020 (pueden estar vacíos).
        self._path_functions = {
            k: v for k, v in (self.config.get("path_functions") or {}).items()
            if isinstance(k, str) and isinstance(v, str)
        }
        self._loader_calls = {
            k: v for k, v in (self.config.get("loader_calls") or {}).items()
            if isinstance(k, str) and isinstance(v, dict)
        }

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def resolve(self, raw, language, source_file):
        """Devuelve path absoluto (posix) o None.

        Parámetros:
            raw: string crudo extraído del import.
            language: 'php' | 'javascript' | 'typescript' | 'python' | otro.
            source_file: path absoluto del archivo que contiene el import.
        """
        if raw is None:
            return None
        raw_str = str(raw)

        # SEM-020 — loader sentinel? El scanner lo empaquetó; extraemos la
        # llamada completa y evaluamos el argumento configurado.
        if raw_str.startswith(LOADER_SENTINEL):
            src = Path(source_file).resolve() if source_file else None
            return self._resolve_loader_call(raw_str, src)

        cleaned = self._strip_quotes(raw_str)
        if not cleaned:
            return None

        lang = (language or "").lower()
        src = Path(source_file).resolve() if source_file else None

        if lang == "php":
            return self._resolve_php(cleaned, src, raw_original=raw_str)
        if lang in ("javascript", "typescript", "jsx", "tsx"):
            return self._resolve_js(cleaned, src)
        if lang == "python":
            return self._resolve_python(cleaned, src)
        if lang in ("html", "htm"):
            return self._resolve_html(cleaned, src)
        # Lenguaje desconocido: tratamos el raw como path relativo simple
        # sólo si se parece a un path (tiene `/` o empieza con `.`).
        return self._resolve_generic(cleaned, src)

    # ------------------------------------------------------------------
    # PHP
    # ------------------------------------------------------------------
    def _resolve_php(self, raw, source_file, raw_original=None):
        """Resuelve includes/requires PHP.

        Casos que cubre:
            'utils.php'                              → relativo al archivo
            './utils.php', '../lib/x.php'            → relativo al archivo
            '/abs/path/to/x.php'                     → absoluto del FS
            '__DIR__ . "/sub/file.php"'              → dir del archivo + sub
            'PLUGIN_DIR . "includes/loader.php"'     → constante desconocida,
                                                       intenta como relativo
                                                       al project_root.
            SEM-020:
            'get_template_directory_uri() . "/js/x.js"' →
                                                       theme_root + /js/x.js
        Devuelve None si no existe nada matcheante.
        """
        if source_file is None:
            return None

        # SEM-020 — path_functions evaluator: si el raw contiene alguna
        # función conocida + concatenación, evaluar la función y luego
        # resolver el literal concatenado.
        candidate_from_fn = self._evaluate_path_function_expr(
            raw_original if raw_original is not None else raw, source_file, language="php",
        )
        if candidate_from_fn is not None:
            resolved = self._resolve_absolute_path(candidate_from_fn)
            if resolved:
                return resolved

        # Formas compuestas con " . " (concatenación PHP).
        # Recogemos todos los literales string y juntamos lo que suene a path.
        literals = self._extract_string_literals(raw)
        if literals:
            # Si hay un __DIR__ o __FILE__ en la expresión, la base es el dir
            # del archivo fuente. Caso contrario, asumimos project_root como
            # base (probable constante tipo PLUGIN_DIR definida externamente).
            base_is_file_dir = any(tok in raw for tok in _PHP_FILE_CONSTANTS)
            candidate = "".join(literals).lstrip("/\\")
            if base_is_file_dir:
                base = source_file.parent
            else:
                base = self.project_root
            return self._try_resolve(base, candidate, ())

        # Caso simple: el raw ya era un literal (el scanner capturó sin comillas).
        candidate = raw.strip()
        if not candidate:
            return None

        # Absoluto de filesystem (Windows: 'C:/...'; Unix: raro en PHP).
        if os.path.isabs(candidate):
            p = Path(candidate)
            return self._to_posix_if_in_project(p)

        # Leading-slash típico de `__DIR__ . '/sub/file.php'` — el outbound
        # scanner capturó sólo el literal stripeando el `__DIR__`. En PHP
        # esa barra es separador, no raíz del filesystem. Se interpreta
        # primero como source-dir-relative, luego como project-root-relative
        # (PHP-inbound-019).
        probe = candidate.lstrip("/\\") if candidate[:1] in ("/", "\\") else candidate

        # Relativo al archivo fuente primero; si no, project_root.
        for base in (source_file.parent, self.project_root):
            resolved = self._try_resolve(base, probe, ())
            if resolved:
                return resolved
        return None

    # ------------------------------------------------------------------
    # SEM-020 — evaluador de path_functions / loader_calls
    # ------------------------------------------------------------------
    def _evaluate_path_function_expr(self, raw, source_file, language):
        """Intenta resolver una expresión con forma:
            <fn>( [args] ) . 'literal'
            <fn>( [args] ) . "literal"
        donde <fn> está en `path_functions`. También cubre el caso PHP
        interpolado `"$var/literal"` donde `$var` fue asignada a `<fn>()`
        en el MISMO archivo (aliasing simple).

        Devuelve un path absoluto string (posix) o None si no aplica.

        Uso:
            `get_template_directory_uri() . '/js/main.js'`
              → theme_root + '/js/main.js'
            `"$dir/assets/css/tokens.css"` (con `$dir = get_template_directory_uri()`)
              → theme_root + '/assets/css/tokens.css'
        """
        if not raw or not self._path_functions:
            return None
        expr = str(raw)

        # Caso 1: fn() . 'literal'  (concatenación explícita)
        # Regex: <fn>\s*\([^)]*\)\s*\.\s*['"]([^'"]+)['"]
        fn_names = "|".join(re.escape(n) for n in self._path_functions)
        if fn_names:
            pat = re.compile(
                r"(" + fn_names + r")\s*\([^)]*\)\s*\.\s*['\"]([^'\"]+)['\"]"
            )
            m = pat.search(expr)
            if m:
                fn = m.group(1)
                literal = m.group(2)
                base = self._resolve_path_function_token(
                    self._path_functions[fn], source_file,
                )
                if base is not None:
                    return self._join_base_and_literal(base, literal)

        # Caso 2: interpolación PHP tipo "$var/literal" + asignación
        # `$var = fn()` detectada en el mismo archivo.
        if language == "php":
            interp = self._php_interpolation_path(expr, source_file)
            if interp is not None:
                return interp

        return None

    def _php_interpolation_path(self, expr, source_file):
        """Caso 2 de _evaluate_path_function_expr: PHP interpolation.

        Si `expr` contiene `"$varname/…"` y en el archivo fuente hay una
        asignación `$varname = <fn>();` con <fn> en path_functions, expande
        al path correspondiente.
        """
        m = re.search(r'"\$([A-Za-z_][A-Za-z0-9_]*)([^"]*)"', expr)
        if not m:
            # Probar sintaxis con llaves: "{$var}/…"
            m = re.search(r'"\{?\$([A-Za-z_][A-Za-z0-9_]*)\}?([^"]*)"', expr)
        if not m:
            return None
        var_name = m.group(1)
        tail = m.group(2) or ""
        # Buscar asignación en el archivo fuente.
        if not source_file or not source_file.is_file():
            return None
        try:
            with open(source_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            return None
        fn_names = "|".join(re.escape(n) for n in self._path_functions)
        if not fn_names:
            return None
        assign_pat = re.compile(
            r"\$" + re.escape(var_name) + r"\s*=\s*(" + fn_names + r")\s*\("
        )
        am = assign_pat.search(content)
        if not am:
            return None
        fn = am.group(1)
        base = self._resolve_path_function_token(
            self._path_functions[fn], source_file,
        )
        if base is None:
            return None
        # tail puede venir con leading "/" o sin.
        literal = tail.strip()
        if not literal:
            return None
        return self._join_base_and_literal(base, literal)

    def _resolve_path_function_token(self, template, source_file):
        """Reemplaza tokens en el template y devuelve un path absoluto Path.

        Tokens soportados: {theme_root}, {plugins_root}, {source_dir}.
        """
        if template is None:
            return None
        s = str(template)
        replacements = {
            "{theme_root}": str(self._theme_root),
            "{plugins_root}": str(self._plugins_root),
            "{source_dir}": str(source_file.parent) if source_file else str(self.project_root),
        }
        for tok, val in replacements.items():
            s = s.replace(tok, val)
        # Si no quedó absoluto, interpretarlo como relativo a project_root.
        p = Path(s)
        if not p.is_absolute():
            p = self.project_root / s
        return p

    @staticmethod
    def _join_base_and_literal(base, literal):
        """Concatena base (Path) con literal (string) respetando leading '/'."""
        lit = literal.lstrip("/\\")
        return (Path(base) / lit).as_posix()

    def _resolve_absolute_path(self, candidate):
        """Verifica si `candidate` (str path absoluto o posix) existe y está
        dentro del proyecto. Devuelve posix string o None.

        Intenta:
          1. El path tal cual (con extensión si la trae).
          2. Mismo path + extensión conocida si no tiene.
        """
        if not candidate:
            return None
        p = Path(candidate)
        if p.is_file():
            return self._to_posix_if_in_project(p)
        # Sin extensión → probar .php/.js/.css comunes (el ext_default
        # puede venir del loader_calls; este método solo se usa como
        # fallback cuando el raw NO especifica extensión).
        if "." not in p.name:
            for ext in (".php", ".js", ".css"):
                q = Path(str(p) + ext)
                if q.is_file():
                    return self._to_posix_if_in_project(q)
        return None

    def _resolve_loader_call(self, sentinel_raw, source_file):
        """Procesa un raw empaquetado por el scanner como loader_call.

        Formato: `@@LOADER@@<fn>@@<call_body>` — `call_body` es el contenido
        completo entre paréntesis (posiblemente multi-arg, con comillas,
        concatenaciones, etc.). Extraemos el argumento `arg` según config
        y lo resolvemos.
        """
        if not sentinel_raw.startswith(LOADER_SENTINEL):
            return None
        payload = sentinel_raw[len(LOADER_SENTINEL):]
        if LOADER_SENTINEL not in payload:
            return None
        fn_name, _, body = payload.partition(LOADER_SENTINEL)
        spec = self._loader_calls.get(fn_name)
        if not spec:
            return None
        arg_index = int(spec.get("arg", 1))
        ext_default = spec.get("ext_default")
        base_tok = spec.get("base")  # Opcional: fuerza base (ej. {theme_root}).

        # Extraer argumento `arg_index` (1-based) del call body.
        arg_expr = self._split_call_args(body, arg_index)
        if arg_expr is None:
            return None
        arg_expr = arg_expr.strip()

        # Language por default es PHP (único stack con loader_calls hoy);
        # las mantenemos en config con `language: "php"` por si algún día
        # se agregan JS/TS.
        lang = (spec.get("language") or "php").lower()

        # 1. Intentar evaluar path_functions sobre el arg (cubre
        #    `get_template_directory_uri() . '/js/main.js'`).
        resolved_from_fn = self._evaluate_path_function_expr(
            arg_expr, source_file, language=lang,
        )
        if resolved_from_fn:
            p = self._resolve_absolute_path(
                self._maybe_append_ext(resolved_from_fn, ext_default)
            )
            if p:
                return p

        # 2. Si el arg es un literal string puro → usar base configurada o
        #    interpretar según idioma.
        literal = self._strip_quotes(arg_expr)
        if literal and literal == arg_expr.strip().strip("'\"`").strip():
            # (arg era un literal puro sin operaciones)
            candidate = self._maybe_append_ext(literal, ext_default)
            # base explícita en config (get_template_part → {theme_root}).
            if base_tok:
                base_path = self._resolve_path_function_token(base_tok, source_file)
                if base_path is not None:
                    full = self._join_base_and_literal(base_path, candidate)
                    resolved = self._resolve_absolute_path(full)
                    if resolved:
                        return resolved
            # Fallback: resolver por lenguaje normal.
            if lang == "php":
                return self._resolve_php(candidate, source_file, raw_original=candidate)
            if lang in ("javascript", "typescript"):
                return self._resolve_js(candidate, source_file)
            return self._resolve_generic(candidate, source_file)

        # 3. Último recurso: extraer primer literal de la expresión + base.
        literals = self._extract_string_literals(arg_expr)
        if literals:
            joined = "".join(literals)
            candidate = self._maybe_append_ext(joined, ext_default)
            if base_tok:
                base_path = self._resolve_path_function_token(base_tok, source_file)
                if base_path is not None:
                    full = self._join_base_and_literal(base_path, candidate)
                    resolved = self._resolve_absolute_path(full)
                    if resolved:
                        return resolved
            # Fallback PHP-like (__DIR__ concat): relativo al archivo.
            return self._resolve_php(
                candidate, source_file, raw_original=arg_expr,
            )
        return None

    @staticmethod
    def _maybe_append_ext(path_str, ext_default):
        """Agrega `ext_default` si `path_str` no termina en extensión conocida.

        Devuelve string. Si `ext_default` es falsy, devuelve path_str tal cual.
        """
        if not ext_default or not path_str:
            return path_str
        low = path_str.lower()
        for ext in _KNOWN_PATH_EXTENSIONS:
            if low.endswith(ext):
                return path_str
        # Strip query/fragment antes de añadir.
        return path_str + ext_default

    @staticmethod
    def _split_call_args(body, arg_index):
        """Divide el cuerpo de la llamada en argumentos respetando quotes y
        paréntesis anidados. Devuelve el argumento 1-based o None si no hay
        suficientes.

        No es un parser completo — suficiente para los patterns que nos
        interesan (loader calls con 1-4 args, strings simples o con .concat).
        """
        if not body:
            return None
        args = []
        depth = 0
        current = []
        in_str = None  # char de quote activo, o None
        escape = False
        for ch in body:
            if escape:
                current.append(ch)
                escape = False
                continue
            if in_str:
                current.append(ch)
                if ch == "\\":
                    escape = True
                elif ch == in_str:
                    in_str = None
                continue
            if ch in ("'", '"', "`"):
                in_str = ch
                current.append(ch)
                continue
            if ch in "([{":
                depth += 1
                current.append(ch)
                continue
            if ch in ")]}":
                depth -= 1
                current.append(ch)
                continue
            if ch == "," and depth == 0:
                args.append("".join(current))
                current = []
                continue
            current.append(ch)
        if current:
            args.append("".join(current))
        if 1 <= arg_index <= len(args):
            return args[arg_index - 1]
        return None

    # ------------------------------------------------------------------
    # JavaScript / TypeScript
    # ------------------------------------------------------------------
    def _resolve_js(self, raw, source_file):
        """Resuelve imports/requires JS/TS + URLs de `fetch()`.

        Casos cubiertos:
            './utils', '../foo/bar'   → relativo al archivo, prueba
                                        extensiones y index.{js,ts,...}
            '/api/x.php'              → leading-slash → project-root-relative
                                        (URL semántica del browser, no FS)
            './api/x.php' que no
            resuelve file-relative    → fallback project-root-relative
                                        (FIX-026: fetch() en JS usa URL
                                        semantics, no Node module resolution)
            'C:/abs/path'             → absoluto del FS
            'react', 'lodash'         → bare specifier → None (externo)
            '@scope/pkg'              → bare scoped   → None (externo)
            '@/components/foo'        → alias común (Next/Vite). No podemos
                                        resolver sin config del bundler:
                                        intentamos como si `@` == raíz del
                                        proyecto; si no resuelve → None.
        """
        if source_file is None:
            return None

        # Alias '@/...': intentar como project_root-relative.
        if raw.startswith("@/"):
            candidate = raw[2:]
            return self._try_resolve(
                self.project_root, candidate, _JS_CANDIDATE_EXTS,
                try_index=True,
            )

        # Bare specifier (paquete npm, scoped o no): externo.
        if not (raw.startswith(".") or raw.startswith("/") or raw.startswith("\\")):
            return None

        # Windows absoluto real (ej: 'C:/...', 'D:\\...').
        if re.match(r"^[A-Za-z]:[\\/]", raw):
            p = Path(raw)
            if p.exists():
                return self._to_posix_if_in_project(p)
            return None

        # Leading-slash (`/api/x.php`) → root-relative del proyecto.
        # FIX-026: Los `fetch('/api/x.php')` en JS son URLs relativas al
        # root del sitio web, no paths de filesystem. Se interpretan como
        # project-root-relative (cross-platform), no como FS absolutos.
        if raw.startswith("/") and not raw.startswith("//"):
            candidate = raw.lstrip("/\\")
            resolved = self._try_resolve(
                self.project_root, candidate, _JS_CANDIDATE_EXTS,
                try_index=True,
            )
            if resolved:
                return resolved
            return None

        # Relativo al archivo fuente (Node.js module resolution clásica).
        resolved = self._try_resolve(
            source_file.parent, raw, _JS_CANDIDATE_EXTS, try_index=True,
        )
        if resolved:
            return resolved

        # FIX-026: Fallback project-root-relative para `fetch('./api/x.php')`.
        # En JS web, `./` dentro de un fetch() es URL-relative a la página,
        # no al archivo JS. Si el resolve file-relative falla, intentar
        # project_root como base — típico para endpoints en `<root>/api/`
        # llamados desde `<root>/js/admin.js`.
        if raw.startswith("./") or raw.startswith("../"):
            # Colapsar secuencias iniciales de './' y '../' para probar
            # root-relative (la URL base real la fija el browser según la
            # página, no el archivo JS — mejor heurística disponible).
            candidate = raw
            while candidate.startswith("./") or candidate.startswith("../"):
                candidate = candidate[2:] if candidate.startswith("./") else candidate[3:]
            if candidate:
                return self._try_resolve(
                    self.project_root, candidate, _JS_CANDIDATE_EXTS,
                    try_index=True,
                )
        return None

    # ------------------------------------------------------------------
    # Python
    # ------------------------------------------------------------------
    def _resolve_python(self, raw, source_file):
        """Resuelve imports Python.

        El scanner Python (stdlib ast) normaliza los imports a una de estas
        formas:
            'pkg.sub.mod'            → import pkg.sub.mod
            'pkg.sub:name'           → from pkg.sub import name
            '.relmod'                → from . import relmod
            '..pkg:name'             → from ..pkg import name
            '.:name'                 → from . import name

        El resolver interpreta el prefijo de puntos como niveles relativos.

        INIT-032 — Si el import es `from pkg import name` (shape `pkg:name`)
        y `pkg` resuelve a un paquete con __init__.py, parseamos el __init__
        buscando re-exports de `name` (ej. `from .sub import name`, `from
        .sub import *` con `name` presente). Si existe, devolvemos el path
        del submódulo real.
        """
        if source_file is None:
            return None

        # Separar nombre importado (después de ':') del path del módulo.
        module_part, _, imported_name = raw.partition(":")
        module_part = module_part.strip()
        imported_name = imported_name.strip()
        if not module_part:
            return None

        # Contar leading dots para niveles relativos.
        dots = 0
        for ch in module_part:
            if ch == ".":
                dots += 1
            else:
                break
        dotted = module_part[dots:]

        if dots > 0:
            # Relativo: subir (dots - 1) niveles desde el paquete del archivo.
            base = source_file.parent
            for _ in range(dots - 1):
                base = base.parent
            parts = dotted.split(".") if dotted else []
        else:
            base = self.project_root
            parts = dotted.split(".") if dotted else []

        if not parts:
            # `from . import foo` sin nombre de módulo → apunta al __init__
            # del paquete. Como skippeamos __init__.py por ignore_patterns,
            # devolvemos el directorio mismo → no existe como archivo.
            return None

        candidate_rel = "/".join(parts)

        # INIT-032 — CASO A: from <pkg> import <name>.
        #   Si `parts` resuelve a un paquete (tiene __init__.py) y
        #   `imported_name` está presente, intentar resolver el re-export
        #   antes de devolver el __init__ mismo.
        if imported_name:
            init_path = (base / candidate_rel / "__init__.py").resolve()
            if init_path.is_file() and self._is_inside_project(init_path):
                reexport = self._trace_reexport(init_path, imported_name)
                if reexport:
                    return reexport
                # Si no hay re-export, intentar como submódulo directo:
                # `from pkg import name` → pkg/name.py.
                for ext in _PY_CANDIDATE_EXTS:
                    sub = (base / candidate_rel / (imported_name + ext)).resolve()
                    if sub.is_file() and self._is_inside_project(sub):
                        return sub.as_posix()
                # Fallback al __init__.
                return init_path.as_posix()
            # Caso B: `from pkg.sub import name` donde pkg.sub es módulo
            # (archivo pkg/sub.py). Intentar archivo directo con
            # imported_name como símbolo — no cambia resolve target.

        # Probar archivo directo con extensiones .py/.pyi
        for ext in _PY_CANDIDATE_EXTS:
            p = (base / (candidate_rel + ext)).resolve()
            if p.is_file() and self._is_inside_project(p):
                return p.as_posix()
        # Probar paquete: parts[-1]/__init__.py
        init_path = (base / candidate_rel / "__init__.py").resolve()
        if init_path.is_file() and self._is_inside_project(init_path):
            return init_path.as_posix()
        return None

    def _trace_reexport(self, init_py_path, name):
        """INIT-032 — Parsea `init_py_path` con ast y busca si `name` está
        re-exportado desde un submódulo. Devuelve el path posix del submódulo
        fuente o None.

        Reglas:
          - `from .sub import name` → name viene de `<dir>/sub.py`.
          - `from .sub import name as alias` → si alias == name, match.
          - `from .sub import *` → no podemos saber sin parsear sub.py;
            heurística: si `sub.py` define `name`, devolver su path. Ojo:
            solo inspeccionamos top-level def/class para el * case.
          - `from . import sub` → no es un re-export del símbolo.
        """
        try:
            with open(init_py_path, "r", encoding="utf-8", errors="ignore") as f:
                src = f.read()
            tree = ast.parse(src)
        except (OSError, SyntaxError, ValueError):
            return None

        pkg_dir = init_py_path.parent

        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            # Solo re-exports relativos (level>=1) desde dentro del paquete.
            level = node.level or 0
            if level < 1:
                continue
            sub_mod = node.module or ""
            if not sub_mod:
                # `from . import name` — apunta a un submódulo con el nombre.
                # Si alguna alias matchea `name`, resolver al archivo name.py.
                for alias in node.names:
                    target_name = alias.asname or alias.name
                    if target_name == name:
                        candidate = (pkg_dir / (alias.name + ".py")).resolve()
                        if candidate.is_file() and self._is_inside_project(candidate):
                            return candidate.as_posix()
                continue
            # `from .sub import X` / `from .sub import X as Y` / `from .sub import *`
            # Resolver el submódulo relativo.
            base = pkg_dir
            for _ in range(level - 1):
                base = base.parent
            sub_parts = sub_mod.split(".")
            sub_candidate = (base.joinpath(*sub_parts)).resolve()
            sub_py = Path(str(sub_candidate) + ".py")
            if not (sub_py.is_file() and self._is_inside_project(sub_py)):
                # Probar paquete anidado:
                sub_init = (sub_candidate / "__init__.py").resolve()
                if sub_init.is_file() and self._is_inside_project(sub_init):
                    sub_py = sub_init
                else:
                    continue
            # ¿Nombre importado match?
            for alias in node.names:
                if alias.name == "*":
                    # Verificar que `name` esté definido en el submódulo.
                    if self._symbol_defined_in(sub_py, name):
                        return sub_py.as_posix()
                    continue
                target_name = alias.asname or alias.name
                if target_name == name:
                    return sub_py.as_posix()
        return None

    @staticmethod
    def _symbol_defined_in(py_path, name):
        """True si el archivo .py tiene top-level def/class/assign de `name`."""
        try:
            with open(py_path, "r", encoding="utf-8", errors="ignore") as f:
                src = f.read()
            tree = ast.parse(src)
        except (OSError, SyntaxError, ValueError):
            return False
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == name:
                    return True
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == name:
                        return True
        return False

    # ------------------------------------------------------------------
    # HTML (HTML-019)
    # ------------------------------------------------------------------
    def _resolve_html(self, raw, source_file):
        """Resuelve referencias de atributos HTML (src/href/action).

        Casos cubiertos:
            'assets/css/main.css'        → relativo al archivo fuente
            './img/logo.png'             → relativo al archivo fuente
            '/assets/js/app.js'          → root-relative (project_root)
            'sedes' (sin extensión)      → prueba sedes.html, sedes/index.html
            'contacto.html'              → resolve directo
            'foo.js?v=1' / 'foo.js#x'    → stripea query/fragment antes
            '#anchor'                    → None (intra-page nav)
            'mailto:…', 'tel:…', 'javascript:…' → None
            'http://…', 'https://…', '//cdn.…' → raw crudo (external)
              · el caller (GRF-021) lo clasifica: external declarado o descarte.

        Devuelve:
            - path posix absoluto dentro del proyecto, o
            - el URL crudo si es absoluto (http/https/protocol-relative),
              para que GRF-021 clasifique, o
            - None si es intra-page o scheme no-resoluble.
        """
        if source_file is None:
            return None

        # 1. Strip whitespace + strip fragment + strip query.
        candidate = raw.strip()
        if not candidate:
            return None

        # 2. Schemes que nunca se resuelven.
        lower = candidate.lower()
        for prefix in _HTML_UNRESOLVABLE_PREFIXES:
            if lower.startswith(prefix):
                return None

        # 3. Fragment-only → navegación dentro de la página, sin edge.
        if candidate.startswith("#"):
            return None

        # 4. URLs absolutas/protocol-relative → devolvemos None. No son archivos
        #    del repo. El caller (GRF-021 / _classify_outbound) examina el raw
        #    original para decidir si son external services o descarte.
        if (
            candidate.startswith("http://")
            or candidate.startswith("https://")
            or candidate.startswith("//")
        ):
            return None

        # 5. Stripear query y fragment (`foo.js?v=1#x` → `foo.js`).
        for sep in ("?", "#"):
            idx = candidate.find(sep)
            if idx >= 0:
                candidate = candidate[:idx]
        candidate = candidate.strip()
        if not candidate:
            return None

        # 6. Ruta normal. Determinar base según root-relative vs. file-relative.
        if candidate.startswith("/") or candidate.startswith("\\"):
            base = self.project_root
            rel = candidate.lstrip("/\\")
        else:
            base = source_file.parent
            rel = candidate
        if not rel:
            return None

        # 7. Intento 1: path con extensión tal cual.
        target = (base / rel).resolve()
        if target.is_file():
            return self._to_posix_if_in_project(target)

        # 8. Sin extensión reconocida → probar .html/.htm/.php e index.*
        has_known_ext = any(
            rel.lower().endswith(ext) for ext in _HTML_EXTENSIONLESS_EXTS
        ) or "." in rel.rsplit("/", 1)[-1]

        if not has_known_ext:
            for ext in _HTML_EXTENSIONLESS_EXTS:
                candidate_path = (base / (rel + ext)).resolve()
                if candidate_path.is_file():
                    return self._to_posix_if_in_project(candidate_path)
            # Directorio con index.html/.htm/.php
            for ext in _HTML_EXTENSIONLESS_EXTS:
                candidate_path = (base / rel / ("index" + ext)).resolve()
                if candidate_path.is_file():
                    return self._to_posix_if_in_project(candidate_path)

        # 9. Último recurso: si `rel` apunta a un directorio existente, probar
        #    index.html/.php dentro aunque tuviera extensión.
        if target.is_dir():
            for ext in _HTML_EXTENSIONLESS_EXTS:
                candidate_path = target / ("index" + ext)
                if candidate_path.is_file():
                    return self._to_posix_if_in_project(candidate_path)

        return None

    # ------------------------------------------------------------------
    # Generic (lenguajes sin resolver dedicado)
    # ------------------------------------------------------------------
    def _resolve_generic(self, raw, source_file):
        """Último recurso: si parece path relativo, intenta resolverlo."""
        if source_file is None:
            return None
        looks_like_path = raw.startswith(".") or "/" in raw or "\\" in raw
        if not looks_like_path:
            return None
        for base in (source_file.parent, self.project_root):
            resolved = self._try_resolve(base, raw, ())
            if resolved:
                return resolved
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _try_resolve(self, base, candidate, extensions, try_index=False):
        """Intenta resolver `candidate` respecto a `base`.

        Orden:
            1. base/candidate exacto si es archivo.
            2. base/candidate + cada extensión.
            3. si `try_index`: base/candidate/index.{ext}.

        Devuelve path posix absoluto o None.
        """
        if not candidate:
            return None
        target = (base / candidate).resolve()
        if target.is_file():
            return self._to_posix_if_in_project(target)
        for ext in extensions:
            attempt = target.with_suffix(target.suffix + ext) if target.suffix else Path(str(target) + ext)
            if attempt.is_file():
                return self._to_posix_if_in_project(attempt)
        if try_index:
            for ext in extensions:
                attempt = target / ("index" + ext)
                if attempt.is_file():
                    return self._to_posix_if_in_project(attempt)
        return None

    def _to_posix_if_in_project(self, path):
        if self._is_inside_project(path):
            return path.as_posix()
        return None

    def _is_inside_project(self, path):
        try:
            path.resolve().relative_to(self.project_root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _strip_quotes(raw):
        s = raw.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"', "`"):
            return s[1:-1].strip()
        return s

    @staticmethod
    def _extract_string_literals(expr):
        """Extrae literales entre comillas simples/dobles de una expresión.

        'PLUGIN_DIR . "includes/" . "file.php"' → ['includes/', 'file.php']
        '__DIR__ . "/sub/x.php"'                → ['/sub/x.php']
        Devuelve lista vacía si no hay literales o si ya venía sin comillas.
        """
        matches = re.findall(r"'([^']*)'|\"([^\"]*)\"", expr)
        return [g1 or g2 for g1, g2 in matches]
