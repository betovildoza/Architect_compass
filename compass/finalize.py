"""finalize — pase end-of-run del pipeline (VAL-014 + métricas + emisión).

Extraído de `compass/core.py` (REF-033). Incluye también los helpers de
fingerprint cache (INC-008) que se usan en el loop de `analyze()` pero
persisten en `finalize()`.

Estructura de finalize (Sesión 10 · CONS-029 + LLM-VIEW-028 agregados):
  0. _validate_local_config()       → atlas.audit.warnings + consola    (VAL-014, SES 7)
  1. _attach_metadata_calls()       → atlas.files[*].metadata.*         (GRF-021 + AST-024)
  1b. _consolidate_metadata()       → atlas.metadata_consolidated       (CONS-029, SES 10)
  2. _compute_metrics()             → health + cycles + delta           (SES 6A — SCR-009, CYC-011, DIF-010)
  3. _emit_dot_graph()              → connectivity.dot                  (GRF-013 + EDG-023 + AST-024)
  4. _emit_graph_html()             → graph.html (vis-network wrapper)  (GRF-013)
  5. _write_atlas()                 → atlas.json
  5b. _write_atlas_compact()        → atlas.compact.json                (LLM-VIEW-028, SES 10)
  6. _rotate_history()              → .map/history/YYYYmmdd_HHMM_*.json (DIF-010)
  7. _persist_fingerprints()        → .map/fingerprints.json            (INC-008)
  8. _update_feedback_log()         → .map/feedback.log
  9. _print_summary()               → stdout
"""

import hashlib
import json
from datetime import datetime

from compass.consolidator import (
    build_compact_atlas,
    build_metadata_consolidated,
)
from compass.graph_emitter import (
    build_dot_content,
    build_graph_html,
    validate_dot_syntax,
)
from compass.dashboard_detector import detect_dashboards_in_atlas
from compass.metrics import (
    HISTORY_DIR_NAME,
    build_snapshot_name,
    compute_health_score,
    detect_cycles,
    diff_against_previous,
    load_previous_snapshot,
    save_snapshot,
)
from compass.validation import validate_local_config


FINGERPRINTS_NAME = "fingerprints.json"
FINGERPRINTS_VERSION = 1


