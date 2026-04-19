"""dashboard_detector — detectar UIs servidas (dashboards) por markers de forma.

SESIÓN 20 (ITEM 2): Identifica archivos que representan dashboards o UIs
servidas mediante análisis stack-agnóstico de FORMA, no de framework.

Markers (combinados):
  - HTML: estructura de control (buttons, inputs, forms) + script tags que cargan JS.
  - JS: presencia de fetch/XMLHttpRequest/WebSocket con rutas locales
    (ej: "/api/...", "/action/...", "http://localhost:*").

Criterio mínimo: HTML carga JS que contiene fetch/websocket → entry point implícito.
"""

import re
from pathlib import Path


def has_control_structure(html_content):
    """Detecta si HTML tiene estructura de controles (buttons, forms, inputs con handlers).

    Busca:
      - <button>, <input> con onclick/onchange/oninput
      - <form>
      - onclick/onchange/oninput en elementos generales
    """
    if not html_content:
        return False

    patterns = [
        r'<button\b[^>]*(?:onclick|onchange|oninput)',
        r'<input\b[^>]*(?:onclick|onchange|oninput)',
        r'<form\b',
        r'\bonclick\s*=',
        r'\bonchange\s*=',
        r'\boninput\s*=',
    ]

    for pattern in patterns:
        if re.search(pattern, html_content, re.IGNORECASE):
            return True

    return False


def extract_script_sources(html_content):
    """Extrae src de <script src="..."> tags.

    Devuelve lista de paths relativos (ej: ['js/app.js', 'vendor.js']).
    """
    if not html_content:
        return []

    # Buscar <script src="...">
    pattern = r'<script\s+[^>]*src\s*=\s*["\']([^"\']+)["\']'
    return re.findall(pattern, html_content, re.IGNORECASE)


def has_local_fetch(js_content):
    """Detecta si JS contiene fetch/XMLHttpRequest/WebSocket a rutas locales.

    Busca:
      - fetch("...", fetch('/...', etc.)
      - XMLHttpRequest.open("...", "/...", etc.)
      - new WebSocket("ws://localhost:...", etc.)
      - Rutas tipo "/api/...", "/action/..." (paths locales)
    """
    if not js_content:
        return False

    local_routes = [
        r'fetch\s*\(\s*["\']/?api/',
        r'fetch\s*\(\s*["\']/?action/',
        r'fetch\s*\(\s*["\']\.?\/[^"\']*["\']',
        r'XMLHttpRequest.*open\s*\(\s*["\'](?:GET|POST)["\']?\s*,\s*["\']/?api/',
        r'XMLHttpRequest.*open\s*\(\s*["\'](?:GET|POST)["\']?\s*,\s*["\']/?action/',
        r'new\s+WebSocket\s*\(\s*["\']ws(?:s)?:\/\/localhost',
        r'axios\s*\.\s*(?:get|post|put|patch|delete)\s*\(\s*["\']/?api/',
        r'axios\s*\.\s*(?:get|post|put|patch|delete)\s*\(\s*["\']/?action/',
        r'\.then\s*\(\s*(?:function\s*\(\s*\w+\s*\)|[^)]*)\s*=>\s*',  # promise chain
    ]

    for pattern in local_routes:
        if re.search(pattern, js_content, re.IGNORECASE):
            return True

    return False


