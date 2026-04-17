"""Consolidación metadata + export compacto — Sesión 10.

Funciones puras stdlib-only invocadas desde `ArchitectCompass.finalize()`.
Se mantienen fuera de `core.py` para no invadir el scope del refactor
pendiente (REF-033).

  * CONS-029 — build_metadata_consolidated(atlas)
      Invierte la vista per-source `atlas.files[*].metadata.{assets,calls,filtered_refs}`
      a una vista global `{target: [source1, source2, ...]}` y la devuelve
      para ser pegada como `atlas.metadata_consolidated`. La vista per-source
      NO se toca — sigue intacta en `files[*].metadata`.

  * LLM-VIEW-028 — build_compact_atlas(atlas, edges, cycles, external_nodes)
      Construye un dict mínimo apto para pasar como contexto a un agente LLM:
      `nodes`, `edges`, `cycles`, `metadata_consolidated`, `summary`, `health`.
      Sin metadata explotada per-source. Typical size ~20-25% del atlas.json.

Ambas funciones son **puras**: no tocan disco, no dependen del objeto
ArchitectCompass, reciben ya calculados los datos.
"""

from __future__ import annotations


# =============================================================================
# CONS-029 — Consolidación metadata per-source → global
# =============================================================================

# Campos del shape `metadata` per-source que se consolidan. Cada uno es una
# lista de targets (strings). La inversión resultante es `{target: [sources]}`.
_CONSOLIDATABLE_FIELDS = ("assets", "calls", "filtered_refs")


def build_metadata_consolidated(atlas):
    """Invierte la vista per-source a una vista global.

    Input:
        atlas: dict con `files` populado, donde cada archivo puede tener
            `metadata.{assets,calls,filtered_refs}` como lista de strings.

    Output:
        dict con shape:
            {
              "assets":        {target: [source1, source2, ...]},
              "calls":         {target: [source1, source2, ...]},
              "filtered_refs": {target: [source1, source2, ...]},
            }

    Cada lista de sources está deduplicada y ordenada alfabéticamente
    (estable para diff). Los targets también se ordenan.
    """
    out = {field: {} for field in _CONSOLIDATABLE_FIELDS}
    files = atlas.get("files", {}) or {}
    for rel_path, node in files.items():
        md = (node or {}).get("metadata") or {}
        for field in _CONSOLIDATABLE_FIELDS:
            values = md.get(field) or []
            for target in values:
                if not target:
                    continue
                sources = out[field].setdefault(target, [])
                if rel_path not in sources:
                    sources.append(rel_path)
    # Orden estable (targets alfabéticos, sources dedupeados + ordenados).
    return {
        field: {t: sorted(srcs) for t, srcs in sorted(pairs.items())}
        for field, pairs in out.items()
    }


# =============================================================================
# LLM-VIEW-028 — Export compacto para agentes IA
# =============================================================================

# Schema del `atlas.compact.json`:
#   {
#     "schema_version": "compact/1",
#     "project_name": str,
#     "generated_at": str,
#     "summary": {total_files, relevant_files},
#     "health": {total, orphans, connectivity, dead_exports, external_deps},
#     "labels":     [str, ...]                      # pool unificado de paths + external labels
#                                                     # (referenciados por nodes[*][0] y edges[*][0/1])
#     "stacks":     [str, ...]                       # pool de nombres de stack
#     "edge_types": [str, ...]                       # pool de edge_type (import/fetch/href/…)
#     "edge_kinds": [str, ...]                       # pool de kind (file/external/…)
#     "nodes": [
#         [label_idx, stack_idx, orphan_flag]        # orphan_flag: 0=no, 1=no_inbound, 2=dynamic_declared
#     ],
#     "externals": [
#         [label_idx, tier_str_or_empty]
#     ],
#     "edges": [
#         [src_idx, tgt_idx, type_idx, kind_idx]     # todos índices a pools
#     ],
#     "cycles": [[path1, path2, path1]],
#     "entry_points": [str],
#     "metadata_consolidated": {...},  # producto de CONS-029
#   }


