"""Emisor de grafo — GRF-013 + EDG-023 + AST-024 (+ Sesión 6C refinements).

Funciones puras (stdlib-only) que producen los artefactos visuales del
grafo a partir del atlas ya construido + edges + externos + config:

    * build_dot_content(...)     → string `.dot` profesional con clustering,
                                    colores por tipo de nodo y labels/colores
                                    por edge_type (EDG-023).
    * build_graph_html(...)      → HTML wrapper universal basado en vis-network
                                    (zoom/pan nativo, física interactiva). Se
                                    emite SIEMPRE para cualquier proyecto.
    * validate_dot_syntax(text)  → smoke check sin Graphviz.

Sesión 6C — cambios:
    - Template HTML externalizado a `compass/templates/graph.html.tpl` y leído
      en runtime con `pathlib`. ~100 líneas menos en este módulo.
    - Adopta vis-network (reference: ETCA `.map/graph_test.html`) reemplazando
      Viz.js/Graphviz → SVG estático. vis-network da zoom/pan/drag nativo.
    - 3 hardcodes a config: `graph.vis_network_cdn_url`, `graph.rankdir`,
      `graph.node_shapes`. Defaults preservados si no están en config.
"""

from __future__ import annotations

import json
from pathlib import Path


# =============================================================================
# Defaults (overridables vía mapper_config.json::graph.*)
# =============================================================================

_DEFAULT_NODE_COLORS = {
    "normal":   {"fillcolor": "#f5f5f5", "color": "#333333"},
    "orphan":   {"fillcolor": "#fff3cd", "color": "#b7791f"},
    "cycle":    {"fillcolor": "#fde0dc", "color": "#c0392b"},
    "external": {"fillcolor": "#ffcccc", "color": "#cc0000"},
}

_DEFAULT_EDGE_COLORS = {
    "import": "#1f7a1f", "require": "#333333", "include": "#555555",
    "src":    "#1f5fbf", "href":    "#2e86de", "action":  "#8e44ad",
    "fetch":  "#c0392b", "enqueue": "#7d3c98", "use":     "#888888",
}

# Shape por kind de nodo — configurable vía graph.node_shapes (Sesión 6C).
_DEFAULT_NODE_SHAPES = {
    "normal":   "box",
    "orphan":   "box",
    "cycle":    "box",
    "external": "cylinder",
}

_DEFAULT_RANKDIR = "LR"
_VALID_RANKDIRS = {"LR", "TB", "RL", "BT"}
_DEFAULT_VIS_NETWORK_CDN = (
    "https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"
)

# TIER-035 — colores por tier del external (overridable vía
# graph.external_tier_colors).
_DEFAULT_EXTERNAL_TIER_COLORS = {
    "stdlib":  "#9ca3af",
    "package": "#60a5fa",
    "service": "#a78bfa",
    "wrapper": "#f59e0b",
}

# GRAPH-036 — estilo del entry point (overridable vía
# graph.entry_point_*).
_DEFAULT_ENTRY_POINT_BORDER_COLOR = "#fbbf24"
_DEFAULT_ENTRY_POINT_BORDER_WIDTH = 4
_DEFAULT_ENTRY_POINT_SIZE_BOOST = 10
_DEFAULT_ENTRY_POINT_LABEL_PREFIX = ""

# Path al template HTML (Sesión 6C — externo para mantenibilidad).
_TEMPLATE_PATH = Path(__file__).parent / "templates" / "graph.html.tpl"


# =============================================================================
# Helpers comunes
# =============================================================================