def is_dashboard_html(html_path, files_dict, file_contents):
    """Determina si un HTML es dashboard: carga JS que contiene fetch/websocket a rutas locales.

    Stack-agnóstico: detecta por FORMA (carga JS + fetch local), no por framework.

    Criterios (relajados post-SESIÓN 20):
      - HTML carga script(s) internos
      - Al menos uno de esos scripts contiene fetch/websocket/axios a rutas locales
      - Opcionalmente: HTML tiene estructura de controles (buttons, forms) — BONUS

    Args:
        html_path: path relativo del archivo HTML (ej: "index.html", "src/dashboard/index.html")
        files_dict: dict[rel_path: node] del atlas (para validar que JS existen)
        file_contents: dict[rel_path: content] — contenidos de archivos ya leídos
                       (para evitar re-leer)

    Devuelve: (is_dashboard: bool, reason: str o None)
    """
    if not html_path.endswith(('.html', '.htm')):
        return False, None

    # Leer contenido HTML (si no está en cache, no lo leen aquí — conservador)
    if html_path not in file_contents:
        return False, None

    html_content = file_contents.get(html_path, "")

    # 1. Debe cargar script(s) — criterio mínimo
    script_srcs = extract_script_sources(html_content)
    if not script_srcs:
        return False, None

    # 2. Al menos uno de esos scripts debe tener fetch/websocket local
    fetch_found = False
    for script_src in script_srcs:
        # Resolver path relativo al HTML directory
        html_dir = str(Path(html_path).parent)
        if html_dir == ".":
            resolved_script = script_src
        else:
            resolved_script = str(Path(html_dir) / script_src).replace("\\", "/")

        # Normalizar (remove ../ si aplica — simplista)
        resolved_script = resolved_script.lstrip("./")

        if resolved_script in file_contents:
            js_content = file_contents[resolved_script]
            if has_local_fetch(js_content):
                fetch_found = True
                break

    if not fetch_found:
        return False, None

    # 3. BONUS: si tiene estructura de controles, es más seguro. Pero no es requerido.
    has_controls = has_control_structure(html_content)
    reason_suffix = "(with controls)" if has_controls else "(framework-based, inferred from JS)"

    return True, f"dashboard_markers {reason_suffix}"


def detect_dashboards_in_atlas(atlas, project_root):
    """Escanea atlas para detectar dashboards y promover a entry_points.

    Args:
        atlas: dict atlas.json
        project_root: Path al root del proyecto

    Devuelve: dict con { "promoted": [list de paths], "reason": "dashboard_markers" }
             o vacío si ninguno detectado.

    NOTA: Este detector es CONSERVADOR — necesita leer archivos HTML+JS completos.
    Si el proyecto es grande o la lectura es costosa, esto puede tomar tiempo.
    """
    promoted = []

    # Construir cache de contenidos para archivos ambiguos que son HTML
    ambiguous_html = [
        f for f in atlas.get("ambiguous", [])
        if f.endswith(('.html', '.htm'))
    ]

    if not ambiguous_html:
        return {}

    # Lectura perezosa: solo los necesarios
    file_contents = {}
    for html_file in ambiguous_html:
        html_path = project_root / html_file
        if html_path.exists():
            try:
                with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
                    file_contents[html_file] = f.read()
            except Exception:
                pass  # Si falla lectura, conservador → no es dashboard

    # Ahora, para cada HTML, extraer scripts y leer esos
    for html_file in ambiguous_html:
        if html_file not in file_contents:
            continue

        html_content = file_contents[html_file]
        script_srcs = extract_script_sources(html_content)

        for script_src in script_srcs:
            html_dir = str(Path(html_file).parent)
            if html_dir == ".":
                resolved_script = script_src
            else:
                resolved_script = str(Path(html_dir) / script_src).replace("\\", "/")
            resolved_script = resolved_script.lstrip("./")

            # Leer script si existe
            script_path = project_root / resolved_script
            if script_path.exists():
                try:
                    with open(script_path, 'r', encoding='utf-8', errors='ignore') as f:
                        file_contents[resolved_script] = f.read()
                except Exception:
                    pass

    # Detectar dashboards
    files_dict = atlas.get("files", {})
    for html_file in ambiguous_html:
        is_dashboard, reason = is_dashboard_html(html_file, files_dict, file_contents)
        if is_dashboard:
            promoted.append(html_file)

    if promoted:
        return {
            "promoted": promoted,
            "reason": "dashboard_markers",
        }

    return {}