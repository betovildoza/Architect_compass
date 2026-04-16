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


# Atributos que contienen referencias a otros recursos.
# Captura el valor entre comillas simples o dobles del atributo.
_HTML_ATTR_PATTERNS = [
    # <script src="..."> / <script type="..." src="...">
    r"""<script\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""",
    # <link href="..."> (CSS, preload, icon, etc.)
    r"""<link\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""",
    # <img src="...">
    r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""",
    # <a href="...">
    r"""<a\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""",
    # <form action="...">
    r"""<form\b[^>]*?\baction\s*=\s*["']([^"']+)["']""",
    # <iframe src="...">
    r"""<iframe\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""",
    # <video src="..."> (el más común es <source> anidado, pero por si acaso)
    r"""<video\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""",
    # <audio src="...">
    r"""<audio\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""",
    # <source src="..."> — hijos de <video>/<audio>/<picture>
    r"""<source\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""",
    # FIX-026: JS embebido en <script> inline (sin src=) suele hacer fetch()
    # a endpoints del mismo proyecto. El scanner JS no ve HTML, pero estos
    # calls SON dependencias reales. Capturamos sólo literales (no template
    # literals con interpolación — eso es territorio de SEM-020/NET-022).
    # Se usa contra TODO el contenido HTML; como el pattern pide paréntesis
    # abierto inmediato, no matchea contra texto accidental "fetch" en copy.
    r"""\bfetch\s*\(\s*["']([^"']+)["']""",
]


class HtmlScanner(_BaseScanner):
    """Scanner para archivos HTML — extrae referencias a otros recursos."""

    def __init__(self):
        self._compiled = [re.compile(p, re.I | re.S) for p in _HTML_ATTR_PATTERNS]

    def extract_imports(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            return []

        out = []
        for regex in self._compiled:
            for match in regex.findall(content):
                value = str(match).strip()
                if not value:
                    continue
                out.append(value)
        return out