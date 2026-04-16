import os
import json
import re
import fnmatch
import hashlib
from pathlib import Path
from datetime import datetime

from compass.stack_detector import StackDetector, resolve_file_stack
from compass.path_resolver import PathResolver
from compass.scanners import (
    get_scanner,
    languages_without_scanner,
    reset_cache as reset_scanner_cache,
    _definition_applies_to_language,
)


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


# -----------------------------------------------------------------------------
# Config schema v2 (CFG-005)
# -----------------------------------------------------------------------------
# Top-level keys reconocidos en mapper_config.json:
#
#   basal_rules        → ignore_folders, text_extensions, ignore_files,
#                        ignore_patterns   (IGN-016)
#   stack_markers      → detección de stack (STK-001)
#   language_grammars  → scanner dispatcher (SCN-003)
#   scoring            → network/persistence/identity triggers (SCR-009)
#   graph              → unify_external_nodes, ignore_outbound_patterns
#   definitions        → recetas regex Tier 3 (SCN-003)
#
# El config local vive en [proyecto]/.map/compass.local.json y contiene
# solo overrides (no el schema completo). El archivo legacy
# .map/mapper_config.json se sigue leyendo por compatibilidad.
# -----------------------------------------------------------------------------

LOCAL_CONFIG_NAME = "compass.local.json"
LEGACY_LOCAL_CONFIG_NAME = "mapper_config.json"
LOCAL_TEMPLATE_NAME = "compass.local.json"
FINGERPRINTS_NAME = "fingerprints.json"
FINGERPRINTS_VERSION = 1

_SCHEMA_SECTIONS = (
    "basal_rules",
    "stack_markers",
    "language_grammars",
    "scoring",
    "graph",
    "definitions",
    "dynamic_deps",
    "external_services",
)

