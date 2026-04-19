"""Framework static mount detector — SEM-020.

Detecta configuración de static files en frameworks web (Flask, FastAPI, Express)
por análisis estático de código, extrayendo los mount points que mapean URLs
a rutas del filesystem.

Estructura:
    detect_framework_mounts(project_root: Path) → dict[str, dict[str, str]]

    Devuelve:
    {
        "flask": {
            "/static": "/path/to/static",  # mount_point → absolute_path
            ...
        },
        "fastapi": {
            "/static": "/path/to/static",
            ...
        },
        ...
    }

Política:
    - Detección por señales en el código (Flask("__name__"), FastAPI(), etc.)
    - NO hardcodear por nombre de folder (framework-agnóstico).
    - Defaults: Flask → "/static" → "./static" (relativo al app file).
    - Resultados cached por project_root (caro hacer análisis full cada scan).
"""

import re
from pathlib import Path
from typing import Dict


def detect_framework_mounts(project_root: Path) -> Dict[str, Dict[str, str]]:
    """Escanea el proyecto y extrae mount points de frameworks web.

    Devuelve dict[framework_name → dict[mount_point → absolute_path]].

    Ejemplos:
        {
            "flask": {
                "/static": "c:\\projects\\app\\static",
            },
            "fastapi": {
                "/api/static": "c:\\projects\\app\\static",
            },
        }
    """
    mounts = {}

    # 1. Buscar Flask apps
    flask_mounts = _detect_flask_mounts(project_root)
    if flask_mounts:
        mounts["flask"] = flask_mounts

    # 2. Buscar FastAPI apps
    fastapi_mounts = _detect_fastapi_mounts(project_root)
    if fastapi_mounts:
        mounts["fastapi"] = fastapi_mounts

    # 3. Buscar Express apps (Node/JavaScript)
    # Nice-to-have, ahora sin implementación; se puede extender.

    return mounts


def detect_server_entry_points(project_root: Path) -> Dict[str, str]:
    """18A.2 — Detecta WSGI/ASGI servers (waitress, uvicorn, hypercorn, gunicorn).

    Devuelve dict[archivo → server_type].

    Patrones detectados:
      - waitress.serve(app, ...)
      - uvicorn.run(app, ...)
      - uvicorn.run("module:app", ...)
      - hypercorn.run(app, ...)
      - gunicorn invocations (CLI pattern)

    El archivo que invoca al server se marca como entry point (GRAPH-036 extension).
    """
    servers = {}

    # Patrones de detectores por servidor
    patterns = {
        "waitress": re.compile(r"waitress\.serve\s*\(\s*(\w+)\s*,"),
        "uvicorn": re.compile(r"uvicorn\.run\s*\(\s*(?:['\"]([^'\"]+)['\"]|(\w+))\s*,"),
        "hypercorn": re.compile(r"hypercorn\.run\s*\(\s*(\w+)\s*,"),
    }

    excluded_dirs = {".venv", "venv", ".env", "node_modules", "__pycache__", ".git", "dist", "build", ".next"}

    for py_file in project_root.rglob("*.py"):
        if any(part in excluded_dirs for part in py_file.parts):
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue

        for server_name, pattern in patterns.items():
            if pattern.search(content):
                rel_path = py_file.relative_to(project_root).as_posix()
                servers[rel_path] = server_name

    return servers


def _detect_flask_mounts(project_root: Path) -> Dict[str, str]:
    """Busca Flask(__name__, static_folder=...) en los .py del proyecto.

    Patrón esperado:
        app = Flask(__name__, static_folder="static")
        app = Flask(__name__, static_folder="./assets", static_url_path="/assets")

    Devuelve dict[url_path → absolute_filesystem_path].

    Nota: Excluye .venv, node_modules, __pycache__ y otros directorios estándar.
    """
    mounts = {}
    flask_pattern = re.compile(
        r'Flask\s*\(\s*["\']?__name__["\']?\s*(?:,\s*)?'
        r'(?:static_folder\s*=\s*["\']([^"\']+)["\'])?'
        r'(?:,\s*static_url_path\s*=\s*["\']([^"\']+)["\'])?'
    )

    # Patrones a excluir: virtualenvs, node_modules, cache, dist, etc.
    excluded_dirs = {".venv", "venv", ".env", "node_modules", "__pycache__", ".git", "dist", "build", ".next"}

    for py_file in project_root.rglob("*.py"):
        # Saltar archivos en directorios excluidos
        if any(part in excluded_dirs for part in py_file.parts):
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue

        # Buscar `Flask(...)` con static_folder y/o static_url_path
        for match in flask_pattern.finditer(content):
            static_folder = match.group(1)
            static_url_path = match.group(2)

            # Defaults: Flask defaults to "/static" → "static/" (relativo a app location)
            if not static_url_path:
                static_url_path = "/static"
            if not static_folder:
                static_folder = "static"

            # Resolver static_folder relativo a py_file
            static_abs = (py_file.parent / static_folder).resolve()

            # Normalizar static_url_path: asegurar que empiece con /
            if not static_url_path.startswith("/"):
                static_url_path = "/" + static_url_path

            mounts[static_url_path] = static_abs.as_posix()

    return mounts


def _detect_fastapi_mounts(project_root: Path) -> Dict[str, str]:
    """Busca FastAPI() + app.mount("/static", StaticFiles(...)) en los .py.

    Patrón esperado:
        from fastapi.staticfiles import StaticFiles
        app.mount("/static", StaticFiles(directory="static"), name="static")
        app.mount("/assets", StaticFiles(directory="./client/build"), name="assets")

    Devuelve dict[mount_point → absolute_path].

    Nota: Limitación de análisis estático: si `directory` es variable,
    no se puede resolver. El scanner solo maneja directorios string.
    """
    mounts = {}

    # Buscar app.mount("/path", StaticFiles(directory="..."))
    mount_pattern = re.compile(
        r'app\.mount\s*\(\s*["\']([^"\']+)["\']\s*,\s*'
        r'StaticFiles\s*\(\s*directory\s*=\s*["\']([^"\']+)["\']\s*\)'
    )

    # Patrones a excluir
    excluded_dirs = {".venv", "venv", ".env", "node_modules", "__pycache__", ".git", "dist", "build", ".next"}

    for py_file in project_root.rglob("*.py"):
        # Saltar archivos en directorios excluidos
        if any(part in excluded_dirs for part in py_file.parts):
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue

        for match in mount_pattern.finditer(content):
            mount_point = match.group(1)
            directory = match.group(2)

            # Resolver directory relativo a py_file
            dir_abs = (py_file.parent / directory).resolve()

            # Normalizar mount_point: asegurar que empiece con /
            if not mount_point.startswith("/"):
                mount_point = "/" + mount_point

            mounts[mount_point] = dir_abs.as_posix()

    return mounts