"""Filtrado transversal de comentarios (MARKUP-061 II).

Principio (invariante del proyecto): ningún scanner no-AST debe emitir un edge
cuyo target provenga de una región COMENTADA del archivo. Aplica a
HTML/CSS/JS/TS/PHP, en AMBOS tiers (regex y tree-sitter), con paridad.

Decisión de arquitectura: helper transversal único, parametrizado por sintaxis
de comentario por CLASE de lenguaje, consumido por TODOS los passes regex de
TODOS los scanners no-AST. Universal del lenguaje → vive en código, NO en
mapper_config (la sintaxis de comentario no es opt-in; es propiedad del
lenguaje). Por CLASE, nunca por archivo.

Python queda EXENTO: usa el módulo `ast` stdlib, que descarta comentarios por
construcción (un `# import os` jamás produce un nodo import). Por eso `python`
está ausente de `_COMMENT_SYNTAX` a propósito — `strip_comments(text, "python")`
es no-op seguro.

Approach del strip: cada región comentada se REEMPLAZA por espacios del mismo
largo (los `\n` se preservan tal cual). Así se conservan offsets de byte y
números de línea — cero efecto colateral en ningún pass presente o futuro
(PHP-018b empareja `$var = ...` con `require $var` por adyacencia). NO se borra
texto.

String-awareness (el corazón del riesgo): un marcador de comentario DENTRO de
un string literal NO es comentario. Un único paso sobre el texto trackea si
está dentro de `"..."`, `'...'` (y backtick `` `...` `` para JS/TS) y solo
reconoce aperturas de comentario fuera de string. Esto protege `http://`
(el `//` está... fuera de string en código pero el host completo es URL — ver
nota abajo), `#fff` en CSS (`#` no es comentario CSS), `<link href="a//b">`
(dentro de atributo), y marcadores dentro de strings.

Nota sobre `http://` en código: el `//` de `http://` aparece típicamente DENTRO
de un string literal (`$url = "http://x"`), por lo que el string-awareness lo
protege. El caso de un `//` fuera de string que sea parte de una URL desnuda no
es sintaxis válida en estos lenguajes, así que no se contempla.
"""

# Sintaxis de comentario por CLASE de lenguaje. Cada entry: lista de specs.
# spec = (open, close) para block; (line_marker, None) para line.
_COMMENT_SYNTAX = {
    "html": [("<!--", "-->")],
    "css":  [("/*", "*/")],
    "js":   [("/*", "*/"), ("//", None)],
    "ts":   [("/*", "*/"), ("//", None)],
    "php":  [("/*", "*/"), ("//", None), ("#", None)],
    # Python AUSENTE a propósito: usa AST (descarta comentarios por
    # construcción). No se filtra por texto.
}

# Comillas que abren string por clase. HTML/CSS usan `"` y `'`; JS/TS/PHP
# además backtick (template literals JS; PHP no tiene backtick-string pero
# incluirlo es inocuo porque el backtick PHP es shell_exec, raro en estos
# scanners y no contiene marcadores de comentario relevantes).
_STRING_QUOTES = {
    "html": ("\"", "'"),
    "css":  ("\"", "'"),
    "js":   ("\"", "'", "`"),
    "ts":   ("\"", "'", "`"),
    "php":  ("\"", "'"),
}

# Normalización del `language` del pipeline → clase de comentario.
# El pipeline pasa language ∈ {php, javascript, typescript, html, htm, css,
# tsx, jsx}. Tabla en código (no en config).
_LANG_TO_COMMENT_CLASS = {
    "php": "php",
    "javascript": "js",
    "js": "js",
    "typescript": "ts",
    "ts": "ts",
    "tsx": "ts",
    "jsx": "ts",
    "html": "html",
    "htm": "html",
    "css": "css",
}


def _comment_class(language):
    """Normaliza un `language` del pipeline a su clase de comentario, o None
    si no hay sintaxis conocida (no-op seguro)."""
    if not language:
        return None
    return _LANG_TO_COMMENT_CLASS.get(str(language).lower())


def _blank_run(text, start, end):
    """Devuelve una versión de `text[start:end]` con cada char reemplazado por
    espacio salvo los `\n` (preserva líneas/offsets)."""
    return "".join("\n" if c == "\n" else " " for c in text[start:end])


def strip_comments(text, language):
    """Devuelve `text` con las regiones comentadas REEMPLAZADAS por espacios
    del mismo largo (preserva offsets y líneas). String-aware: NO trata como
    comentario un marcador dentro de un string literal. Si `language` no tiene
    sintaxis conocida, devuelve `text` intacto (no-op seguro).
    """
    if not text:
        return text
    cls = _comment_class(language)
    if cls is None:
        return text
    specs = _COMMENT_SYNTAX.get(cls)
    if not specs:
        return text
    quotes = _STRING_QUOTES.get(cls, ("\"", "'"))

    # Separar specs en line-comments y block-comments para el matcher.
    line_markers = [open_ for open_, close in specs if close is None]
    block_specs = [(open_, close) for open_, close in specs if close is not None]

    out = list(text)
    n = len(text)
    i = 0
    in_string = False
    string_quote = ""

    while i < n:
        ch = text[i]

        if in_string:
            # Dentro de string: buscar el cierre. Respetar escape `\` solo en
            # clases que lo soportan (js/ts/php/css usan `\`; html no, pero el
            # backslash en atributos HTML es literal — tratarlo como escape es
            # inofensivo porque no hay `\"` semántico en HTML que rompa esto).
            if ch == "\\" and cls in ("js", "ts", "php", "css"):
                i += 2  # saltar el char escapado
                continue
            if ch == string_quote:
                in_string = False
                string_quote = ""
            i += 1
            continue

        # Fuera de string. ¿Abre un string?
        if ch in quotes:
            in_string = True
            string_quote = ch
            i += 1
            continue

        # ¿Abre un block comment?
        matched_block = False
        for open_, close in block_specs:
            if text.startswith(open_, i):
                # Buscar el cierre (primer cierre gana — no hay anidamiento
                # real en CSS/JS/HTML/PHP).
                close_idx = text.find(close, i + len(open_))
                if close_idx == -1:
                    end = n  # comentario sin cerrar → hasta EOF
                else:
                    end = close_idx + len(close)
                blanked = _blank_run(text, i, end)
                out[i:end] = list(blanked)
                i = end
                matched_block = True
                break
        if matched_block:
            continue

        # ¿Abre un line comment?
        matched_line = False
        for marker in line_markers:
            if text.startswith(marker, i):
                nl_idx = text.find("\n", i)
                end = n if nl_idx == -1 else nl_idx  # no neutralizar el \n
                blanked = _blank_run(text, i, end)
                out[i:end] = list(blanked)
                i = end
                matched_line = True
                break
        if matched_line:
            continue

        i += 1

    return "".join(out)
