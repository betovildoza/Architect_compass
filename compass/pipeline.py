"""pipeline — analyze() orchestration (scan loop + wiring).

Extraído de `compass/core.py` (REF-033). Coordina scanners (SCN-003),
PathResolver (RES-002), StackDetector (STK-001), outbound classification
(GRF-021/NET-022/NET-023/TIER-035), metadata collection (GRF-021/AST-024),
dynamic deps (DYN-007), entry points (GRAPH-036) y orphans.

Se expone como mixin (`AnalyzePipelineMixin`) para preservar firmas
internas. Depende de los atributos de `ArchitectCompass` y de los métodos
de `OutboundResolverMixin`.
"""

import fnmatch
import os
import re
from pathlib import Path

from compass.scanners import (
    languages_without_scanner,
    reset_cache as reset_scanner_cache,
)
from compass.stack_detector import resolve_file_stack


# Mapping extensión → lenguaje. Autoritativo para decidir qué scanner usar:
# el stack da contexto semántico (WordPress vs. Vanilla-PHP), pero el
# lenguaje del archivo lo determina su extensión.
_EXTENSION_LANGUAGE = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".php": "php",
    ".rb": "ruby",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
}


def _language_for_file(filename):
    """Devuelve el nombre de lenguaje para `filename` según su extensión."""
    ext = os.path.splitext(filename)[1].lower()
    return _EXTENSION_LANGUAGE.get(ext, "")


def _definition_applies_to_stack(definition, file_stack):
    """DEF-025 — guardián de contexto por stack.

    Para configs pre-DEF-025 que declaran `stack` (o `stacks`) en una
    definition, validar que el stack del archivo coincida antes de sumar
    `tech_scores`. Esto evita que una regex pensada para `Tauri` matchee
    sobre un `.js` vanilla y genere la identity falsa `Tauri-Desktop-App-JS`
    en un proyecto HTML+PHP.

    Reglas:
      - Si la definition NO declara `stack` ni `stacks` → aplica a todos
        (language-based post-DEF-025 — el filtro de lenguaje ya actuó
        antes, acá solo chequeamos si hay restricción adicional por stack).
      - Si declara `stack` (string) → match exacto case-insensitive.
      - Si declara `stacks` (lista) → cualquiera matchea.
      - Si `file_stack` es vacío y la definition restringe stack, no aplica.
    """
    declared_single = definition.get("stack")
    declared_list = definition.get("stacks")
    if not declared_single and not declared_list:
        return True
    declared = []
    if declared_single:
        declared.append(str(declared_single).lower())
    if declared_list:
        declared.extend(str(x).lower() for x in declared_list)
    if not file_stack:
        return False
    return str(file_stack).lower() in declared


