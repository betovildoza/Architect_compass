"""compass.cli — CLI dispatcher (CLI-015).

Profesionaliza Architect's Compass como una CLI real con subcomandos,
flags estructurados, y output visual con `rich`.

Subcomandos:
    compass scan [path] [flags]     — análisis + auditoría completa (default).
    compass symbols [path] [flags]  — extrae funciones/clases (SYM-004).
    compass init [path]             — siembra .map/compass.local.{json,md}.
    compass graph [path] [flags]    — re-emite graph.html sin re-scan.

Flags globales (cuando aplican):
    --root PATH / -r       — root del proyecto (default cwd).
    --config PATH / -c     — ruta a mapper_config.json (override del global).
    --output DIR / -o      — destino de .map/ (default <root>/.map).
    -v / --verbose         — más detalle.
    -q / --quiet           — solo errores.

Flags de scan:
    --full                 — fuerza re-scan completo (ignora cache INC-008).
    --no-diff              — saltea delta vs snapshot previo.
    --no-graph             — no emite graph.html.
    --no-history           — no rota snapshot a .map/history/.

Arquitectura:
    El dispatcher es delgado: parsea, resuelve paths, instancia
    `ArchitectCompass` o llama a `architect_symbols.build_symbols`, y
    delega el render a `compass.cli_ui` (rich opcional). Todo el análisis
    vive intacto en `compass/pipeline.py` + `compass/finalize.py`.

Backward-compat:
    `compass [path]` sin subcomando es equivalente a `compass scan [path]`
    para preservar el uso legacy de `python architect_compass.py`.
    Los entry points `architect_compass.py` y `architect_symbols.py`
    siguen funcionando como wrappers.

Exit codes:
    0  — éxito.
    1  — error de uso (path inválido, config corrupto, etc).
    2  — error de análisis (excepción dentro del pipeline).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from compass.cli_ui import (
    count_scannable_files,
    make_console,
    make_progress,
    print_summary_table,
    print_symbols_table,
)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_scan(args: argparse.Namespace) -> int:
    """Subcomando `scan` — análisis completo + auditoría."""
    # Imports diferidos para que `compass init` / `--help` no paguen el costo
    # de cargar todo el pipeline si no se necesita.
    from compass.core import ArchitectCompass

    root = _resolve_root(args)
    if not root.is_dir():
        _err(f"--root no existe o no es directorio: {root}")
        return 1

    config_path = _resolve_config(args)
    if config_path is not None and not config_path.is_file():
        _err(f"--config no existe: {config_path}")
        return 1

    output_dir = _resolve_output(args, root)
    console, bundle = make_console(quiet=args.quiet)

    if not args.quiet:
        console.print(
            f"[bold cyan]Compass scan[/bold cyan] · root=[green]{root}[/green]"
        )

    try:
        compass = ArchitectCompass(
            force_full=args.full,
            project_root=root,
            config_path=config_path,
            output_dir=output_dir,
        )
    except Exception as e:
        return _fatal(console, "Error inicializando ArchitectCompass", e, args.verbose)

    total = 0
    if not args.quiet:
        try:
            total = count_scannable_files(
                project_root=compass.project_root,
                text_extensions=compass.text_extensions,
                ignore_folders=compass.ignore_folders,
                ignore_files=compass.ignore_files,
                ignore_patterns=compass.ignore_patterns,
            )
        except Exception:
            total = 0

    progress = make_progress(
        total=total, console=console, bundle=bundle, quiet=args.quiet,
    )

    t0 = time.time()
    with progress:
        compass._progress_callback = progress.callback()
        try:
            compass.analyze()
        except Exception as e:
            return _fatal(console, "Error en analyze()", e, args.verbose)
        finally:
            compass._progress_callback = None

    _apply_finalize_skips(compass, args)

    try:
        compass.finalize()
    except Exception as e:
        return _fatal(console, "Error en finalize()", e, args.verbose)

    elapsed = time.time() - t0

    if not args.quiet:
        console.print()
        print_summary_table(console, bundle, compass.atlas)
        console.print(
            f"[dim]Outputs en[/dim] [cyan]{compass.map_dir}[/cyan] "
            f"[dim]· {elapsed:.2f}s[/dim]"
        )

    return 0


def _apply_finalize_skips(compass, args: argparse.Namespace) -> None:
    """Patch dinámico de pasos opcionales del finalize (--no-* flags).

    Mantenemos `compass.finalize()` con flujo único; parcheamos los métodos
    individuales por instancia. El atlas no se ve afectado salvo en las
    claves correspondientes (graph.html, .map/history/, atlas.delta).
    """
    if args.no_graph:
        compass._emit_graph_html = lambda: None
    if args.no_diff:
        original = compass._compute_metrics

        def metrics_no_diff():
            original()
            compass.atlas.pop("delta", None)
        compass._compute_metrics = metrics_no_diff
    if args.no_history:
        compass._rotate_history = lambda: None


def cmd_symbols(args: argparse.Namespace) -> int:
    """Subcomando `symbols` — extrae funciones/clases (SYM-004)."""
    # `architect_symbols.py` vive en la raíz del repo como standalone tool;
    # reutilizamos su `build_symbols()` para no duplicar la lógica.
    sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))
    try:
        import architect_symbols as sym_module
    except Exception as e:
        print(f"ERROR no se pudo importar architect_symbols: {e}", file=sys.stderr)
        return 1

    root = _resolve_root(args)
    if not root.is_dir():
        _err(f"--root no existe o no es directorio: {root}")
        return 1

    output = (
        Path(args.output).resolve()
        if args.output
        else (root / ".map" / "symbols.json")
    )

    console, bundle = make_console(quiet=args.quiet)
    if not args.quiet:
        console.print(
            f"[bold cyan]Compass symbols[/bold cyan] · "
            f"root=[green]{root}[/green]"
        )

    t0 = time.time()
    try:
        result = sym_module.build_symbols(root, verbose=args.verbose)
    except Exception as e:
        return _fatal(console, "Error en build_symbols", e, args.verbose)
    elapsed = time.time() - t0
    result["elapsed_seconds"] = round(elapsed, 3)

    if args.stdout:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if not args.quiet:
            stats = result.get("stats", {})
            print_symbols_table(console, bundle, stats, elapsed, output)
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Subcomando `init` — siembra .map/compass.local.{json,md}."""
    from compass.template_io import (
        LOCAL_CONFIG_NAME,
        LOCAL_HELP_NAME,
        ensure_local_template,
    )

    root = _resolve_root(args)
    if not root.is_dir():
        _err(f"--root no existe o no es directorio: {root}")
        return 1

    map_dir = _resolve_output(args, root)
    map_dir.mkdir(parents=True, exist_ok=True)
    script_dir = Path(__file__).parent.parent.absolute()

    json_path = map_dir / LOCAL_CONFIG_NAME
    md_path = map_dir / LOCAL_HELP_NAME
    json_existed = json_path.exists()
    md_existed = md_path.exists()

    ensure_local_template(map_dir, script_dir)

    console, _ = make_console(quiet=args.quiet)
    if not args.quiet:
        console.print(
            f"[bold cyan]Compass init[/bold cyan] · root=[green]{root}[/green]"
        )
        console.print(
            f"  {LOCAL_CONFIG_NAME}: "
            f"{'[yellow]ya existía[/yellow]' if json_existed else '[green]creado[/green]'}  "
            f"({json_path})"
        )
        console.print(
            f"  {LOCAL_HELP_NAME}:   "
            f"{'[yellow]ya existía[/yellow]' if md_existed else '[green]creado[/green]'}  "
            f"({md_path})"
        )
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    """Subcomando `graph` — re-emite graph.html desde atlas.json existente.

    No re-escanea: lee `.map/atlas.json` + `.map/connectivity.dot`,
    reconstruye edges/external nodes a partir del atlas y vuelve a llamar
    a `build_graph_html`. Útil iterando sobre estilos del renderer.
    """
    from compass.graph_emitter import build_graph_html

    root = _resolve_root(args)
    map_dir = _resolve_output(args, root)
    atlas_path = map_dir / "atlas.json"
    dot_path = map_dir / "connectivity.dot"
    out_path = map_dir / "graph.html"

    console, _ = make_console(quiet=args.quiet)

    if not atlas_path.is_file():
        _err(f"No existe atlas.json en {map_dir} — corré `compass scan` primero.")
        return 1
    if not dot_path.is_file():
        _err(f"No existe connectivity.dot en {map_dir} — corré `compass scan` primero.")
        return 1

    try:
        atlas = json.loads(atlas_path.read_text(encoding="utf-8"))
    except Exception as e:
        _err(f"atlas.json ilegible: {e}")
        return 1
    try:
        dot_content = dot_path.read_text(encoding="utf-8")
    except Exception as e:
        _err(f"connectivity.dot ilegible: {e}")
        return 1

    edges = _rebuild_edges_from_atlas(atlas)
    external_nodes = _rebuild_external_nodes_from_atlas(atlas)
    cycles = atlas.get("cycles", []) or []
    orphans = atlas.get("orphans", []) or []
    external_tiers = atlas.get("external_tiers", {}) or {}
    entry_points = atlas.get("entry_points", []) or []
    graph_config = atlas.get("graph_config") or {}

    file_nodes = set(orphans)
    for (s, t, _et, kind) in edges:
        file_nodes.add(s)
        if kind == "file":
            file_nodes.add(t)

    try:
        html = build_graph_html(
            dot_content=dot_content,
            project_name=atlas.get("project_name", "project"),
            generated_at=atlas.get("generated_at", ""),
            node_count=len(file_nodes),
            edge_count=len(edges),
            cycle_count=len(cycles),
            edges=edges,
            external_nodes=external_nodes,
            orphans=orphans,
            cycles=cycles,
            graph_config=graph_config,
            external_tiers=external_tiers,
            entry_points=entry_points,
        )
    except Exception as e:
        return _fatal(console, "Error generando graph.html", e, args.verbose)

    out_path.write_text(html, encoding="utf-8")
    if not args.quiet:
        console.print(
            f"[bold cyan]Compass graph[/bold cyan] · "
            f"[green]regenerado[/green] {out_path}"
        )
        console.print(
            f"  nodes={len(file_nodes)} edges={len(edges)} "
            f"externals={len(external_nodes)} cycles={len(cycles)}"
        )
    return 0


