"""config_loader — jerarquía basal (repo) + local (proyecto) + fingerprint.

Extraído de `compass/core.py` (REF-033). Implementa el pase `__init__` del
orchestrator (`ArchitectCompass`) como funciones + mixin.

Jerarquía (ver `load_config_hierarchy`):
  1. `mapper_config.json` en la raíz del repo de Compass — basal.
  2. `[proyecto]/.map/compass.local.json` — overrides del proyecto.
  3. `[proyecto]/.map/mapper_config.json` — legacy (se lee si el nuevo no
     existe todavía; warning al usuario).

Post-merge aplica `*_remove` keys para permitir restar entries del basal
(p.ej. `asset_extensions_remove: [".svg"]`).

VAL-014: guarda el local crudo en `self._raw_local_config` para que la
validación end-of-run pueda inspeccionarlo sin ambigüedad (post-merge el
shape cambia).
"""

import hashlib
import json

from compass.template_io import (
    LEGACY_LOCAL_CONFIG_NAME,
    LOCAL_CONFIG_NAME,
)


# Top-level keys reconocidos en mapper_config.json (CFG-005):
#   basal_rules        → ignore_folders, text_extensions, ignore_files,
#                        ignore_patterns   (IGN-016)
#   stack_markers      → detección de stack (STK-001)
#   language_grammars  → scanner dispatcher (SCN-003)
#   scoring            → network/persistence/identity triggers (SCR-009)
#   graph              → unify_external_nodes, ignore_outbound_patterns
#   definitions        → recetas regex Tier 3 (SCN-003)
#   http_loaders       → funciones HTTP por lenguaje (NET-022)
#   external_services  → SDKs + URL patterns por host (GRF-021 + NET-022)
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


# Sesión 6C — removal directives soportados en basal_rules.
# Formato: `<list_name>_remove: [...]` resta las entries del basal.
_REMOVAL_KEYS = (
    "asset_extensions",
    "ignore_patterns",
    "ignore_files",
)


class ConfigLoaderMixin:
    """Mixin con los métodos de carga/merge de config.

    Consume: `self.global_config_path`, `self.local_config_path`,
        `self.legacy_local_config_path`.
    Produce: `self._raw_local_config`, `self._raw_local_config_path` como
        side-effects de `load_config_hierarchy()`; devuelve el config merged.
    """

    # Expuesto como atributo de clase por backward-compat (validation.py no lo
    # usa, pero algunos consumidores externos del legado sí).
    _REMOVAL_KEYS = _REMOVAL_KEYS

    def load_config_hierarchy(self):
        """Carga basal (repo) + overrides locales (proyecto) en ese orden."""
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