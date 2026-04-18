"""outbound_resolver — clasificación de raw imports a file/external/discard.

Extraído de `compass/core.py` (REF-033). Centraliza GRF-021 (external
services), NET-022 (URL-based resolution), NET-023 (auto-promoción de
imports no resueltos) y TIER-035 (ranking stdlib/package/wrapper/service).

Contrato (usado por pipeline.py):
    classify_outbound(state, raw, language, source_abs, unify_lower)
        → {"kind": "file" | "external" | "discard", "label": str | None, ...}

`state` es el caller (`ArchitectCompass`) con:
    self.path_resolver, self.project_root, self.external_services,
    self._external_index, self._external_url_index, self.graph_rules,
    self.config, self.asset_extensions, self.ignore_files,
    self.ignore_patterns.

Parte de la API se expone como mixin (`OutboundResolverMixin`) para
preservar los nombres privados históricos (`self._classify_outbound`,
`self._is_asset_target`, etc.) sin romper invocaciones internas.
"""

import fnmatch
import os
import re
from pathlib import Path
from urllib.parse import urlparse as _urlparse

from compass.stdlib_filter import is_python_stdlib as _is_python_stdlib


# TIER-035 — ranking para que un segundo registro de un mismo external no
# degrade su tier. service gana siempre (señal de red externa).
_TIER_RANK = {"stdlib": 1, "package": 2, "wrapper": 3, "service": 4}


def _tier_rank(tier):
    return _TIER_RANK.get(tier, 0)


# NET-023 — regex de identifier Python válido (ASCII-only, primer char
# letra o underscore). Usado por `_auto_promote_external` para no
# promover cualquier basura (ej. fragmentos accidentales del scanner).
_PY_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


# FIX-030 — Dotfiles de config que NUNCA deben aparecer como targets
# del grafo, aunque el usuario haya overriden ignore_patterns vaciándolo.
# Defense-in-depth para el caso disparador 2026-04-16: cerbero-setup/.env
# apareciendo como nodo `AI-Agent-Framework` en level2agent-engine.
_DOTFILE_TARGET_PATTERNS = (
    ".env", ".env.*",
    ".gitignore", ".gitattributes",
    ".editorconfig",
    ".prettierrc", ".prettierrc.*",
    ".eslintrc", ".eslintrc.*",
)


def build_external_index(services):
    """Normaliza external_services para lookup rápido.

    Acepta dos shapes de config:
      - dict[id, {match:[...], label:...}]   (formato actual, preferido)
      - list[{label:..., match:[...]}]       (formato legacy, PLAN-compat)

    Devuelve list[(needle_lower, display_label)]. El orden se preserva
    para que el primer match gane en caso de empate (raro pero posible).
    """
    out = []
    if isinstance(services, dict):
        iterable = services.values()
    elif isinstance(services, list):
        iterable = services
    else:
        return out
    for entry in iterable:
        if not isinstance(entry, dict):
            continue
        label = entry.get("label") or entry.get("name") or ""
        matches = entry.get("match") or []
        if not label or not isinstance(matches, list):
            continue
        for needle in matches:
            if not needle:
                continue
            out.append((str(needle).strip().lower(), str(label).strip()))
    return out


def build_external_url_index(services):
    """NET-022 — Construye índice de URL patterns para matchear hosts.

    Acepta dos shapes de config (dict o list, como build_external_index).
    Devuelve list[(compiled_regex, display_label)]. Cada entry de
    `external_services` puede tener un campo `match_urls` (lista de regex
    patterns aplicados contra el hostname extraído de la URL).
    """
    out = []
    if isinstance(services, dict):
        iterable = services.values()
    elif isinstance(services, list):
        iterable = services
    else:
        return out
    for entry in iterable:
        if not isinstance(entry, dict):
            continue
        label = entry.get("label") or entry.get("name") or ""
        url_patterns = entry.get("match_urls") or []
        if not label or not isinstance(url_patterns, list):
            continue
        for pattern in url_patterns:
            if not pattern:
                continue
            try:
                compiled = re.compile(str(pattern), re.IGNORECASE)
                out.append((compiled, str(label).strip()))
            except re.error:
                continue
    return out


