"""Defaults del scanner — patrones y configuraciones universales del stack.

Este módulo centraliza los valores por defecto que son universales a cada
lenguaje/stack y no deberían requerir configuración por proyecto. Se usan
cuando el config (mapper_config.json o compass.local.json) no especifica
valores alternativos.

Política: si es universal al stack, va aquí. Si es extensión opt-in
custom del proyecto, va en config.
"""

# LOAD-038 — Python filesystem loaders universales (stdlib).
# Estos son patrones que SIEMPRE deberían detectarse en cualquier proyecto Python,
# sin requerir mapper_config.json.
# Estructura: fn_name → {arg, language, edge_type}
# donde `arg` es la posición del argumento con el path (1-based) o la descripción
# del lugar donde está el path.
DEFAULT_PYTHON_LOADERS = {
    "open": {"arg": 1, "language": "python", "edge_type": "load"},
    "json.load": {"arg": 1, "language": "python", "edge_type": "load"},
    "read_text": {"arg": 1, "language": "python", "edge_type": "load"},
    "read_bytes": {"arg": 1, "language": "python", "edge_type": "load"},
    "path_literal": {"arg": 1, "language": "python", "edge_type": "load"},  # VAR = path / "literal"
    # 18A.2 — Flask file serving
    "send_from_directory": {"arg": 1, "language": "python", "edge_type": "load"},  # send_from_directory(dir, filename) → dir+file combined en scanner
    "send_file": {"arg": 1, "language": "python", "edge_type": "load"},  # send_file(filepath)
}

# Futuros: DEFAULT_PHP_LOADERS, DEFAULT_JS_LOADERS, etc.

# ORP-1 — Patrones universales para clasificar archivos como orphans.
# Estos son archivos que son inherentemente descartables (backups, temporales, etc.)
# sin ambigüedad, según convenciones universales en prácticamente todos los lenguajes.
# Estructura: {extensions, name_suffixes, folder_segments}
DEFAULT_ORPHAN_PATTERNS = {
    "extensions": [
        ".bak",      # backup
        ".old",      # old version
        ".orig",     # original (pre-patch)
        ".tmp",      # temporary
        ".swp",      # vim swap
        ".swo",      # vim swap (older)
        ".rej",      # patch rejection
    ],
    "name_suffixes": [
        "_old",
        "_bak",
        "_backup",
        "_deprecated",
        "_legacy",
        "_orig",
        "_tmp",
    ],
    "folder_segments": [
        "archive",
        "backup",
        "deprecated",
        "old",
        "trash",
        "_trash",
        "_old",
    ],
}