import os
import sys
import json
import re
import fnmatch
import hashlib
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse as _urlparse

from compass.stack_detector import StackDetector, resolve_file_stack
from compass.path_resolver import PathResolver
from compass.scanners import (
    get_scanner,
    languages_without_scanner,
    reset_cache as reset_scanner_cache,
    _definition_applies_to_language,
)
from compass.scanners.base import (
    normalize_edge_item,
    DEFAULT_EDGE_TYPE,
    resolve_default_edge_type,
)
from compass.metrics import (
    compute_health_score,
    detect_cycles,
    diff_against_previous,
    load_previous_snapshot,
    save_snapshot,
    build_snapshot_name,
    HISTORY_DIR_NAME,
)
from compass.graph_emitter import (
    build_dot_content,
    build_graph_html,
    validate_dot_syntax,
)
from compass.validation import validate_local_config


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
#   http_loaders       → funciones HTTP por lenguaje (NET-022)
#   external_services  → SDKs + URL patterns por host (GRF-021 + NET-022)
#
# El config local vive en [proyecto]/.map/compass.local.json y contiene
# solo overrides (no el schema completo). El archivo legacy
# .map/mapper_config.json se sigue leyendo por compatibilidad.
# -----------------------------------------------------------------------------

LOCAL_CONFIG_NAME = "compass.local.json"
LEGACY_LOCAL_CONFIG_NAME = "mapper_config.json"
LOCAL_TEMPLATE_NAME = "compass.local.json"
LOCAL_HELP_NAME = "compass.local.md"
LOCAL_HELP_TEMPLATE = "compass.local.md.tpl"
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
    "http_loaders",
)

# ------------------------------------------------------------------
# UX-031 + md-split (Sesión 7, pase 2) — shape del template por campo:
#   1. <campo>             — el campo ACTIVO (vacío, para editar). PRIMERO.
#   2. _example_<campo>    — shape de referencia con _WARNING banner
#                            explícito. Va como APÉNDICE inmediatamente
#                            después del activo.
# La documentación larga ("cuándo usar", sintaxis, casos típicos, workflow)
# se migró a un archivo paralelo `compass.local.md` al lado del JSON,
# generado desde `compass/templates/compass.local.md.tpl`. El JSON queda
# solo con datos + ejemplos; el user lee el MD una vez para entender el
# shape y después solo toca el JSON.
#
# El _WARNING dentro de cada _example_<campo> es la señal redundante:
# si alguien edita ahí, VAL-014 (warning 5) lo detecta al cierre del run
# comparando con el default shipeado (pelando _WARNING antes de comparar).
# ------------------------------------------------------------------

_EXAMPLE_WARNING = (
    "⚠ ESTE ES UN EJEMPLO DE REFERENCIA. NO EDITAR AQUÍ. "
    "Copiá la estructura al campo activo de arriba (mismo nombre sin "
    "el prefijo '_example_'). Ediciones en '_example_*' NO tienen efecto "
    "y Compass emite un warning al detectar drift vs el default shipeado."
)


# ------------------------------------------------------------------
# NET-023 complement — stdlib filter para auto-promoción externals.
#
# NET-023 promueve imports Python no-resueltos a [EXTERNAL:<head>]. Sin
# filtro, módulos stdlib (`os`, `sys`, `json`, `re`, `pathlib`, etc.)
# aparecen como nodos externos y ensucian el grafo con ruido que nunca
# es una dependencia real del proyecto.
#
# Estrategia:
#   - Python 3.10+: `sys.stdlib_module_names` (frozenset oficial).
#   - Fallback estático para Python 3.8/3.9 (baseline del proyecto).
#
# Config flag top-level `external_include_stdlib` (default False):
#   - False → stdlib filtrada (comportamiento default post-filtro).
#   - True  → stdlib vuelve a aparecer (parity con pre-filtro NET-023).
#
# El set fallback cubre ~280 módulos top-level de Python 3.8. Fuente:
# docs Python 3.8 (`docs.python.org/3.8/py-modindex.html`) + ajustes por
# módulos removidos en 3.9/3.10 pero presentes en 3.8 (formatter, parser,
# symbol, imp, binhex) — los dejamos para que `pathlib.head` matchee en
# entornos 3.8/3.9 exactos.
# ------------------------------------------------------------------