def build_compact_atlas(
    atlas,
    edges,
    external_nodes,
    external_tiers=None,
):
    """Construye el dict compacto para `atlas.compact.json`.

    Args:
        atlas: el atlas "full" ya finalizado (con cycles, health, etc.).
        edges: lista de tuplas `(src, tgt, edge_type, kind)` — la misma
            que `ArchitectCompass._edges`.
        external_nodes: dict `{label: display_name}` de externals emitidos.
        external_tiers: dict opcional `{label: tier}` (TIER-035).

    Returns:
        dict listo para `json.dump` con shape mínimo.

    Propiedades:
        * Sin `metadata.{assets,calls,filtered_refs}` per-source — en su lugar
          usa `metadata_consolidated` (una sola vez, global).
        * Preserva topología (mismos nodes + edges + cycles que el full).
        * No incluye `connectivity.inbound/outbound` humanos (strings
          "a -> b") — esos son redundantes con `edges` estructuradas.
        * No incluye `identities`, `stack_map`, `graph_filters`, `anomalies`,
          `audit.warnings`, `delta` — ruido para el LLM.
    """
    files = atlas.get("files", {}) or {}
    orphans = set(atlas.get("orphans", []) or [])

    # Pools de strings repetidos — pensado para recorte de tokens en LLM.
    label_pool = []
    label_idx = {}

    def _intern_label(name):
        if name not in label_idx:
            label_idx[name] = len(label_pool)
            label_pool.append(name)
        return label_idx[name]

    stack_pool = []
    stack_idx_map = {}

    def _intern_stack(name):
        if name not in stack_idx_map:
            stack_idx_map[name] = len(stack_pool)
            stack_pool.append(name)
        return stack_idx_map[name]

    type_pool = []
    type_idx_map = {}

    def _intern_type(t):
        if t not in type_idx_map:
            type_idx_map[t] = len(type_pool)
            type_pool.append(t)
        return type_idx_map[t]

    kind_pool = []
    kind_idx_map = {}

    def _intern_kind(k):
        if k not in kind_idx_map:
            kind_idx_map[k] = len(kind_pool)
            kind_pool.append(k)
        return kind_idx_map[k]

    # orphan_flag: 0=no orphan, 1=no_inbound, 2=dynamic_declared.
    _ORPHAN_CODE = {None: 0, "no_inbound": 1, "dynamic_declared": 2}

    # Nodes — tuple-form compacto con path pooled.
    nodes = []
    for rel_path in sorted(files.keys()):
        node = files[rel_path] or {}
        stack = node.get("stack") or "unknown"
        reason = node.get("orphan_reason")
        if rel_path in orphans and not reason:
            reason = "no_inbound"
        flag = _ORPHAN_CODE.get(reason, 0)
        nodes.append([_intern_label(rel_path), _intern_stack(stack), flag])

    # Externals — [label_idx, tier_or_empty].
    tiers = external_tiers or {}
    externals = []
    for label in sorted((external_nodes or {}).keys()):
        externals.append([_intern_label(label), tiers.get(label) or ""])

    # Edges — pools de edge_type / kind / labels (src + tgt).
    seen_edges = set()
    tmp_edges = []  # [(src_str, tgt_str, et, kind)] para ordenar antes de poolear
    for edge in edges or []:
        # Defensivo: los edges son tuplas 4 pero aceptamos 3 también.
        if len(edge) == 4:
            src, tgt, et, kind = edge
        elif len(edge) == 3:
            src, tgt, et = edge
            kind = "file"
        else:
            continue
        key = (src, tgt, et, kind)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        tmp_edges.append((src, tgt, et, kind))
    # Orden estable para diff.
    tmp_edges.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
    compact_edges = [
        [_intern_label(src), _intern_label(tgt), _intern_type(et), _intern_kind(kind)]
        for (src, tgt, et, kind) in tmp_edges
    ]

    health = atlas.get("health", {}) or {}
    # Breakdown mínimo — solo scores, no detalles.
    health_compact = {"total": health.get("total", 0)}
    for dim in ("orphans", "connectivity", "dead_exports", "external_deps"):
        sub = health.get(dim)
        if isinstance(sub, dict) and "score" in sub:
            health_compact[dim] = sub["score"]

    return {
        "schema_version": "compact/1",
        "project_name": atlas.get("project_name", ""),
        "generated_at": atlas.get("generated_at", ""),
        "summary": dict(atlas.get("summary", {}) or {}),
        "health": health_compact,
        "entry_points": list(atlas.get("entry_points", []) or []),
        "labels": label_pool,
        "stacks": stack_pool,
        "edge_types": type_pool,
        "edge_kinds": kind_pool,
        "nodes": nodes,
        "externals": externals,
        "edges": compact_edges,
        "cycles": list(atlas.get("cycles", []) or []),
        "metadata_consolidated": atlas.get("metadata_consolidated", {}) or {},
    }
