import os
import json
import re
import fnmatch
from pathlib import Path
from datetime import datetime

from compass.stack_detector import StackDetector, resolve_file_stack
from compass.path_resolver import PathResolver
from compass.scanners import get_scanner, languages_without_scanner


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
LOCAL_TEMPLATE_NAME = "compass.local.template.json"

_SCHEMA_SECTIONS = (
    "basal_rules",
    "stack_markers",
    "language_grammars",
    "scoring",
    "graph",
    "definitions",
)

_LOCAL_TEMPLATE = {
    "_comment": (
        "Overrides locales para Architect's Compass. Solo incluí lo que "
        "quieras sumar o pisar respecto del mapper_config.json basal. "
        "Las listas se extienden (dedup); las definitions con el mismo "
        "'name' pisan a las globales."
    ),
    "basal_rules": {
        "ignore_folders": [],
        "ignore_files": [],
        "ignore_patterns": []
    },
    "definitions": []
}


class ArchitectCompass:
    def __init__(self):
        self.script_dir = Path(__file__).parent.parent.absolute()
        self.global_config_path = self.script_dir / "mapper_config.json"
        self.project_root = Path.cwd()
        self.map_dir = self.project_root / ".map"
        self.local_config_path = self.map_dir / LOCAL_CONFIG_NAME
        self.legacy_local_config_path = self.map_dir / LEGACY_LOCAL_CONFIG_NAME

        self.config = self.load_config_hierarchy()

        # Vistas cómodas de las secciones (siempre dicts, nunca None)
        self.rules = self.config.get("basal_rules", {}) or {}
        self.graph_rules = self.config.get("graph", {}) or {}
        self.scoring_rules = self.config.get("scoring", {}) or {}

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

        self.atlas = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "project_name": self.project_root.name,
            "identities": [],
            "stack_map": dict(self.stack_map),
            "summary": {"total_files": 0, "relevant_files": 0},
            "connectivity": {"inbound": [], "outbound": []},
            "audit": {"structural_health": 100.0, "warnings": []},
            "anomalies": []
        }
        self.dot_edges = []

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------
    def ensure_local_template(self):
        """Crea un `compass.local.template.json` en `.map/` la primera vez.

        El template contiene solo placeholders de overrides (schema v2). El
        usuario lo copia a `compass.local.json` y edita lo que necesite.
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

                # Stack por archivo (longest-prefix match en StackMap).
                file_stack = self.resolve_stack_for(rel_path)
                stack_file_counts[file_stack] = stack_file_counts.get(file_stack, 0) + 1

                # Lenguaje por archivo (autoritativo por extensión).
                language = _language_for_file(file)

                try:
                    is_relevant = self._scan_file(
                        file_path=file_path,
                        rel_path=rel_path,
                        filename=file,
                        language=language,
                        inbound_index=inbound_index,
                        tech_scores=tech_scores,
                        unify_lower=unify_lower,
                        compiled_ignore_outbound=compiled_ignore_outbound,
                    )
                    if is_relevant:
                        self.atlas["summary"]["relevant_files"] += 1
                except Exception as e:
                    self.atlas["anomalies"].append(f"{rel_path}: {str(e)}")

        # Feedback: lenguajes que no tuvieron scanner disponible.
        missing = languages_without_scanner()
        if missing:
            self.atlas["audit"]["warnings"].append(
                "Sin scanner disponible: " + ", ".join(sorted(m for m in missing if m))
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
        (definition_name, [compiled_patterns]).
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
                out.append((df.get("name", "unknown"), compiled))
        return out

    def _scan_file(self, *, file_path, rel_path, filename, language,
                   inbound_index, tech_scores, unify_lower,
                   compiled_ignore_outbound):
        """Escanea un archivo: inbound scoring + outbound via scanner/resolver.

        Devuelve True si el archivo es "relevante" (tiene inbound matches,
        outbound matches, o es .js/.css — criterio heredado del core viejo).
        """
        is_relevant = any(filename.endswith(ext) for ext in (".js", ".css"))

        # Inbound: se sigue leyendo contenido para pattern matching de scoring.
        if inbound_index:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                content = ""
            for name, compiled_list in inbound_index:
                for pat, regex in compiled_list:
                    if regex.search(content):
                        self.atlas["connectivity"]["inbound"].append(
                            f"{rel_path} <- {pat}"
                        )
                        tech_scores[name] = tech_scores.get(name, 0) + 10
                        is_relevant = True

        # Outbound: delegado al scanner dispatcher.
        scanner = get_scanner(language, self.config)
        raw_imports = scanner.extract_imports(str(file_path))
        if not raw_imports:
            return is_relevant

        src_abs = str(file_path.resolve())
        for raw in raw_imports:
            final_node = self._resolve_outbound_node(
                raw, language, src_abs, unify_lower
            )
            if final_node is None:
                continue
            if any(r.search(final_node) for r in compiled_ignore_outbound):
                continue
            if final_node == rel_path:
                continue

            self.atlas["connectivity"]["outbound"].append(
                f"{rel_path} -> {final_node}"
            )
            self.dot_edges.append(
                f'    "{rel_path}" -> "{final_node}" [label="calls", color="red"];'
            )
            is_relevant = True
        return is_relevant

    def _resolve_outbound_node(self, raw, language, source_abs, unify_lower):
        """Devuelve el label final para un outbound, o None para descartarlo.

        Orden:
            1. Match exacto contra unify_external_nodes (bare npm package o
               similar) → devolver el nombre lowercased (nodo unificado).
            2. PathResolver.resolve() → posix rel al project_root si resolvió.
            3. Si no resolvió y NO parece path (sin /, sin . inicial) → None
               (evitar nodos fantasma: memory/feedback_resolve_identity.md).
            4. Si no resolvió pero parece path → devolver la versión stripeada
               como label externo.
        """
        if raw is None:
            return None
        cleaned = str(raw).strip().strip("'\"`").strip()
        if not cleaned:
            return None

        # Nodo unificado (react, axios, anthropic, ...). Aceptamos match por
        # igualdad exacta lower-cased o por token base (primer segmento antes
        # de '/' — ej: '@tauri-apps/api' → 'tauri-apps').
        lower = cleaned.lower()
        if lower in unify_lower:
            return lower
        head = lower.split("/", 1)[0].lstrip("@")
        if head in unify_lower:
            return head

        resolved_abs = self.path_resolver.resolve(raw, language, source_abs)
        if resolved_abs:
            try:
                return Path(resolved_abs).resolve().relative_to(
                    self.project_root
                ).as_posix()
            except ValueError:
                return None

        # No resolvió. Fallback controlado: SOLO aceptar como nodo externo
        # si el raw parece path o bare specifier razonable. Nunca convertir
        # con limpieza agresiva (ese era el bug de _resolve_identity).
        if "/" in cleaned or cleaned.startswith(".") or cleaned.startswith("@"):
            return cleaned
        # Bare specifiers (react, lodash) también son nodos externos válidos.
        if re.match(r"^[A-Za-z0-9_.\-]+$", cleaned):
            return cleaned
        return None

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
        for edge in sorted(set(self.dot_edges)):
            dot_content += edge + "\n"
        dot_content += "}"

        with open(self.map_dir / "connectivity.dot", "w", encoding="utf-8") as f:
            f.write(dot_content)

        with open(self.map_dir / "atlas.json", "w", encoding="utf-8") as f:
            json.dump(self.atlas, f, indent=4, ensure_ascii=False)

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