def _rebuild_edges_from_atlas(atlas: Dict[str, Any]):
    """Best-effort reconstrucción de la lista de edges desde el atlas.

    El atlas serializa connectivity.outbound como strings `src -> tgt` sin
    edge_type ni kind. Para `compass graph` alcanza: los colores/types
    vienen del .dot embebido; lo que necesitamos son labels + counts.
    Devolvemos tuples `(src, tgt, "uses", kind)`.
    """
    out = []
    outbound = atlas.get("connectivity", {}).get("outbound", []) or []
    files_known = set(atlas.get("files", {}).keys())
    externals_known = set((atlas.get("external_tiers") or {}).keys())
    for line in outbound:
        if " -> " not in line:
            continue
        try:
            src, tgt = line.split(" -> ", 1)
        except ValueError:
            continue
        src = src.strip()
        tgt = tgt.strip()
        if tgt in files_known:
            kind = "file"
        elif tgt in externals_known or tgt.startswith("[EXTERNAL:"):
            kind = "external"
        else:
            kind = "external_legacy"
        out.append((src, tgt, "uses", kind))
    return out


def _rebuild_external_nodes_from_atlas(atlas: Dict[str, Any]) -> Dict[str, str]:
    """Devuelve dict[label → display_name] reconstruido desde external_tiers."""
    tiers = atlas.get("external_tiers", {}) or {}
    return {label: label for label in tiers.keys()}