class AnalyzePipelineMixin:
    """Mixin con analyze() + helpers (file indexing, orphans).

    La detección de entry points (GRAPH-036) se extrae a `EntryPointsMixin`
    (`compass/entry_points.py`) para mantener cada módulo dentro del límite
    de tamaño del REF-033.
    """

    # ------------------------------------------------------------------
    # File indexing / ignore rules (IGN-016)
    # ------------------------------------------------------------------
    def _index_existing_files(self):
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in self.ignore_folders]
            for file in files:
                if not any(file.endswith(ext) for ext in self.text_extensions):
                    continue
                rel_path = os.path.relpath(
                    os.path.join(root, file), self.project_root
                ).replace("\\", "/")
                if self._is_ignored(rel_path, file):
                    continue
                self.file_registry[rel_path] = rel_path
                path_no_ext = os.path.splitext(rel_path)[0]
                self.file_registry[path_no_ext] = rel_path
                self.file_registry[path_no_ext.replace("/", ".")] = rel_path

    def _is_ignored(self, rel_path, filename):
        """IGN-016: True si el archivo match-ea ignore_files o ignore_patterns.

        - `ignore_files`: path exacto (posix, relativo a project_root).
        - `ignore_patterns`: glob fnmatch; se prueba contra basename y rel_path.
        """
        if rel_path in self.ignore_files:
            return True
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(rel_path, pattern):
                return True
        return False

    # ------------------------------------------------------------------
    # SEM-020 — detección de roots WordPress para el PathResolver
    # ------------------------------------------------------------------
    def _detect_wp_roots(self):
        """Detecta `theme_root` y `plugins_root` absolutos si el proyecto
        tiene un sub-árbol WordPress. Devuelve `(theme_root, plugins_root)`
        — cada uno puede ser None si no se detecta.

        Heurística mínima (sin I/O extra — sólo consulta stack_map):
            - Si algún subdir del stack_map tiene stack 'WordPress-Development'
              y existe `functions.php` dentro, es candidato a theme_root.
            - Si el proyecto root contiene `themes/<X>/functions.php`,
              elegimos ese como theme_root.
            - plugins_root = el primer `wp-content/plugins/` absoluto que
              encontremos, o `<project_root>/wp-content/plugins` como fallback
              si existe.

        Para ETCA (themes/etca-aula/functions.php) el resultado es
        `theme_root = <project>/themes/etca-aula`. Para proyectos non-WP,
        ambos son None y el PathResolver usa project_root como fallback.
        """
        theme_root = None
        plugins_root = None

        # 1. Preferir candidatos del stack_map con stack WordPress-Development.
        wp_stack_keys = [
            rel for rel, stack in getattr(self, "stack_map", {}).items()
            if rel and "WordPress" in str(stack)
        ]
        # 2. Buscar directorios con functions.php (theme marker).
        candidates = []
        for rel in wp_stack_keys:
            p = self.project_root / rel
            if (p / "functions.php").is_file():
                candidates.append(p)
        # Fallback: walk `themes/` si existe (hasta 2 niveles).
        themes_dir = self.project_root / "themes"
        if not candidates and themes_dir.is_dir():
            try:
                for child in themes_dir.iterdir():
                    if child.is_dir() and (child / "functions.php").is_file():
                        candidates.append(child)
            except OSError:
                pass
        # wp-content/themes/<X>/functions.php
        wp_themes = self.project_root / "wp-content" / "themes"
        if not candidates and wp_themes.is_dir():
            try:
                for child in wp_themes.iterdir():
                    if child.is_dir() and (child / "functions.php").is_file():
                        candidates.append(child)
            except OSError:
                pass
        if candidates:
            theme_root = candidates[0].resolve()

        # 3. plugins_root: `wp-content/plugins` bajo project_root o
        #    directamente `plugins/` si el proyecto es el wp-content mismo.
        for rel in ("wp-content/plugins", "plugins"):
            cand = self.project_root / rel
            if cand.is_dir():
                plugins_root = cand.resolve()
                break

        return theme_root, plugins_root

    # ------------------------------------------------------------------
    # Dynamic deps (DYN-007)
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_dynamic_deps(raw):
        """Normaliza `dynamic_deps` del config a dict[str, list[str]]."""
        out = {}
        if not isinstance(raw, dict):
            return out
        for owner, value in raw.items():
            if not isinstance(owner, str):
                continue
            owner_norm = owner.replace("\\", "/").strip()
            if not owner_norm or owner_norm.startswith("_"):
                continue
            targets = []
            if isinstance(value, list):
                targets = [str(t).replace("\\", "/").strip() for t in value if t]
            elif isinstance(value, dict):
                raw_targets = value.get("targets") or []
                if isinstance(raw_targets, list):
                    targets = [str(t).replace("\\", "/").strip() for t in raw_targets if t]
            elif isinstance(value, str):
                # Descripción libre: el owner queda declarado pero sin
                # targets concretos. Aún así se marca como dynamic_declared
                # si aparece como huérfano (cubre autoloaders pasivos).
                targets = []
            out[owner_norm] = targets
        return out

    def _dynamic_target_set(self):
        """Set de todos los targets cubiertos por dynamic_deps."""
        out = set()
        for targets in self._dynamic_deps.values():
            for t in targets:
                out.add(t)
        return out

    # ------------------------------------------------------------------
    # Stack resolution por archivo (STK-001 + MST-006)
    # ------------------------------------------------------------------
    def resolve_stack_for(self, rel_path):
        """Stack aplicable a `rel_path` vía longest-prefix match en stack_map."""
        return resolve_file_stack(rel_path, self.stack_map)

    # ------------------------------------------------------------------
    # Analyze pipeline
    # ------------------------------------------------------------------
    def analyze(self):
        tech_scores = {}
        stack_file_counts = {}

        # INC-008: invalidar cache de scanners antes de cada run para evitar
        # servir scanners con patterns viejas si la config se recargó en el
        # mismo proceso (ver SESSION_LOG.md Sesión 4 hallazgo #5).
        reset_scanner_cache()

        # Pre-compilar inbound regex por definition (SCN-003 deja el
        # outbound al scanner dispatcher; inbound sigue aquí porque es
        # scoring de identidades, no graph building).
        inbound_index = self._compile_inbound_patterns()

        unify_list = self.graph_rules.get("unify_external_nodes", [])
        unify_lower = {item.lower() for item in unify_list}
        ignore_outbound_patterns = self.graph_rules.get(
            "ignore_outbound_patterns", []
        )
        compiled_ignore_outbound = [
            re.compile(p, re.I) for p in ignore_outbound_patterns
        ]

        scanned = 0
        reused = 0

        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in self.ignore_folders]

            for file in files:
                if not any(file.endswith(ext) for ext in self.text_extensions):
                    continue
                file_path = Path(root) / file
                rel_path = file_path.relative_to(self.project_root).as_posix()
                if self._is_ignored(rel_path, file):
                    continue

                self.atlas["summary"]["total_files"] += 1
                self._all_scanned_files.append(rel_path)

                # Stack por archivo (longest-prefix match en StackMap).
                file_stack = self.resolve_stack_for(rel_path)
                stack_file_counts[file_stack] = stack_file_counts.get(file_stack, 0) + 1

                # Lenguaje por archivo (autoritativo por extensión).
                language = _language_for_file(file)

                # INC-008: fingerprint + cache lookup
                fingerprint = self._file_fingerprint(file_path)
                cached = self.previous_cache.get(rel_path)
                use_cached = (
                    not self.force_full
                    and fingerprint is not None
                    and isinstance(cached, dict)
                    and cached.get("fingerprint") == fingerprint
                )

                try:
                    if use_cached:
                        is_relevant = self._apply_cached_scan(
                            rel_path=rel_path,
                            cached=cached,
                            tech_scores=tech_scores,
                        )
                        # El cache mantiene su estructura tal cual, con
                        # fingerprint actualizado por las dudas (y stack
                        # del run actual, que puede haber cambiado).
                        self.current_cache[rel_path] = dict(cached)
                        self.current_cache[rel_path]["stack"] = file_stack
                        reused += 1
                    else:
                        (
                            is_relevant, file_outbound, file_inbound,
                            file_tech_delta, file_metadata_calls,
                        ) = self._scan_file(
                            file_path=file_path,
                            rel_path=rel_path,
                            filename=file,
                            language=language,
                            file_stack=file_stack,
                            inbound_index=inbound_index,
                            tech_scores=tech_scores,
                            unify_lower=unify_lower,
                            compiled_ignore_outbound=compiled_ignore_outbound,
                        )
                        if file_metadata_calls:
                            self._metadata_calls[rel_path] = file_metadata_calls
                        if fingerprint is not None:
                            # EDG-023 — guardar edge_types por target para
                            # reproducir el label en runs cacheados. Se
                            # extraen de `self._edges` filtrando por src.
                            edge_types = {
                                tgt: et for (s, tgt, et, _k) in self._edges
                                if s == rel_path
                            }
                            # AST-024 — persistir assets/filtered_refs por
                            # archivo para que el replay cacheado preserve
                            # metadata + filter counts consistentes entre runs.
                            self.current_cache[rel_path] = {
                                "fingerprint": fingerprint,
                                "outbound_targets": file_outbound,
                                "inbound_patterns": file_inbound,
                                "tech_scores": file_tech_delta,
                                "is_relevant": is_relevant,
                                "stack": file_stack,
                                "metadata_calls": file_metadata_calls,
                                "edge_types": edge_types,
                                "metadata_assets": list(
                                    self._metadata_assets.get(rel_path, [])
                                ),
                                "metadata_filtered_refs": list(
                                    self._metadata_filtered_refs.get(rel_path, [])
                                ),
                            }
                        scanned += 1

                    if is_relevant:
                        self.atlas["summary"]["relevant_files"] += 1
                except Exception as e:
                    self.atlas["anomalies"].append(f"{rel_path}: {str(e)}")

                # CLI-015 — hook de progreso opcional (no-op si no se setea).
                # El callback recibe (rel_path, scanned_count, reused_count)
                # — la CLI lo usa para alimentar el progress bar de rich.
                cb = getattr(self, "_progress_callback", None)
                if cb is not None:
                    try:
                        cb(rel_path, scanned, reused)
                    except Exception:
                        # Defensivo: un bug en la UI no debe romper el scan.
                        pass

        # INC-008: dejar visible cuántos archivos se reutilizaron del cache.
        self.atlas["summary"]["scanned_files"] = scanned
        self.atlas["summary"]["reused_from_cache"] = reused

        # Feedback: lenguajes que no tuvieron scanner disponible.
        missing = {m for m in languages_without_scanner() if m}
        if missing:
            self.atlas["audit"]["warnings"].append(
                "Sin scanner disponible: " + ", ".join(sorted(missing))
            )

        # Identidades regex-based (scanner Tier 3) + stack detection (STK-001).
        # Se listan ambas fuentes: tech_scores vienen de patterns matcheados,
        # stack_file_counts viene de la jerarquía lock/framework/content/ext.
        identity_index = {}
        for name, score in tech_scores.items():
            identity_index[name] = {
                "tech": name,
                "confidence": min(score, 100),
                "source": "patterns",
            }
        for stack_name, count in stack_file_counts.items():
            if stack_name in identity_index:
                identity_index[stack_name]["files"] = count
                identity_index[stack_name]["source"] = "patterns+stack_markers"
            else:
                identity_index[stack_name] = {
                    "tech": stack_name,
                    "confidence": min(count, 100),
                    "files": count,
                    "source": "stack_markers",
                }
        self.atlas["identities"] = list(identity_index.values())

        # GRAPH-036 — detectar entry points del proyecto (ANTES de compute_orphans
        # para que entry_points esté disponible en el check de exclusión de orphans).
        self._detect_entry_points()

        # DYN-007: clasificar orphans. Un archivo es huérfano cuando ningún
        # otro archivo del proyecto lo referencia (no aparece como destino
        # en outbound). Si está declarado como owner o como target en
        # `dynamic_deps`, se marca con orphan_reason="dynamic_declared".
        # Entry points también se excluyen de ser marcados como huérfanos (BUG-1 fix).
        self._compute_orphans()

        self.run_audit()

    # ------------------------------------------------------------------
    # Scan por archivo (delegado a scanner + PathResolver)
    # ------------------------------------------------------------------
    def _compile_inbound_patterns(self):
        """Compila inbound regex por definition. Devuelve lista de tuplas
        (definition_name, definition_dict, [compiled_patterns]).

        DEF-017: la `definition_dict` se conserva para que el caller pueda
        decidir si aplica al lenguaje del archivo (vía
        `_definition_applies_to_language`).
        """
        out = []
        for df in self.config.get("definitions", []) or []:
            patterns = df.get("patterns", {}) or {}
            compiled = []
            for pat in patterns.get("inbound", []) or []:
                try:
                    compiled.append((pat, re.compile(pat, re.I)))
                except re.error:
                    continue
            if compiled:
                out.append((df.get("name", "unknown"), df, compiled))
        return out

    # _scan_file y _apply_cached_scan se extraen a compass.scan_worker
    # (ScanWorkerMixin) para mantener tamaños bajo el límite del REF-033.

    # ------------------------------------------------------------------
    # Orphans (DYN-007) + audit
    # ------------------------------------------------------------------
    def _compute_orphans(self):
        """DYN-007: clasifica archivos según participación y criterios explícitos.

        Reglas (SESIÓN 20 — ITEM 1):
          - Archivo es "participante" si es source OR target de algún edge.
          - Si NO participante Y NO es entry point → candidato a tier "ambiguous"
            o "orphan", según criterio explícito.
          - tier "orphan": archivo con evidencia explícita de descarte (patrón de
            nombre, doc, config). Por ahora CONSERVADOR → vacío hasta criterios.
          - tier "ambiguous": archivo SIN inbound, SIN entry point, SIN criterio
            de descarte. Representa incertidumbre (puede ser legítimo no-usado,
            puede ser muerto). Conservador por diseño.
          - Si está en `dynamic_deps`, se marca con `tier: "dynamic"` (es una
            categoría también).
          - Cada archivo se registra en `atlas.files[rel_path]` con su
            stack, tier y, si aplica, razones.

        18B fix: Incluir AMBOS sources y targets. Un archivo con outbound edges
        (es source) no debe ser orphan aunque nadie lo importe.
        """
        # Construir set de sources Y targets internos (paths relativos al proyecto).
        internal_sources = set()
        internal_targets = set()
        file_registry = self._file_registry_paths_set()
        for edge in self.atlas["connectivity"]["outbound"]:
            try:
                source, target = edge.split(" -> ", 1)
            except ValueError:
                continue
            source = source.strip()
            target = target.strip()
            if source in file_registry:
                internal_sources.add(source)
            if target in file_registry:
                internal_targets.add(target)

        dynamic_targets = self._dynamic_target_set()
        dynamic_owners = set(self._dynamic_deps.keys())
        entry_points_set = set(self.atlas.get("entry_points", []))
        # Un archivo es "participante" si es source OR target de algún edge
        internal_participants = internal_sources | internal_targets

        # Inicializar listas de tiers
        self.atlas["ambiguous"] = []

        for rel_path in self._all_scanned_files:
            node = {
                "stack": self.resolve_stack_for(rel_path),
            }
            is_participant = rel_path in internal_participants
            is_entry_point = rel_path in entry_points_set

            # Clasificar según tier
            if rel_path in dynamic_owners or rel_path in dynamic_targets:
                node["tier"] = "dynamic"
                node["reason"] = "declared_in_dynamic_deps"
                if rel_path in dynamic_owners and self._dynamic_deps[rel_path]:
                    node["dynamic_targets"] = list(self._dynamic_deps[rel_path])
            elif is_participant or is_entry_point:
                node["tier"] = "connected"
            else:
                # No participante, no entry point, no dynamic
                # Aplicar criterio explícito para orphan vs ambiguous
                if self._should_be_explicit_orphan(rel_path):
                    node["tier"] = "orphan"
                    node["reason"] = "explicit_pattern"
                    self.atlas["orphans"].append(rel_path)
                else:
                    node["tier"] = "ambiguous"
                    node["reason"] = "no_inbound_no_entry_point"
                    self.atlas["ambiguous"].append(rel_path)

            self.atlas["files"][rel_path] = node

    def _should_be_explicit_orphan(self, rel_path):
        """SESIÓN 21 (ORP-1) — Clasifica archivos como orphan según patrones explícitos.

        Devuelve True si el archivo matchea criterios universales de descarte:
          - Extensión: .bak, .old, .orig, .tmp, .swp, .swo, .rej
          - Sufijo de nombre: _old, _bak, _backup, _deprecated, _legacy, _orig, _tmp
          - Segmento de carpeta: archive, backup, deprecated, old, trash, _trash, _old

        Defaults en compass/defaults.py::DEFAULT_ORPHAN_PATTERNS.
        Override vía mapper_config.json `orphan_patterns` (extend, no replace).
        """
        from compass.defaults import DEFAULT_ORPHAN_PATTERNS
        from compass.orphan_classifier import merge_orphan_patterns, is_orphan

        # Merge defaults with user config
        user_patterns = self.config.get("orphan_patterns", {})
        merged_patterns = merge_orphan_patterns(DEFAULT_ORPHAN_PATTERNS, user_patterns)

        return is_orphan(rel_path, merged_patterns)

    def _file_registry_paths_set(self):
        """Set de paths relativos posix de los archivos indexados.

        Distinto del `file_registry` (que también incluye variantes sin
        extensión y dotted-paths para el viejo identity matcher). Acá
        sólo necesitamos los paths reales para clasificar orphans.
        """
        if not hasattr(self, "_indexed_paths_cache"):
            self._indexed_paths_cache = {
                v for v in self.file_registry.values()
            }
        return self._indexed_paths_cache

    def run_audit(self):
        total = self.atlas["summary"]["total_files"]
        relevant = self.atlas["summary"]["relevant_files"]
        if total > 0:
            self.atlas["audit"]["structural_health"] = round((relevant / total) * 100, 2)