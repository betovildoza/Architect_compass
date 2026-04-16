"""Métricas post-análisis — Sesión 6A.

Funciones puras (stdlib-only) que `ArchitectCompass.finalize()` invoca al
cierre del run. Viven acá y no en `core.py` para que la sesión 6B (GRF-013 +
EDG-023 + AST-024) reciba una superficie de `finalize()` limpia:

    * SCR-009 — compute_health_score(atlas) → (total, breakdown)
    * DIF-010 — diff_against_previous(current, previous) → delta dict
    * CYC-011 — detect_cycles(outbound_edges) → list[cycle]

Todas las funciones son **puras**: reciben datos ya calculados, no tocan
disco, no dependen del objeto ArchitectCompass. Los wrappers de I/O
(cargar/guardar history, escribir atlas) se quedan en `core.py`.
"""

from __future__ import annotations

import json
from pathlib import Path


# =============================================================================
# SCR-009 — Score breakdown
# =============================================================================

# Pesos default por dimensión. Suman 1.0. Fuente: PLAN.md SCR-009.
# Sesión 6C — overridable vía `scoring_weights.health_weights` en mapper_config.
# Si la suma del override difiere de 1.0 (±0.01) se revierte a defaults.
_HEALTH_WEIGHTS = {
    "orphans":       0.40,
    "connectivity":  0.30,
    "dead_exports":  0.15,
    "external_deps": 0.15,
}

_HEALTH_WEIGHT_KEYS = tuple(_HEALTH_WEIGHTS.keys())


def _resolve_health_weights(config):
    """Devuelve pesos válidos desde config; defaults si el override es inválido.

    Validaciones:
      - Las 4 keys obligatorias presentes en el override.
      - Suma ∈ [0.99, 1.01]. Si no, warning y fallback a defaults.
    """
    if not isinstance(config, dict):
        return dict(_HEALTH_WEIGHTS), None
    section = (config.get("scoring_weights") or {}).get("health_weights")
    if not isinstance(section, dict):
        return dict(_HEALTH_WEIGHTS), None
    resolved = {}
    for k in _HEALTH_WEIGHT_KEYS:
        try:
            resolved[k] = float(section[k])
        except (KeyError, TypeError, ValueError):
            return (
                dict(_HEALTH_WEIGHTS),
                f"health_weights: falta o inválido '{k}', usando defaults",
            )
    total = sum(resolved.values())
    if abs(total - 1.0) > 0.01:
        return (
            dict(_HEALTH_WEIGHTS),
            f"health_weights: suma={total:.3f} ≠ 1.0, usando defaults",
        )
    return resolved, None


def _score_orphans(total_files, orphan_count):
    """Score 0-100 proporcional a % de archivos no huérfanos."""
    if total_files <= 0:
        return 100.0
    ratio = 1.0 - (orphan_count / total_files)
    return round(max(0.0, min(1.0, ratio)) * 100, 2)


def _score_connectivity(total_files, inbound_count):
    """Score basado en promedio de inbound por archivo.

    avg_inbound ≥ 1.0 → 100 (cada archivo es referenciado al menos una vez
    en promedio). Por debajo, escala lineal: avg=0.5 → 50, avg=0 → 0.
    """
    if total_files <= 0:
        return 100.0, 0.0
    avg = inbound_count / total_files
    score = round(max(0.0, min(1.0, avg)) * 100, 2)
    return score, round(avg, 2)


def _score_dead_exports(total_files, dead_count):
    """Score 0-100 proporcional a % de archivos NO dead-exports.

    `dead_exports`: archivos que hacen outbound (exportan/llaman) pero
    nadie los referencia como inbound — módulos potencialmente muertos.
    Lo tratamos como señal: más dead_exports → score menor.
    """
    if total_files <= 0:
        return 100.0
    ratio = 1.0 - (dead_count / total_files)
    return round(max(0.0, min(1.0, ratio)) * 100, 2)