_LOCAL_TEMPLATE = {
    "_README": [
        "compass.local.json — Overrides por proyecto de Architect's Compass.",
        "",
        "Cómo leer este archivo:",
        "  • Los campos REALES (basal_rules, dynamic_deps, definitions,",
        "    external_services) arrancan vacíos ({} o []).",
        "  • Al lado de cada campo real hay un '_example_<campo>' con datos",
        "    FAKE pero realistas, mostrando el shape exacto que el tool espera.",
        "  • Los '_how_to_<campo>' son tips cortos (una o dos líneas) sobre",
        "    cuándo usar cada campo.",
        "  • Todo lo que empiece con '_' es ignorado por Compass. Podés borrar",
        "    los ejemplos sin afectar el análisis.",
        "",
        "Workflow típico:",
        "  1. Corré `compass` sin tocar nada — ves los huérfanos y ruido.",
        "  2. Si un huérfano es falso (lo carga un autoloader) → agregalo a",
        "     dynamic_deps copiando el shape del '_example_dynamic_deps'.",
        "  3. Si querés excluir ruido (vendor, minificados) → basal_rules.",
        "  4. Si tu proyecto usa un framework custom → definitions.",
        "  5. Si hablás con un SDK externo custom → external_services.",
        "",
        "Merge: tus entradas se SUMAN al mapper_config.json basal del tool",
        "(dedup automático). En 'definitions', si repetís un 'name' pisás el",
        "basal; si no, se agrega al final. Borrar un campo entero (o dejarlo",
        "vacío) no saca nada del basal — solo omite tus overrides."
    ],

    "_how_to_basal_rules": [
        "Reglas de scanning — excluís carpetas/archivos/patterns del análisis.",
        "  ignore_folders  → nombre EXACTO de carpeta (a cualquier profundidad).",
        "                    NO es path. Ejemplo: 'vendor', no 'src/vendor'.",
        "  ignore_files    → path relativo posix EXACTO desde la raíz del proyecto.",
        "  ignore_patterns → globs fnmatch. Se prueban contra basename y rel_path.",
        "                    Ejemplo: '*.min.js' matchea 'foo.min.js' en cualquier dir."
    ],
    "_example_basal_rules": {
        "ignore_folders": ["node_modules", "vendor", "dist", ".serena", "brandbook-legacy"],
        "ignore_files": [
            "scripts/Search-Replace-DB/index.php",
            "docs/third-party/legacy-admin.php",
            "assets/sede-fake.jpg"
        ],
        "ignore_patterns": ["*.min.js", "*.min.css", "*.bundle.js", "*.map", "*.backup.php"]
    },
    "basal_rules": {
        "ignore_folders": [],
        "ignore_files": [],
        "ignore_patterns": []
    },

    "_how_to_dynamic_deps": [
        "Declarás archivos que el scanner NO puede resolver estáticamente",
        "(autoloaders, hooks WP, includes con variables, plugins reflexivos).",
        "Los marcados acá dejan de aparecer como huérfanos falsos.",
        "",
        "La KEY es el owner (el archivo que carga cosas). El VALUE puede ser:",
        "  • string     → sólo declarar el owner con una nota (no sabés targets)",
        "  • list       → lista de targets concretos que carga",
        "  • dict       → { description, targets } si querés ambos",
        "",
        "Paths siempre relativos posix desde la raíz del proyecto."
    ],
    "_example_dynamic_deps": {
        "includes/autoload.php": "carga dinámicamente src/modules/*.php via spl_autoload_register",
        "src/hooks.php": [
            "src/handlers/save-post.php",
            "src/handlers/delete-post.php",
            "src/handlers/publish-post.php"
        ],
        "wp-content/themes/mytheme/functions.php": {
            "description": "enqueues vía wp_enqueue_script/style — el scanner WP no resuelve get_template_directory_uri() todavía (ver SEM-020)",
            "targets": [
                "wp-content/themes/mytheme/js/main.js",
                "wp-content/themes/mytheme/css/style.css",
                "wp-content/themes/mytheme/inc/custom-taxonomies.php"
            ]
        }
    },
    "dynamic_deps": {},

    "_how_to_definitions": [
        "Recetas regex Tier 3 para scanning de patterns por lenguaje.",
        "Cada entry representa un 'dialect' o framework: patterns inbound",
        "(suman tech_score al archivo que matchea) y outbound (generan",
        "edges del grafo). Copiá el shape de '_example_definitions' y editá.",
        "",
        "Campos por entry:",
        "  name     — único. Si coincide con uno del basal, lo PISA.",
        "  stack    — (opcional) nombre del stack al que pertenece (sólo doc).",
        "  language — ('php'|'javascript'|'python'|'html'|...) OBLIGATORIO.",
        "             Las patterns sólo corren contra archivos de ese lenguaje.",
        "  tier     — 'regex_fallback' (por ahora el único soportado).",
        "  patterns.inbound[]  → regex SIN capture group (string match → scoring).",
        "  patterns.outbound[] → regex CON un capture group; el grupo 1 es el",
        "                        target de la dependencia que se resuelve a path."
    ],
    "_example_definitions": [
        {
            "name": "MyFramework-PHP-Endpoints",
            "stack": "MyFramework",
            "language": "php",
            "tier": "regex_fallback",
            "patterns": {
                "inbound": [
                    "@Route\\(",
                    "register_endpoint\\s*\\("
                ],
                "outbound": [
                    "call_service\\s*\\(\\s*['\"]([^'\"]+)['\"]",
                    "include_template\\s*\\(\\s*['\"]([^'\"]+)['\"]"
                ]
            }
        },
        {
            "name": "MyProject-JS-ApiWrapper",
            "stack": "MyProject",
            "language": "javascript",
            "tier": "regex_fallback",
            "patterns": {
                "inbound": [],
                "outbound": [
                    "apiReq\\s*\\(\\s*['\"][A-Z]+['\"]\\s*,\\s*['\"]([^'\"]+)['\"]"
                ]
            }
        }
    ],
    "definitions": [],

    "_how_to_external_services": [
        "SDKs externos. Cuando el scanner captura un import/require que",
        "matchea alguno de los 'match' strings, el grafo emite un nodo",
        "'[EXTERNAL:<label>]' (cilindro rojo) en vez de buscar archivo del repo.",
        "",
        "Shape: dict { id: { label, match: [str, ...] } }.",
        "El 'id' es interno (sólo para vos). El 'label' es lo que se muestra",
        "en el grafo. 'match' es lista de needles case-insensitive — se",
        "compara por igualdad, prefijo '<needle>/', o primer segmento de",
        "paquete scoped."
    ],
    "_example_external_services": {
        "my_internal_api": {
            "label": "Mi-API-Interna",
            "match": ["my-internal-sdk", "@mycompany/api-client"]
        },
        "legacy_erp": {
            "label": "ERP-Legacy",
            "match": ["LegacyErp\\\\Client", "legacy_erp_connect"]
        },
        "mercadopago": {
            "label": "MercadoPago",
            "match": ["mercadopago", "@mercadopago/sdk-js", "MercadoPago\\\\SDK"]
        }
    },
    "external_services": {}
}