class FinalizeMixin:
    """Mixin con finalize() + fingerprint cache (INC-008) + emisión.

    Los helpers de fingerprint viven acá porque `_load_fingerprints` se
    invoca en `__init__` y `_persist_fingerprints` al cierre, pero
    conceptualmente son parte del ciclo INC-008 (cache end-of-run).
    """

    # ------------------------------------------------------------------
    # Incremental cache (INC-008)
    # ------------------------------------------------------------------
    def _load_fingerprints(self):
        """Lee `.map/fingerprints.json` si existe; devuelve dict de files.

        Devuelve estructura `{rel_path: {fingerprint, outbound_targets,
        inbound_patterns, tech_scores, is_relevant, stack}}`. Si el archivo
        no existe, está corrupto, cambió de versión, el config cambió, o
        el run es full, devuelve dict vacío (forzando re-scan completo).
        """
        if self.force_full:
            return {}
        if not self.fingerprints_path.exists():
            return {}
        try:
            with open(self.fingerprints_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        if data.get("version") != FINGERPRINTS_VERSION:
            return {}
        # Si el config cambió, invalidamos todo el cache: las patterns,
        # ignore_outbound o unify_external_nodes pueden haber cambiado y
        # los edges cacheados serían inconsistentes.
        if data.get("config_fingerprint") != self._config_fingerprint():
            return {}
        files = data.get("files")
        if not isinstance(files, dict):
            return {}
        # TIER-035 — exponer external_tiers cacheados para que el replay
        # pueda reusarlos sin recomputar (el recomputo pierde info parcial
        # como URL host → service cuando el host no está en match_urls).
        cached_tiers = data.get("external_tiers")
        if isinstance(cached_tiers, dict):
            self._cached_external_tiers = dict(cached_tiers)
        else:
            self._cached_external_tiers = {}
        return files

    @staticmethod
    def _file_fingerprint(file_path):
        """SHA-256 del contenido binario del archivo. None si falla I/O."""
        try:
            h = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except OSError:
            return None

    def _persist_fingerprints(self):
        """Escribe `.map/fingerprints.json` con `current_cache`."""
        payload = {
            "version": FINGERPRINTS_VERSION,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "config_fingerprint": self._config_fingerprint(),
            "files": self.current_cache,
            # TIER-035 — persistir external_tiers computados en este run para
            # que el cached replay no tenga que re-clasificar (información
            # parcialmente perdible — p.ej. URL host por external_services
            # sin match_urls config).
            "external_tiers": dict(self._external_node_tiers),
        }
        try:
            with open(self.fingerprints_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"⚠️ No se pudo persistir fingerprints: {e}")

    # ------------------------------------------------------------------
    # Finalize pipeline
    # ------------------------------------------------------------------
    # VAL-014 corre al INICIO de finalize() (no al fin de analyze()) porque:
    #   - Necesita el config ya merged (que sí construye `__init__`), pero
    #     también el project_root ya walked para chequear existencia de
    #     dynamic_deps.targets. Post-analyze() es el punto natural.
    #   - Queremos que los warnings aparezcan en atlas.audit.warnings antes
    #     de persistirlo (paso 5).
    #
    # Orden post-6B: los cycles (CYC-011) se computan ANTES de emitir el
    # `.dot` — GRF-013 colorea nodos en ciclos con su shape especial, así
    # que necesita `atlas.cycles` poblado antes de dibujar. `metadata.assets`
    # también se adjunta antes para que el atlas salga consistente.
    # La emisión del `.dot` + `.html` se delega a compass/graph_emitter.py —
    # funciones puras stdlib que espejan el patrón de compass/metrics.py.
    def finalize(self):
        self._run_config_validation()
        self._detect_and_promote_dashboards()  # SESIÓN 20 (ITEM 2)
        self._detect_and_promote_wp_templates()  # SESIÓN 21 (ITEM 3)
        self._attach_metadata_calls()
        self._consolidate_metadata()   # CONS-029 (Sesión 10)
        self._compute_metrics()
        self._emit_dot_graph()
        self._emit_graph_html()
        self._write_atlas()
        self._write_atlas_compact()    # LLM-VIEW-028 (Sesión 10)
        self._rotate_history()
        self._persist_fingerprints()
        self._update_feedback_log()
        self._print_summary()

    def _consolidate_metadata(self):
        """CONS-029 (Sesión 10) — vista global invertida de metadata.

        `atlas.files[*].metadata.{assets,calls,filtered_refs}` hoy duplica
        targets entre archivos (ej. 30 HTMLs × favicon = 30 entries). Se
        mantiene la vista per-source (humano) y se AGREGA la consolidada
        con shape `{target: [source1, ...]}` en `atlas.metadata_consolidated`.
        """
        self.atlas["metadata_consolidated"] = build_metadata_consolidated(self.atlas)

    def _write_atlas_compact(self):
        """LLM-VIEW-028 (Sesión 10) — `.map/atlas.compact.json`.

        Shape mínimo para pasar como contexto a un agente LLM — sin metadata
        explotada per-source, usa `metadata_consolidated` de CONS-029.
        Preserva topología (mismos nodes + edges + cycles que atlas.json).
        """
        compact = build_compact_atlas(
            atlas=self.atlas,
            edges=self._edges,
            external_nodes=self._external_nodes,
            external_tiers=self._external_node_tiers,
        )
        # Dump compacto (separators sin whitespace) — el archivo está pensado
        # para ser ingerido por un agente LLM; minimizar tokens vale más que
        # legibilidad humana (para eso está atlas.json con indent=4).
        with open(self.map_dir / "atlas.compact.json", "w", encoding="utf-8") as f:
            json.dump(compact, f, separators=(",", ":"), ensure_ascii=False)

    def _run_config_validation(self):
        """VAL-014 (Sesión 7) — valida el compass.local.json del proyecto.

        Warnings se acumulan SIN abortar. Se agregan a `atlas.audit.warnings`
        y se guardan en `self._config_warnings` para que `_print_summary`
        los muestre como sección `CONFIG WARNINGS:` (solo si hay ≥1).

        Usa el `_LOCAL_TEMPLATE` module-level como default shipeado para
        detectar drift en `_example_*` (warning 5).
        """
        # Import local para evitar ciclo con template_io si algo cambia.
        from compass.template_io import _LOCAL_TEMPLATE
        try:
            warnings = validate_local_config(
                local_config=getattr(self, "_raw_local_config", {}) or {},
                merged_config=self.config,
                project_root=self.project_root,
                map_dir=self.map_dir,
                default_template=_LOCAL_TEMPLATE,
            )
        except Exception as e:
            # Defensivo: si la validación tiene un bug, no queremos que
            # tire el run entero. Log como warning y seguir.
            warnings = [f"validation: error interno — {e}"]
        self._config_warnings = list(warnings)
        # Exponer en atlas.audit.warnings para consumidores programáticos
        # (LLM-VIEW-028 futuro). Prefijo estable `config:` para que otros
        # consumidores puedan filtrarlos aparte de los warnings de audit.
        for w in warnings:
            self.atlas["audit"]["warnings"].append(f"config: {w}")

    def _detect_and_promote_dashboards(self):
        """SESIÓN 20 (ITEM 2) — detecta dashboards por markers de forma.

        Analiza archivos HTML ambiguos para determinar si son dashboards servidos:
        - HTML con estructura de controles (buttons, forms, inputs con handlers)
        - Carga script(s) interno(s)
        - Ese script contiene fetch/websocket a rutas locales (/api/..., /action/...)

        Si se detecta, promociona el HTML a entry_point con reason "dashboard_markers"
        y lo remueve de ambiguous.
        """
        result = detect_dashboards_in_atlas(
            atlas=self.atlas,
            project_root=self.project_root,
        )

        if result.get("promoted"):
            promoted = result["promoted"]
            reason = result.get("reason", "dashboard_markers")

            for html_file in promoted:
                # Remover de ambiguous
                if html_file in self.atlas["ambiguous"]:
                    self.atlas["ambiguous"].remove(html_file)

                # Agregar a entry_points
                if html_file not in self.atlas.get("entry_points", []):
                    self.atlas["entry_points"].append(html_file)

                # Marcar en files node
                if html_file in self.atlas["files"]:
                    self.atlas["files"][html_file]["tier"] = "connected"
                    self.atlas["files"][html_file]["entry_point_reason"] = reason

    def _detect_and_promote_wp_templates(self):
        """SESIÓN 21 (ITEM 3) — detecta y marca templates WordPress como entry points.

        Identifica proyectos WordPress por markers (style.css, functions.php, wp-config.php, wp-content/).
        Para proyectos WP, clasifica archivos PHP que matchean la template hierarchy como entry points.

        Ejemplos: index.php, front-page.php, single-*.php, archive-*.php, page-*.php, etc.
        Son auto-cargados por WordPress según la URL, no orfans ni ambiguos.
        """
        from compass.wordpress_detector import (
            detect_wordpress_project,
            is_wp_template,
        )

        is_wp_project = detect_wordpress_project(self.project_root)

        if not is_wp_project:
            return

        # Iterate over all files and mark WP templates as entry points
        for rel_path in list(self.atlas.get("files", {}).keys()):
            if not rel_path.endswith(".php"):
                continue

            if is_wp_template(rel_path):
                # Remover de ambiguous si está ahí
                if rel_path in self.atlas.get("ambiguous", []):
                    self.atlas["ambiguous"].remove(rel_path)

                # Agregar a entry_points
                if rel_path not in self.atlas.get("entry_points", []):
                    self.atlas["entry_points"].append(rel_path)

                # Marcar en files node
                if rel_path in self.atlas["files"]:
                    self.atlas["files"][rel_path]["tier"] = "connected"
                    self.atlas["files"][rel_path]["entry_point_reason"] = "wp_template_hierarchy"

    def _collect_graph_nodes(self):
        """Devuelve set de rel_paths que deben renderizarse en el grafo.

        Incluye (a) todos los archivos con edges entrantes o salientes,
        (b) todos los orphans listados (para que aparezcan visualmente
        aunque no tengan edges). NO incluye externals — esos se emiten
        como cilindros fuera de clusters.
        """
        nodes = set()
        for (src, tgt, _et, kind) in self._edges:
            nodes.add(src)
            if kind == "file":
                nodes.add(tgt)
        # Orphans: presentes en atlas.orphans pero quizás sin edges.
        for orphan in self.atlas.get("orphans", []):
            nodes.add(orphan)
        return nodes

    def _emit_dot_graph(self):
        """Paso 1 — emite `connectivity.dot` profesional (GRF-013 + EDG-023).

        Clustering por directorio top-level, colores por kind de nodo
        (normal/orphan/cycle) y colores/labels por edge_type.
        """
        nodes = self._collect_graph_nodes()
        cycles = self.atlas.get("cycles", []) or []
        dot_content = build_dot_content(
            nodes=nodes,
            edges=self._edges,
            external_nodes=self._external_nodes,
            orphans=self.atlas.get("orphans", []),
            cycles=cycles,
            graph_config=self.graph_rules,
        )
        # Cache del `.dot` para que _emit_graph_html lo embeba.
        self._dot_content = dot_content
        with open(self.map_dir / "connectivity.dot", "w", encoding="utf-8") as f:
            f.write(dot_content)
        # Smoke check — dejamos el resultado en atlas.audit.warnings si falla.
        ok, msg = validate_dot_syntax(dot_content)
        if not ok:
            self.atlas["audit"]["warnings"].append(f"dot syntax: {msg}")
        # EDG-023 + AST-024 — exponer filter_counts en atlas para observabilidad.
        # `rendered_edges` = edges únicos en el `.dot` (deduplicados por
        # (src, tgt, edge_type)). `raw_edges` = lista completa pre-dedup.
        unique_edges = {(s, t, et) for (s, t, et, _k) in self._edges}
        self.atlas["graph_filters"] = dict(self._filter_counts)
        self.atlas["graph_filters"]["rendered_edges"] = len(unique_edges)
        self.atlas["graph_filters"]["raw_edges"] = len(self._edges)
        # TIER-035 — expone la clasificación de tier en el atlas para
        # consumidores (LLM view futuro, diff, HTML viewer).
        if self._external_node_tiers:
            self.atlas["external_tiers"] = dict(self._external_node_tiers)

    def _emit_graph_html(self):
        """Paso 2 — emite `graph.html` universal (Sesión 6C).

        Template vis-network externalizado en `compass/templates/graph.html.tpl`.
        Se emite SIEMPRE, para cualquier proyecto/stack. Zoom/pan/drag nativos.
        """
        dot_content = getattr(self, "_dot_content", "") or ""
        cycles = self.atlas.get("cycles", []) or []
        html = build_graph_html(
            dot_content=dot_content,
            project_name=self.atlas.get("project_name", "project"),
            generated_at=self.atlas.get("generated_at", ""),
            node_count=len(self._collect_graph_nodes()),
            edge_count=len(self._edges),
            cycle_count=len(cycles),
            edges=self._edges,
            external_nodes=self._external_nodes,
            orphans=self.atlas.get("orphans", []),
            ambiguous=self.atlas.get("ambiguous", []),
            cycles=cycles,
            graph_config=self.graph_rules,
            external_tiers=self._external_node_tiers,
            entry_points=self.atlas.get("entry_points", []),
        )
        with open(self.map_dir / "graph.html", "w", encoding="utf-8") as f:
            f.write(html)

    def _attach_metadata_calls(self):
        """Paso 3 — copia `_metadata_calls/_metadata_assets/_metadata_filtered_refs`
        a `atlas.files[*].metadata.*` (GRF-021 + AST-024).
        """
        for rel_path, calls in self._metadata_calls.items():
            self._ensure_metadata(rel_path)["calls"] = calls
        # AST-024 — assets binarios referenciados pero no emitidos como edges.
        for rel_path, assets in self._metadata_assets.items():
            # dedup + orden estable
            seen = []
            for a in assets:
                if a not in seen:
                    seen.append(a)
            self._ensure_metadata(rel_path)["assets"] = seen
        # AST-024 (scope extendido) — refs a archivos ignorados por config.
        for rel_path, refs in self._metadata_filtered_refs.items():
            seen = []
            for r in refs:
                if r not in seen:
                    seen.append(r)
            self._ensure_metadata(rel_path)["filtered_refs"] = seen

    def _ensure_metadata(self, rel_path):
        """Garantiza que `atlas.files[rel_path]["metadata"]` exista y devuelve el dict."""
        node = self.atlas["files"].get(rel_path)
        if node is None:
            # El archivo puede no estar en atlas.files si el walk no lo tocó
            # (ej. nunca fue escaneado pero aparece como target). Creamos
            # el nodo mínimo para no perder la metadata.
            node = {"stack": self.resolve_stack_for(rel_path)}
            self.atlas["files"][rel_path] = node
        if "metadata" not in node:
            node["metadata"] = {}
        return node["metadata"]

    def _compute_metrics(self):
        """Paso 3 — SCR-009 + CYC-011 + DIF-010. Popula `atlas`.

        Orden importante:
          a. cycles — info-only, alimenta el diff pero NO el score (PLAN).
          b. health — independiente de cycles.
          c. delta  — contra último snapshot de .map/history/.

        El snapshot nuevo se persiste en `_rotate_history()` (paso 5),
        DESPUÉS de que `atlas` ya tiene health/cycles; así el snapshot
        del próximo run puede diffear correctamente.
        """
        # CYC-011
        repo_paths = list(self.atlas.get("files", {}).keys())
        outbound_edges = self.atlas["connectivity"]["outbound"]
        cycles = detect_cycles(outbound_edges, repo_paths)
        self.atlas["cycles"] = cycles

        # SCR-009 — se calcula con la foto actual del atlas (cycles ya está).
        # Sesión 6C: pesos opcionalmente overrideables vía scoring_weights.
        total_score, breakdown, weights_warning = compute_health_score(
            self.atlas, self.config,
        )
        self.atlas["health"] = breakdown
        # Back-compat: también dejamos el total top-level para consumidores
        # que quieran leerlo rápido.
        self.atlas["health"]["total"] = total_score
        if weights_warning:
            self.atlas["audit"]["warnings"].append(weights_warning)
        # audit.structural_health (existente desde la v1) NO se toca: es la
        # métrica relevant/total que ya usan scripts y el log. El nuevo
        # health coexiste.

        # DIF-010 — cargar snapshot previo y calcular delta. Fallback al
        # `.map/atlas.json` pre-6A para sembrar el primer delta cuando
        # history/ todavía no tiene entradas.
        history_dir = self.map_dir / HISTORY_DIR_NAME
        fallback_atlas = self.map_dir / "atlas.json"
        previous = load_previous_snapshot(history_dir, fallback_atlas)
        # No diffear contra el run actual (mismo generated_at — típico de
        # la segunda invocación sin cambios si el fallback se re-lee a sí
        # mismo; acá nunca pasa porque fallback lee atlas.json ANTES de
        # que lo sobreescribamos, pero defensivo igual).
        if previous and previous.get("generated_at") == self.atlas.get("generated_at"):
            previous = None
        delta = diff_against_previous(self.atlas, previous)
        if delta is not None:
            self.atlas["delta"] = delta

    def _write_atlas(self):
        """Paso 4 — escribe `.map/atlas.json`."""
        with open(self.map_dir / "atlas.json", "w", encoding="utf-8") as f:
            json.dump(self.atlas, f, indent=4, ensure_ascii=False)

    def _rotate_history(self):
        """Paso 5 — DIF-010: persiste snapshot y rota a últimas 10 runs.

        El snapshot es el atlas tal como se escribió — incluye health,
        cycles, stack_map. No incluye delta (evita recursion de deltas).
        """
        history_dir = self.map_dir / HISTORY_DIR_NAME
        snapshot_name = build_snapshot_name(
            self.atlas["generated_at"], self.atlas["project_name"],
        )
        # Copia sin `delta` — el histórico es self-contained.
        snapshot = {k: v for k, v in self.atlas.items() if k != "delta"}
        save_snapshot(history_dir, snapshot_name, snapshot)

    def _update_feedback_log(self):
        """Paso 7 — prepend al `.map/feedback.log`."""
        log_path = self.map_dir / "feedback.log"
        structural = self.atlas["audit"]["structural_health"]
        health_total = self.atlas.get("health", {}).get("total", 0)
        cycles_count = len(self.atlas.get("cycles", []) or [])

        new_entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] COMPASS RUN\n"
        new_entry += f"  - Salud Estructural (relevant/total): {structural}%\n"
        new_entry += f"  - Health Score (breakdown): {health_total}\n"
        new_entry += (
            f"  - Archivos: {self.atlas['summary']['total_files']} "
            f"(Relevantes: {self.atlas['summary']['relevant_files']})\n"
        )
        new_entry += f"  - Ciclos detectados: {cycles_count}\n"
        if "delta" in self.atlas:
            delta = self.atlas["delta"]
            hd = delta.get("health_delta", {})
            new_entry += (
                f"  - Delta vs run previo: total={hd.get('total', 0):+}, "
                f"files +{len(delta['files']['added'])}/"
                f"-{len(delta['files']['removed'])}, "
                f"orphans +{len(delta['orphans']['added'])}/"
                f"-{len(delta['orphans']['removed'])}\n"
            )
        new_entry += "=" * 40 + "\n\n"

        old_content = ""
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                old_content = f.read()
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(new_entry + old_content)

    def _print_summary(self):
        """Paso 8 — stdout summary."""
        structural = self.atlas["audit"]["structural_health"]
        health = self.atlas.get("health", {})
        total = health.get("total", 0)
        cycles = self.atlas.get("cycles", []) or []

        print(f"\n✨ Architect Compass finalizado.")
        print(f"📊 Salud Estructural (relevant/total): {structural}%")
        print(f"📈 Health Score: {total}/100")
        bd = {k: health.get(k, {}).get("score") for k in
              ("orphans", "connectivity", "dead_exports", "external_deps")}
        print(
            f"    orphans={bd['orphans']} | connectivity={bd['connectivity']} | "
            f"dead_exports={bd['dead_exports']} | external_deps={bd['external_deps']}"
        )

        if cycles:
            print(f"🔁 Ciclos detectados: {len(cycles)}")
            for c in cycles[:5]:
                print(f"    {' → '.join(c)}")
            if len(cycles) > 5:
                print(f"    … ({len(cycles) - 5} más en atlas.json[\"cycles\"])")

        # EDG-023 + AST-024 — reportar conteos de filtros aplicados al grafo.
        fc = self._filter_counts
        filtered_total = (
            fc["asset"] + fc["ignored"] + fc["self_edge"] + fc["ignore_outbound"]
        )
        if filtered_total:
            print(
                f"🔕 Edges filtradas del grafo: total={filtered_total} "
                f"(assets={fc['asset']}, ignored={fc['ignored']}, "
                f"self={fc['self_edge']}, patterns={fc['ignore_outbound']})"
            )

        if "delta" in self.atlas:
            delta = self.atlas["delta"]
            hd = delta["health_delta"]
            print(
                f"🔀 Delta vs run previo ({delta.get('previous_generated_at')}): "
                f"health {hd['total']:+} "
                f"(files +{len(delta['files']['added'])}/"
                f"-{len(delta['files']['removed'])}, "
                f"orphans +{len(delta['orphans']['added'])}/"
                f"-{len(delta['orphans']['removed'])})"
            )

        # VAL-014 — CONFIG WARNINGS section. Solo imprimir si hay.
        cw = getattr(self, "_config_warnings", None) or []
        if cw:
            print("\nCONFIG WARNINGS:")
            for w in cw:
                print(f"  ⚠ {w}")

        if structural < 80.0:
            print(" 💡 SUGERENCIA (ES):")
            print(" La salud estructural es baja porque faltan reglas específicas.")
            print(" Configurá '.map/compass.local.json' usando el template")