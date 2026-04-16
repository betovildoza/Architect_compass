"""Validación de `compass.local.json` — VAL-014 (Sesión 7).

Corre al inicio de `finalize()` después de que `analyze()` ya caminó el
proyecto y sabemos qué archivos existen en disco. Acumula warnings sin
abortar: los escribe en `atlas.audit.warnings` y los expone para que el
caller los imprima como sección `CONFIG WARNINGS` al cierre.

Reglas implementadas:

    1. dynamic_deps.<owner>.targets (o list plano) con paths que no
       existen en disco → `⚠ dynamic_deps: 'X' no existe en el proyecto`.
    2. definition.stack declarado sin stack correspondiente en
       stack_markers del config merged → `⚠ stack 'X' sin definición`.
       (Nota: nombramos la función con el caso "stacks referenciados"
       porque los stacks son los del `stack_markers`; el inverso — un
       stack_markers que no aparece en ninguna definition — no es error,
       mucho código se agrupa por stack sin necesitar una definition).
    3. Campos desconocidos en top-level del `compass.local.json`
       (distintos de _*, basal_rules, dynamic_deps, definitions,
       external_services, graph, scoring, stack_markers, language_grammars,
       scoring_weights) → `⚠ campo desconocido 'X'` — con sugerencia si
       hay un campo válido cercano por Levenshtein simple.
    4. Legacy en `.map/` del proyecto auditado: `mapper_config*.json` o
       `compass.local.template.json` → `⚠ legacy: 'X' es del schema v1 —
       borrar o reemplazar por compass.local.json`.
    5. Drift `_example_<campo>` vs default shipeado. Señal FUERTE de que
       el user editó el ejemplo creyendo que era el campo activo. Solo
       dispara si el campo activo está también vacío/default (evita
       falsos positivos cuando el user es consciente de que tiene el
       ejemplo editado como "scratchpad" y además tiene el campo activo
       con data propia).

Todas las rutas de salida usan posix / rel al project_root.

La lógica vive en un módulo separado (no en core.py) porque core.py
ya pasa holgadamente las 600 líneas y crece con cada sesión. Patrón
alineado con `metrics.py` (6A) y `graph_emitter.py` (6B/6C).
"""

from __future__ import annotations

import json
from pathlib import Path


# -----------------------------------------------------------------------------
# Schema conocido (UX-031 — campos activos del template)
# -----------------------------------------------------------------------------

_KNOWN_TOP_LEVEL_FIELDS = (
    # Campos activos expuestos a usuarios en el template.
    "basal_rules",
    "dynamic_deps",
    "definitions",
    "external_services",
    # Campos de schema que el usuario puede eventualmente overridear.
    "graph",
    "scoring",
    "scoring_weights",
    "stack_markers",
    "language_grammars",
)

# Prefijos reservados que Compass ignora al mergear (ver _merge_local_into).
# Estos NO se tratan como "desconocidos".
_IGNORED_PREFIXES = ("_",)