_PYTHON_STDLIB_FALLBACK = frozenset({
    # Core / builtins wrappers
    "__future__", "__main__", "_thread", "abc", "aifc", "antigravity",
    "argparse", "array", "ast", "asynchat", "asyncio", "asyncore", "atexit",
    "audioop", "base64", "bdb", "binascii", "binhex", "bisect", "builtins",
    "bz2", "cProfile", "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd",
    "code", "codecs", "codeop", "collections", "colorsys", "compileall",
    "concurrent", "configparser", "contextlib", "contextvars", "copy",
    "copyreg", "crypt", "csv", "ctypes", "curses", "dataclasses", "datetime",
    "dbm", "decimal", "difflib", "dis", "distutils", "doctest", "email",
    "encodings", "ensurepip", "enum", "errno", "faulthandler", "fcntl",
    "filecmp", "fileinput", "fnmatch", "formatter", "fractions", "ftplib",
    "functools", "gc", "genericpath", "getopt", "getpass", "gettext", "glob",
    "graphlib", "grp", "gzip", "hashlib", "heapq", "hmac", "html", "http",
    "idlelib", "imaplib", "imghdr", "imp", "importlib", "inspect", "io",
    "ipaddress", "itertools", "json", "keyword", "lib2to3", "linecache",
    "locale", "logging", "lzma", "macpath", "mailbox", "mailcap", "marshal",
    "math", "mimetypes", "mmap", "modulefinder", "msilib", "msvcrt",
    "multiprocessing", "netrc", "nis", "nntplib", "ntpath", "numbers",
    "opcode", "operator", "optparse", "os", "ossaudiodev", "parser", "pathlib",
    "pdb", "pickle", "pickletools", "pipes", "pkgutil", "platform", "plistlib",
    "poplib", "posix", "posixpath", "pprint", "profile", "pstats", "pty",
    "pwd", "py_compile", "pyclbr", "pydoc", "pydoc_data", "pyexpat", "queue",
    "quopri", "random", "re", "readline", "reprlib", "resource", "rlcompleter",
    "runpy", "sched", "secrets", "select", "selectors", "shelve", "shlex",
    "shutil", "signal", "site", "smtpd", "smtplib", "sndhdr", "socket",
    "socketserver", "spwd", "sqlite3", "sre_compile", "sre_constants",
    "sre_parse", "ssl", "stat", "statistics", "string", "stringprep",
    "struct", "subprocess", "sunau", "symbol", "symtable", "sys", "sysconfig",
    "syslog", "tabnanny", "tarfile", "telnetlib", "tempfile", "termios",
    "test", "textwrap", "threading", "time", "timeit", "tkinter", "token",
    "tokenize", "tomllib", "trace", "traceback", "tracemalloc", "tty",
    "turtle", "turtledemo", "types", "typing", "unicodedata", "unittest",
    "urllib", "uu", "uuid", "venv", "warnings", "wave", "weakref",
    "webbrowser", "winreg", "winsound", "wsgiref", "xdrlib", "xml", "xmlrpc",
    "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo",
})


# TIER-035 — ranking para que un segundo registro de un mismo external no
# degrade su tier. service gana siempre (señal de red externa).
_TIER_RANK = {"stdlib": 1, "package": 2, "wrapper": 3, "service": 4}


def _tier_rank(tier):
    return _TIER_RANK.get(tier, 0)


def _is_python_stdlib(module_head):
    """NET-023 complement — True si `module_head` es un módulo stdlib de Python.

    Precedencia:
      - Python 3.10+: `sys.stdlib_module_names` (frozenset oficial del CPython
        que corresponde a la versión del intérprete activo).
      - Python 3.8/3.9: fallback estático `_PYTHON_STDLIB_FALLBACK`.

    `module_head` es el primer segmento del import (ej. para `os.path`,
    head = `os`; para `urllib.request`, head = `urllib`).
    """
    if not module_head:
        return False
    stdlib_names = getattr(sys, "stdlib_module_names", None)
    if stdlib_names is not None:
        return module_head in stdlib_names
    return module_head in _PYTHON_STDLIB_FALLBACK

