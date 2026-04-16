"""HTML scanner (Tier 3, dedicado) — HTML-019.

Extrae referencias de los atributos estándar que enlazan a otros recursos del
repo: `<script src>`, `<link href>`, `<img src>`, `<a href>`, `<form action>`,
`<iframe src>`, `<video src>`, `<source src>`, `<audio src>`.

Diseño:
    - Scanner dedicado (no comparte patterns con `RegexFallbackScanner`)
      porque el resolver HTML tiene edge cases muy específicos (fragments,
      mailto:/tel:/javascript:, query strings, rutas sin extensión) que no
      encajan en el pipeline genérico.
    - Devuelve strings crudos. El filtrado fino (fragment-only, schemes no
      resolubles) y la resolución a paths del repo quedan en
      `PathResolver._resolve_html`.
    - Las URLs absolutas (`http://`, `https://`, `//cdn.…`) se dejan pasar
      como raws — `_resolve_html` devolverá None (no existen en el repo) y
      GRF-021 decide si las vuelve a nodo `[EXTERNAL:*]`.
"""

import re

from compass.scanners.base import Scanner as _BaseScanner


# Atributos que contienen referencias a otros recursos + edge_type (EDG-023).
# Cada entry: (regex, edge_type). edge_type se preserva hasta el `.dot`.
_HTML_ATTR_PATTERNS = [
    # <script src="..."> / <script type="..." src="...">
    (r"""<script\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", "src"),
    # <link href="..."> (CSS, preload, icon, etc.)
    (r"""<link\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""", "href"),
    # <img src="...">
    (r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", "src"),
    # <a href="...">
    (r"""<a\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""", "href"),
    # <form action="...">
    (r"""<form\b[^>]*?\baction\s*=\s*["']([^"']+)["']""", "action"),
    # <iframe src="...">
    (r"""<iframe\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", "src"),
    # <video src="..."> (el más común es <source> anidado, pero por si acaso)
    (r"""<video\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", "src"),
    # <audio src="...">
    (r"""<audio\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", "src"),
    # <source src="..."> — hijos de <video>/<audio>/<picture>
    (r"""<source\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", "src"),
    # FIX-026: JS embebido en <script> inline (sin src=) suele hacer fetch()
    # a endpoints del mismo proyecto. El scanner JS no ve HTML, pero estos
    # calls SON dependencias reales. Capturamos sólo literales (no template
    # literals con interpolación — eso es territorio de SEM-020/NET-022).
    (r"""\bfetch\s*\(\s*["']([^"']+)["']""", "fetch"),
]


class HtmlScanner(_BaseScanner):
    """Scanner para archivos HTML — extrae referencias a otros recursos."""

    def __init__(self):
        self._compiled = [
            (re.compile(pat, re.I | re.S), edge_type)
            for pat, edge_type in _HTML_ATTR_PATTERNS
        ]

    def extract_imports(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            return []

        out = []
        for regex, edge_type in self._compiled:
            for match in regex.findall(content):
                value = str(match).strip()
                if not value:
                    continue
                out.append((value, edge_type))
        return out