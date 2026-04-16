"""Scanner base interface — SCN-003 + EDG-023.

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
"""

from abc import ABC, abstractmethod


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