_LOCAL_TEMPLATE = {
    # ---- basal_rules ------------------------------------------------
    "basal_rules": {
        "ignore_folders": [],
        "ignore_files": [],
        "ignore_patterns": []
    },
    "_example_basal_rules": {
        "_WARNING": _EXAMPLE_WARNING,
        "ignore_folders": ["node_modules", "vendor", "dist", ".serena", "brandbook-legacy"],
        "ignore_files": [
            "scripts/Search-Replace-DB/index.php",
            "docs/third-party/legacy-admin.php",
            "assets/sede-fake.jpg"
        ],
        "ignore_patterns": ["*.min.js", "*.min.css", "*.bundle.js", "*.map", "*.backup.php"]
    },

    # ---- dynamic_deps -----------------------------------------------
    "dynamic_deps": {},
    "_example_dynamic_deps": {
        "_WARNING": _EXAMPLE_WARNING,
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

    # ---- definitions ------------------------------------------------
    "definitions": [],
    "_example_definitions": [
        {
            "_WARNING": _EXAMPLE_WARNING
        },
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

    # ---- stack_markers ----------------------------------------------
    "stack_markers": {},
    "_example_stack_markers": {
        "_WARNING": _EXAMPLE_WARNING,
        "MiFramework-Custom": {
            "files": ["mi-framework.lock", "mfw.config.js"],
            "folders": ["mfw-core"],
            "extensions": [".mfw"]
        }
    },

    # ---- external_services ------------------------------------------
    "external_services": {},
    "_example_external_services": {
        "_WARNING": _EXAMPLE_WARNING,
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
    }
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
            # DYN-007: nodos por archivo, con `orphan_reason` opcional cuando
            # el archivo está marcado como dependencia dinámica declarada.
            "files": {},
            "orphans": []
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
    # Config loading
    # ------------------------------------------------------------------
    def ensure_local_template(self):
        """Crea `compass.local.json` + `compass.local.md` en `.map/` la primera vez.

        Escribe AMBOS archivos en paralelo (md-split, Sesión 7 pase 2):
          - `compass.local.json` → shape con campos activos vacíos + bloques
            `_example_<campo>` de referencia (banner `_WARNING` interno).
          - `compass.local.md`   → documentación user-facing (qué hace cada
            campo, sintaxis, workflow de edición). Leída desde
            `compass/templates/compass.local.md.tpl`.

        Idempotente: si alguno ya existe, no lo pisa (el user puede haberlo
        editado). Los dos archivos se manejan independientes — faltando uno,
        solo se regenera ese.
        """
        self._ensure_local_json()
        self._ensure_local_help_md()

    def _ensure_local_json(self):
        template_path = self.map_dir / LOCAL_TEMPLATE_NAME
        if template_path.exists():
            return
        try:
            with open(template_path, "w", encoding="utf-8") as f:
                json.dump(_LOCAL_TEMPLATE, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ No se pudo crear el template local: {e}")

    def _ensure_local_help_md(self):
        help_path = self.map_dir / LOCAL_HELP_NAME
        if help_path.exists():
            return
        source = self.script_dir / "compass" / "templates" / LOCAL_HELP_TEMPLATE
        try:
            content = source.read_text(encoding="utf-8")
            help_path.write_text(content, encoding="utf-8")
        except FileNotFoundError:
            print(
                f"⚠️ Template de ayuda no encontrado: {source} "
                "(se omite compass.local.md)"
            )
        except Exception as e:
            print(f"⚠️ No se pudo crear compass.local.md: {e}")

    def load_config_hierarchy(self):
        """Carga basal (repo) + overrides locales (proyecto) en ese orden.

        Jerarquía:
          1. `mapper_config.json` en la raíz del repo de Compass — basal.
          2. `[proyecto]/.map/compass.local.json` — overrides del proyecto.
          3. `[proyecto]/.map/mapper_config.json` — legacy (se lee si el
             nuevo no existe todavía; warning al usuario).

        Sesión 6C: post-merge aplica `*_remove` keys para permitir restar
        entries del basal (ej. `asset_extensions_remove: [".svg"]`).

        Sesión 7 (VAL-014): guarda el local crudo en `self._raw_local_config`
        para que la validación end-of-run pueda inspeccionarlo sin ambigüedad
        (post-merge el shape cambia).
        """
        config = self._load_global_config()
        local_config, local_path_used = self._load_local_config()
        # VAL-014 — referencia al local crudo para validación posterior.
        self._raw_local_config = local_config or {}
        self._raw_local_config_path = local_path_used
        if local_config:
            self._merge_local_into(config, local_config)
            self._apply_removal_directives(config, local_config)
            print(f"✅ Config local cargada: {local_path_used.name}")
        return config

    # Sesión 6C — removal directives soportados en basal_rules.
    # Formato: `<list_name>_remove: [...]` resta las entries del basal.
    _REMOVAL_KEYS = (
        "asset_extensions",
        "ignore_patterns",
        "ignore_files",
    )

    @classmethod
    def _apply_removal_directives(cls, config, local_config):
        """Aplica `*_remove` del basal_rules local al basal merged.

        El user no puede hoy REMOVER una extensión del default (solo extender).
        Esto permite `{"basal_rules": {"asset_extensions_remove": [".svg"]}}`
        para proyectos que necesiten salir del default.
        """
        local_basal = (local_config or {}).get("basal_rules") or {}
        if not isinstance(local_basal, dict):
            return
        merged_basal = config.setdefault("basal_rules", {})
        for base_key in cls._REMOVAL_KEYS:
            remove_key = f"{base_key}_remove"
            removals = local_basal.get(remove_key)
            if not isinstance(removals, list) or not removals:
                continue
            current = merged_basal.get(base_key) or []
            if not isinstance(current, list):
                continue
            removal_set = {str(r) for r in removals if r}
            merged_basal[base_key] = [x for x in current if x not in removal_set]

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
            # Sesión 6C — `*_remove` se procesa en `_apply_removal_directives`
            # tras el merge; acá lo saltamos para no contaminar el basal con
            # claves sintéticas.
            if key.endswith("_remove"):
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
        # TIER-035 — exponer external_tiers cacheados para que el replay
        # pueda reusarlos sin recomputar (el recomputo pierde info parcial
        # como URL host → service cuando el host no está en match_urls).
        cached_tiers = data.get("external_tiers")
        if isinstance(cached_tiers, dict):
            self._cached_external_tiers = dict(cached_tiers)
        else:
            self._cached_external_tiers = {}
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

        # GRAPH-036 — detectar entry points del proyecto.
        self._detect_entry_points()

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
        DEFAULT_EDGE_TYPE para cada target. En el próximo scan-full el
        cache se regenera con edge_types reales.

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
        kept_targets = []
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
            kept_targets.append(tgt)
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

    @staticmethod
    def _build_external_url_index(services):
        """NET-022 — Construye índice de URL patterns para matchear hosts.

        Acepta dos shapes de config (dict o list, como _build_external_index).
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

    # Session 8 — NET-022b. Hostnames locales / de red privada (RFC 1918)
    # no son dependencias externas reales: son dev-noise (p.ej. `localhost`,
    # `127.0.0.1`, `192.168.x.x`) que ensucia el grafo. Se filtran en la
    # rama URL de `_classify_outbound` antes de emitir el nodo external.
    @staticmethod
    def _is_local_hostname(host):
        """Devuelve True si `host` es loopback, wildcard o red privada
        RFC 1918. Acepta hostname con/sin puerto (`localhost:3000`).
        """
        if not host:
            return False
        h = str(host).strip().lower()
        # Separar puerto si viene pegado (urlparse.hostname ya lo remueve,
        # pero este helper es defensivo por si se llama con host:port crudo).
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
        #    Imports Python y bare specifiers JS/TS que (a) no resolvieron
        #    contra el repo, (b) no matchearon external_services, (c) no
        #    matchearon unify_external_nodes → se promueven a
        #    `[EXTERNAL:<head>]` en vez de descartarse. Evita perder señal
        #    de dependencias reales (tiktoken, pydantic, fastapi, lodash,
        #    etc.) que no están hardcodeadas en el config.
        #
        #    Reglas por lenguaje:
        #      - Python: raw no-relativo (no empieza con `.`), sin `/`,
        #        primer segmento debe ser identifier válido. Head = primer
        #        segmento tras split por `.` y `:` (el scanner emite shape
        #        `pkg.sub:name` o `pkg.sub`). Relativos (`.foo`, `..pkg:x`)
        #        quedan como discard (son del repo pero no resolvieron —
        #        señal de bug/archivo faltante, no dep externa).
        #      - JS/TS: bare specifier (no empieza con `./`, `../`, `/`,
        #        `\`). Para scoped (`@scope/pkg/sub`) head = `@scope/pkg`
        #        (dos primeros segmentos). Para no-scoped (`lodash/get`)
        #        head = primer segmento.
        #      - PHP: por ahora no se aplica (la resolución PHP usa paths,
        #        no bare specifiers; las deps cross-plugin son scope de
        #        capa 2 fuera del alcance actual).
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

    # NET-023 — regex de identifier Python válido (ASCII-only, primer char
    # letra o underscore). Usado por `_auto_promote_external` para no
    # promover cualquier basura (ej. fragmentos accidentales del scanner).
    _PY_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

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
                # No debería pasar con el scanner stdlib (genera dotted),
                # pero si aparece un raw con slash lo tratamos como path
                # no-resuelto → discard.
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

    def _register_edge(self, src_rel, target_label, kind, edge_type=None):
        """EDG-023 — persiste un edge estructurado.

        Guarda `(src, target, edge_type, kind)` en `self._edges`. El
        rendering final al `.dot` lo hace `graph_emitter.build_dot_content`
        con colores por `edge_type` y kind (GRF-013).
        """
        et = edge_type or self.default_edge_type
        self._edges.append((src_rel, target_label, et, kind))

    def _is_asset_target(self, rel_path):
        """AST-024 — True si el target tiene una extensión de asset binario."""
        if not self.asset_extensions:
            return False
        ext = os.path.splitext(rel_path)[1].lower()
        return ext in self.asset_extensions

    # FIX-030 — Dotfiles de config que NUNCA deben aparecer como targets
    # del grafo, aunque el usuario haya overriden ignore_patterns vaciándolo.
    # Defense-in-depth para el caso disparador 2026-04-16: cerbero-setup/.env
    # apareciendo como nodo `AI-Agent-Framework` en level2agent-engine.
    # Son archivos de config/metadata — nunca fuente ni target real de
    # dependencias. El usuario puede editar ignore_patterns libremente;
    # este set fija un piso mínimo para la emisión del grafo (NO afecta
    # el walk: un archivo de config sigue pudiendo indexarse como source
    # si el user lo necesita expresamente removiéndolo de ignore_patterns).
    _DOTFILE_TARGET_PATTERNS = (
        ".env", ".env.*",
        ".gitignore", ".gitattributes",
        ".editorconfig",
        ".prettierrc", ".prettierrc.*",
        ".eslintrc", ".eslintrc.*",
    )

    def _is_ignored_target(self, rel_path):
        """AST-024 (scope extendido) — True si el target matchea ignore_*.

        Respeta `ignore_files` (path exacto) e `ignore_patterns` (globs
        fnmatch) también en la emisión de edges, no sólo en el índice de
        scan. Resuelve el hallazgo 2026-04-16 documentado en PLAN AST-024.

        FIX-030 — defense-in-depth: dotfiles de config (`.env`, `.gitignore`,
        `.eslintrc*`, etc.) SIEMPRE se filtran como targets del grafo,
        incluso si el usuario vació `ignore_patterns`. Evita que aparezcan
        como nodos con stack heredado del directorio (caso level2agent
        `cerbero-setup/.env` etiquetado `AI-Agent-Framework`).
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

    # TIER-035 — clasificación de tier para externals (package|stdlib|wrapper).
    # `service` se setea directamente en `_classify_outbound` cuando hay match
    # de URL o de external_service declarado. Este helper cubre la rama donde
    # el external se resolvió por nombre de paquete (unify legacy o
    # auto-promote), que son los dos lugares donde hay ambigüedad package vs
    # stdlib vs wrapper.
    def _classify_external_tier(self, display_label, language, is_service):
        if is_service:
            return "service"
        if not display_label:
            return "package"
        # Wrapper? El config `graph.external_wrappers` agrupa nombres
        # custom por lenguaje + "any" (cross-lang).
        if self._is_external_wrapper(display_label, language):
            return "wrapper"
        # Stdlib? Hoy solo Python tiene tabla confiable (sys.stdlib_module_names).
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

        Busca en la lista del lenguaje específico y en "any". Match case-insensitive
        por nombre completo del display (ej. `apiReq`).
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

    # GRAPH-036 — regex para `if __name__ == "__main__":` (variantes con
    # comillas simples/dobles + whitespace flexible).
    _PY_MAIN_RE = re.compile(
        r"^\s*if\s+__name__\s*==\s*['\"]__main__['\"]\s*:\s*$",
        re.MULTILINE,
    )

    # GRAPH-036 — regex para extraer paths de .bat/.sh (línea con `python
    # algo.py`, `node algo.js`, o ruta directa tipo `SET SCRIPT_PATH="..."`).
    # Captura cualquier token con extensión .py/.js/.ts/.mjs/.php/.sh/.bat.
    _SCRIPT_REF_RE = re.compile(
        r'''["']?([A-Za-z0-9_./\\:-]+\.(?:py|js|ts|mjs|tsx|jsx|php|sh|bat))["']?''',
        re.IGNORECASE,
    )

    def _detect_entry_points(self):
        """GRAPH-036 — detecta entry points del proyecto y los guarda en
        `atlas.entry_points`.

        Heurísticas:
          - **Python:** archivo contiene `if __name__ == "__main__":`.
          - **Shell/Batch en raíz:** archivos `.bat` / `.sh` en el root del
            proyecto se escanean para extraer referencias a scripts
            `.py/.js/.ts/...` — esos scripts referenciados se marcan como
            entry points (si existen en el repo).
          - **Node.js:** `package.json` en raíz → `main`, `bin` (string u
            objeto), `scripts.start` (si referencia un file directamente).
          - **PHP:** archivos `index.php` en la raíz del proyecto (no en
            subdirs — solo raíz).

        Output: lista ordenada de paths posix relativos al project_root,
        todos presentes en `self._all_scanned_files` (o agregados si existen
        pero quedaron fuera del walk — ej. `.bat` que no se indexa por
        extension).
        """
        entry_set = set()
        indexed = set(self._all_scanned_files)

        # 1) Python `__main__` — escaneo directo de los .py indexados.
        for rel_path in self._all_scanned_files:
            if not rel_path.endswith(".py"):
                continue
            try:
                abs_path = self.project_root / rel_path
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue
            if self._PY_MAIN_RE.search(content):
                entry_set.add(rel_path)

        # 2) Shell/Batch en raíz — leer cada .bat/.sh directamente de disco
        # (no están indexados por `text_extensions` default).
        try:
            for item in self.project_root.iterdir():
                if not item.is_file():
                    continue
                if item.suffix.lower() not in (".bat", ".sh"):
                    continue
                try:
                    content = item.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for m in self._SCRIPT_REF_RE.finditer(content):
                    raw = m.group(1).strip().strip("\"'")
                    if not raw:
                        continue
                    # Normalizar separadores y convertir absoluto → relativo
                    # si cae dentro del proyecto.
                    candidate = self._normalize_entry_candidate(raw)
                    if candidate and candidate in indexed:
                        entry_set.add(candidate)
        except OSError:
            pass

        # 3) package.json en raíz.
        pkg_json_path = self.project_root / "package.json"
        if pkg_json_path.is_file():
            try:
                pkg = json.loads(
                    pkg_json_path.read_text(encoding="utf-8", errors="ignore")
                )
            except (OSError, ValueError):
                pkg = None
            if isinstance(pkg, dict):
                # main
                main = pkg.get("main")
                if isinstance(main, str):
                    cand = self._normalize_entry_candidate(main)
                    if cand and cand in indexed:
                        entry_set.add(cand)
                # bin (string u objeto)
                bin_val = pkg.get("bin")
                if isinstance(bin_val, str):
                    cand = self._normalize_entry_candidate(bin_val)
                    if cand and cand in indexed:
                        entry_set.add(cand)
                elif isinstance(bin_val, dict):
                    for _k, v in bin_val.items():
                        if isinstance(v, str):
                            cand = self._normalize_entry_candidate(v)
                            if cand and cand in indexed:
                                entry_set.add(cand)
                # scripts.start (extraer archivo referenciado si existe)
                scripts = pkg.get("scripts")
                if isinstance(scripts, dict):
                    start_cmd = scripts.get("start")
                    if isinstance(start_cmd, str):
                        for m in self._SCRIPT_REF_RE.finditer(start_cmd):
                            cand = self._normalize_entry_candidate(m.group(1))
                            if cand and cand in indexed:
                                entry_set.add(cand)

        # 4) PHP + HTML estático: index.{php,html,htm} SOLO en raíz.
        #    No matchear `index.*` en subdirs — solo root.
        for candidate in ("index.php", "index.html", "index.htm"):
            p = self.project_root / candidate
            if p.is_file() and candidate in indexed:
                entry_set.add(candidate)

        # Persistir ordenado — estable para diff.
        self.atlas["entry_points"] = sorted(entry_set)

    def _normalize_entry_candidate(self, raw):
        """GRAPH-036 — normaliza un raw path (bat/sh/package.json) a posix
        relativo al project_root si cae dentro. Devuelve None si es externo
        o no se puede mapear.
        """
        if not raw:
            return None
        raw = raw.strip().strip('"').strip("'")
        # Windows vars simples del tipo %FOO% o $FOO — no se pueden resolver.
        if "%" in raw or (raw.startswith("$") and "/" not in raw):
            return None
        # Cleanup separadores.
        p = raw.replace("\\", "/")
        # Quitar prefijos relativos.
        while p.startswith("./"):
            p = p[2:]
        try:
            # Absoluto: intentar re-relativizar.
            candidate_path = Path(raw)
            if candidate_path.is_absolute():
                try:
                    rel = candidate_path.resolve().relative_to(
                        self.project_root
                    ).as_posix()
                    return rel
                except (ValueError, OSError):
                    return None
            # Relativo — asumimos root del proyecto como base.
            return p
        except (ValueError, OSError):
            return None

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
    # Estructura de finalize (Sesión 7 · VAL-014 agregado al inicio):
    #   0. _validate_local_config()       → atlas.audit.warnings + consola    (VAL-014, SES 7)
    #   1. _attach_metadata_calls()       → atlas.files[*].metadata.*         (GRF-021 + AST-024)
    #   2. _compute_metrics()             → health + cycles + delta           (SES 6A — SCR-009, CYC-011, DIF-010)
    #   3. _emit_dot_graph()              → connectivity.dot                  (GRF-013 + EDG-023 + AST-024)
    #   4. _emit_graph_html()             → graph.html (vis-network wrapper)  (GRF-013)
    #   5. _write_atlas()                 → atlas.json
    #   6. _rotate_history()              → .map/history/YYYYmmdd_HHMM_*.json (DIF-010)
    #   7. _persist_fingerprints()        → .map/fingerprints.json            (INC-008)
    #   8. _update_feedback_log()         → .map/feedback.log
    #   9. _print_summary()               → stdout
    #
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
        self._attach_metadata_calls()
        self._compute_metrics()
        self._emit_dot_graph()
        self._emit_graph_html()
        self._write_atlas()
        self._rotate_history()
        self._persist_fingerprints()
        self._update_feedback_log()
        self._print_summary()

    def _run_config_validation(self):
        """VAL-014 (Sesión 7) — valida el compass.local.json del proyecto.

        Warnings se acumulan SIN abortar. Se agregan a `atlas.audit.warnings`
        y se guardan en `self._config_warnings` para que `_print_summary`
        los muestre como sección `CONFIG WARNINGS:` (solo si hay ≥1).

        Usa el `_LOCAL_TEMPLATE` module-level como default shipeado para
        detectar drift en `_example_*` (warning 5).
        """
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
