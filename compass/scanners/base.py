"""Scanner base interface — SCN-003 + EDG-023 + NET-022.

Define la interfaz abstracta que implementan los tres tiers de scanners:

    Tier 1 — python.Scanner        (ast stdlib)
    Tier 2 — treesitter.Scanner    (grammar por lenguaje, opt-in)
    Tier 3 — regex_fallback.Scanner (config-driven)

La única responsabilidad del scanner es devolver una lista de imports crudos
extraídos del archivo. La resolución a paths absolutos vive en
compass.path_resolver.PathResolver.

EDG-023 — formato de retorno:
    Cada item de la lista devuelta por `extract_imports` puede ser:
      - `str` con el target crudo (legacy, pre-EDG-023 — edge_type se asume
        genérico `"use"`).
      - `tuple(str, str)` con `(target, edge_type)`. Ejemplos de edge_type:
        `import`, `require`, `include`, `src`, `href`, `action`, `fetch`,
        `enqueue`, `use`. El caller normaliza con `normalize_edge_item`.

NET-022 — helpers para detección de URLs literales en llamadas HTTP:
    `build_http_loader_regex` compila un regex que matchea nombres de
    funciones HTTP seguidos de un argumento string literal con URL.
    `extract_http_host` extrae el hostname de una URL string.
"""

import re
from abc import ABC, abstractmethod
from urllib.parse import urlparse


# EDG-023: edge_type por defecto si el scanner no lo declara.
# Sesión 6C: configurable vía mapper_config.json::graph.default_edge_type.
# `DEFAULT_EDGE_TYPE` sigue siendo el fallback hardcoded — el caller que
# quiera respetar la config debe usar `resolve_default_edge_type(config)`.
DEFAULT_EDGE_TYPE = "use"


def resolve_default_edge_type(config):
    """Devuelve el edge_type default declarado en config (o hardcoded).

    Sesión 6C: el orquestador (core.py) lee esto una vez por run y lo pasa a
    `normalize_edge_item` vía parámetro `default_edge_type`.
    """
    if not isinstance(config, dict):
        return DEFAULT_EDGE_TYPE
    graph = config.get("graph") or {}
    raw = graph.get("default_edge_type")
    if raw:
        return str(raw)
    return DEFAULT_EDGE_TYPE


def normalize_edge_item(item, default_edge_type=None):
    """Convierte item de scanner → `(target, edge_type)`.

    Acepta `str` (legacy) o `tuple(str, str)`. Si el item no declara
    edge_type, usa `default_edge_type` (o `DEFAULT_EDGE_TYPE` hardcoded).
    Sesión 6C: `default_edge_type` configurable.
    """
    fallback = default_edge_type or DEFAULT_EDGE_TYPE
    if item is None:
        return None, fallback
    if isinstance(item, tuple):
        if len(item) == 0:
            return None, fallback
        target = item[0]
        edge_type = item[1] if len(item) > 1 and item[1] else fallback
    else:
        target = item
        edge_type = fallback
    if target is None:
        return None, edge_type
    target_str = str(target).strip()
    if not target_str:
        return None, edge_type
    return target_str, str(edge_type)


def build_http_loader_regex(loader_names):
    """NET-022 — Compila un regex que matchea cualquiera de `loader_names`
    seguido de paréntesis y un argumento string literal (single o double quote).

    Retorna un `re.Pattern` compilado cuyo group(1) captura la URL literal,
    o None si `loader_names` está vacío.

    Ejemplo de match:
        requests.get("https://api.openai.com/v1/chat")
        fetch('https://example.com/api')
        requests.get(
            "https://api.example.com/endpoint"
        )

    El regex es case-sensitive y requiere match exacto del nombre.
    Para nombres con puntos (requests.get), el punto se escapa.
    re.DOTALL permite matchear calls multi-línea.
    """
    if not loader_names:
        return None
    # Escapar nombres y ordenar por longitud descendente para que
    # `requests.request` no sea pre-empted por `requests` solo.
    escaped = sorted(
        (re.escape(name) for name in loader_names if name),
        key=len, reverse=True,
    )
    if not escaped:
        return None
    names_alt = "|".join(escaped)
    # Pattern: \b<name>\s*(\s*["'](<url>)["']
    # El \b previene matches parciales (ej. "my_requests.get" no matchea
    # "requests.get" porque el \b falla contra el underscore — CORRECCIÓN:
    # \b matchea entre _ y . pero no entre alfanum y alfanum, así que
    # usamos una alternativa: lookahead/lookbehind negativo para alfanum).
    # Simplificación: usamos (?<![a-zA-Z0-9_]) como lookbehind.
    pattern = r"(?<![a-zA-Z0-9_])(?:" + names_alt + r")\s*\(\s*[\"']([^\"']+)[\"']"
    return re.compile(pattern, re.DOTALL)


def extract_http_host(url_string):
    """NET-022 — Extrae hostname de una URL string usando urlparse.

    Retorna hostname lowercase sin puerto, o None si no es http(s).
    """
    if not url_string:
        return None
    parsed = urlparse(url_string)
    if parsed.scheme not in ("http", "https"):
        return None
    return parsed.hostname  # lowercase, sin puerto


class Scanner(ABC):
    """Interfaz común. `extract_imports` devuelve raws (str o tuple)."""

    @abstractmethod
    def extract_imports(self, file_path):
        """Lee `file_path` y devuelve una lista de imports crudos.

        Cada item es `str` (legacy) o `tuple(target, edge_type)` (EDG-023).
        PathResolver consume solo el `target`; core.py preserva el
        `edge_type` para el label del `.dot`.

        Si el archivo no se puede leer o parsear, el scanner devuelve [].
        """
        raise NotImplementedError


class NullScanner(Scanner):
    """Scanner no-op para lenguajes sin cobertura disponible."""

    def extract_imports(self, file_path):
        return []