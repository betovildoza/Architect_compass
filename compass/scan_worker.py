"""scan_worker — per-file scan + cached replay (SCN-003 / INC-008).

Extraído de `compass/pipeline.py` (REF-033 sub-split). Aísla las dos
rutinas largas del loop de `analyze()`:

  - `_scan_file`: inbound scoring + outbound via scanner/resolver + filtros
    AST-024 + EDG-023.
  - `_apply_cached_scan`: replay de contribuciones cacheadas para un
    archivo no modificado (INC-008).

Se expone como mixin (`ScanWorkerMixin`) por consistencia con el resto
del pipeline. Depende de `OutboundResolverMixin` (por `_classify_outbound`,
`_is_asset_target`, `_is_ignored_target`, `_register_edge`,
`_register_external_node`, `_reclassify_cached_target`, `_tier_from_display`).
"""

from compass.scanners import (
    get_scanner,
    _definition_applies_to_language,
)
from compass.scanners.base import normalize_edge_item

from compass.pipeline import _definition_applies_to_stack


class ScanWorkerMixin:
    """Mixin con las rutinas per-file del loop de `analyze()`."""

    def _scan_file(self, *, file_path, rel_path, filename, language,
                   file_stack, inbound_index, tech_scores, unify_lower,
                   compiled_ignore_outbound):
        """Escanea un archivo: inbound scoring + outbound via scanner/resolver.

        Devuelve la tupla `(is_relevant, outbound_targets, inbound_patterns,
        tech_scores_delta, metadata_calls)` para que INC-008 cachee el
        detalle por archivo y pueda reproducir las contribuciones sin
        re-leer el contenido. `metadata_calls` es la lista de raws que
        GRF-021 clasifica como builtin/stdlib/no-resolvable (no emiten edge
        pero quedan visibles en atlas.files[rel_path].metadata.calls).

        DEF-025 — guardián de contexto: una definition solo incrementa
        `tech_scores` si es *compatible* con el archivo. El modo language
        lo valida `_definition_applies_to_language`. El modo stack (legacy
        de configs pre-DEF-025 que declaran `stack` en la definition) lo
        valida `_definition_applies_to_stack` contra `file_stack`. Esto
        elimina los falsos positivos tipo `Tauri-Desktop-App-JS` sumando
        score en un proyecto HTML+PHP por matchear regex genéricas sobre
        JS vanilla.
        """
        is_relevant = any(filename.endswith(ext) for ext in (".js", ".css"))
        outbound_targets = []
        inbound_patterns = []
        tech_scores_delta = {}
        metadata_calls = []

        # Inbound: se sigue leyendo contenido para pattern matching de scoring.
        # DEF-017: filtrar por lenguaje del archivo. Si la definition no
        # declara `language`, aplica a todos (backward-compat).
        # DEF-025: además validar por stack si la definition lo declara
        # (guardián de contexto — ver docstring).
        if inbound_index:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                content = ""
            for name, df, compiled_list in inbound_index:
                if not _definition_applies_to_language(df, language):
                    continue
                if not _definition_applies_to_stack(df, file_stack):
                    continue
                for pat, regex in compiled_list:
                    if regex.search(content):
                        self.atlas["connectivity"]["inbound"].append(
                            f"{rel_path} <- {pat}"
                        )
                        tech_scores[name] = tech_scores.get(name, 0) + 10
                        tech_scores_delta[name] = tech_scores_delta.get(name, 0) + 10
                        inbound_patterns.append(pat)
                        is_relevant = True

        # Outbound: delegado al scanner dispatcher.
        scanner = get_scanner(language, self.config)
        raw_imports = scanner.extract_imports(str(file_path))
        if not raw_imports:
            return (
                is_relevant, outbound_targets, inbound_patterns,
                tech_scores_delta, metadata_calls,
            )

        src_abs = str(file_path.resolve())
        # EDG-023 + AST-024 — contenedores para metadata del archivo.
        file_assets = []
        file_filtered_refs = []
        for raw_item in raw_imports:
            # EDG-023 — cada item puede ser str (legacy) o tuple
            # `(target, edge_type)`. Normalizamos acá para que el resto del
            # pipeline reciba siempre `(raw, edge_type)`.
            # Sesión 6C: default_edge_type viene del config.
            raw, edge_type = normalize_edge_item(
                raw_item, default_edge_type=self.default_edge_type,
            )
            if raw is None:
                continue
            classification = self._classify_outbound(
                raw, language, src_abs, unify_lower,
            )
            kind = classification["kind"]

            if kind == "discard":
                # GRF-021 — builtin/stdlib/no-resolvable. Se guarda como
                # metadata del nodo fuente para no perder la señal, pero
                # NO emite nodo ni edge.
                call_label = classification.get("label")
                if call_label and call_label not in metadata_calls:
                    metadata_calls.append(call_label)
                continue

            final_node = classification["label"]
            if any(r.search(final_node) for r in compiled_ignore_outbound):
                self._filter_counts["ignore_outbound"] += 1
                continue
            if final_node == rel_path:
                self._filter_counts["self_edge"] += 1
                continue

            # AST-024 — filtros de emisión: assets binarios y refs a archivos
            # ignorados (por ignore_files / ignore_patterns del config).
            # Ambos aplican SOLO para targets que resuelven a archivos del
            # repo (`kind == "file"`). Externals y legacy pasan sin filtro.
            # Nota: contamos UNIQUE (source, target) pairs para consistencia
            # entre first-run y cached-replay (el cache dedupa por target).
            if kind == "file":
                if self._is_asset_target(final_node):
                    if final_node not in file_assets:
                        file_assets.append(final_node)
                        self._filter_counts["asset"] += 1
                    continue
                if self._is_ignored_target(final_node):
                    if final_node not in file_filtered_refs:
                        file_filtered_refs.append(final_node)
                        self._filter_counts["ignored"] += 1
                    continue

            self.atlas["connectivity"]["outbound"].append(
                f"{rel_path} -> {final_node}"
            )
            self._register_edge(rel_path, final_node, kind, edge_type)
            if kind == "external":
                self._register_external_node(
                    final_node,
                    classification["label_display"],
                    tier=classification.get("tier"),
                )
            outbound_targets.append(final_node)
            is_relevant = True
        # AST-024 — persistir metadata de assets/filtered_refs a nivel core.
        if file_assets:
            self._metadata_assets[rel_path] = file_assets
        if file_filtered_refs:
            self._metadata_filtered_refs[rel_path] = file_filtered_refs
        return (
            is_relevant, outbound_targets, inbound_patterns,
            tech_scores_delta, metadata_calls,
        )

    def _apply_cached_scan(self, *, rel_path, cached, tech_scores):
        """Replica las contribuciones cacheadas de un archivo no modificado.

        INC-008: cuando el fingerprint del archivo coincide con el del run
        anterior, no leemos contenido — replicamos los edges, inbound
        matches y tech_scores que ya conocíamos. Esto asume que el config
        (patterns, ignore_outbound, unify) no cambió: si cambió, el caller
        debe haber llamado `force_full=True` o haber invalidado el cache.

        EDG-023: los caches viejos no tienen `edge_types` — default a
        `self.default_edge_type` para cada target. En el próximo scan-full
        el cache se regenera con edge_types reales.

        AST-024: los filtros de asset/ignored se aplican también al replay
        cacheado — si el usuario agregó `asset_extensions` al config y los
        targets viejos incluyen imágenes, el cache_invalidation por
        `_config_fingerprint` debería haber invalidado esto ya; pero si
        no (caso edge), filtramos defensivamente.
        """
        outbound_targets = cached.get("outbound_targets") or []
        inbound_patterns = cached.get("inbound_patterns") or []
        tech_delta = cached.get("tech_scores") or {}
        metadata_calls = cached.get("metadata_calls") or []
        edge_types = cached.get("edge_types") or {}
        cached_assets = cached.get("metadata_assets") or []
        cached_filtered = cached.get("metadata_filtered_refs") or []
        is_relevant = bool(cached.get("is_relevant"))

        # AST-024 — restaurar metadata + contar como filtros (consistencia
        # con el first-run). No re-clasificamos (ya lo hizo el run original),
        # solo reflejamos la señal en `_filter_counts` y metadata.
        if cached_assets:
            self._metadata_assets[rel_path] = list(cached_assets)
            self._filter_counts["asset"] += len(cached_assets)
        if cached_filtered:
            self._metadata_filtered_refs[rel_path] = list(cached_filtered)
            self._filter_counts["ignored"] += len(cached_filtered)

        for pat in inbound_patterns:
            self.atlas["connectivity"]["inbound"].append(f"{rel_path} <- {pat}")
        for tgt in outbound_targets:
            # Re-clasificar al emitir el edge: si el target sigue siendo un
            # external service declarado, emitir como external; si es path
            # del repo, emitir como file; si no, tratarlo como external
            # legacy (no debería pasar si el config no cambió — pero si
            # cambió, el cache ya fue invalidado antes de llegar acá).
            kind, display = self._reclassify_cached_target(tgt)
            # AST-024 — filtros defensivos también en replay.
            if kind == "file":
                if self._is_asset_target(tgt):
                    self._filter_counts["asset"] += 1
                    self._metadata_assets.setdefault(rel_path, []).append(tgt)
                    continue
                if self._is_ignored_target(tgt):
                    self._filter_counts["ignored"] += 1
                    self._metadata_filtered_refs.setdefault(rel_path, []).append(tgt)
                    continue
            self.atlas["connectivity"]["outbound"].append(f"{rel_path} -> {tgt}")
            et = edge_types.get(tgt, self.default_edge_type)
            self._register_edge(rel_path, tgt, kind, et)
            if kind == "external":
                # TIER-035 — preferir tier cacheado del run previo (preserva
                # la señal de `service` obtenida por URL literal cuando el
                # display es solo un hostname sin match en config). Fallback
                # a recompute si no hay cached.
                tier = self._cached_external_tiers.get(tgt)
                if not tier:
                    tier = self._tier_from_display(display, language=None)
                self._register_external_node(tgt, display, tier=tier)
        for name, delta in tech_delta.items():
            tech_scores[name] = tech_scores.get(name, 0) + delta
        if metadata_calls:
            self._metadata_calls[rel_path] = list(metadata_calls)

        return is_relevant