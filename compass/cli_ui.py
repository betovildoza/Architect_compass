"""compass.cli_ui — rich-backed UX helpers for the CLI (CLI-015).

Aislamos el uso de `rich` acá para que `compass/cli.py` quede enfocado en
dispatch + argparse. Si rich no está instalado, devolvemos fallbacks planos
que no rompen nada (satisface el constraint de stdout-redirect y entornos
sin dependencia).

API pública:
    make_console(quiet, force_no_rich) → (console, bundle_or_None)
    make_progress(total, console, bundle, quiet) → context manager con
        `.callback()` compatible con `ArchitectCompass._progress_callback`.
    print_summary_table(console, bundle, atlas)    → tabla end-of-run del scan.
    print_symbols_table(console, bundle, stats, elapsed, output)
                                                   → tabla end-of-run de symbols.
    count_scannable_files(...)                     → pre-walk para fijar total.

Todas las funciones toleran `bundle=None` cayendo a print plano.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional


# ---------------------------------------------------------------------------
# Rich import lazy — devuelve dict con las clases o None si no está.
# ---------------------------------------------------------------------------

def _import_rich() -> Optional[Dict[str, Any]]:
    try:
        from rich.console import Console
        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            TextColumn,
            TimeElapsedColumn,
        )
        from rich.table import Table
        return {
            "Console": Console,
            "Progress": Progress,
            "BarColumn": BarColumn,
            "MofNCompleteColumn": MofNCompleteColumn,
            "TextColumn": TextColumn,
            "TimeElapsedColumn": TimeElapsedColumn,
            "Table": Table,
        }
    except ImportError:
        return None


class _PlainConsole:
    """Fallback sin rich — print stripping de markup básico."""

    _MARKUP_RE = re.compile(r"\[/?[a-zA-Z0-9_ #]+\]")

    def __init__(self, quiet: bool = False):
        self._quiet = quiet

    def print(self, *args, **kwargs):
        if self._quiet and not kwargs.pop("force", False):
            return
        out = []
        for a in args:
            out.append(self._MARKUP_RE.sub("", str(a)))
        kwargs.pop("style", None)
        print(" ".join(out))

    def rule(self, title: str = "", **kwargs):
        if self._quiet:
            return
        print(f"\n--- {title} ---" if title else "\n---")


def make_console(quiet: bool = False, force_no_rich: bool = False):
    """Devuelve (console, bundle) — bundle es None si rich no está o forzado."""
    if force_no_rich:
        return _PlainConsole(quiet=quiet), None
    bundle = _import_rich()
    if bundle is None:
        return _PlainConsole(quiet=quiet), None
    Console = bundle["Console"]
    if quiet:
        return Console(quiet=True), bundle
    return Console(), bundle


# ---------------------------------------------------------------------------
# Progress reporter — wrapper context-manager con callback para el scan loop.
# ---------------------------------------------------------------------------

class _NullProgress:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def callback(self) -> Optional[Callable]:
        return None


class _RichProgress:
    def __init__(self, total: int, console, bundle: Dict[str, Any]):
        self._total = total
        Progress = bundle["Progress"]
        TextColumn = bundle["TextColumn"]
        BarColumn = bundle["BarColumn"]
        MofN = bundle["MofNCompleteColumn"]
        TimeElapsed = bundle["TimeElapsedColumn"]
        self._progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofN(),
            TextColumn("·"),
            TimeElapsed(),
            TextColumn("· [dim]{task.fields[fname]}[/dim]"),
            console=console,
            transient=False,
        )
        self._task_id = None

    def __enter__(self):
        self._progress.__enter__()
        self._task_id = self._progress.add_task(
            "[cyan]Scanning[/cyan]",
            total=self._total or None,
            fname="",
        )
        return self

    def __exit__(self, *a):
        return self._progress.__exit__(*a)

    def callback(self) -> Callable:
        def cb(rel_path: str, scanned: int, reused: int):
            display = rel_path
            if len(display) > 60:
                display = "…" + display[-59:]
            self._progress.update(self._task_id, advance=1, fname=display)
        return cb


def make_progress(total: int, console, bundle, quiet: bool = False):
    """Devuelve progress reporter: rich-backed, o no-op si quiet/sin rich."""
    if quiet or bundle is None:
        return _NullProgress()
    return _RichProgress(total=total, console=console, bundle=bundle)


# ---------------------------------------------------------------------------
# Pre-walk para fijar total del progress bar.
# ---------------------------------------------------------------------------

def count_scannable_files(
    project_root: Path,
    text_extensions,
    ignore_folders,
    ignore_files,
    ignore_patterns,
) -> int:
    """Pre-walk barato (solo filename + ignore) para saber total de archivos."""
    count = 0
    text_set = tuple(text_extensions)
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if d not in ignore_folders]
        for fname in files:
            if not any(fname.endswith(e) for e in text_set):
                continue
            rel = os.path.relpath(
                os.path.join(root, fname), project_root,
            ).replace("\\", "/")
            if rel in ignore_files:
                continue
            if any(
                fnmatch.fnmatch(fname, p) or fnmatch.fnmatch(rel, p)
                for p in ignore_patterns
            ):
                continue
            count += 1
    return count


# ---------------------------------------------------------------------------
# Semantic colors + summary tables.
# ---------------------------------------------------------------------------

def health_color(score: float) -> str:
    """Color rich según health score: <50 rojo, 50-70 amarillo, >70 verde."""
    if score is None:
        return "white"
    if score < 50:
        return "red"
    if score < 70:
        return "yellow"
    return "green"


def print_summary_table(console, bundle, atlas: Dict[str, Any]) -> None:
    """Render tabla end-of-run del scan con colores semánticos."""
    health_total = atlas.get("health", {}).get("total", 0) or 0
    structural = atlas.get("audit", {}).get("structural_health", 0) or 0
    summary = atlas.get("summary", {}) or {}
    total_files = summary.get("total_files", 0)
    relevant = summary.get("relevant_files", 0)
    orphans = len(atlas.get("orphans", []) or [])
    cycles = len(atlas.get("cycles", []) or [])
    externals = len(atlas.get("external_tiers") or {})
    graph_filters = atlas.get("graph_filters", {}) or {}
    rendered_edges = graph_filters.get("rendered_edges", 0)
    delta = atlas.get("delta")

    h_color = health_color(health_total)
    s_color = health_color(structural)

    if bundle is None:
        console.print(f"Health Score : {health_total}/100")
        console.print(f"Structural   : {structural}%")
        console.print(f"Files        : {total_files} (relevant: {relevant})")
        console.print(f"Orphans      : {orphans}")
        console.print(f"Cycles       : {cycles}")
        console.print(f"External nodes: {externals}")
        console.print(f"Rendered edges: {rendered_edges}")
        return

    Table = bundle["Table"]
    table = Table(
        title="Architect's Compass — Resumen",
        title_style="bold cyan",
        show_header=True,
        header_style="bold magenta",
        expand=False,
    )
    table.add_column("Métrica", style="dim", width=24)
    table.add_column("Valor", justify="right")
    table.add_row(
        "Health Score",
        f"[bold {h_color}]{health_total}/100[/bold {h_color}]",
    )
    table.add_row(
        "Structural Health",
        f"[{s_color}]{structural}%[/{s_color}]",
    )
    table.add_row("Files (total / relevant)", f"{total_files} / {relevant}")
    orphan_color = "red" if orphans > max(total_files, 1) * 0.3 else (
        "yellow" if orphans > 0 else "green"
    )
    table.add_row("Orphans", f"[{orphan_color}]{orphans}[/{orphan_color}]")
    cycle_color = "red" if cycles > 0 else "green"
    table.add_row("Cycles", f"[{cycle_color}]{cycles}[/{cycle_color}]")
    table.add_row("External nodes", str(externals))
    table.add_row("Rendered edges", str(rendered_edges))

    if delta:
        hd = delta.get("health_delta", {}) or {}
        sign = hd.get("total", 0)
        d_color = "green" if sign > 0 else ("red" if sign < 0 else "white")
        table.add_row(
            "Delta vs prev",
            f"[{d_color}]{sign:+}[/{d_color}] health",
        )

    console.print(table)


def print_symbols_table(
    console, bundle, stats: Dict[str, Any], elapsed: float, output: Path,
) -> None:
    """Render tabla end-of-run del subcomando symbols."""
    if bundle is None:
        console.print(
            f"[symbols] OK — "
            f"{stats.get('files_with_symbols', 0)}/{stats.get('files_scanned', 0)} files · "
            f"{stats.get('functions', 0)} funcs · {stats.get('classes', 0)} clases · "
            f"{stats.get('warnings', 0)} warnings · {elapsed:.2f}s"
        )
        console.print(f"[symbols] Escrito: {output}")
        return
    Table = bundle["Table"]
    table = Table(
        title="Symbols extraction",
        title_style="bold cyan",
        header_style="bold magenta",
        show_header=True,
    )
    table.add_column("Métrica", style="dim")
    table.add_column("Valor", justify="right")
    table.add_row("Files scanned", str(stats.get("files_scanned", 0)))
    table.add_row("Files with symbols", str(stats.get("files_with_symbols", 0)))
    table.add_row("Functions", str(stats.get("functions", 0)))
    table.add_row("Classes", str(stats.get("classes", 0)))
    warn_count = stats.get("warnings", 0)
    warn_color = "red" if warn_count > 0 else "green"
    table.add_row("Warnings", f"[{warn_color}]{warn_count}[/{warn_color}]")
    table.add_row("Elapsed", f"{elapsed:.2f}s")
    console.print(table)
    console.print(f"[dim]Output:[/dim] [cyan]{output}[/cyan]")