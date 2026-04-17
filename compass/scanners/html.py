"""HTML scanner (Tier 3, dedicado) — HTML-019 + FIX-027.

Extrae referencias de los atributos estándar que enlazan a otros recursos del
repo: `<script src>`, `<link href>`, `<img src>`, `<form action>`,
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
    - Session 8 (NET-022b): `<a href>` queda EXCLUIDO del scan. Los links
      de `<a>` son navegación/contenido (linkedin, schema.org, sitemaps.org,
      etc.) — no son dependencias funcionales del código. Los atributos que
      SÍ cargan recursos que el browser ejecuta o renderiza (`script src`,
      `link href`, `img src`, `iframe src`, media, `form action`) se
      mantienen.

FIX-027 — Inline JS fetch scan:
    - Extrae el contenido de bloques `<script>…</script>` inline (sin `src`)
      y corre regex JS-lite sobre él: `fetch(...)`, `axios.get/post/...`,
      y wrappers declarados en `http_loaders.javascript` del config
      (ej. `apiReq`, `apiCall`, `api.get`).
    - NO parseamos JS con AST (eso traería dependencia externa). Un regex
      conservador con word-boundary lookbehind cubre los patrones típicos
      en páginas HTML estáticas (el scope es HTML, no JS real puro).
    - Las URLs literales externas (`fetch('https://api.openai.com/…')`)
      quedan como raws y core.py las clasifica vía NET-022 como
      `[EXTERNAL:host]`.
"""

import re

from compass.scanners.base import Scanner as _BaseScanner, build_http_loader_regex


# Atributos que contienen referencias a otros recursos + edge_type (EDG-023).
# Cada entry: (regex, edge_type). edge_type se preserva hasta el `.dot`.
_HTML_ATTR_PATTERNS = [
    # <script src="..."> / <script type="..." src="...">
    (r"""<script\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", "src"),
    # <link href="..."> (CSS, preload, icon, etc.)
    (r"""<link\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""", "href"),
    # <img src="...">
    (r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", "src"),
    # NOTA (Session 8 / NET-022b): `<a href>` EXCLUIDO — es navegación de
    # contenido, no dependencia funcional. Ver docstring del módulo.
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


_SCRIPT_BLOCK_RE = re.compile(
    r"<script\b(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script\s*>",
    re.I | re.S,
)


class HtmlScanner(_BaseScanner):
    """Scanner para archivos HTML — extrae referencias a otros recursos.

    FIX-027: acepta `config` opcional para componer el regex de wrappers
    HTTP a escanear dentro de `<script>` blocks inline.
    """

    def __init__(self, config=None):
        self._compiled = [
            (re.compile(pat, re.I | re.S), edge_type)
            for pat, edge_type in _HTML_ATTR_PATTERNS
        ]
        # FIX-027 — wrappers HTTP declarados en config.http_loaders.javascript
        # (mezclamos con typescript ya que HTML inline puede llevar TS-ish).
        # Siempre se agregan `fetch` y `axios.*` como baseline si están en
        # config; si config no está presente caemos al fetch() hardcoded.
        loader_names = []
        if isinstance(config, dict):
            for key in ("javascript", "typescript"):
                loader_names.extend(
                    (config.get("http_loaders") or {}).get(key) or []
                )
        # Dedup preservando orden.
        seen = set()
        self._loader_names = []
        for n in loader_names:
            if n and n not in seen:
                seen.add(n)
                self._loader_names.append(n)
        self._script_loader_regex = build_http_loader_regex(self._loader_names)

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

        # FIX-027 — pasar por bloques <script> inline sin src y aplicar
        # el regex de wrappers HTTP (fetch/axios/apiReq/...).
        if self._script_loader_regex:
            for script_match in _SCRIPT_BLOCK_RE.finditer(content):
                block = script_match.group(1) or ""
                if not block.strip():
                    continue
                for m in self._script_loader_regex.finditer(block):
                    url = m.group(1)
                    if url:
                        out.append((url, "fetch"))
        return out