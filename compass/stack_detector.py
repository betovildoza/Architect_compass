"""Stack detection — STK-001 + MST-006.

Detecta el stack del proyecto auditado usando una jerarquía determinista:

    1. Lock files        (composer.json, package.json, requirements.txt, ...)
    2. Framework markers (wp-config.php, functions.php, next.config.js, ...)
    3. Content markers   (substrings dentro de archivos, ej: "Plugin Name:")
    4. Extension majority (desempate cuando nada de lo anterior resuelve)

Config: consume `stack_markers` de `mapper_config.json` (schema v2, CFG-005).
Cada entrada declara listas opcionales de `lock_files`, `framework_markers`,
`content_markers` y `extensions`. El campo `extensions` (STK-001b) se usa
sólo en la capa de desempate por extensión-mayoritaria: a cada extensión
encontrada en el árbol se le asigna el primer stack del config que la
declare, y se elige el stack con más ocurrencias.

MST-006 — Multi-stack detection:
    `detect(project_root)` devuelve un `StackMap: dict[str, str]` que mapea
    subdirectorios (posix, relativos a la raíz; `""` = raíz) al stack
    detectado en ese subárbol. La raíz siempre tiene entrada (fallback a
    `"Generic"` si nada matchea). Solo se agregan subdirectorios cuyo stack
    local difiere del heredado por longest-prefix match — así el StackMap
    no se infla con entradas redundantes.

El consumidor (core.py::analyze) resuelve el stack por archivo usando
`resolve_file_stack(rel_path, stack_map)` — longest-prefix match sobre las
claves del StackMap.
"""

import os
import fnmatch
from collections import Counter
from pathlib import Path


# Cuántos bytes del archivo leer como máximo al buscar content_markers.
# Los markers reales (ej: "Plugin Name:") viven en el header; evitamos
# leer 10 MB sólo para detectar stack.
_CONTENT_SCAN_MAX_BYTES = 8192

# Extensiones que NO se escanean por content_markers.
# Los archivos de config (JSON/YAML) suelen *declarar* los markers como
# strings — escanearlos provoca falsos positivos (ej: mapper_config.json
# contiene la string "Plugin Name:" como dato, no como marker real).
# Los content_markers viven en código fuente, no en config.
_CONTENT_SCAN_SKIP_EXTENSIONS = {
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".md", ".txt", ".log",
}