# ---------------------------------------------------------------------------
# Helpers — resolución de paths, errores
# ---------------------------------------------------------------------------

def _resolve_root(args: argparse.Namespace) -> Path:
    candidate = getattr(args, "root", None)
    if candidate is None:
        candidate = getattr(args, "path", None)
    if candidate is None:
        return Path.cwd().resolve()
    return Path(candidate).resolve()


def _resolve_config(args: argparse.Namespace) -> Optional[Path]:
    cfg = getattr(args, "config", None)
    if cfg is None:
        return None
    return Path(cfg).resolve()


def _resolve_output(args: argparse.Namespace, root: Path) -> Path:
    out = getattr(args, "output", None)
    if out is None:
        return (root / ".map").resolve()
    return Path(out).resolve()


def _err(msg: str) -> None:
    print(f"compass: error: {msg}", file=sys.stderr)


def _fatal(console, prefix: str, exc: Exception, verbose: bool) -> int:
    """Imprime error útil, stack trace solo si --verbose. Devuelve 2."""
    if verbose:
        import traceback
        traceback.print_exc()
    else:
        console.print(f"[bold red]ERROR[/bold red] {prefix}: {exc}")
        console.print("[dim]Repetí con --verbose para ver el stack trace.[/dim]")
    return 2


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------

def _add_global_flags(parser: argparse.ArgumentParser) -> None:
    """Flags compartidos por la mayoría de subcomandos."""
    parser.add_argument(
        "-r", "--root", default=None, metavar="PATH",
        help="Directorio raíz del proyecto a analizar (default: cwd).",
    )
    parser.add_argument(
        "-c", "--config", default=None, metavar="PATH",
        help="Ruta a un mapper_config.json explícito (override del global del repo).",
    )
    parser.add_argument(
        "-o", "--output", default=None, metavar="DIR",
        help="Destino del directorio de outputs (default: <root>/.map).",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Mostrar más detalle (incluye stack trace en errores).",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Silenciar output excepto errores.",
    )