def _score_external_deps(total_targets, external_targets):
    """Score 0-100 según ratio de edges que NO son externas.

    Un proyecto 100% interno → 100. 50% externo → 50. 100% externo → 0.
    Es una medida de *acoplamiento a servicios externos*. Si no hay edges,
    devuelve 100 (nada de qué preocuparse).
    """
    if total_targets <= 0:
        return 100.0
    ratio = 1.0 - (external_targets / total_targets)
    return round(max(0.0, min(1.0, ratio)) * 100, 2)


def compute_health_score(atlas, config=None):
    """Calcula el score total + breakdown por dimensión.

    Input: el dict `atlas` ya poblado por `analyze()` (antes de que
    finalize haga I/O). `config` opcional para leer pesos overrideados
    (Sesión 6C: `scoring_weights.health_weights`). Si es None, usa defaults.

    Output: (total_score: float 0-100, breakdown: dict listo para atlas,
             warning: str | None — señal para que el caller loguee si el
             override fue descartado por inválido)
    """
    weights, warning = _resolve_health_weights(config or {})
    total_files = atlas.get("summary", {}).get("total_files", 0)
    orphan_files = list(atlas.get("orphans", []))
    outbound_edges = atlas.get("connectivity", {}).get("outbound", []) or []
    files = atlas.get("files", {}) or {}

    # Contar inbound real (edges cuyo target es archivo del repo).
    repo_paths = set(files.keys())
    inbound_count = 0
    external_targets = 0
    outbound_by_source = {}       # src → set(targets)
    inbound_by_target = {}        # tgt → count
    for edge in outbound_edges:
        try:
            src, tgt = edge.split(" -> ", 1)
        except ValueError:
            continue
        src, tgt = src.strip(), tgt.strip()
        outbound_by_source.setdefault(src, set()).add(tgt)
        if tgt.startswith("[EXTERNAL:") and tgt.endswith("]"):
            external_targets += 1
        elif tgt in repo_paths:
            inbound_count += 1
            inbound_by_target[tgt] = inbound_by_target.get(tgt, 0) + 1

    # dead_exports: archivo con outbound pero sin inbound (y no declarado
    # como dynamic_declared ni siendo un entry point). Es un proxy: no
    # trackeamos exports, pero un archivo que llama y nadie llama es
    # candidato a "export muerto".
    dead_exports = []
    for src, _targets in outbound_by_source.items():
        if src not in repo_paths:
            continue
        if inbound_by_target.get(src, 0) > 0:
            continue
        reason = files.get(src, {}).get("orphan_reason")
        if reason == "dynamic_declared":
            continue
        dead_exports.append(src)
    dead_exports.sort()

    orphan_score = _score_orphans(total_files, len(orphan_files))
    conn_score, avg_inbound = _score_connectivity(total_files, inbound_count)
    dead_score = _score_dead_exports(total_files, len(dead_exports))
    total_targets = sum(
        1
        for e in outbound_edges
        if " -> " in e
    )
    ext_score = _score_external_deps(total_targets, external_targets)

    total = round(
        orphan_score * weights["orphans"]
        + conn_score * weights["connectivity"]
        + dead_score * weights["dead_exports"]
        + ext_score * weights["external_deps"],
        2,
    )

    breakdown = {
        "total": total,
        "weights": dict(weights),
        "orphans": {
            "score": orphan_score,
            "count": len(orphan_files),
            "files": orphan_files[:20],  # cap visual; el atlas ya tiene la lista completa en "orphans"
        },
        "connectivity": {
            "score": conn_score,
            "avg_inbound": avg_inbound,
            "total_inbound_edges": inbound_count,
        },
        "dead_exports": {
            "score": dead_score,
            "count": len(dead_exports),
            "files": dead_exports[:20],
        },
        "external_deps": {
            "score": ext_score,
            "external_targets": external_targets,
            "total_targets": total_targets,
        },
    }
    return total, breakdown, warning


