"""core — fachada `ArchitectCompass` (REF-033).

La lógica antes monolítica (2483 líneas) se factorizó en módulos hermanos:

  - `compass.template_io`       — shipment de `compass.local.json` + help MD.
  - `compass.config_loader`     — jerarquía basal + local + fingerprint.
  - `compass.outbound_resolver` — GRF-021/NET-022/NET-023/TIER-035/FIX-030.
  - `compass.pipeline`          — analyze() + scan loop + entry points + orphans.
  - `compass.finalize`          — VAL-014 + métricas + emisión + fingerprint cache.

Este archivo queda como façade: `ArchitectCompass` hereda los mixins, define
`__init__` y re-exporta el nombre histórico para `from compass.core import
ArchitectCompass`. Los re-exports de constantes (`LOCAL_CONFIG_NAME`,
`FINGERPRINTS_NAME`, `_LOCAL_TEMPLATE`, etc.) también se preservan por si
algún consumidor externo los lee por su ruta antigua.
"""

from datetime import datetime
from pathlib import Path

from compass.config_loader import ConfigLoaderMixin
from compass.entry_points import EntryPointsMixin
from compass.finalize import (
    FINGERPRINTS_NAME,
    FINGERPRINTS_VERSION,
    FinalizeMixin,
)
from compass.outbound_resolver import OutboundResolverMixin
from compass.path_resolver import PathResolver
from compass.pipeline import AnalyzePipelineMixin
from compass.scan_worker import ScanWorkerMixin
from compass.scanners.base import resolve_default_edge_type
from compass.stack_detector import StackDetector
from compass.template_io import (
    LEGACY_LOCAL_CONFIG_NAME,
    LOCAL_CONFIG_NAME,
    LOCAL_HELP_NAME,
    LOCAL_HELP_TEMPLATE,
    LOCAL_TEMPLATE_NAME,
    _EXAMPLE_WARNING,
    _LOCAL_TEMPLATE,
    ensure_local_template,
)


__all__ = [
    "ArchitectCompass",
    # Re-exports históricos (backward-compat para consumidores externos).
    "LOCAL_CONFIG_NAME",
    "LEGACY_LOCAL_CONFIG_NAME",
    "LOCAL_TEMPLATE_NAME",
    "LOCAL_HELP_NAME",
    "LOCAL_HELP_TEMPLATE",
    "FINGERPRINTS_NAME",
    "FINGERPRINTS_VERSION",
    "_EXAMPLE_WARNING",
    "_LOCAL_TEMPLATE",
]


