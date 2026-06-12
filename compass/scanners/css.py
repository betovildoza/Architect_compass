"""CSS scanner (TSD-046, D7) — `@import` dual-tier.

Hoy CSS cae a NullScanner (warning "Sin scanner disponible: css"). Este
scanner extrae los `@import` que enlazan a otros archivos CSS del repo,
con edge_type `"imports"`. La resolución (relativa al archivo CSS) la hace
`PathResolver` por el camino genérico — los raws son paths relativos con
extensión, que `_resolve_generic` resuelve desde `source_file.parent`.

Dual-tier:
  - Tier 2 (tree-sitter): grammar `css` del language-pack. Recorre nodos
    `import_statement` / `@import` y extrae el target (string o `url(...)`).
  - Tier 3 (regex): 4 variantes de sintaxis `@import` como fallback. Se usa
    cuando el binding no está instalado (zero-install intacto).

Las 4 variantes de `@import` cubiertas por el regex:
  1. @import "theme.css";
  2. @import 'theme.css';
  3. @import url("theme.css");
  4. @import url(theme.css);          (sin comillas)
Con media query opcional al final (`@import "x.css" screen;`) — el target
es siempre el primer string/url.

Las URLs absolutas (`@import "https://fonts.googleapis.com/...";`) se
emiten como raw — el resolver devuelve None y GRF-021 las clasifica.
"""

import re

from compass.scanners.base import Scanner as _BaseScanner

_CSS_EDGE = "imports"

# Tier 3 — regex de las 4 variantes. Captura el primer string entre comillas
# o el contenido de url(...). El non-capturing `(?:url\()?` + alternancia
# cubre las formas con y sin url().
_CSS_IMPORT_RE = re.compile(
    r"""@import\s+"""
    r"""(?:url\(\s*)?"""              # url( opcional
    r"""(?:"([^"]+)"|'([^']+)'|([^"')\s;]+))""",  # "x" | 'x' | x (sin comillas)
    re.IGNORECASE,
)


def _regex_imports(content):
    out = []
    for m in _CSS_IMPORT_RE.finditer(content):
        target = m.group(1) or m.group(2) or m.group(3)
        if target:
            target = target.strip().rstrip(")").strip()
            if target:
                out.append((target, _CSS_EDGE))
    return out


class CssScanner(_BaseScanner):
    """Scanner CSS dual-tier. `tier_name` ∈ {tree-sitter-pack, regex}."""

    def __init__(self, config=None):
        self._parser = None
        self.tier_name = "regex"
        # Tier 2 — intentar el parser CSS del language-pack (D1).
        try:
            from compass.scanners.treesitter import _load_parser
            self._parser, self.tier_name = _load_parser("@pack", "css")
        except Exception:
            self._parser = None
            self.tier_name = "regex"

    def extract_imports(self, file_path):
        try:
            with open(file_path, "rb") as f:
                data = f.read()
        except OSError:
            return []

        if self._parser is not None:
            try:
                return self._ts_imports(data)
            except Exception:
                # Cualquier fallo del AST → caer a regex sobre el mismo texto.
                pass

        content = data.decode("utf-8", errors="ignore")
        return _regex_imports(content)

    def _ts_imports(self, data):
        tree = self._parser.parse(data)
        out = []
        self._walk(tree.root_node, data, out)
        # Si el AST no encontró nada (grammar dispar), fallback regex.
        if not out:
            return _regex_imports(data.decode("utf-8", errors="ignore"))
        return out

    def _walk(self, node, src, out):
        if node.type in ("import_statement", "at_rule"):
            text = src[node.start_byte:node.end_byte].decode(
                "utf-8", errors="ignore"
            )
            if text.lower().lstrip().startswith("@import"):
                for target, edge in _regex_imports(text):
                    out.append((target, edge))
        for child in node.children:
            self._walk(child, src, out)