# =============================================================================
# CYC-011 — Ciclos en el grafo
# =============================================================================

def detect_cycles(outbound_edges, repo_paths):
    """DFS clásico sobre edges archivo→archivo para detectar ciclos.

    Devuelve lista de ciclos; cada ciclo es una lista de rel_paths empezando
    y terminando en el mismo nodo: `["a.php", "b.php", "a.php"]`.

    Solo considera edges intra-repo (filtra `[EXTERNAL:*]`). Deduplica ciclos
    por normalización canónica (rotar para arrancar por el nodo min-orden).

    PLAN.md CYC-011: los ciclos son información arquitectónica — se reportan
    pero NO penalizan el health score.
    """
    if not outbound_edges or not repo_paths:
        return []

    # Construir adjacency list. Solo edges donde ambos endpoints están en repo.
    graph = {}
    repo_set = set(repo_paths)
    for edge in outbound_edges:
        try:
            src, tgt = edge.split(" -> ", 1)
        except ValueError:
            continue
        src, tgt = src.strip(), tgt.strip()
        if src not in repo_set or tgt not in repo_set:
            continue
        graph.setdefault(src, set()).add(tgt)

    cycles_raw = []
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {}
    stack = []

    def dfs(node):
        color[node] = GRAY
        stack.append(node)
        for nxt in sorted(graph.get(node, ())):
            c = color.get(nxt, WHITE)
            if c == GRAY:
                # Back-edge → ciclo. Extraer desde stack[idx(nxt):].
                try:
                    idx = stack.index(nxt)
                except ValueError:
                    continue
                cycle = stack[idx:] + [nxt]
                cycles_raw.append(cycle)
            elif c == WHITE:
                dfs(nxt)
        stack.pop()
        color[node] = BLACK

    # Ordenar nodos para determinismo.
    for start in sorted(graph.keys()):
        if color.get(start, WHITE) == WHITE:
            dfs(start)

    # Deduplicar: rotar cada ciclo para arrancar por su nodo mínimo y
    # comparar como tupla. Los ciclos son direccionales, no reversibles.
    seen = set()
    out = []
    for cycle in cycles_raw:
        # cycle viene como [a, b, c, a]; normalizar sobre [a, b, c].
        body = cycle[:-1]
        if not body:
            continue
        min_idx = min(range(len(body)), key=lambda i: body[i])
        rotated = body[min_idx:] + body[:min_idx]
        key = tuple(rotated)
        if key in seen:
            continue
        seen.add(key)
        out.append(list(rotated) + [rotated[0]])

    return out


# =============================================================================
# DIF-010 — Diff entre runs
# =============================================================================

# Directorio donde vive el historial. Últimas N runs, la más vieja se rota.
HISTORY_DIR_NAME = "history"
HISTORY_MAX_ENTRIES = 10