class ArchitectCompass(
    ConfigLoaderMixin,
    OutboundResolverMixin,
    AnalyzePipelineMixin,
    ScanWorkerMixin,
    EntryPointsMixin,
    FinalizeMixin,
):
    """Orquestador de la auditoría estructural.

    Responsabilidades:
      - bootstrap del contexto del run (`__init__`): config + resolvers +
        scanners + fingerprint cache + contenedores de metadata.
      - orquestar `analyze()` (scan loop — provisto por AnalyzePipelineMixin).
      - orquestar `finalize()` (emisión y métricas — provisto por FinalizeMixin).

    Los detalles de cada sub-sistema viven en su módulo hermano; este archivo
    solo wirea el estado compartido (`self.*`) y expone el API público.
    """

    def __init__(
        self,
        force_full=False,
        project_root=None,
        config_path=None,
        output_dir=None,
        progress_callback=None,
    ):
        """Inicializa el contexto del run.

        Parámetros:
            force_full: si True, ignora el cache de fingerprints y re-escanea
                todos los archivos (CLI-015 --full).
            project_root: Path raíz del proyecto a escanear. Default: cwd.
                Permite que la CLI fije --root sin tener que cambiar cwd.
            config_path: Path a un mapper_config.json explícito que reemplaza
                al global del repo de Compass. Si None usa el global default.
                Es la opción 1 de la jerarquía de config (CLI-015 --config).
            output_dir: Path al directorio de salida (.map/). Default:
                <project_root>/.map. Permite que la CLI fije --output sin
                contaminar el árbol del proyecto.
            progress_callback: callable opcional `cb(rel_path, scanned, reused)`
                invocado por el scan loop tras procesar cada archivo. Sirve
                para que la CLI muestre progress bars sin cambiar la
                semántica del análisis. Default None = no-op.
        """
        self.force_full = bool(force_full)
        self.script_dir = Path(__file__).parent.parent.absolute()
        if config_path is not None:
            self.global_config_path = Path(config_path).resolve()
        else:
            self.global_config_path = self.script_dir / "mapper_config.json"
        if project_root is not None:
            self.project_root = Path(project_root).resolve()
        else:
            self.project_root = Path.cwd()
        if output_dir is not None:
            self.map_dir = Path(output_dir).resolve()
        else:
            self.map_dir = self.project_root / ".map"
        self.local_config_path = self.map_dir / LOCAL_CONFIG_NAME
        self.legacy_local_config_path = self.map_dir / LEGACY_LOCAL_CONFIG_NAME
        self.fingerprints_path = self.map_dir / FINGERPRINTS_NAME
        # Hook de observabilidad para CLI (no afecta atlas output).
        self._progress_callback = progress_callback

        self.config = self.load_config_hierarchy()

        # Vistas cómodas de las secciones (siempre dicts, nunca None)
        self.rules = self.config.get("basal_rules", {}) or {}
        self.graph_rules = self.config.get("graph", {}) or {}
        self.scoring_rules = self.config.get("scoring", {}) or {}
        # GRF-021: external services (SDKs por nombre de import).
        self.external_services = self.config.get("external_services", {}) or {}
        self._external_index = self._build_external_index(self.external_services)
        # NET-022: índice de URL patterns para matchear hostname → label.
        self._external_url_index = self._build_external_url_index(self.external_services)
        # Sesión 6C: default_edge_type configurable (graph.default_edge_type).
        self.default_edge_type = resolve_default_edge_type(self.config)

        self.map_dir.mkdir(exist_ok=True)
        self.ensure_local_template()

        # --- Filtros de scan (IGN-016) -----------------------------------
        self.ignore_folders = set(self.rules.get("ignore_folders", []))
        self.ignore_files = set(self.rules.get("ignore_files", []))
        self.ignore_patterns = list(self.rules.get("ignore_patterns", []))
        self.text_extensions = set(
            self.rules.get("text_extensions", [".py", ".js", ".json", ".css"])
        )

        # AST-024 — extensiones de asset binario (imágenes, fonts, media).
        # Targets que resuelven a archivos con estas extensiones NO emiten
        # nodo ni edge en el grafo; se acumulan en `metadata.assets` del
        # nodo fuente. Config key: `basal_rules.asset_extensions`.
        self.asset_extensions = set(
            ext.lower() for ext in
            (self.rules.get("asset_extensions") or []) if ext
        )
        # Contadores de filtros (AST-024 + EDG-023) — para reportar al usuario
        # cuántas edges se descartaron antes de emitir el grafo.
        self._filter_counts = {
            "asset": 0,          # AST-024: target con extensión binaria
            "ignored": 0,        # AST-024/EDG-023: target matchea ignore_*
            "self_edge": 0,      # edge src == tgt
            "ignore_outbound": 0,  # match contra graph.ignore_outbound_patterns
        }

        # Registro para unificar identidades de archivos
        self.file_registry = {}
        self._index_existing_files()

        # --- Stack detection (STK-001 + MST-006) -------------------------
        # StackMap: dict[str, str] — keys = subdir posix rel a project_root
        # ("" = raíz), values = stack name. Resolución por archivo via
        # longest-prefix match (resolve_file_stack).
        self.stack_detector = StackDetector(
            stack_markers=self.config.get("stack_markers", {}) or {},
            ignore_folders=self.ignore_folders,
            text_extensions=self.text_extensions,
        )
        self.stack_map = self.stack_detector.detect(self.project_root)

        # --- Path resolver (RES-002 + SEM-020) ---------------------------
        # PathResolver convierte raw imports a paths absolutos posix. El
        # scanner dispatcher (SCN-003) produce los raws; el resolver los
        # interpreta según el lenguaje del archivo fuente.
        # SEM-020: detectar theme_root / plugins_root para proyectos WP.
        theme_root, plugins_root = self._detect_wp_roots()
        self.path_resolver = PathResolver(
            self.project_root,
            config=self.config,
            theme_root=theme_root,
            plugins_root=plugins_root,
        )

        # --- Incremental cache (INC-008) ---------------------------------
        # `previous_cache` es el contenido previo de fingerprints.json. Si
        # `force_full` o el archivo no existe / es inválido / cambió de
        # versión, partimos vacío. `current_cache` se va llenando durante
        # analyze() y se persiste en finalize().
        # TIER-035 — _cached_external_tiers se puebla dentro de _load_fingerprints
        # si el cache tenía tiers de un run previo. Default vacío.
        self._cached_external_tiers = {}
        self.previous_cache = self._load_fingerprints()
        self.current_cache = {}

        self.atlas = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "project_name": self.project_root.name,
            "identities": [],
            "stack_map": dict(self.stack_map),
            "summary": {"total_files": 0, "relevant_files": 0},
            "connectivity": {"inbound": [], "outbound": []},
            "audit": {"structural_health": 100.0, "warnings": []},
            "anomalies": [],
            # DYN-007: nodos por archivo, con `tier` y `reason` para clasificación.
            # SESIÓN 20 (ITEM 1): tier = "connected" | "orphan" | "ambiguous" | "dynamic"
            "files": {},
            "orphans": [],
            "ambiguous": []
        }
        # EDG-023 — edges estructuradas: lista de tuplas
        # `(src_rel, target_label, edge_type, kind)`. El `.dot` se renderiza
        # desde acá en `_emit_dot_graph()` via graph_emitter.build_dot_content.
        # `kind`: "file" | "external" | "external_legacy".
        self._edges = []
        # GRF-021: nodos externos emitidos (label → display name). Cada
        # external_service matcheado genera un único nodo `[EXTERNAL:<label>]`,
        # con shape cylinder + color rojo. Se unifican las edges entrantes.
        self._external_nodes = {}
        # TIER-035: tier semántico por external node label.
        # dict[str label → str tier ('stdlib'|'package'|'service'|'wrapper')].
        self._external_node_tiers = {}
        # GRF-021: llamadas builtin/stdlib/no-resolvable por archivo fuente.
        # dict[rel_path: list[str]]. Se emiten como `metadata.calls` del
        # nodo en atlas.files, no como edges ni nodos del grafo.
        self._metadata_calls = {}
        # AST-024 — assets por archivo fuente: dict[rel_path: list[str]].
        # Se agregan como `metadata.assets` del nodo source.
        self._metadata_assets = {}
        # AST-024 (scope extendido): refs filtradas por ignore_*.
        # dict[rel_path: list[str]]. Se agregan como `metadata.filtered_refs`.
        self._metadata_filtered_refs = {}
        # Lista de archivos vistos en el walk para la pasada de orphans.
        self._all_scanned_files = []
        # Cache normalizado de dynamic_deps: dict[str, list[str]].
        self._dynamic_deps = self._normalize_dynamic_deps(
            self.config.get("dynamic_deps", {}) or {}
        )

    # ------------------------------------------------------------------
    # Template shipment (delegado a compass.template_io)
    # ------------------------------------------------------------------
    def ensure_local_template(self):
        """Crea `compass.local.json` + `compass.local.md` en `.map/` la primera vez.

        Delegado a `compass.template_io.ensure_local_template` — mantenemos
        el método en la clase para preservar la API `self.ensure_local_template()`.
        """
        ensure_local_template(self.map_dir, self.script_dir)

    def _ensure_local_json(self):
        """Shim backward-compat — los tests/validation podrían llamarlo."""
        from compass.template_io import _ensure_local_json
        _ensure_local_json(self.map_dir)

    def _ensure_local_help_md(self):
        """Shim backward-compat — los tests/validation podrían llamarlo."""
        from compass.template_io import _ensure_local_help_md
        _ensure_local_help_md(self.map_dir, self.script_dir)