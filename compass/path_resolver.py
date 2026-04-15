"""Path resolver — RES-002.

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
"""

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


class PathResolver:
    """Resuelve imports crudos a paths absolutos dentro del proyecto."""

    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()

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
        cleaned = self._strip_quotes(str(raw))
        if not cleaned:
            return None

        lang = (language or "").lower()
        src = Path(source_file).resolve() if source_file else None

        if lang == "php":
            return self._resolve_php(cleaned, src)
        if lang in ("javascript", "typescript", "jsx", "tsx"):
            return self._resolve_js(cleaned, src)
        if lang == "python":
            return self._resolve_python(cleaned, src)
        # Lenguaje desconocido: tratamos el raw como path relativo simple
        # sólo si se parece a un path (tiene `/` o empieza con `.`).
        return self._resolve_generic(cleaned, src)

    # ------------------------------------------------------------------
    # PHP
    # ------------------------------------------------------------------
    def _resolve_php(self, raw, source_file):
        """Resuelve includes/requires PHP.

        Casos que cubre:
            'utils.php'                              → relativo al archivo
            './utils.php', '../lib/x.php'            → relativo al archivo
            '/abs/path/to/x.php'                     → absoluto del FS
            '__DIR__ . "/sub/file.php"'              → dir del archivo + sub
            'PLUGIN_DIR . "includes/loader.php"'     → constante desconocida,
                                                       intenta como relativo
                                                       al project_root.
        Devuelve None si no existe nada matcheante.
        """
        if source_file is None:
            return None

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

        # Absoluto de filesystem.
        if os.path.isabs(candidate):
            p = Path(candidate)
            return self._to_posix_if_in_project(p)

        # Relativo al archivo fuente primero; si no, project_root.
        for base in (source_file.parent, self.project_root):
            resolved = self._try_resolve(base, candidate, ())
            if resolved:
                return resolved
        return None

    # ------------------------------------------------------------------
    # JavaScript / TypeScript
    # ------------------------------------------------------------------
    def _resolve_js(self, raw, source_file):
        """Resuelve imports/requires JS/TS.

        Casos cubiertos:
            './utils', '../foo/bar'   → relativo al archivo, prueba
                                        extensiones y index.{js,ts,...}
            '/abs/path'               → absoluto del FS
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

        # Absoluto.
        if os.path.isabs(raw):
            p = Path(raw)
            if p.exists():
                return self._to_posix_if_in_project(p)
            return None

        # Relativo al archivo fuente.
        return self._try_resolve(
            source_file.parent, raw, _JS_CANDIDATE_EXTS, try_index=True,
        )

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
        """
        if source_file is None:
            return None

        # Separar nombre importado (después de ':') del path del módulo.
        module_part, _, _imported_name = raw.partition(":")
        module_part = module_part.strip()
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