def load_previous_snapshot(history_dir, fallback_atlas_path=None):
    """Devuelve el último snapshot en `history_dir` (dict) o None.

    Fallback para primer run post-introducción de history: si no hay
    snapshots todavía pero existe un `atlas.json` previo de runs pre-6A,
    se usa ese como "último" para emitir un delta inicial. El caller
    detecta esto y el primer run post-6A queda sembrando el history.
    """
    hd = Path(history_dir)
    if hd.exists() and hd.is_dir():
        entries = sorted(
            (p for p in hd.iterdir() if p.is_file() and p.suffix == ".json"),
            key=lambda p: p.name,
        )
        if entries:
            latest = entries[-1]
            try:
                with open(latest, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
    # Fallback a atlas.json del run inmediatamente anterior (antes de 6A).
    if fallback_atlas_path and Path(fallback_atlas_path).exists():
        try:
            with open(fallback_atlas_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
    return None


def save_snapshot(history_dir, snapshot_name, atlas):
    """Persiste `atlas` como snapshot y rota a las últimas N entradas."""
    hd = Path(history_dir)
    hd.mkdir(parents=True, exist_ok=True)
    snapshot_path = hd / snapshot_name
    try:
        with open(snapshot_path, "w", encoding="utf-8") as f:
            json.dump(atlas, f, indent=2, ensure_ascii=False)
    except OSError:
        return
    # Rotación: mantener sólo las últimas HISTORY_MAX_ENTRIES.
    entries = sorted(
        (p for p in hd.iterdir() if p.is_file() and p.suffix == ".json"),
        key=lambda p: p.name,
    )
    excess = len(entries) - HISTORY_MAX_ENTRIES
    for old in entries[:max(0, excess)]:
        try:
            old.unlink()
        except OSError:
            continue


def diff_against_previous(current_atlas, previous_atlas):
    """Delta entre dos atlases. None si no hay previous.

    Campos del delta:
      - previous_generated_at
      - files: {added:[...], removed:[...]}
      - edges: {added:[...], removed:[...]}   (max 50 de cada uno para no explotar)
      - orphans: {added:[...], removed:[...]}
      - health_delta: diff numérico total (current - previous), y por dimensión.
      - cycles_delta: {added:[...], removed:[...]}
    """
    if previous_atlas is None:
        return None

    cur_files = set(current_atlas.get("files", {}).keys())
    prev_files = set(previous_atlas.get("files", {}).keys())
    cur_edges = set(current_atlas.get("connectivity", {}).get("outbound", []) or [])
    prev_edges = set(previous_atlas.get("connectivity", {}).get("outbound", []) or [])
    cur_orphans = set(current_atlas.get("orphans", []) or [])
    prev_orphans = set(previous_atlas.get("orphans", []) or [])
    cur_cycles = {tuple(c) for c in (current_atlas.get("cycles", []) or [])}
    prev_cycles = {tuple(c) for c in (previous_atlas.get("cycles", []) or [])}

    cur_health = current_atlas.get("health", {}) or {}
    prev_health = previous_atlas.get("health", {}) or {}
    cur_total = cur_health.get("total", 0) or 0
    prev_total = prev_health.get("total", 0) or 0

    def _dim_delta(name):
        c = (cur_health.get(name) or {}).get("score", 0) or 0
        p = (prev_health.get(name) or {}).get("score", 0) or 0
        return round(c - p, 2)

    return {
        "previous_generated_at": previous_atlas.get("generated_at"),
        "files": {
            "added": sorted(cur_files - prev_files),
            "removed": sorted(prev_files - cur_files),
        },
        "edges": {
            "added": sorted(cur_edges - prev_edges)[:50],
            "removed": sorted(prev_edges - cur_edges)[:50],
            "added_count": len(cur_edges - prev_edges),
            "removed_count": len(prev_edges - cur_edges),
        },
        "orphans": {
            "added": sorted(cur_orphans - prev_orphans),
            "removed": sorted(prev_orphans - cur_orphans),
        },
        "cycles": {
            "added": [list(c) for c in sorted(cur_cycles - prev_cycles)],
            "removed": [list(c) for c in sorted(prev_cycles - cur_cycles)],
        },
        "health_delta": {
            "total": round(cur_total - prev_total, 2),
            "orphans":       _dim_delta("orphans"),
            "connectivity":  _dim_delta("connectivity"),
            "dead_exports":  _dim_delta("dead_exports"),
            "external_deps": _dim_delta("external_deps"),
        },
    }


def build_snapshot_name(generated_at, project_name):
    """YYYYmmdd_HHMM_<project>.json — PLAN DIF-010."""
    # `generated_at` viene como "YYYY-MM-DD HH:MM:SS"; reducir a YYYYmmdd_HHMM.
    stamp = generated_at.replace("-", "").replace(":", "").replace(" ", "_")
    stamp = stamp[:13]  # "YYYYmmdd_HHMM"
    safe_project = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in (project_name or "project")
    )
    return f"{stamp}_{safe_project}.json"