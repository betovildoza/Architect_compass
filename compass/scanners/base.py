"""Scanner base interface — SCN-003.

Define la interfaz abstracta que implementan los tres tiers de scanners:

    Tier 1 — python.Scanner        (ast stdlib)
    Tier 2 — treesitter.Scanner    (grammar por lenguaje, opt-in)
    Tier 3 — regex_fallback.Scanner (config-driven)

La única responsabilidad del scanner es devolver una lista de strings crudos
extraídos del archivo (los imports/requires/includes). La resolución a paths
absolutos vive en compass.path_resolver.PathResolver.
"""

from abc import ABC, abstractmethod


class Scanner(ABC):
    """Interfaz común. `extract_imports` devuelve raw strings."""

    @abstractmethod
    def extract_imports(self, file_path):
        """Lee `file_path` y devuelve una lista de strings crudos.

        Cada string es el argumento crudo de un import/require/include tal
        cual lo vio el scanner (AST node text o match regex). El
        PathResolver los interpreta después según el lenguaje.

        Si el archivo no se puede leer o parsear, el scanner devuelve [].
        """
        raise NotImplementedError


class NullScanner(Scanner):
    """Scanner no-op para lenguajes sin cobertura disponible."""

    def extract_imports(self, file_path):
        return []