class StackDetector:
    """Detector determinista de stacks por subárbol.

    Parámetros:
        stack_markers: dict {stack_name: {lock_files, framework_markers,
            content_markers}} — viene de config["stack_markers"].
        ignore_folders: set de nombres de carpetas a saltear durante el walk.
        text_extensions: iterable de extensiones a considerar para el conteo
            de extension-majority y para leer content_markers.
    """

    def __init__(self, stack_markers, ignore_folders=None, text_extensions=None):
        self.stack_markers = stack_markers or {}
        self.ignore_folders = set(ignore_folders or [])
        self.text_extensions = set(text_extensions or [])
        self._extension_hints = self._build_extension_hints(self.stack_markers)

    @staticmethod
    def _build_extension_hints(stack_markers):
        """Invierte `stack_markers[*].extensions` a `{ext: stack_name}`.

        STK-001b: el mapping extensión → stack vive en config. Se preserva
        el orden de declaración de `stack_markers` — si dos stacks
        declaran la misma extensión (ej: Modern-Web-Stack y JavaScript
        ambos reclamando `.js`), gana el primero en aparecer. Dicts en
        Python 3.7+ preservan orden de inserción, así que el orden del
        JSON manda.
        """
        hints = {}
        for stack_name, markers in stack_markers.items():
            if not isinstance(markers, dict):
                continue
            for ext in markers.get("extensions", []) or []:
                if not isinstance(ext, str):
                    continue
                ext_norm = ext.lower()
                if not ext_norm.startswith("."):
                    ext_norm = "." + ext_norm
                hints.setdefault(ext_norm, stack_name)
        return hints

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def detect(self, project_root):
        """Devuelve el StackMap para `project_root`.

        Claves posix relativas a la raíz (`""` = raíz). Valores = stack name.
        La raíz siempre está presente. Los subdirectorios sólo aparecen si
        su stack difiere del heredado por prefix match.
        """
        project_root = Path(project_root)

        # 1. Detectar stack de la raíz.
        root_stack = self._detect_directory(project_root, project_root)
        if root_stack is None:
            root_stack = self._detect_by_extension_majority(project_root)
        if root_stack is None:
            root_stack = "Generic"

        stack_map = {"": root_stack}

        # 2. Barrer subdirectorios buscando stacks distintos al heredado.
        # Los subdirectorios requieren señal fuerte (lock o framework marker);
        # content markers y extension-majority NO se aplican — evitan ruido.
        for subdir in self._walk_directories(project_root):
            rel = subdir.relative_to(project_root).as_posix()
            if rel == ".":
                continue

            local_stack = self._detect_directory(
                subdir, project_root, allow_content=False
            )
            if local_stack is None:
                continue

            inherited = resolve_file_stack(rel, stack_map)
            if local_stack != inherited:
                stack_map[rel] = local_stack

        return stack_map

    # ------------------------------------------------------------------
    # Detección por directorio (una capa por método — inspeccionable)
    # ------------------------------------------------------------------
    def _detect_directory(self, directory, project_root, allow_content=True):
        """Aplica lock → framework → content. Devuelve stack name o None.

        `allow_content=False` para subdirectorios: los content_markers son
        señal débil (propensa a falsos positivos por substring match en
        docstrings / comentarios) — sólo se usan en la raíz, cuando lock +
        framework ya fallaron. Los subdirectorios deben demostrar un stack
        propio con señal fuerte (lock file o framework marker explícito).
        """
        stack = self._match_by_lock_files(directory)
        if stack:
            return stack
        stack = self._match_by_framework_markers(directory)
        if stack:
            return stack
        if allow_content:
            stack = self._match_by_content_markers(directory)
            if stack:
                return stack
        return None

    def _match_by_lock_files(self, directory):
        """Capa 1: archivo de lock presente en `directory` (no recursivo)."""
        files_in_dir = self._list_files(directory)
        for stack_name, markers in self.stack_markers.items():
            for lock in markers.get("lock_files", []):
                if self._file_present(lock, files_in_dir, directory):
                    return stack_name
        return None

    def _match_by_framework_markers(self, directory):
        """Capa 2: archivo canónico del framework presente en `directory`."""
        files_in_dir = self._list_files(directory)
        for stack_name, markers in self.stack_markers.items():
            for fm in markers.get("framework_markers", []):
                if self._file_present(fm, files_in_dir, directory):
                    return stack_name
        return None

    def _match_by_content_markers(self, directory):
        """Capa 3: substring matcheado en cualquier archivo directo de `directory`."""
        files_in_dir = self._list_files(directory)
        if not files_in_dir:
            return None

        # Filtrar por extensiones de texto para no abrir binarios, y excluir
        # archivos de config/documentación donde los markers podrían aparecer
        # como *datos* (ej: mapper_config.json declara "Plugin Name:" como
        # marker — no debe auto-detectarse como WordPress).
        candidates = []
        for f in files_in_dir:
            ext = os.path.splitext(f)[1].lower()
            if ext in _CONTENT_SCAN_SKIP_EXTENSIONS:
                continue
            if self.text_extensions and ext and ext not in self.text_extensions:
                continue
            candidates.append(directory / f)
        if not candidates:
            return None

        for stack_name, markers in self.stack_markers.items():
            content_markers = markers.get("content_markers", [])
            if not content_markers:
                continue
            for file_path in candidates:
                if self._file_contains_any(file_path, content_markers):
                    return stack_name
        return None

    def _detect_by_extension_majority(self, project_root):
        """Capa 4: extensión dominante en el árbol → stack hint.

        Sólo se usa para la raíz cuando ninguna otra capa resolvió. Los
        subdirectorios no usan este fallback para evitar inflar el StackMap.
        """
        counter = Counter()
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if d not in self.ignore_folders]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if not ext:
                    continue
                if self.text_extensions and ext not in self.text_extensions:
                    continue
                counter[ext] += 1

        for ext, _count in counter.most_common():
            hint = self._extension_hints.get(ext)
            if hint:
                return hint
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _walk_directories(self, project_root):
        """Itera todos los subdirectorios respetando `ignore_folders`."""
        for root, dirs, _files in os.walk(project_root):
            dirs[:] = [d for d in dirs if d not in self.ignore_folders]
            for d in dirs:
                yield Path(root) / d

    @staticmethod
    def _list_files(directory):
        try:
            return [
                name for name in os.listdir(directory)
                if (directory / name).is_file()
            ]
        except (OSError, PermissionError):
            return []

    @staticmethod
    def _file_present(marker, files_in_dir, directory):
        """True si `marker` está en `directory`.

        El marker puede ser:
          - un nombre simple (composer.json) → match exacto contra basename.
          - un path relativo (src-tauri/src/main.rs) → resolvemos desde
            `directory` y chequeamos existencia.
          - un glob simple (*.lock) → fnmatch contra basenames.
        """
        if "/" in marker or "\\" in marker:
            return (directory / marker).exists()
        if any(ch in marker for ch in "*?["):
            return any(fnmatch.fnmatch(f, marker) for f in files_in_dir)
        return marker in files_in_dir

    @staticmethod
    def _file_contains_any(file_path, needles):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(_CONTENT_SCAN_MAX_BYTES)
        except (OSError, PermissionError):
            return False
        return any(needle in head for needle in needles)


# ----------------------------------------------------------------------
# Resolución por archivo — longest-prefix match
# ----------------------------------------------------------------------
def resolve_file_stack(rel_path, stack_map):
    """Devuelve el stack aplicable a `rel_path` según `stack_map`.

    Longest-prefix match sobre las claves del map (directorios posix). La
    raíz (`""`) siempre existe como fallback. El caller garantiza que
    `rel_path` esté en posix, relativo al project_root.
    """
    if not stack_map:
        return "Generic"

    rel_path = rel_path.replace("\\", "/").lstrip("./")
    best_key = ""
    best_len = -1
    for key in stack_map:
        if key == "":
            continue
        # key = "admin", rel_path = "admin/foo.php" → match
        # key = "admin", rel_path = "administrative/x.php" → NO match
        if rel_path == key or rel_path.startswith(key + "/"):
            if len(key) > best_len:
                best_key = key
                best_len = len(key)
    return stack_map.get(best_key, stack_map.get("", "Generic"))