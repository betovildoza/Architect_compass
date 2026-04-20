"""
WordPress Template Hierarchy Auto-detect (RES-003).

Detecta WordPress theme roots (buscando recursivamente markers del theme:
style.css + functions.php/index.php en la misma carpeta) y marca archivos
que matchean la WP template hierarchy dentro de ese theme como entry points.

Diseño:
- Un "theme root" es una carpeta con `style.css` + (`functions.php` | `index.php`).
  Ese es el criterio canónico de WP (no solo `style.css`, que cualquier sitio
  puede tener; no solo `wp-config.php`, que vive en la raíz del install WP).
- La búsqueda es recursiva pero limitada (MAX_SCAN_DEPTH) para no recorrer
  repos enormes. Cubre proyectos donde el tema WP convive con otras cosas
  (caso ETCA: sitio estático + API PHP + tema en themes/etca-aula/).
- `is_wp_template(rel_path, theme_roots)` valida que el archivo esté DENTRO
  de algún theme root (no solo que su basename matchee). Evita falsos
  positivos tipo `api/legacy/index.php`.
- Se mantienen `detect_wordpress_project()` y `mark_wp_templates_as_entry_points()`
  por compatibilidad, pero el pipeline usa `find_wp_theme_roots()` +
  `is_wp_template(path, roots)` directamente.

Templates auto-cargados por WordPress:
- Exact: index.php, front-page.php, home.php, 404.php, search.php, singular.php,
         comments.php, header.php, footer.php, sidebar.php, attachment.php, page.php
- Glob:  single-*.php, archive-*.php, page-*.php, category-*.php, tag-*.php,
         taxonomy-*.php, author-*.php, date-*.php, template-*.php
"""
import fnmatch
from pathlib import Path


# Markers canónicos de WP (uso solo informativo; la detección real usa
# WP_THEME_MARKERS con criterio compuesto).
WP_MARKERS = {
    "style.css",
    "functions.php",
    "wp-config.php",
    "wp-content",
    "wp-includes",
}

# Theme root = carpeta con style.css + alguno de los companions. style.css
# por sí sola aparece en sitios no-WP; exigir companion da señal robusta.
WP_THEME_STYLE = "style.css"
WP_THEME_COMPANIONS = ("functions.php", "index.php")

# Profundidad máxima de búsqueda al escanear subcarpetas de un proyecto.
# 4 cubre el caso común (themes/mi-theme/, wp-content/themes/mi-theme/) sin
# caminar repos gigantes.
MAX_SCAN_DEPTH = 4

# Carpetas que nunca tiene sentido scannear en busca de theme roots.
_WP_SCAN_IGNORE = {
    ".git", ".svn", ".hg",
    "node_modules", "vendor", "__pycache__",
    ".map", ".claude", "dist", "build", ".next",
    "venv", ".venv",
}

# Basenames exactos auto-cargados por WP.
WP_EXACT_TEMPLATES = {
    "index.php",
    "front-page.php",
    "home.php",
    "404.php",
    "search.php",
    "singular.php",
    "comments.php",
    "header.php",
    "footer.php",
    "sidebar.php",
    "attachment.php",
    "page.php",
}

# Glob patterns de la template hierarchy.
WP_GLOB_PATTERNS = [
    "single-*.php",
    "archive-*.php",
    "page-*.php",
    "category-*.php",
    "tag-*.php",
    "taxonomy-*.php",
    "author-*.php",
    "date-*.php",
    "template-*.php",
]

# WP theme-implicit entry points: archivos que el core de WordPress carga por
# convención cuando el theme está activo, sin que ningún PHP los referencie.
# Son basenames a buscar DENTRO de cada theme root. Si existen, se marcan como
# entry_point con reason `wp_theme_implicit`.
#
# Razón: un scanner estático no puede ver el código de WP que carga estos
# archivos (vive fuera del repo). Sin esta marca quedan como ambiguous/huérfanos
# aparentes pese a ser parte funcional del theme.
WP_THEME_IMPLICIT_FILES = (
    "style.css",        # WP lo enqueue automáticamente como theme stylesheet
    "theme.json",       # Full Site Editing (FSE) / block themes
    "functions.php",    # WP lo incluye en cada load del theme
    "rtl.css",          # stylesheet RTL auto-cargado si locale es RTL
    "screenshot.png",   # preview del theme en admin (no código, pero es parte del theme)
    "screenshot.jpg",   # alternativa al PNG
    "readme.txt",       # metadata del theme para el repo oficial
)


