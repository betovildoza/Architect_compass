"""HTML scanner tree-sitter (TSD-046, D7) — paridad HTML-019 + FIX-027.

Camino Tier 2 para HTML: extrae los MISMOS atributos que `HtmlScanner`
(script/link/img/form/iframe/video/audio/source) desde el AST tree-sitter
en vez de regex, y pasa el texto de cada bloque `<script>` inline por el
MISMO regex de loaders (reuso de `build_http_loader_regex`).

Paridad obligatoria con el regex (D7):
  - misma exclusión de `<a href>` (navegación/contenido, no dependencia);
  - mismos edge_types por atributo (src/href/action/fetch);
  - mismo tratamiento de `<script>` inline (FIX-027).

Ganancia real de tree-sitter: tags multilínea/malformados, atributos en
cualquier orden, extracción exacta de bloques script. Para HTML bien
formado rinde casi igual que el regex; el valor es robustez.

Si el binding no está disponible, el constructor levanta ImportError y el
dispatcher cae a `HtmlScanner` (el fallback probado) — zero-install intacto.
"""

import re

from compass.scanners.base import Scanner as _BaseScanner, build_http_loader_regex

# tag → (atributo que enlaza recurso, edge_type). `<a>` AUSENTE a propósito.
_TAG_ATTR_EDGE = {
    "script": ("src", "src"),
    "link": ("href", "href"),
    "img": ("src", "src"),
    "form": ("action", "action"),
    "iframe": ("src", "src"),
    "video": ("src", "src"),
    "audio": ("src", "src"),
    "source": ("src", "src"),
}

# Fallback: fetch() literal en script inline (paridad con _HTML_ATTR_PATTERNS).
_INLINE_FETCH_RE = re.compile(r"""\bfetch\s*\(\s*["']([^"']+)["']""", re.I | re.S)


class TreeSitterHtmlScanner(_BaseScanner):
    """Scanner HTML Tier 2. `tier_name` = "tree-sitter-pack"."""

    def __init__(self, config=None):
        from compass.scanners.treesitter import _load_parser
        self._parser, self.tier_name = _load_parser("@pack", "html")

        # FIX-027 — wrappers HTTP declarados en config (mismo criterio que
        # HtmlScanner): javascript + typescript.
        loader_names = []
        if isinstance(config, dict):
            for key in ("javascript", "typescript"):
                loader_names.extend(
                    (config.get("http_loaders") or {}).get(key) or []
                )
        seen = set()
        self._loader_names = []
        for n in loader_names:
            if n and n not in seen:
                seen.add(n)
                self._loader_names.append(n)
        self._script_loader_regex = build_http_loader_regex(self._loader_names)

    def extract_imports(self, file_path):
        try:
            with open(file_path, "rb") as f:
                data = f.read()
        except OSError:
            return []
        try:
            tree = self._parser.parse(data)
        except Exception:
            return []

        out = []
        self._walk(tree.root_node, data, out)
        return out

    # ------------------------------------------------------------------
    @staticmethod
    def _text(node, src):
        return src[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")

    def _walk(self, node, src, out):
        if node.type in ("element", "script_element", "style_element"):
            self._handle_element(node, src, out)
        for child in node.children:
            self._walk(child, src, out)

    def _handle_element(self, node, src, out):
        # El primer hijo es el start_tag; de ahí salen tag_name y attrs.
        start_tag = None
        for child in node.children:
            if child.type in ("start_tag", "self_closing_tag"):
                start_tag = child
                break
        if start_tag is None:
            return
        tag_name = self._tag_name(start_tag, src)
        if tag_name is None:
            return

        # Atributo que enlaza recurso (excluye <a href> por no estar en el map).
        spec = _TAG_ATTR_EDGE.get(tag_name)
        if spec is not None:
            wanted_attr, edge_type = spec
            value = self._attr_value(start_tag, wanted_attr, src)
            if value:
                out.append((value.strip(), edge_type))

        # FIX-027 — <script> inline (sin src): pasar el texto por loaders.
        if tag_name == "script" and spec is not None:
            has_src = self._attr_value(start_tag, "src", src) is not None
            if not has_src:
                block = self._script_text(node, src)
                if block.strip():
                    self._scan_inline_script(block, out)

    @staticmethod
    def _tag_name(start_tag, src):
        for child in start_tag.children:
            if child.type == "tag_name":
                return src[child.start_byte:child.end_byte].decode(
                    "utf-8", errors="ignore"
                ).lower()
        return None

    def _attr_value(self, start_tag, attr_name, src):
        """Devuelve el valor del atributo `attr_name` (case-insensitive), o
        None si no está. None ≠ "" (string vacío significa presente-vacío)."""
        for child in start_tag.children:
            if child.type != "attribute":
                continue
            name = None
            value = None
            for sub in child.children:
                if sub.type == "attribute_name":
                    name = self._text(sub, src).lower()
                elif sub.type in ("attribute_value", "quoted_attribute_value"):
                    raw = self._text(sub, src)
                    value = raw.strip().strip("\"'")
            if name == attr_name.lower():
                return value if value is not None else ""
        return None

    def _script_text(self, element_node, src):
        """Texto interno de un <script>…</script> (entre start/end tag)."""
        for child in element_node.children:
            if child.type in ("raw_text", "text"):
                return self._text(child, src)
        return ""

    def _scan_inline_script(self, block, out):
        if self._script_loader_regex:
            for m in self._script_loader_regex.finditer(block):
                url = m.group(1)
                if url:
                    out.append((url, "fetch"))
        else:
            for m in _INLINE_FETCH_RE.finditer(block):
                url = m.group(1)
                if url:
                    out.append((url, "fetch"))