def _escape_dot_id(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _cluster_key(rel_path):
    if not rel_path:
        return "<root>"
    norm = str(rel_path).replace("\\", "/")
    return "<root>" if "/" not in norm else norm.split("/", 1)[0]


def _nodes_in_cycles(cycles):
    out = set()
    for cycle in (cycles or []):
        for node in (cycle or []):
            out.add(node)
    return out


def _merge_color_dict(defaults, override):
    result = {k: dict(v) if isinstance(v, dict) else v
              for k, v in defaults.items()}
    if not isinstance(override, dict):
        return result
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            merged = dict(result[k])
            merged.update(v)
            result[k] = merged
        else:
            result[k] = v
    return result


def _classify_node(rel_path, orphan_set, cycle_set):
    if rel_path in cycle_set:
        return "cycle"
    if rel_path in orphan_set:
        return "orphan"
    return "normal"


def _resolve_rankdir(graph_config):
    raw = (graph_config or {}).get("rankdir", _DEFAULT_RANKDIR)
    rankdir = str(raw).upper()
    return rankdir if rankdir in _VALID_RANKDIRS else _DEFAULT_RANKDIR


def _resolve_node_shapes(graph_config):
    shapes = dict(_DEFAULT_NODE_SHAPES)
    override = (graph_config or {}).get("node_shapes") or {}
    if isinstance(override, dict):
        for k, v in override.items():
            if v:
                shapes[k] = str(v)
    return shapes


# =============================================================================
# DOT emission (GRF-013 + EDG-023)
# =============================================================================

def _render_subgraph(cluster_id, cluster_label, nodes_in_cluster,
                     orphan_set, cycle_set, node_colors, node_shapes):
    lines = []
    safe_cluster_id = (
        _escape_dot_id(cluster_id)
        .replace("-", "_").replace(".", "_").replace("/", "_")
    )
    safe_label = _escape_dot_id(cluster_label)
    lines.append(f'    subgraph "cluster_{safe_cluster_id}" {{')
    lines.append(f'        label="{safe_label}";')
    lines.append('        style="rounded,filled";')
    lines.append('        fillcolor="#fafafa"; color="#cccccc";')
    lines.append('        fontname="Arial"; fontsize=11;')
    for rel_path in sorted(nodes_in_cluster):
        kind = _classify_node(rel_path, orphan_set, cycle_set)
        colors = node_colors.get(kind, node_colors["normal"])
        shape = node_shapes.get(kind, "box")
        safe_id = _escape_dot_id(rel_path)
        fill = colors.get("fillcolor", "#f5f5f5")
        stroke = colors.get("color", "#333333")
        lines.append(
            f'        "{safe_id}" [shape={shape}, '
            f'fillcolor="{fill}", color="{stroke}"];'
        )
    lines.append('    }')
    return lines


def _render_external_nodes(external_nodes, node_colors, node_shapes):
    lines = []
    ext_colors = node_colors.get("external", _DEFAULT_NODE_COLORS["external"])
    shape = node_shapes.get("external", "cylinder")
    fill = ext_colors.get("fillcolor", "#ffcccc")
    stroke = ext_colors.get("color", "#cc0000")
    for label, display in sorted(external_nodes.items()):
        safe_id = _escape_dot_id(label)
        safe_disp = _escape_dot_id(display)
        lines.append(
            f'    "{safe_id}" [label="{safe_disp}", shape={shape}, '
            f'style=filled, fillcolor="{fill}", color="{stroke}", '
            f'fontname="Arial"];'
        )
    return lines


def _render_edges(edges, edge_colors):
    seen = set()
    lines = []
    for (src, tgt, edge_type, _kind) in sorted(set(edges)):
        key = (src, tgt, edge_type)
        if key in seen:
            continue
        seen.add(key)
        safe_src = _escape_dot_id(src)
        safe_tgt = _escape_dot_id(tgt)
        safe_label = _escape_dot_id(edge_type)
        color = edge_colors.get(edge_type, edge_colors.get("use", "#888888"))
        lines.append(
            f'    "{safe_src}" -> "{safe_tgt}" '
            f'[label="{safe_label}", color="{color}", '
            f'fontname="Arial", fontsize=9];'
        )
    return lines


def _render_legend(edge_colors, used_edge_types, node_colors):
    if not used_edge_types:
        return []
    lines = []
    lines.append('    subgraph "cluster_legend" {')
    lines.append('        label="Leyenda"; style="rounded,filled";')
    lines.append('        fillcolor="#ffffff"; color="#999999";')
    lines.append('        fontname="Arial"; fontsize=10; rank=sink;')
    for kind in ("normal", "orphan", "cycle"):
        c = node_colors.get(kind, _DEFAULT_NODE_COLORS[kind])
        fill = c.get("fillcolor", "#f5f5f5")
        stroke = c.get("color", "#333333")
        lines.append(
            f'        "_legend_node_{kind}" '
            f'[label="{kind}", fillcolor="{fill}", color="{stroke}", '
            f'shape=box, style="rounded,filled", fontname="Arial", fontsize=9];'
        )
    prev = None
    for et in sorted(used_edge_types):
        color = edge_colors.get(et, edge_colors.get("use", "#888888"))
        node_id = f"_legend_edge_{et}"
        lines.append(
            f'        "{node_id}" [label="{et}", shape=plaintext, '
            f'fontname="Arial", fontsize=9, fontcolor="{color}"];'
        )
        if prev is not None:
            lines.append(
                f'        "{prev}" -> "{node_id}" '
                f'[color="{color}", label="{et}", fontname="Arial", fontsize=8];'
            )
        prev = node_id
    lines.append('    }')
    return lines


def build_dot_content(*, nodes, edges, external_nodes, orphans, cycles,
                      graph_config=None):
    """Arma el contenido completo del `.dot` (GRF-013 + EDG-023 + 6C).

    `rankdir` y `node_shapes` se leen de `graph_config` con defaults razonables.
    """
    graph_config = graph_config or {}
    node_colors = _merge_color_dict(
        _DEFAULT_NODE_COLORS, graph_config.get("node_colors") or {}
    )
    edge_colors = dict(_DEFAULT_EDGE_COLORS)
    edge_colors.update(graph_config.get("edge_colors") or {})
    node_shapes = _resolve_node_shapes(graph_config)
    rankdir = _resolve_rankdir(graph_config)

    orphan_set = set(orphans or [])
    cycle_set = _nodes_in_cycles(cycles)

    clusters = {}
    for rel_path in nodes:
        clusters.setdefault(_cluster_key(rel_path), set()).add(rel_path)

    lines = []
    lines.append("digraph G {")
    lines.append(f"    rankdir={rankdir};")
    lines.append("    concentrate=false; compound=true;")
    lines.append('    graph [fontname="Arial", fontsize=12, '
                 'labelloc="t", label="Architect\'s Compass — Connectivity Graph"];')
    lines.append('    node [style="rounded,filled", fontname="Arial", fontsize=10];')
    lines.append('    edge [arrowsize=0.7];')

    for cluster_id in sorted(clusters.keys()):
        lines.extend(_render_subgraph(
            cluster_id=cluster_id, cluster_label=cluster_id,
            nodes_in_cluster=clusters[cluster_id],
            orphan_set=orphan_set, cycle_set=cycle_set,
            node_colors=node_colors, node_shapes=node_shapes,
        ))
    lines.extend(_render_external_nodes(external_nodes or {}, node_colors, node_shapes))
    lines.extend(_render_edges(edges, edge_colors))
    used_edge_types = {et for (_s, _t, et, _k) in edges if et}
    lines.extend(_render_legend(edge_colors, used_edge_types, node_colors))
    lines.append("}")
    return "\n".join(lines) + "\n"


# =============================================================================
# HTML viewer universal (vis-network) — Sesión 6C
# =============================================================================

def _load_template():
    """Lee el template externo. Fallback mínimo si no existe (defensivo)."""
    try:
        return _TEMPLATE_PATH.read_text(encoding="utf-8")
    except OSError:
        # Fallback minimal — reporta el problema pero no rompe el run.
        return (
            "<!DOCTYPE html><html><body>"
            "<h1>Architect's Compass — {PROJECT_NAME}</h1>"
            "<p>Template not found at {PATH}. Re-install the compass package.</p>"
            "</body></html>"
        ).replace("{PATH}", str(_TEMPLATE_PATH))


def build_graph_html(
    *, dot_content, project_name, generated_at,
    node_count, edge_count, cycle_count,
    edges=None, external_nodes=None, orphans=None, cycles=None,
    graph_config=None,
    external_tiers=None, entry_points=None,
):
    """Genera el `graph.html` universal basado en vis-network.

    Se emite SIEMPRE, para cualquier proyecto/stack. vis-network da zoom/pan/
    drag nativos (reemplaza el SVG estático de Viz.js pre-6C).

    El `dot_content` sigue aceptándose por compat con el caller, pero el
    viewer no lo consume — usa `edges` como tuplas `(src, tgt, edge_type, kind)`.
    """
    template = _load_template()
    graph_config = graph_config or {}

    cdn = str(
        graph_config.get("vis_network_cdn_url") or _DEFAULT_VIS_NETWORK_CDN
    )
    edge_colors = dict(_DEFAULT_EDGE_COLORS)
    edge_colors.update(graph_config.get("edge_colors") or {})

    # Serializar edges como lista JSON de `[src, tgt, edge_type]`. Filtrar
    # kinds que no aportan al grafo visible (nada — todos aportan hoy).
    edges = edges or []
    edges_raw = [
        [str(src), str(tgt), str(et or "use")]
        for (src, tgt, et, _kind) in edges
    ]

    # Externals: set de labels `[EXTERNAL:*]` presentes en el grafo.
    externals_list = sorted(external_nodes or {})

    orphans_list = sorted(orphans or [])

    # Nodes en ciclos (planos, sin estructura de lista-de-ciclos).
    cycle_nodes = sorted(_nodes_in_cycles(cycles or []))

    # TIER-035 — tier colors y mapping label→tier.
    tier_colors = dict(_DEFAULT_EXTERNAL_TIER_COLORS)
    tier_colors.update(graph_config.get("external_tier_colors") or {})
    ext_tiers_map = dict(external_tiers or {})

    # GRAPH-036 — entry point style + lista de paths.
    ep_border_color = (
        graph_config.get("entry_point_border_color")
        or _DEFAULT_ENTRY_POINT_BORDER_COLOR
    )
    try:
        ep_border_width = int(
            graph_config.get(
                "entry_point_border_width", _DEFAULT_ENTRY_POINT_BORDER_WIDTH
            )
        )
    except (TypeError, ValueError):
        ep_border_width = _DEFAULT_ENTRY_POINT_BORDER_WIDTH
    try:
        ep_size_boost = int(
            graph_config.get(
                "entry_point_size_boost", _DEFAULT_ENTRY_POINT_SIZE_BOOST
            )
        )
    except (TypeError, ValueError):
        ep_size_boost = _DEFAULT_ENTRY_POINT_SIZE_BOOST
    ep_label_prefix = str(
        graph_config.get(
            "entry_point_label_prefix", _DEFAULT_ENTRY_POINT_LABEL_PREFIX
        )
    )
    entry_points_list = sorted(entry_points or [])

    safe_project = str(project_name or "project")
    replacements = {
        "{PROJECT_NAME}": safe_project.replace("{", "").replace("}", ""),
        "{GENERATED_AT}": str(generated_at or ""),
        "{NODE_COUNT}": str(node_count),
        "{EDGE_COUNT}": str(edge_count),
        "{CYCLE_COUNT}": str(cycle_count),
        "{VIS_NETWORK_CDN}": cdn,
        "{EDGES_RAW_JSON}": json.dumps(edges_raw, ensure_ascii=False),
        "{EXTERNALS_JSON}": json.dumps(externals_list, ensure_ascii=False),
        "{ORPHANS_JSON}": json.dumps(orphans_list, ensure_ascii=False),
        "{CYCLES_NODES_JSON}": json.dumps(cycle_nodes, ensure_ascii=False),
        "{EDGE_COLORS_JSON}": json.dumps(edge_colors, ensure_ascii=False),
        "{EXTERNAL_TIERS_JSON}": json.dumps(ext_tiers_map, ensure_ascii=False),
        "{TIER_COLORS_JSON}": json.dumps(tier_colors, ensure_ascii=False),
        "{ENTRY_POINTS_JSON}": json.dumps(entry_points_list, ensure_ascii=False),
        "{ENTRY_POINT_BORDER_COLOR}": str(ep_border_color),
        "{ENTRY_POINT_BORDER_WIDTH}": str(ep_border_width),
        "{ENTRY_POINT_SIZE_BOOST}": str(ep_size_boost),
        "{ENTRY_POINT_LABEL_PREFIX}": ep_label_prefix,
    }
    out = template
    for placeholder, value in replacements.items():
        out = out.replace(placeholder, value)
    return out


# =============================================================================
# Validation helper
# =============================================================================

def validate_dot_syntax(text):
    """Smoke check de sintaxis `.dot` sin Graphviz.

    Valida balance `{/}` y que cada statement termine en `;` o sea cabecera.
    Devuelve `(ok: bool, msg: str)`.
    """
    if not text or not text.strip():
        return False, "empty dot content"
    opens = text.count("{")
    closes = text.count("}")
    if opens != closes:
        return False, f"brace mismatch: {opens} '{{' vs {closes} '}}'"
    errors = []
    for idx, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("//") or line.startswith("#") or line.startswith("/*"):
            continue
        if line in ("{", "}"):
            continue
        if line.endswith("{"):
            continue
        if line.startswith(("digraph", "subgraph", "graph")):
            if line.endswith("{") or line.endswith(";"):
                continue
        if line.endswith(";"):
            continue
        errors.append(f"line {idx} missing ';' or not a header: {line[:80]}")
        if len(errors) > 5:
            break
    if errors:
        return False, "; ".join(errors)
    return True, "ok"