def find_wp_theme_roots(project_root, max_depth=MAX_SCAN_DEPTH):
    """
    Busca todas las carpetas bajo project_root que son theme roots WP.

    Criterio: la carpeta contiene `style.css` Y (`functions.php` O `index.php`).

    Args:
        project_root: Path raíz del proyecto escaneado.
        max_depth: Profundidad máxima (0 = solo raíz, 1 = raíz + hijas, ...).

    Returns:
        Lista de Path absolutos (carpetas theme root). Orden estable por path.
    """
    root = Path(project_root).resolve()
    if not root.is_dir():
        return []

    found = []

    def _is_theme_root(folder):
        if not (folder / WP_THEME_STYLE).is_file():
            return False
        return any((folder / c).is_file() for c in WP_THEME_COMPANIONS)

    def _walk(folder, depth):
        if _is_theme_root(folder):
            found.append(folder)
        if depth >= max_depth:
            return
        try:
            entries = list(folder.iterdir())
        except (OSError, PermissionError):
            return
        for entry in entries:
            if not entry.is_dir():
                continue
            if entry.name in _WP_SCAN_IGNORE or entry.name.startswith("."):
                continue
            _walk(entry, depth + 1)

    _walk(root, 0)
    found.sort(key=lambda p: p.as_posix())
    return found


def iter_wp_theme_implicit_paths(theme_roots, project_root):
    """
    Para cada theme_root, yields los rel_paths (posix, relativos a project_root)
    de los archivos theme-implicit que existen en disco.

    Un archivo theme-implicit es uno que WordPress carga por convención cuando
    el theme está activo (ver WP_THEME_IMPLICIT_FILES). No aparecen como targets
    de ningún edge estático porque quien los carga es el core de WP (fuera del
    repo escaneado).

    Yields:
        tuples (rel_path_posix, basename) — rel_path siempre posix-style.
    """
    root = Path(project_root).resolve()
    for theme_root in theme_roots:
        for basename in WP_THEME_IMPLICIT_FILES:
            candidate = theme_root / basename
            if not candidate.is_file():
                continue
            try:
                rel = candidate.resolve().relative_to(root)
            except ValueError:
                continue
            yield rel.as_posix(), basename


def detect_wordpress_project(project_root):
    """
    Compat: True si se encuentra al menos un theme root o marker WP clásico.

    Kept for external callers. El pipeline usa find_wp_theme_roots() directo.
    """
    if find_wp_theme_roots(project_root):
        return True
    # Fallback al marker clásico en raíz (wp-config.php, wp-content/) — por si
    # alguien escanea un install WP completo donde la raíz NO es el theme.
    root = Path(project_root)
    for marker in ("wp-config.php", "wp-content", "wp-includes"):
        if (root / marker).exists():
            return True
    return False


def is_wp_template(rel_path, theme_roots=None, project_root=None):
    """
    True si `rel_path` (posix, relativo a project_root) es un template WP
    y cae dentro de algún theme root.

    Args:
        rel_path: path relativo (ej. "themes/etca-aula/index.php").
        theme_roots: lista de Path absolutos (resultado de find_wp_theme_roots).
            Si None, solo chequea el basename (modo legacy, menos preciso).
        project_root: Path raíz del proyecto, requerido si theme_roots dado.

    Returns:
        True si es template y está dentro de un theme root (o legacy mode).
    """
    basename = Path(rel_path).name

    matches_name = basename in WP_EXACT_TEMPLATES or any(
        fnmatch.fnmatch(basename, pat) for pat in WP_GLOB_PATTERNS
    )
    if not matches_name:
        return False

    # Modo legacy: solo basename (compat con llamadas antiguas).
    if theme_roots is None:
        return True

    # Verificar que rel_path esté dentro de algún theme root.
    if project_root is None:
        return False
    abs_path = (Path(project_root) / rel_path).resolve()
    for root in theme_roots:
        try:
            abs_path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def mark_wp_templates_as_entry_points(nodes, is_wp_project):
    """
    Compat: marca templates en un dict de nodos por basename.

    Kept por compatibilidad con tests/llamadas externas. El pipeline nuevo
    usa find_wp_theme_roots + is_wp_template(path, roots) directamente en
    finalize.py para ganar precisión (path-scoped, no basename-only).
    """
    if not is_wp_project:
        return

    for node_id, node in nodes.items():
        rel_path = node.get("path", "")
        if not rel_path.endswith(".php"):
            continue
        if is_wp_template(rel_path):
            if "entry_point_reason" not in node:
                node["entry_point_reason"] = "wp_template_hierarchy"
            elif isinstance(node["entry_point_reason"], str):
                node["entry_point_reason"] = [node["entry_point_reason"], "wp_template_hierarchy"]
            else:
                node["entry_point_reason"].append("wp_template_hierarchy")