# Session 8 — NET-022b. Hostnames locales / de red privada (RFC 1918)
# no son dependencias externas reales: son dev-noise (p.ej. `localhost`,
# `127.0.0.1`, `192.168.x.x`) que ensucia el grafo.
def _is_local_hostname(host):
    """True si `host` es loopback, wildcard o red privada RFC 1918."""
    if not host:
        return False
    h = str(host).strip().lower()
    if ":" in h:
        h = h.split(":", 1)[0]
    if h in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        return True
    if h.startswith("192.168.") or h.startswith("10."):
        return True
    # RFC 1918: 172.16.0.0/12 → 172.16.x.x a 172.31.x.x
    if h.startswith("172."):
        parts = h.split(".")
        if len(parts) >= 2:
            try:
                second = int(parts[1])
                if 16 <= second <= 31:
                    return True
            except ValueError:
                pass
    return False


class OutboundResolverMixin:
    """Mixin con los métodos de clasificación de outbound imports.

    Consume: `self.path_resolver`, `self.project_root`, `self.config`,
        `self.graph_rules`, `self.external_services`, `self._external_index`,
        `self._external_url_index`, `self.asset_extensions`,
        `self.ignore_files`, `self.ignore_patterns`.
    """

    # Expuesto como atributos de clase por backward-compat (validation/tests).
    _DOTFILE_TARGET_PATTERNS = _DOTFILE_TARGET_PATTERNS
    _PY_IDENT_RE = _PY_IDENT_RE

    @staticmethod
    def _build_external_index(services):
        return build_external_index(services)

    @staticmethod
    def _build_external_url_index(services):
        return build_external_url_index(services)

    @staticmethod
    def _is_local_hostname(host):
        return _is_local_hostname(host)

    def _match_external_service(self, cleaned):
        """Devuelve el display label si `cleaned` matchea algún external_service.

        Match por:
          - igualdad lower-case contra cualquier needle
          - primer segmento antes de `/` (para paquetes scoped tipo
            `@anthropic-ai/sdk`, el full string es la needle natural)
          - prefijo de namespace PHP (`Anthropic\\Anthropic\\Client` matchea
            needle `anthropic\\anthropic`).
        """
        if not cleaned:
            return None
        c = cleaned.lower()
        for needle, label in self._external_index:
            if not needle:
                continue
            if c == needle or c.startswith(needle + "/") or c.startswith(needle + "\\"):
                return label
            # Bare npm package (ej: needle "openai" matchea "openai",
            # "openai@latest", "openai/resources").
            head = c.split("/", 1)[0].lstrip("@")
            if head == needle.lstrip("@"):
                return label
        return None

    def _match_external_by_url(self, hostname):
        """NET-022 — Devuelve display label si `hostname` matchea algún
        pattern de `external_services[*].match_urls`. None si no matchea.
        """
        if not hostname:
            return None
        h = hostname.lower()
        for regex, label in self._external_url_index:
            if regex.fullmatch(h):
                return label
        return None

    def _classify_outbound(self, raw, language, source_abs, unify_lower):
        """GRF-021 — clasifica un raw outbound en una de 3 categorías:

            kind="file"     → resuelve a un archivo del repo.
                              label = posix path relativo a project_root.
            kind="external" → matchea algún external_service declarado.
                              label = "[EXTERNAL:<DisplayLabel>]"
                              label_display = DisplayLabel
            kind="discard"  → builtin/stdlib/lib local/no-resolvable.
                              label = None  (el caller lo mete en metadata.calls)

        Precedencia: archivo del repo > external_service > unify_external_nodes
        (legacy) > discard.
        """
        if raw is None:
            return {"kind": "discard", "label": None}
        cleaned = str(raw).strip().strip("'\"`").strip()
        if not cleaned:
            return {"kind": "discard", "label": None}

        # 0. NET-022 — URL literal → external by host.
        #    URLs no son paths resolvibles — desviar ANTES del resolve() para
        #    evitar un wasted lookup y un posible false positive si hay un
        #    archivo con nombre parecido. urlparse es stdlib, zero-cost.
        _parsed_url = _urlparse(cleaned)
        if _parsed_url.scheme in ("http", "https") and _parsed_url.hostname:
            host = _parsed_url.hostname.lower()
            # NET-022b: descartar loopback / wildcard / redes privadas
            # (RFC 1918). Son dev-noise, no dependencias funcionales.
            if self._is_local_hostname(host):
                return {"kind": "discard", "label": cleaned}
            label = self._match_external_by_url(host) or host
            # TIER-035 — URL → service (red externa).
            return {
                "kind": "external",
                "label": f"[EXTERNAL:{label}]",
                "label_display": label,
                "tier": "service",
            }

        # 1. Archivo del repo (precedencia máxima).
        resolved_abs = self.path_resolver.resolve(raw, language, source_abs)
        if resolved_abs:
            try:
                posix = Path(resolved_abs).resolve().relative_to(
                    self.project_root
                ).as_posix()
                return {"kind": "file", "label": posix}
            except ValueError:
                pass  # Fuera del project_root — seguir clasificando.

        # 2. External service declarado (Level 1 — GRF-021).
        #    Cubre SDKs por nombre de import. Las URLs absolutas ya se
        #    desvían en paso 0 (NET-022) — no llegan acá.
        ext_label = self._match_external_service(cleaned)
        if ext_label:
            # TIER-035 — SDK declarado (import match) → service.
            # Los external_services cubren casi siempre red externa.
            return {
                "kind": "external",
                "label": f"[EXTERNAL:{ext_label}]",
                "label_display": ext_label,
                "tier": "service",
            }

        # 3. Legacy `unify_external_nodes` — se mantiene como categoría
        #    external genérica para backward-compat con proyectos cuyos
        #    archivos cacheaban este tipo de label. En runs nuevos estos
        #    también terminan clasificándose bien (GRF-021 cubre los SDKs
        #    comunes), pero no invalidamos el path.
        lower = cleaned.lower()
        head = lower.split("/", 1)[0].lstrip("@")
        if lower in unify_lower or head in unify_lower:
            # Tratamos el unify como external genérico: mismo shape, label
            # = nombre del paquete. Evita regresión visual en grafos viejos.
            display = head if head in unify_lower else lower
            # TIER-035 — legacy unify son bare names de paquetes (fetch,
            # axios, anthropic). Clasificamos como package por default;
            # si es un wrapper declarado, el branch final lo resuelve más
            # abajo (no — ese branch corre después; acá elegimos package).
            return {
                "kind": "external",
                "label": f"[EXTERNAL:{display}]",
                "label_display": display,
                "tier": self._classify_external_tier(
                    display, language, is_service=False,
                ),
            }

        # 4. NET-023 — auto-promoción de imports no resueltos a externals.
        promoted = self._auto_promote_external(cleaned, language)
        if promoted:
            return {
                "kind": "external",
                "label": f"[EXTERNAL:{promoted}]",
                "label_display": promoted,
                "tier": self._classify_external_tier(
                    promoted, language, is_service=False,
                ),
            }

        # 5. Resto (builtins, stdlib, funciones de framework, libs locales
        #    sin resolver, URLs absolutas http/https no-declaradas, imports
        #    PHP sin match). NO emiten nodo ni edge. Se acumulan en
        #    metadata.calls del nodo fuente para no perder la señal.
        return {"kind": "discard", "label": cleaned}

    def _auto_promote_external(self, cleaned, language):
        """NET-023 — devuelve el head del import si califica como external.

        Llamado SOLO en el fallback de `_classify_outbound`, después de
        agotar resolución repo + external_services + unify_external_nodes.
        No aplica a PHP (retorna None).

        Retorna:
            - string (el head a usar como display label) si promueve.
            - None si el raw no califica (caerá al discard).
        """
        if not cleaned:
            return None
        lang = (language or "").lower()

        if lang == "python":
            # Relativo → no promover (es del repo, falló la resolución;
            # mejor dejarlo en metadata.calls como señal de bug).
            if cleaned.startswith("."):
                return None
            # El scanner Python emite `pkg.sub:name` o `pkg.sub`. Separamos
            # por `:` (from-import) y por `.` (submodule). Head = primer
            # segmento antes de ambos separadores.
            module_part = cleaned.split(":", 1)[0]
            if "/" in module_part or "\\" in module_part:
                return None
            head = module_part.split(".", 1)[0].strip()
            if not head or not self._PY_IDENT_RE.match(head):
                return None
            # NET-023 complement — stdlib filter. Por default ocultamos
            # `os`, `sys`, `json`, `re`, `pathlib`, etc. del grafo (son ruido,
            # nunca son una dep real del proyecto). El user puede revertir
            # seteando `external_include_stdlib: true` en mapper_config.json
            # o en su compass.local.json.
            if not self.config.get("external_include_stdlib", False):
                if _is_python_stdlib(head):
                    return None
            return head

        if lang in ("javascript", "typescript", "jsx", "tsx"):
            # Bare specifier: no empieza con `.` ni con `/` ni con `\`.
            # Los schemes `http://` / `https://` / `//` YA fueron excluidos
            # por el path_resolver (devolvió None sin consumirlos) pero
            # aparecen acá como `cleaned`. Filtrar explícitamente.
            if (
                cleaned.startswith(".")
                or cleaned.startswith("/")
                or cleaned.startswith("\\")
            ):
                return None
            low = cleaned.lower()
            if (
                low.startswith("http://")
                or low.startswith("https://")
                or low.startswith("//")
                or ":" in cleaned.split("/", 1)[0]  # protocolos genéricos
            ):
                return None
            # Scoped package `@scope/pkg[/sub]` → head = `@scope/pkg`.
            if cleaned.startswith("@"):
                parts = cleaned.split("/")
                if len(parts) < 2 or not parts[0][1:] or not parts[1]:
                    return None
                return parts[0] + "/" + parts[1]
            # No-scoped: head = primer segmento.
            head = cleaned.split("/", 1)[0].strip()
            if not head:
                return None
            return head

        # PHP y otros: no aplica NET-023 hoy.
        return None

    def _is_asset_target(self, rel_path):
        """AST-024 — True si el target tiene una extensión de asset binario."""
        if not self.asset_extensions:
            return False
        ext = os.path.splitext(rel_path)[1].lower()
        return ext in self.asset_extensions

    def _is_ignored_target(self, rel_path):
        """AST-024 (scope extendido) — True si el target matchea ignore_*.

        Respeta `ignore_files` (path exacto) e `ignore_patterns` (globs
        fnmatch) también en la emisión de edges, no sólo en el índice de
        scan.

        FIX-030 — defense-in-depth: dotfiles de config (`.env`, `.gitignore`,
        `.eslintrc*`, etc.) SIEMPRE se filtran como targets del grafo.
        """
        if rel_path in self.ignore_files:
            return True
        basename = os.path.basename(rel_path)
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(basename, pattern) or fnmatch.fnmatch(rel_path, pattern):
                return True
        # FIX-030 — piso mínimo independiente de la config.
        for pattern in self._DOTFILE_TARGET_PATTERNS:
            if fnmatch.fnmatch(basename, pattern):
                return True
        return False

    def _classify_external_tier(self, display_label, language, is_service):
        """TIER-035 — clasificación de tier para externals.

        `service` se setea directamente en `_classify_outbound` cuando hay match
        de URL o de external_service declarado. Este helper cubre la rama donde
        el external se resolvió por nombre de paquete (unify legacy o
        auto-promote).
        """
        if is_service:
            return "service"
        if not display_label:
            return "package"
        # Wrapper? El config `graph.external_wrappers` agrupa nombres
        # custom por lenguaje + "any" (cross-lang).
        if self._is_external_wrapper(display_label, language):
            return "wrapper"
        # Stdlib? Hoy solo Python tiene tabla confiable.
        head = str(display_label).split("/", 1)[0].split(".", 1)[0]
        lang = (language or "").lower()
        if lang == "python" and _is_python_stdlib(head):
            return "stdlib"
        return "package"

    def _tier_from_display(self, display_label, language=None):
        """TIER-035 — tier a partir del display label del external.

        Usado en rutas donde no hay contexto del raw (ej. cached replay).
        Heurística:
          - URL-like (contiene `.` y TLD reconocible o match vs URL index) → service.
          - Match por nombre contra `external_services[*].match` → service.
          - Wrapper custom → wrapper.
          - Stdlib Python → stdlib.
          - Resto → package.
        """
        if not display_label:
            return "package"
        # Service by URL host match.
        if self._match_external_by_url(display_label):
            return "service"
        # Service by name — scan external_services labels.
        for entry in (self.external_services.values()
                      if isinstance(self.external_services, dict)
                      else (self.external_services or [])):
            if isinstance(entry, dict):
                lbl = (entry.get("label") or "").strip()
                if lbl and lbl == str(display_label).strip():
                    return "service"
        return self._classify_external_tier(
            display_label, language, is_service=False,
        )

    def _is_external_wrapper(self, display_label, language):
        """TIER-035 — True si `display_label` está en `graph.external_wrappers`.

        Busca en la lista del lenguaje específico y en "any". Match
        case-insensitive por nombre completo del display (ej. `apiReq`).
        """
        wrappers_cfg = (self.graph_rules.get("external_wrappers") or {})
        if not isinstance(wrappers_cfg, dict):
            return False
        lang = (language or "").lower()
        candidates = set()
        for key in ("any", lang):
            lst = wrappers_cfg.get(key) or []
            if isinstance(lst, list):
                for name in lst:
                    if name:
                        candidates.add(str(name).lower())
        return str(display_label).lower() in candidates

    def _reclassify_cached_target(self, tgt):
        """Devuelve (kind, display_label) para un target cacheado.

        Los labels del cache vienen ya normalizados: o son paths repo-relativos
        (archivo), o son labels tipo `[EXTERNAL:Anthropic]` (external), o son
        bare names (legacy `unify_external_nodes`). Distinguimos por el formato
        del string — sin tocar el cache.
        """
        if tgt.startswith("[EXTERNAL:") and tgt.endswith("]"):
            return "external", tgt[len("[EXTERNAL:"):-1]
        if tgt in self._file_registry_paths_set():
            return "file", tgt
        # Legacy: label externo tipo `anthropic`. Reemitir como file-ish
        # edge coloreado rojo para preservar visual. GRF-021 ya no genera
        # estos nuevos, pero si existen en cache vieja los tratamos como
        # external genérico.
        return "external_legacy", tgt

    def _register_edge(self, src_rel, target_label, kind, edge_type=None):
        """EDG-023 — persiste un edge estructurado.

        Guarda `(src, target, edge_type, kind)` en `self._edges`. El
        rendering final al `.dot` lo hace `graph_emitter.build_dot_content`
        con colores por `edge_type` y kind (GRF-013).
        """
        et = edge_type or self.default_edge_type
        self._edges.append((src_rel, target_label, et, kind))

    def _register_external_node(self, node_label, display_label, tier=None):
        """Registra un nodo `[EXTERNAL:X]` para renderizarlo con shape/color.

        Unifica por label — múltiples sources apuntando al mismo external
        reusan el mismo nodo.

        TIER-035 — `tier` opcional (`stdlib|package|service|wrapper`). Se
        guarda en `self._external_node_tiers`. Si ya existe una entrada con
        un tier más específico (p.ej. service), NO se degrada a package —
        los services ganan (son la señal más fuerte).
        """
        self._external_nodes[node_label] = display_label
        if tier:
            # Precedencia entre tiers: service > wrapper > package > stdlib.
            # Evita que un segundo pass (p.ej. cache replay con tier='package')
            # pise a un URL-match previo (tier='service').
            existing = self._external_node_tiers.get(node_label)
            if not existing or _tier_rank(tier) > _tier_rank(existing):
                self._external_node_tiers[node_label] = tier