class _HelpfulParser(argparse.ArgumentParser):
    """ArgumentParser que muestra --help antes del mensaje de error.

    Comportamiento default de argparse: error escueto + exit. Acá invertimos:
    ante uso inválido (subcomando desconocido, flag inválido, arg faltante),
    imprimimos --help completo + el error específico, y salimos con código 2.
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_help(sys.stderr)
        print(f"\ncompass: error: {message}", file=sys.stderr)
        sys.exit(2)


def _make_parser() -> argparse.ArgumentParser:
    parser = _HelpfulParser(
        prog="compass",
        description=(
            "Architect's Compass — auditoría estructural multi-stack. "
            "Subcomandos: scan (default), symbols, init, graph."
        ),
        epilog="Ejemplo: `compass scan ./mi-proyecto --full --no-history`",
    )
    sub = parser.add_subparsers(
        dest="command", metavar="COMMAND", parser_class=_HelpfulParser,
    )

    p_scan = sub.add_parser(
        "scan",
        help="Análisis + auditoría completa (default si no se pasa subcomando).",
        description=(
            "Escanea el proyecto, construye atlas + grafo, calcula métricas "
            "y emite todos los outputs en <root>/.map/."
        ),
    )
    p_scan.add_argument(
        "path", nargs="?", default=None,
        help="Path al proyecto (alternativa a --root).",
    )
    _add_global_flags(p_scan)
    p_scan.add_argument(
        "--full", action="store_true",
        help="Fuerza re-scan completo, ignora cache de fingerprints (INC-008).",
    )
    p_scan.add_argument(
        "--no-diff", action="store_true",
        help="No calcular delta vs snapshot previo (DIF-010).",
    )
    p_scan.add_argument(
        "--no-graph", action="store_true",
        help="No emitir graph.html (más rápido en CI sin display).",
    )
    p_scan.add_argument(
        "--no-history", action="store_true",
        help="No rotar snapshot a .map/history/ (modo efímero).",
    )
    p_scan.set_defaults(func=cmd_scan)

    p_sym = sub.add_parser(
        "symbols",
        help="Extrae funciones/clases/firmas a .map/symbols.json (SYM-004).",
        description=(
            "Pipeline paralelo al scan principal: extrae símbolos por archivo "
            "(Python AST + regex JS/TS/PHP) para contexto LLM."
        ),
    )
    p_sym.add_argument(
        "path", nargs="?", default=None,
        help="Path al proyecto (alternativa a --root).",
    )
    _add_global_flags(p_sym)
    p_sym.add_argument(
        "--stdout", action="store_true",
        help="Imprimir el JSON a stdout en vez de escribirlo a disco.",
    )
    p_sym.set_defaults(func=cmd_symbols)

    p_init = sub.add_parser(
        "init",
        help="Crea .map/compass.local.{json,md} en el proyecto actual.",
        description=(
            "Siembra los templates de configuración local. Idempotente: "
            "no pisa archivos existentes."
        ),
    )
    p_init.add_argument(
        "path", nargs="?", default=None,
        help="Path al proyecto donde inicializar (default: cwd).",
    )
    _add_global_flags(p_init)
    p_init.set_defaults(func=cmd_init)

    p_graph = sub.add_parser(
        "graph",
        help="Re-emite graph.html desde atlas.json existente (sin re-scan).",
        description=(
            "Útil iterando sobre estilos del renderer: regenera el HTML del "
            "grafo leyendo atlas.json + connectivity.dot ya escritos."
        ),
    )
    p_graph.add_argument(
        "path", nargs="?", default=None,
        help="Path al proyecto (alternativa a --root).",
    )
    _add_global_flags(p_graph)
    p_graph.set_defaults(func=cmd_graph)

    return parser


def _normalize_default_argv(argv: List[str]) -> List[str]:
    """Si no se pasa subcomando explícito, prepend `scan` para preservar
    el comportamiento legacy de `python architect_compass.py [path]`.

    El primer token no-flag se interpreta como subcomando si matchea la
    lista conocida o si "parece" un path (contiene separador de path o
    apunta a un dir/file existente). Si no parece path y no es un
    subcomando válido, lo dejamos pasar a argparse para que muestre
    --help + el error de "invalid choice".
    """
    if not argv:
        return ["scan"]
    valid_commands = {"scan", "symbols", "init", "graph"}
    for token in argv:
        if token.startswith("-"):
            if token in ("-h", "--help"):
                return argv
            continue
        if token in valid_commands:
            return argv
        looks_like_path = (
            "/" in token or "\\" in token or token in (".", "..")
            or Path(token).exists()
        )
        if looks_like_path:
            return ["scan"] + argv
        return argv
    return ["scan"] + argv


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    argv = _normalize_default_argv(list(argv))

    parser = _make_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ncompass: interrumpido por el usuario.", file=sys.stderr)
        return 130


def main_scan(argv: Optional[List[str]] = None) -> int:
    """Entry point legacy — invocado por `architect_compass.py`."""
    if argv is None:
        argv = sys.argv[1:]
    return main(["scan"] + list(argv))


def main_symbols(argv: Optional[List[str]] = None) -> int:
    """Entry point legacy — invocado por `architect_symbols.py`."""
    if argv is None:
        argv = sys.argv[1:]
    return main(["symbols"] + list(argv))


if __name__ == "__main__":
    sys.exit(main())