# Bloques `_example_<campo>` del template default. Se extraen del
# _LOCAL_TEMPLATE en runtime (pasados por el caller) para que drift
# detection compare contra lo que la versión actual de Compass shipea.


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _canonical(data):
    """JSON canonicalizado (sort_keys) para comparación estructural."""
    try:
        return json.dumps(data, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


def _levenshtein_suggest(word, candidates, max_distance=3):
    """Devuelve el candidato más cercano a `word` si la distancia ≤ max_distance.

    Implementación stdlib-only del algoritmo clásico. Suficiente para
    sugerir 'dynamic_deps' cuando el user tipea 'dinamic_deps'.
    """
    best = None
    best_dist = max_distance + 1
    for cand in candidates:
        dist = _levenshtein(word, cand)
        if dist < best_dist:
            best_dist = dist
            best = cand
    return best if best_dist <= max_distance else None


def _levenshtein(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(
                curr[-1] + 1,          # insert
                prev[j] + 1,           # delete
                prev[j - 1] + cost,    # substitute
            ))
        prev = curr
    return prev[-1]


def _file_exists(project_root, rel_posix):
    """Existencia en disco del path relativo posix — case-sensitive por norma."""
    try:
        p = project_root / rel_posix
        return p.exists()
    except (OSError, ValueError):
        return False


# -----------------------------------------------------------------------------
# Checks individuales
# -----------------------------------------------------------------------------

def _check_dynamic_deps(local_config, project_root):
    """Warning 1 — dynamic_deps con targets/owners que no existen en disco."""
    warnings = []
    dyn = (local_config or {}).get("dynamic_deps") or {}
    if not isinstance(dyn, dict):
        return warnings

    for owner, value in dyn.items():
        if not isinstance(owner, str) or owner.startswith("_"):
            continue
        owner_posix = owner.replace("\\", "/").strip()
        if not owner_posix:
            continue
        # Owner no tiene por qué existir como archivo (puede ser una
        # marca abstracta "este proceso carga cosas"), pero si el user
        # puso un path de archivo, validamos que exista.
        if "/" in owner_posix or owner_posix.endswith((".php", ".py", ".js", ".ts", ".html", ".htm", ".css")):
            if not _file_exists(project_root, owner_posix):
                warnings.append(
                    f"dynamic_deps: owner '{owner_posix}' no existe en el proyecto"
                )
        # Targets: acá SI exigimos que el path exista (es lo que "apunta" el owner).
        targets = []
        if isinstance(value, list):
            targets = [str(t).replace("\\", "/").strip() for t in value if t]
        elif isinstance(value, dict):
            raw_targets = value.get("targets") or []
            if isinstance(raw_targets, list):
                targets = [str(t).replace("\\", "/").strip() for t in raw_targets if t]
        for t in targets:
            if not t:
                continue
            if not _file_exists(project_root, t):
                warnings.append(
                    f"dynamic_deps: target '{t}' no existe en el proyecto"
                )
    return warnings


def _check_definitions_stacks(local_config, merged_config):
    """Warning 2 — definitions que declaran `stack` inexistente en stack_markers.

    La lista de stacks conocidos se toma del config MERGED (global + local),
    para que un usuario que declara stacks custom en el mismo local no
    reciba falso positivo.
    """
    warnings = []
    defs = (local_config or {}).get("definitions") or []
    if not isinstance(defs, list):
        return warnings
    known_stacks = set((merged_config or {}).get("stack_markers", {}).keys())
    for d in defs:
        if not isinstance(d, dict):
            continue
        declared = d.get("stack")
        declared_list = d.get("stacks") or []
        names = []
        if declared:
            names.append(str(declared))
        if isinstance(declared_list, list):
            names.extend(str(x) for x in declared_list)
        for name in names:
            if name and name not in known_stacks:
                def_name = d.get("name", "<anónima>")
                warnings.append(
                    f"definitions['{def_name}']: stack '{name}' sin definición en stack_markers"
                )
    return warnings


def _check_unknown_top_level(local_config):
    """Warning 3 — campos top-level desconocidos.

    Sugiere el campo válido más cercano si la distancia Levenshtein ≤ 3.
    """
    warnings = []
    if not isinstance(local_config, dict):
        return warnings
    for key in local_config.keys():
        if not isinstance(key, str):
            continue
        if key.startswith(_IGNORED_PREFIXES):
            continue
        if key in _KNOWN_TOP_LEVEL_FIELDS:
            continue
        suggestion = _levenshtein_suggest(key, _KNOWN_TOP_LEVEL_FIELDS)
        if suggestion:
            warnings.append(
                f"campo desconocido '{key}' — ¿quisiste decir '{suggestion}'?"
            )
        else:
            warnings.append(f"campo desconocido '{key}'")
    return warnings


def _check_legacy_artifacts(map_dir):
    """Warning 4 — artefactos legacy (schema v1) en `.map/` del proyecto."""
    warnings = []
    if not map_dir or not map_dir.exists():
        return warnings
    # Patrones que indican configs viejos pre-schema v2.
    # Nota: `compass.local.json` (sin `.template`) es válido y no se señala.
    for entry in sorted(map_dir.iterdir()):
        if not entry.is_file():
            continue
        name = entry.name
        # mapper_config.json o cualquier mapper_config*.json
        if name.startswith("mapper_config") and name.endswith(".json"):
            warnings.append(
                f"legacy: '.map/{name}' es del schema v1 — "
                f"borrar o reemplazar por compass.local.json"
            )
            continue
        # compass.local.template.json del shape pre-FIX-026 (rename a compass.local.json)
        if name == "compass.local.template.json":
            warnings.append(
                f"legacy: '.map/{name}' es del template pre-FIX-026 — "
                f"borrar o reemplazar por compass.local.json"
            )
    return warnings


def _strip_warning_markers(data):
    """Devuelve una copia de `data` sin claves `_WARNING` anidadas.

    Usado para comparar user vs default sin que el drift sea un falso
    positivo puramente inducido por la adición del banner `_WARNING`
    introducido en UX-031 (Sesión 7). Si tras pelar `_WARNING` el resto
    del ejemplo coincide con el default "desnudo" del user, es una
    desincronización cosmética y NO debe emitir warning.
    """
    if isinstance(data, dict):
        return {
            k: _strip_warning_markers(v)
            for k, v in data.items()
            if k != "_WARNING"
        }
    if isinstance(data, list):
        # En el _example_definitions el primer entry es {"_WARNING": ...};
        # si al pelarlo queda vacío, lo descartamos del list para alinear.
        out = []
        for item in data:
            stripped = _strip_warning_markers(item)
            if isinstance(stripped, dict) and not stripped:
                continue
            out.append(stripped)
        return out
    return data


def _check_example_drift(local_config, default_template):
    """Warning 5 — `_example_<campo>` editado vs default shipeado.

    Señal fuerte de edición equivocada (el user puso datos en el bloque
    ejemplo creyendo que era el campo activo). Dispara solo si:
      1. El `_example_<campo>` difiere estructuralmente del default
         (ignorando `_WARNING` — ver `_strip_warning_markers`).
      2. El campo activo `<campo>` está en default/vacío (señal fuerte
         de que el user puso la data en el ejemplo por error).

    Si el user tiene data en el activo (aunque también tenga data en el
    ejemplo), asumimos que sabe lo que hace — no warnear.
    """
    warnings = []
    if not isinstance(local_config, dict) or not isinstance(default_template, dict):
        return warnings

    for key in default_template.keys():
        if not isinstance(key, str) or not key.startswith("_example_"):
            continue
        if key not in local_config:
            continue  # user borró el ejemplo — OK, no es drift.
        local_example = _strip_warning_markers(local_config[key])
        default_example = _strip_warning_markers(default_template[key])
        # Equality estructural ignorando `_WARNING` — así users con
        # configs pre-UX-031 no reciben warnings falsos por el banner.
        if _canonical(local_example) == _canonical(default_example):
            continue
        # El ejemplo difiere. Chequear si el campo activo está "vacío".
        active_field = key[len("_example_"):]
        active_value = local_config.get(active_field)
        default_active = default_template.get(active_field)
        if _canonical(active_value) != _canonical(default_active):
            # El usuario SÍ tocó el campo activo también — probablemente
            # usó el ejemplo como scratchpad deliberadamente. No warnear.
            continue
        warnings.append(
            f"'{key}' editado — ¿quisiste poner esto en el campo activo "
            f"'{active_field}'? Los ejemplos no surten efecto (ver "
            f"compass.local.md sección 'Bloques _example_*')."
        )
    return warnings


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

def validate_local_config(
    *, local_config, merged_config, project_root, map_dir, default_template,
):
    """Corre todos los checks y devuelve una lista de strings de warning.

    Parámetros:
      local_config     — dict leído del `compass.local.json` del proyecto
                         auditado. Si no había local config, pasar {} o None.
      merged_config    — config efectivo (global + local merged + removals).
      project_root     — Path del raíz del proyecto auditado.
      map_dir          — Path del `.map/` del proyecto (para legacy checks).
      default_template — `_LOCAL_TEMPLATE` del core (para drift detection).

    Returns:
      list[str] — warnings listos para ser consumidos (prefijo `⚠ ` lo
      agrega el caller al imprimirlos; en `atlas.audit.warnings` van como
      strings tal cual).
    """
    warnings = []
    lc = local_config or {}

    warnings.extend(_check_dynamic_deps(lc, project_root))
    warnings.extend(_check_definitions_stacks(lc, merged_config))
    warnings.extend(_check_unknown_top_level(lc))
    warnings.extend(_check_legacy_artifacts(map_dir))
    warnings.extend(_check_example_drift(lc, default_template))

    return warnings