class ArchitectCompass:
    def __init__(self, force_full=False):
        """Inicializa el contexto del run.

        Parámetros:
            force_full: si True, ignora el cache de fingerprints y re-escanea
                todos los archivos. Reservado para CLI-015 (--full).
        """
        self.force_full = bool(force_full)
        self.script_dir = Path(__file__).parent.parent.absolute()
        self.global_config_path = self.script_dir / "mapper_config.json"
        self.project_root = Path.cwd()
        self.map_dir = self.project_root / ".map"
        self.local_config_path = self.map_dir / LOCAL_CONFIG_NAME
        self.legacy_local_config_path = self.map_dir / LEGACY_LOCAL_CONFIG_NAME
        self.fingerprints_path = self.map_dir / FINGERPRINTS_NAME

        self.config = self.load_config_hierarchy()

        # Vistas cómodas de las secciones (siempre dicts, nunca None)
        self.rules = self.config.get("basal_rules", {}) or {}
        self.graph_rules = self.config.get("graph", {}) or {}
        self.scoring_rules = self.config.get("scoring", {}) or {}
        # GRF-021: external services (SDKs por nombre de import).
        self.external_services = self.config.get("external_services", {}) or {}
        self._external_index = self._build_external_index(self.external_services)

        self.map_dir.mkdir(exist_ok=True)
        self.ensure_local_template()

        # --- Filtros de scan (IGN-016) -----------------------------------
        self.ignore_folders = set(self.rules.get("ignore_folders", []))
        self.ignore_files = set(self.rules.get("ignore_files", []))
        self.ignore_patterns = list(self.rules.get("ignore_patterns", []))
        self.text_extensions = set(
            self.rules.get("text_extensions", [".py", ".js", ".json", ".css"])
        )

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

        # --- Path resolver (RES-002) -------------------------------------
        # PathResolver convierte raw imports a paths absolutos posix. El
        # scanner dispatcher (SCN-003) produce los raws; el resolver los
        # interpreta según el lenguaje del archivo fuente.
        self.path_resolver = PathResolver(self.project_root)

        # --- Incremental cache (INC-008) ---------------------------------
        # `previous_cache` es el contenido previo de fingerprints.json. Si
        # `force_full` o el archivo no existe / es inválido / cambió de
        # versión, partimos vacío. `current_cache` se va llenando durante
        # analyze() y se persiste en finalize().
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
            # DYN-007: nodos por archivo, con `orphan_reason` opcional cuando
            # el archivo está marcado como dependencia dinámica declarada.
            "files": {},
            "orphans": []
        }
        self.dot_edges = []
        # GRF-021: nodos externos emitidos (label → display name). Cada
        # external_service matcheado genera un único nodo `[EXTERNAL:<label>]`,
        # con shape cylinder + color rojo. Se unifican las edges entrantes.
        self._external_nodes = {}
        # GRF-021: llamadas builtin/stdlib/no-resolvable por archivo fuente.
        # dict[rel_path: list[str]]. Se emiten como `metadata.calls` del
        # nodo en atlas.files, no como edges ni nodos del grafo.
        self._metadata_calls = {}
        # Lista de archivos vistos en el walk para la pasada de orphans.
        self._all_scanned_files = []
        # Cache normalizado de dynamic_deps: dict[str, list[str]].
        self._dynamic_deps = self._normalize_dynamic_deps(
            self.config.get("dynamic_deps", {}) or {}
        )

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------
    def ensure_local_template(self):
        """Crea un `compass.local.json` en `.map/` la primera vez.

        Si el archivo no existe, lo genera con placeholders de overrides
        (schema v2), incluyendo ejemplos de ignore_folders, ignore_files,
        ignore_patterns y dynamic_deps. El usuario lo edita directamente.
        Si ya existe, no lo sobrescribe (respeta edits previos).
        """
        template_path = self.map_dir / LOCAL_TEMPLATE_NAME
        if template_path.exists():
            return
        try:
            with open(template_path, "w", encoding="utf-8") as f:
                json.dump(_LOCAL_TEMPLATE, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ No se pudo crear el template local: {e}")

    def load_config_hierarchy(self):
        """Carga basal (repo) + overrides locales (proyecto) en ese orden.

        Jerarquía:
          1. `mapper_config.json` en la raíz del repo de Compass — basal.
          2. `[proyecto]/.map/compass.local.json` — overrides del proyecto.
          3. `[proyecto]/.map/mapper_config.json` — legacy (se lee si el
             nuevo no existe todavía; warning al usuario).
        """
        config = self._load_global_config()
        local_config, local_path_used = self._load_local_config()
        if local_config:
            self._merge_local_into(config, local_config)
            print(f"✅ Config local cargada: {local_path_used.name}")
        return config

    def _load_global_config(self):
        base = {section: {} for section in _SCHEMA_SECTIONS}
        base["definitions"] = []
        if not self.global_config_path.exists():
            return base
        try:
            with open(self.global_config_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            # Rellenar secciones faltantes con defaults vacíos
            for section in _SCHEMA_SECTIONS:
                if section not in loaded:
                    loaded[section] = [] if section == "definitions" else {}
            return loaded
        except Exception as e:
            print(f"⚠️ Error crítico cargando config global: {e}")
            return base

    def _load_local_config(self):
        """Intenta leer el config local; devuelve (data, path) o (None, None)."""
        path = self._resolve_local_config_path()
        if not path:
            return None, None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f), path
        except Exception as e:
            print(f"⚠️ Error leyendo {path.name}: {e}")
            return None, None

    def _resolve_local_config_path(self):
        if self.local_config_path.exists():
            return self.local_config_path
        if self.legacy_local_config_path.exists():
            print(
                f"⚠️ `{LEGACY_LOCAL_CONFIG_NAME}` en `.map/` es legacy; "
                f"renombralo a `{LOCAL_CONFIG_NAME}`."
            )
            return self.legacy_local_config_path
        return None

    def _merge_local_into(self, config, local_config):
        """Mergea overrides locales sobre el config basal in-place.

        - `definitions`: las locales pisan a las globales si comparten `name`;
          las nuevas se agregan al final.
        - Resto de secciones (dicts): listas se extienden (dedup ordenado),
          dicts anidados se mergean shallow, scalars se pisan.
        - Claves con prefijo `_` (ej: `_comment`) se ignoran.
        """
        for section, value in local_config.items():
            if section.startswith("_"):
                continue
            if section == "definitions":
                self._merge_definitions(config, value or [])
                continue
            if section not in _SCHEMA_SECTIONS:
                # Desconocida: la copiamos tal cual (forward-compat)
                config[section] = value
                continue
            self._merge_section_dict(config, section, value or {})

    @staticmethod
    def _merge_definitions(config, local_defs):
        existing = config.setdefault("definitions", [])
        index = {d.get("name"): i for i, d in enumerate(existing) if "name" in d}
        for local_def in local_defs:
            name = local_def.get("name")
            if name and name in index:
                existing[index[name]] = local_def
            else:
                existing.append(local_def)

    @staticmethod
    def _merge_section_dict(config, section, local_section):
        base_section = config.setdefault(section, {})
        if not isinstance(base_section, dict) or not isinstance(local_section, dict):
            config[section] = local_section
            return
        for key, val in local_section.items():
            if key.startswith("_"):
                continue
            base_val = base_section.get(key)
            if isinstance(val, list) and isinstance(base_val, list):
                base_section[key] = base_val + [v for v in val if v not in base_val]
            elif isinstance(val, dict) and isinstance(base_val, dict):
                merged = dict(base_val)
                merged.update(val)
                base_section[key] = merged
            else:
                base_section[key] = val

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
        return files

    def _config_fingerprint(self):
        """SHA-256 del JSON del config canonicalizado.

        Cualquier cambio en patterns, definitions, graph rules, etc.
        invalida el cache. Sort keys para que el hash sea estable.
        """
        try:
            blob = json.dumps(self.config, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            return None
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

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
        }
        try:
            with open(self.fingerprints_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"⚠️ No se pudo persistir fingerprints: {e}")

    # ------------------------------------------------------------------
    # Dynamic deps (DYN-007)
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_dynamic_deps(raw):
        """Normaliza `dynamic_deps` del config a dict[str, list[str]].

        El config acepta:
            "owner.php": "descripción libre"          → []  (solo declarar owner)
            "owner.php": ["target1.php", "target2.php"] → lista de targets
            "owner.php": {"description": "...", "targets": [...]}  → dict explícito

        Devuelve siempre un dict {owner_path: [target_path, ...]}; los owners
        sin targets explícitos quedan como [] (cubre el caso "este archivo
        carga *.php dinámicamente, no sé cuáles son").
        """
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
        """Set de todos los targets cubiertos por dynamic_deps.

        Cualquier archivo en este set se considera "alcanzado" por una
        dependencia dinámica declarada — no es huérfano.
        """
        out = set()
        for targets in self._dynamic_deps.values():
            for t in targets:
                out.add(t)
        return out

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
    # Identity resolution (DEPRECATED — RES-002 lo reemplazó)
    # ------------------------------------------------------------------
    # Desde RES-002/SCN-003 (Sesión 4 del PLAN) la resolución de imports
    # se delega a compass.path_resolver.PathResolver vía el scanner
    # dispatcher. Este método queda disponible sólo como referencia
    # histórica; el regex de limpieza `r'[^a-zA-Z0-9\._\/-]'` era la fuente
    # del bug de nodos fantasma (ver memory/feedback_resolve_identity.md)
    # y el `path_style = clean.replace('.', '/')` es la trampa documentada
    # en memory/feedback_path_style_trampa.md. No volver a usarlo.
    def _resolve_identity(self, raw_name):  # pragma: no cover - deprecated
        clean = re.sub(r'[^a-zA-Z0-9\._\/-]', '', str(raw_name)).strip().strip("'\"").rstrip('.')
        path_style = clean.replace(".", "/")

        parts = path_style.split("/")
        for i in range(len(parts), 0, -1):
            candidate = "/".join(parts[:i])
            if candidate in self.file_registry:
                return self.file_registry[candidate]
            if f"{candidate}.py" in self.file_registry:
                return self.file_registry[f"{candidate}.py"]

        for registry_path in self.file_registry:
            if registry_path.endswith(clean) and clean != "":
                return self.file_registry[registry_path]

        return clean

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
                            inbound_index=inbound_index,
                            tech_scores=tech_scores,
                            unify_lower=unify_lower,
                            compiled_ignore_outbound=compiled_ignore_outbound,
                        )
                        if file_metadata_calls:
                            self._metadata_calls[rel_path] = file_metadata_calls
                        if fingerprint is not None:
                            self.current_cache[rel_path] = {
                                "fingerprint": fingerprint,
                                "outbound_targets": file_outbound,
                                "inbound_patterns": file_inbound,
                                "tech_scores": file_tech_delta,
                                "is_relevant": is_relevant,
                                "stack": file_stack,
                                "metadata_calls": file_metadata_calls,
                            }
                        scanned += 1

                    if is_relevant:
                        self.atlas["summary"]["relevant_files"] += 1
                except Exception as e:
                    self.atlas["anomalies"].append(f"{rel_path}: {str(e)}")

        # INC-008: dejar visible cuántos archivos se reutilizaron del cache.
        self.atlas["summary"]["scanned_files"] = scanned
        self.atlas["summary"]["reused_from_cache"] = reused

        # DYN-007: clasificar orphans. Un archivo es huérfano cuando ningún
        # otro archivo del proyecto lo referencia (no aparece como destino
        # en outbound). Si está declarado como owner o como target en
        # `dynamic_deps`, se marca con orphan_reason="dynamic_declared".
        self._compute_orphans()

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

    def _scan_file(self, *, file_path, rel_path, filename, language,
                   inbound_index, tech_scores, unify_lower,
                   compiled_ignore_outbound):
        """Escanea un archivo: inbound scoring + outbound via scanner/resolver.

        Devuelve la tupla `(is_relevant, outbound_targets, inbound_patterns,
        tech_scores_delta, metadata_calls)` para que INC-008 cachee el
        detalle por archivo y pueda reproducir las contribuciones sin
        re-leer el contenido. `metadata_calls` es la lista de raws que
        GRF-021 clasifica como builtin/stdlib/no-resolvable (no emiten edge
        pero quedan visibles en atlas.files[rel_path].metadata.calls).
        """
        is_relevant = any(filename.endswith(ext) for ext in (".js", ".css"))
        outbound_targets = []
        inbound_patterns = []
        tech_scores_delta = {}
        metadata_calls = []

        # Inbound: se sigue leyendo contenido para pattern matching de scoring.
        # DEF-017: filtrar por lenguaje del archivo. Si la definition no
        # declara `language`, aplica a todos (backward-compat).
        if inbound_index:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                content = ""
            for name, df, compiled_list in inbound_index:
                if not _definition_applies_to_language(df, language):
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
        for raw in raw_imports:
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
                continue
            if final_node == rel_path:
                continue

            self.atlas["connectivity"]["outbound"].append(
                f"{rel_path} -> {final_node}"
            )
            self._register_edge(rel_path, final_node, kind)
            if kind == "external":
                self._register_external_node(final_node, classification["label_display"])
            outbound_targets.append(final_node)
            is_relevant = True
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
        """
        outbound_targets = cached.get("outbound_targets") or []
        inbound_patterns = cached.get("inbound_patterns") or []
        tech_delta = cached.get("tech_scores") or {}
        metadata_calls = cached.get("metadata_calls") or []
        is_relevant = bool(cached.get("is_relevant"))

        for pat in inbound_patterns:
            self.atlas["connectivity"]["inbound"].append(f"{rel_path} <- {pat}")
        for tgt in outbound_targets:
            self.atlas["connectivity"]["outbound"].append(f"{rel_path} -> {tgt}")
            # Re-clasificar al emitir el edge: si el target sigue siendo un
            # external service declarado, emitir como external; si es path
            # del repo, emitir como file; si no, tratarlo como external
            # legacy (no debería pasar si el config no cambió — pero si
            # cambió, el cache ya fue invalidado antes de llegar acá).
            kind, display = self._reclassify_cached_target(tgt)
            self._register_edge(rel_path, tgt, kind)
            if kind == "external":
                self._register_external_node(tgt, display)
        for name, delta in tech_delta.items():
            tech_scores[name] = tech_scores.get(name, 0) + delta
        if metadata_calls:
            self._metadata_calls[rel_path] = list(metadata_calls)

        return is_relevant

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

    @staticmethod
    def _build_external_index(services):
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
        #    También cubre URLs absolutas HTML como `https://…` si su host
        #    matchea un needle (no es el caso hoy, pero no rompe). NET-022
        #    hará el parseo proper.
        ext_label = self._match_external_service(cleaned)
        if ext_label:
            return {
                "kind": "external",
                "label": f"[EXTERNAL:{ext_label}]",
                "label_display": ext_label,
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
            return {
                "kind": "external",
                "label": f"[EXTERNAL:{display}]",
                "label_display": display,
            }

        # 4. Resto (builtins, stdlib, funciones de framework, libs locales
        #    sin resolver, URLs absolutas http/https no-declaradas). NO
        #    emiten nodo ni edge. Se acumulan en metadata.calls del nodo
        #    fuente para no perder la señal.
        return {"kind": "discard", "label": cleaned}

    def _register_edge(self, src_rel, target_label, kind):
        """Agrega una línea `.dot` para el edge src → target.

        El color del edge y su estilo dependen del tipo:
            file     → color="red"        (comportamiento existente)
            external → color="#cc4400"    (naranja para SDKs)
            external_legacy → color="red" (compat con cache viejo)
        """
        color = "red"
        if kind == "external":
            color = "#cc4400"
        self.dot_edges.append(
            f'    "{src_rel}" -> "{target_label}" [label="calls", color="{color}"];'
        )

    def _register_external_node(self, node_label, display_label):
        """Registra un nodo `[EXTERNAL:X]` para renderizarlo con shape/color.

        Unifica por label — múltiples sources apuntando al mismo external
        reusan el mismo nodo.
        """
        self._external_nodes[node_label] = display_label

    def _compute_orphans(self):
        """DYN-007: clasifica archivos sin inbound real como huérfanos.

        Reglas:
          - Archivo es candidato a huérfano si ningún edge outbound del
            proyecto lo referencia como target.
          - Si está declarado en `dynamic_deps` (como owner o como target),
            se marca con `orphan_reason: dynamic_declared` y NO se cuenta
            como huérfano "real" en el listado.
          - Cada archivo se registra en `atlas.files[rel_path]` con su
            stack y, si aplica, su `orphan_reason`.
        """
        # Construir set de targets internos (paths relativos al proyecto).
        internal_targets = set()
        for edge in self.atlas["connectivity"]["outbound"]:
            try:
                _, target = edge.split(" -> ", 1)
            except ValueError:
                continue
            target = target.strip()
            if target in self._file_registry_paths_set():
                internal_targets.add(target)

        dynamic_targets = self._dynamic_target_set()
        dynamic_owners = set(self._dynamic_deps.keys())

        for rel_path in self._all_scanned_files:
            node = {
                "stack": self.resolve_stack_for(rel_path),
            }
            is_orphan = rel_path not in internal_targets
            if rel_path in dynamic_owners or rel_path in dynamic_targets:
                node["orphan_reason"] = "dynamic_declared"
                if rel_path in dynamic_owners and self._dynamic_deps[rel_path]:
                    node["dynamic_targets"] = list(self._dynamic_deps[rel_path])
            elif is_orphan:
                node["orphan_reason"] = "no_inbound"
                self.atlas["orphans"].append(rel_path)
            self.atlas["files"][rel_path] = node

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

    # ------------------------------------------------------------------
    # Finalize
    # ------------------------------------------------------------------
    def finalize(self):
        dot_content = (
            "digraph G {\n"
            "    rankdir=LR;\n"
            "    concentrate=true;\n"
            "    node [shape=box, style=rounded, fontname=\"Arial\"];\n"
        )

        # GRF-021: emitir nodos [EXTERNAL:*] con shape distinto.
        for label, display in self._external_nodes.items():
            safe_label = label.replace('"', '\\"')
            dot_content += (
                f'    "{safe_label}" '
                f'[label="{display}", shape=cylinder, '
                f'style=filled, fillcolor="#ffcccc", color="#cc0000", '
                f'fontname="Arial"];\n'
            )

        for edge in sorted(set(self.dot_edges)):
            dot_content += edge + "\n"
        dot_content += "}"

        with open(self.map_dir / "connectivity.dot", "w", encoding="utf-8") as f:
            f.write(dot_content)

        # GRF-021: incluir metadata.calls en atlas.files.
        for rel_path, calls in self._metadata_calls.items():
            node = self.atlas["files"].get(rel_path)
            if node is None:
                continue
            if "metadata" not in node:
                node["metadata"] = {}
            node["metadata"]["calls"] = calls

        with open(self.map_dir / "atlas.json", "w", encoding="utf-8") as f:
            json.dump(self.atlas, f, indent=4, ensure_ascii=False)

        # INC-008: persistir fingerprints + per-file cache para el próximo run.
        self._persist_fingerprints()

        log_path = self.map_dir / "feedback.log"
        health = self.atlas["audit"]["structural_health"]

        new_entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] COMPASS RUN\n"
        new_entry += f"  - Salud Estructural: {health}%\n"
        new_entry += (
            f"  - Archivos: {self.atlas['summary']['total_files']} "
            f"(Relevantes: {self.atlas['summary']['relevant_files']})\n"
        )
        new_entry += "=" * 40 + "\n\n"

        old_content = ""
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                old_content = f.read()
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(new_entry + old_content)

        print(f"\n✨ Architect Compass finalizado.")
        print(f"📊 Salud Estructural: {health}%")

        if health < 80.0:
            print(" 💡 SUGERENCIA (ES):")
            print(" La salud estructural es baja porque faltan reglas específicas.")
            print(" Configurá '.map/compass.local.json' usando el template")
            print("-" * 30)
            print(" 💡 SUGGESTION (EN):")
            print(" Low structural health. The project needs specific rules.")
            print(" Set up '.map/compass.local.json' from the template")
