# Plan de implementación - Architect's Compass v2

## Convenciones de sesión

- Estamos usando subagentes Claude por ocasion excepcional, a pedido de Beto no vamos a usar Cerbero en este repo.
- **Cierre de sesión - archivos deprecados:** al terminar una sesión, cualquier archivo del proyecto que quede obsoleto (schemas viejos, templates reemplazados, artefactos de una implementación anterior que ya no se usa) debe moverse a `.quarantine/` con sufijo `.legacy-vN` o similar. No se borran para respetar el histórico, pero no deben quedar en su ubicación original donde puedan ser cargados por error o generar confusión.
- **Archivos invisibles a búsqueda normal** - los siguientes paths están en `.gitignore` y **no aparecen** en `git status`, `grep` recursivo default, ni tracking de VCS. Si una sesión los necesita, el briefing del subagente debe mencionarlos explícitamente:
  - `.quarantine/` - depósito de obsoletos del proyecto.
  - `compass.bat` - launcher local (NO se versiona; cada instalación lo personaliza).
  - `.claude/` - metadata de Claude Code.
  - `.map/` - outputs del tool (atlas.json, connectivity.dot, feedback.log, compass.local.*).
- **Roadmap (desde 2026-06-12):** el índice de tareas **pendientes** vive en [roadmap.md](roadmap.md) (solo tabla código/estado/descripción de una oración, organizada por fases). Este PLAN.md guarda la descripción ampliada de cada ticket bajo el mismo código — incluyendo los ya completados, que NO se eliminan. [SESSION_LOG.md](SESSION_LOG.md) es el changelog de lo realizado. Al completar un ticket: marcar ✅ acá y en roadmap.md, registrar en SESSION_LOG.md.

---

| ID      | Módulo / Tarea            | Estado    | Descripción                                                                  |
|---------|---------------------------|-----------|------------------------------------------------------------------------------|
| MOD-000 | Modularización            | ✅completada | Separar `architect_compass.py` en paquete `compass/` antes de que crezca    |
| CFG-005 | Config Schema v2          | ✅completada | Reestructurar mapper_config: separar detection, scanning, scoring y graph    |
| STK-001 | Stack Detection           | ✅completada | Reemplazar detección por jerarquía lock-file → framework marker → extensión  |
| STK-001b| Extension hints al config | ✅completada | Externalizar `_EXTENSION_STACK_HINTS` del detector a `mapper_config.json`     |
| RES-002 | Path Resolver             | ✅completada | Resolver paths relativos a absolutos con lógica semántica por lenguaje       |
| SCN-003 | Scanner AST / tree-sitter | ✅completada | Reemplazar regex de extracción de imports por parsers reales por lenguaje    |
| SYM-004 | Symbol Tool               | ✅completada | Tool paralela (`architect_symbols.py`) - extrae funciones/clases/firmas/constantes a `.map/symbols.json`. Python via `ast` stdlib; JS/TS y PHP via regex fallback (PHP restringido a bloques `<?php`). Respeta `basal_rules`. Subcomando `compass.bat symbols`. |
| MST-006 | Multi-stack Detection     | ✅completada | Detectar stacks por subárbol de directorios, no uno global por proyecto       |
| DYN-007 | Dynamic Deps Annotations  | ✅completada | Declarar dependencias dinámicas en config; anotarlas como dynamic_declared    |
| INC-008 | Escaneo incremental       | ✅completada | Fingerprinting por archivo; re-escanear solo archivos modificados             |
| SCR-009 | Score Breakdown           | ✅completada | Descomponer health score en dimensiones: orphans, connectivity, dead, external|
| DIF-010 | Diff entre corridas       | ✅completada | Historial en `.map/history/` (últimas 10), delta al final de cada run        |
| CYC-011 | Detección de ciclos       | ✅completada | DFS sobre el grafo del atlas para detectar y reportar dependencias circulares |
| GRF-013 | HTML Graph Viewer         | ✅completada + ajustes en 6C | Generar `graph.html` universal (vis-network post-6C; Viz.js pre-6C). Zoom/pan/drag nativos. Se emite SIEMPRE para cualquier proyecto. |
| VAL-014 | Config Validation         | ✅completada | Feedback al final del run si hay entradas inválidas en compass.local.json     |
| CLI-015 | CLI Flags & Subcommands   | ✅completada | argparse + rich. Subcomandos scan/symbols/init/graph + flags globales (-r/-c/-o/-v/-q) y de scan (--full/--no-diff/--no-graph/--no-history). Nuevo `compass.py` dispatcher + `compass/cli.py` + `compass/cli_ui.py` (rich UI). Wrappers legacy intactos. Atlas byte-idéntico pre/post. Pyproject/PyPI diferido a sesión futura. |
| IGN-016 | Ignore Files & Patterns   | ✅completada | Excluir archivos individuales y patrones (*.min.js) desde config              |
| DEF-017 | Language filter en definitions[] | ✅completada | Agregar campo `language` a `definitions[]` y filtrar patterns por lenguaje en `RegexFallbackScanner` |
| EVL-001 | Review schema extensions  | 🔲diferido  | Post-implementación + usos reales: evaluar si `extensions` co-localizadas (A) o top-level (B) |
| PHP-018 | Resolver paths PHP root-relativos + `__DIR__ . '…'` | ✅completada | **Sesión 23 validación:** `PathResolver._resolve_php` resuelve leading-slash (`lstrip("/\\")` → project-root-relative) y `__DIR__ . '/sub/file.php'` (vía `_extract_string_literals` + `base_is_file_dir`). Testigo ETCA: 13 APIs resuelven a `api/bootstrap.php` correctamente. Gap remanente con variables dinámicas (`require_once $var`) queda como PHP-018b (ticket nuevo). |
| PHP-018b | PHP require/include con variable (`require_once $var`) | ✅completada | **Sesión 23:** implementado en `compass/scanners/regex_fallback.py`. Dos sub-pases en `.php`: (1) `_collect_php_var_assignments` extrae `$var = dirname(__DIR__[, N]) . 'literal'` o `$var = __DIR__ . 'literal'` acumulando candidatos por varname (reasignaciones condicionales acumulan); (2) `_php_require_var_sentinels` detecta `require|require_once|include|include_once $var` y emite un edge por candidato, resolviendo `dirname(__DIR__, N)` relativo al archivo fuente. Validado en ETCA: `etca_config.php` pasó de 0 a 6 inbound edges (bootstrap.php, oauth-callback.php, blog-post.php, producto.php, sitemap.php, tienda.php - el fix capturó 4 archivos adicionales al gap inicial). Baselines non-WP estables (pass solo se activa en `.php`). |
| HTML-019 | Scanner + resolver HTML   | ✅completada | Scanner HTML (src/href/action/form), resolver `_resolve_html`, patterns en config. Cubre `<script src>`, `<link href>`, `<img src>`, `<a href>`, `<form action>`, `<iframe src>`, `<video src>`, `<source src>` |
| PHP-inbound-019 | Outbound pattern `__DIR__` PHP | ✅completada | +1 regex en `Vanilla-Web-Stack-PHP::patterns.outbound` para capturar `require_once __DIR__ . '/path'` reales - resuelve los 10-12 APIs de ETCA que hoy son falsos huérfanos |
| GRF-021 | Graph cleanup + external Level 1 | ✅completada | 3 categorías en el grafo: archivo repo / external-SDK / metadata. Nodos fantasma (`document.querySelector`, `json`, `curl_exec`) eliminados. Config `external_services` con defaults (Anthropic, OpenAI, Supabase, Stripe, OpenRouter, Gemini, ChromaDB) |
| SEM-020 | Semantic Loader Resolution | ✅completada | PathResolver evalúa símbolos (`get_template_directory_uri()` → `{theme_root}`) + interpolación PHP (`"$dir/file.css"`) + `loader_calls` detectan `wp_enqueue_*`, `get_template_part`, etc. Elimina necesidad de declarar WordPress files en `dynamic_deps`. ETCA: +14 edges internos al tema, health +6.02. |
| NET-022 | Network Externals (Level 2) | ✅completada | **Sesión 23 validación:** `http_loaders` por lenguaje en `mapper_config.json:253-275` cubre `requests.*/urllib/httpx`, `fetch/axios.*`, `wp_remote_*/curl_init/file_get_contents/fopen`. Scanner Python (AST pass, `python.py:133-146`), regex_fallback (PHP/JS/TS, `regex_fallback.py:173-178`), HTML inline `<script>` (`html.py:124-134`). URL-SCAN pass captura cualquier URL literal. `external_services.match_urls` clasifica hosts conocidos (Anthropic/OpenAI/Stripe/etc.). Validado en 4 projects: level2 18 externals (OpenRouter, Context7, Brave, Gemini), Agente_facundo 32 (Anthropic, OpenAI, ChromaDB), ETCA 18 (Resend, Google, Instagram, etc.), self 2. |
| AST-024 | Asset filtering en grafo  | ✅completada + ajustes en 6C | Descartar assets binarios del grafo + `asset_extensions_remove` en compass.local (6C) |
| DEF-025 | Definitions cleanup       | ✅completada | Rediseñar `definitions[]` stack-based → language-based; eliminar falsos positivos en identity detection (ej: "Tauri" en proyecto HTML+PHP) |
| EDG-023 | Edge labels semánticos    | ✅completada + ajustes en 6C | Labels del `.dot` por tipo de dependencia. `default_edge_type` configurable (6C). |
| FIX-026 | UX fixes pre-6            | ✅completada | Template `compass.local.json` más ilustrativo + diagnóstico punto 7 (fetch/action → `api/*` resolution) |
| FIX-027 | Inline JS fetch scan in HTML | ✅completada | Scanner HTML ahora extrae contenido de `<script>…</script>` inline y lo corre contra el regex compuesto desde `http_loaders.javascript`+`typescript` (fetch/axios/apiReq/...). URLs literales emiten edges `fetch` que NET-022 clasifica como `[EXTERNAL:host]` o path interno. |
| NET-022b| Custom API wrappers config | ✅completada | **Sesión 23 validación:** `http_loaders.python/javascript/typescript/php` en `mapper_config.json` ya es extensible - scanner Python mergea defaults + config (`python.py:88-101`). HTML scanner compone regex desde `http_loaders.javascript+typescript` (`html.py:94-107`). Config extiende, nunca reemplaza. Listo para agregar wrappers custom del proyecto (ej. `apiReq`, `apiCall`) sin tocar código. |
| CONS-029 | Consolidación metadata per-source → global | ✅completada | `metadata.{assets,calls,filtered_refs}` duplica refs entre archivos (ej. 30 HTMLs × favicon = 30 entries en ETCA). Mantener per-source (humano) + agregar vista consolidada (LLM/peso). Implementado vía `compass/consolidator.py` + nuevo campo `atlas.metadata_consolidated` (`{target: [sources]}`). Per-source intacta. |
| LLM-VIEW-028 | Export compacto atlas para agentes IA | ✅completada | Atlas humano pesa >1000 líneas para proyectos medianos. Implementado `.map/atlas.compact.json` con schema pooled (labels/stacks/edge_types/edge_kinds como pools de strings + nodes/edges como tuples int-indexed). ETCA: 23% del atlas.json; self: 20.5%; level2: 29.7% - todos <30%. Topología preservada (mismos nodes/edges/cycles). |
| FIX-030 | Ignorar `.env` y dotfiles en grafo | ✅completada | Excluir `.env`, `.env.*`, `.gitignore` y similares como **targets del grafo**. Hoy `.env` aparece como nodo huérfano con `stack` heredado del directorio (caso 2026-04-16: `cerbero-setup/.env` en level2agent-engine etiquetado como `AI-Agent-Framework`). Fix posible por extensión/pattern en basal_rules global + también por filtro en fase de emisión de grafo. |
| UX-031 | Template `compass.local.json` - UX `_example_` vs activo | ✅completada + ajuste md-split pase 2 | Mejorar distinción visual entre campos activos (`basal_rules`, `dynamic_deps`, etc.) y bloques de referencia (`_example_*`). Gotcha detectado 2026-04-16: Beto editó `_example_basal_rules.ignore_folders` creyendo que era el campo activo - las 11 carpetas no surtieron efecto. Pase 1: banner `_WARNING` + orden activo-primero + VAL-014 drift detection. Pase 2 post-review: toda la documentación (`_how_to_*` + `_README`) migrada a `compass.local.md` paralelo leído desde `compass/templates/compass.local.md.tpl`; el JSON queda solo con datos + ejemplos. |
| NET-023 | Auto-promoción de imports externos no resueltos | ✅completada | Cuando un import no resuelve a archivo interno del repo y **no** matchea `external_services`, se auto-promueve a `[EXTERNAL:<paquete>]` automáticamente (ej. `import anthropic` → `[EXTERNAL:anthropic]` sin declararlo). Implementado en Sesión 8. Dedup por nombre de paquete (primer segmento); stdlib filtrado por default vía `external_include_stdlib: false`. |
| INIT-032 | Tracing de re-exports en `__init__.py` | ✅completada | `_resolve_python()` parsea `__init__.py` (stdlib ast) buscando `from .sub import X` / `from .sub import *` y redirige al submódulo fuente. Verificado en level2agent-engine: edges `cerbero.py → engine/api.py`, `engine/tools.py`, `engine/provider.py`, `engine/diff.py`, `engine/log.py`, `engine/loop.py` ahora presentes. Health +6.84. |
| REF-033 | Factorización de `core.py` (pre-CLI-015) | ✅completada | `compass/core.py` cerró Sesión 7 en **1781 líneas** - ~3× el hard limit de 600 del proyecto. Cada sesión 8-10 suma ~40-80 líneas más (wiring NET/CONS). Refactor previo a CLI-015 para separar responsabilidades: candidatos `compass/pipeline.py` (analyze/finalize orchestration), `compass/outbound_resolver.py` (_classify_outbound + _resolve_outbound_node), `compass/template_io.py` (`_LOCAL_TEMPLATE` + ensure_local_template helpers). Sin cambio de comportamiento observable - smoke test post-refactor debe igualar atlas pre-refactor byte-a-byte (o justificar cualquier diff). Bloquea CLI-015: el entry point refactoreado espera boundaries limpios por módulo. |
| TIER-035 | Jerarquía visual de externals | ✅completada | Post-Sesión 8 los externals son una bolsa plana. Clasificar por 4 tiers: `stdlib` (built-ins del lenguaje, oculta por default vía `external_include_stdlib` de NET-023), `package` (deps de package manager - `requirements.txt`/`package.json`/`composer.json`), `service` (URLs matcheadas por `match_urls` de NET-022, color destacado), `wrapper` (HTTP wrappers de `http_loaders` de NET-022b, color distintivo). Campo `tier` en shape de external en `atlas.json`; renderer HTML mapea `tier` → color. Sin cambio de layout, solo colores + leyenda opcional. Depende de NET-022/022b/023 ya implementados. |
| GRAPH-036 | Highlight de entry points | ✅completada | Hoy los entry points (`if __name__ == '__main__'`, `package.json:main/bin/scripts.start`, `index.php` en raíz, archivos referenciados desde `.bat` en raíz) se renderizan iguales al resto y se pierden visualmente. Scanner detecta entry points por heurística por lenguaje; nueva metadata `entry_points: [path, ...]` en `atlas.json`. Renderer HTML aplica borde dorado 3-4px, size +1rem, opcional símbolo ★ en la etiqueta. Tamaño configurable vía `mapper_config.json` (ej. `graph.entry_point_size_boost`). |
| RES-003 | WP Template Hierarchy + Theme-implicit entry points | ✅completada | **Sesión 23 rewrite+extensión:** (a) `find_wp_theme_roots(project_root, max_depth=4)` busca recursivamente carpetas con `style.css` + (`functions.php`\|`index.php`) - fix al bug previo donde el detector solo miraba la raíz y fallaba cuando el tema vivía en subcarpeta. (b) `is_wp_template(rel_path, theme_roots, project_root)` scoped por theme root (evita falsos positivos tipo `api/legacy/index.php`). (c) `page.php` agregado a `WP_EXACT_TEMPLATES`. (d) **Extensión theme-implicit**: `WP_THEME_IMPLICIT_FILES = (style.css, theme.json, functions.php, rtl.css, screenshot.png/jpg, readme.txt)` promovidos a entry_point con reason `wp_theme_implicit` - convención WP core (carga implícita al activar el tema). (e) Helper `_promote_wp_entry` en `finalize.py` soporta reason múltiple (string\|list). Validado en ETCA: 16 templates `wp_template_hierarchy` + 3 theme-implicit (`style.css`, `theme.json`, `functions.php`) → entry_points 1→19, ambiguous 3→1, health 87.61 estable. Baselines non-WP sin regresión (Architect_compass 97.57, level2 91.79, Agente_facundo 88.46). |
| LOAD-038 | Python filesystem loaders | ✅completada | Extender `loader_calls` con `open()`, `json.load()`, `Path(...).read_text()`, `Path(...).read_bytes()` para Python. PythonScanner (Tier 1, AST-based) captura calls vía `_extract_filesystem_loaders()`. Maneja: (1) `open("path")` directo; (2) `json.load(open(...))` nested; (3) `Path("path").read_text/read_bytes()` via constructor arg. PathResolver resuelve literales string como paths relativos al project_root. Stdlib-only, zero regresiones en Architect_compass. |
| BUG-2   | Fix `__init__.py` en ignore_patterns | ✅completada | **Sesión 16**: Archivos como `compass/scanners/python.py` aparecían orphans porque se re-exportan vía `compass/scanners/__init__.py`, pero `__init__.py` estaba ignorado en el scan. Evidencia: 100% de `__init__.py` en Architect_compass + level2agent-engine tienen contenido real (no vacíos). **Approach A:** Quitar `__init__.py` de `ignore_patterns` en mapper_config.json. Resultado: 6 → 4 orphans en Architect_compass (fixed python.py, html.py, treesitter.py). Health +4.55 (87.56 → 92.11). level2agent-engine sin cambios (15 orphans, no dependen de scanners). |
| WEB-039 | Framework static path resolution | 🔲pendiente | Extensión de RES-002 con base paths por framework: Flask `/static/<file>` → `{project_root}/static/<file>`; FastAPI `StaticFiles(directory="static")` → idem; Express `app.use('/static', express.static('public'))` → `{project_root}/public/<file>` cuando HTML tiene `<script src="/static/xxx.js">`. Nueva sección `framework_static_mounts` en `mapper_config.json` con entries por framework (detección por lock file / marker) mapeando URL prefix → filesystem path. Complejidad alta: a veces la config del framework es variable de env, no hardcoded. Afecta: agente_facundo (dashboard JS sueltos). Estimado: ~100-150 líneas. Surgido de "Gaps post-S10.5 (2)". |
| REF-034 | Factorización post-CLI + mover `architect_symbols.py` al paquete | 🔲pendiente | Bundle de refactors pendientes: (a) `path_resolver.py` (1011 líneas - identificado en REF-033), (b) `architect_symbols.py` (~900 líneas, vive en raíz como standalone - moverlo a `compass/symbols.py` para que `compass symbols` no dependa de import cross-paquete), (c) `compass/cli.py` (600 líneas - split en `cli/dispatcher.py` + `cli/handlers.py` si crece más). Ningún archivo debería superar 600 líneas. No bloquea features nuevas; ejecutar cuando alguno de los 3 archivos requiera modificación significativa. |
| CLI-015b | Constructor params para flags `--no-*` en lugar de monkeypatch | 🔲pendiente | CLI-015 implementó `--no-graph`/`--no-history`/`--no-diff` vía monkeypatch de instancia sobre `_emit_graph_html`/`_compute_metrics`/`_rotate_history`. Funciona pero es deuda técnica. Refactor: agregar `emit_graph: bool`, `rotate_history: bool`, `compute_diff: bool` como kwargs del `__init__` de `ArchitectCompass` (default True para preservar comportamiento). CLI los pasa según los flags. Mucho más limpio. ~20 líneas de cambio total. |
| REG-040 | Framework dynamic registration | 🔲pendiente | Detector tipo `loader_calls` para `app.register_blueprint(blueprint_obj)`, `app.include_router(router)` (FastAPI), Django `urlpatterns = [path('foo/', include('app.urls'))]`, y equivalentes en otros frameworks dinámicos (Express `app.use(router)`, Laravel `Route::group(...)`, etc.). Desafío: el argumento es un objeto, no un path - requiere análisis cross-file de símbolos usando `.map/symbols.json` (SYM-004) para resolver exports. **Nota Sesión 21**: caso Agente_facundo (`from .X import bp as X_bp` + `register_blueprint(X_bp)`) queda resuelto por imports estáticos - los 10 blueprints están connected. Pero el ticket cubre casos donde NO hay import estático previo (ej. registro dinámico de routes desde config, blueprints construidos en runtime). Ampliar scope a múltiples frameworks (Flask/FastAPI/Django/Express/Laravel) antes de cerrar. |
| TIER-041 | Tier classification (ambiguous vs orphan) | ✅completada | **Sesión 20 (ITEM 1)**: Clasificación tier en `compass/pipeline.py`. tier=connected (edges), tier=ambiguous (no inbound/entry + conservador), tier=orphan (criterio explícito futuro), tier=dynamic. Visualización graph.html 3 colores. Schema compact/2 con tier pool. Docs en SESSION_LOG. |
| DASH-042 | Dashboard detector stack-agnóstico | ✅completada | **Sesión 20 (ITEM 2)**: Nuevo módulo `compass/dashboard_detector.py`. Stack-agnóstico: HTML carga JS + JS tiene fetch/websocket local → entry_point. Integrado en `_detect_and_promote_dashboards()` de finalize.py. Cero falsos positivos. |
| CMPCT-043 | Compact metadata cleanup (LLM-friendly) | ✅completada | **Sesión 20 (ITEM 3)**: Función `_clean_metadata_for_compact()`. Sentinels @@LOADER@@ → file_loads dict, stdlib filtrado, campos vacíos omitidos. Schema compact/2. ~20% reducción tamaño. |
| ORP-1 | Orphan classification criteria | ✅completada | **Sesión 21**: `DEFAULT_ORPHAN_PATTERNS` en `compass/defaults.py` (extensiones `.bak/.old/.orig/.tmp/.swp/.swo/.rej`, sufijos `_old/_bak/_backup/_deprecated/_legacy/_orig/_tmp`, folder segments `archive/backup/deprecated/old/trash/_trash/_old`). Nuevo módulo `compass/orphan_classifier.py` (merge defaults+config + `is_orphan`). Override opt-in en `mapper_config.json` campo `orphan_patterns` extiende defaults. Lógica en `pipeline.py:_should_be_explicit_orphan`. Validado con archivo temporal `test_old_backup.py` → marcado orphan. |
| ENDP-044 | Framework endpoint highlighting | 🔲pendiente | Detector de decoradores conocidos que marcan funciones como endpoints públicos de un framework: FastAPI (`@app.get/post/put/delete`, `@router.get/...`), Flask (`@app.route`, `@blueprint.route`), FastMCP (`@mcp.tool()`, `@mcp.resource()`), Django (`@api_view` de DRF), Express (no aplica, usa callbacks). Emite metadata `endpoint: {framework, method, path?}` en el nodo del archivo (o en el symbol si está conectado con SYM-004). Renderer HTML aplica borde distintivo o ícono (igual que GRAPH-036 hizo con entry_points). **Scope:** solo etiquetado semántico, no resolución de registros cross-file (ese es REG-040, archivado). Testigos: mcp-write2 (6 tools `@mcp.tool()` en `server.py`), Agente_facundo (blueprints Flask con `@bp.route`), level2agent-engine (si tiene endpoints). Defaults en `compass/defaults.py` → constante `FRAMEWORK_ENDPOINT_DECORATORS`. Extensible vía `mapper_config.json` campo `endpoint_decorators` (opt-in, extiende). Surgido Sesión 23 al evaluar REG-040 - el gap real de los frameworks modernos con decoradores estáticos no es conectividad (ya está), es visualización. ~80-120 líneas. |

---

## ORP-1 - Orphan Classification Criteria

**Responsabilidad:** Definir y clasificar archivos como `tier: orphan` (descartables sin ambigüedad) vs TIER-041 `ambiguous` ("no puedo decidir").

**Decisión Sesión 21:**
Hoy `tier: orphan` está vacío (conservador). Beto define patrones explícitos.

**Defaults en código** (`compass/defaults.py`):
```python
DEFAULT_ORPHAN_PATTERNS = {
    "extensions": [".bak", ".old", ".orig", ".tmp", ".swp", ".swo", ".rej"],
    "name_suffixes": ["_old", "_bak", "_backup", "_deprecated", "_legacy", "_orig", "_tmp"],
    "folder_segments": ["archive", "backup", "deprecated", "old", "trash", "_trash", "_old"],
}
```

**Override opt-in en config** (`mapper_config.json`):
- Nuevo campo `orphan_patterns` (estructura idéntica a defaults)
- Si definido por user: EXTIENDE defaults, no reemplaza
- Ejemplo: user agrega `"archived"` a `folder_segments` → resultado final contiene defaults + archived

**Lógica de clasificación** (Sesión 21: agregar a `pipeline.py` o `finalize.py`):
- Después de calcular `ambiguous`, para cada archivo ambiguous:
  1. Si basename termina en extensión orphan → tier=orphan
  2. Si nombre (pre-extensión) termina en sufijo orphan → tier=orphan
  3. Si cualquier segmento del path relativo está en folder_segments → tier=orphan
- Archivo orphan listado en `summary.orphans[]` (ya existe campo, vacío hoy)

**Visualización:**
- HTML graph: color rojo ya estaba definido para orphan (pre-TIER-041, antes vacío)
- Verificar aplicación correcta del color rojo a nodos orphan reales (Sesión 20: TIER-041 + DASH-042 + CMPCT-043 no lo usaban)

**Validación Sesión 21:**
1. Crear archivo temporal `test_old.py.bak` en Architect_compass → scan → debe aparecer en orphans
2. BORRAR archivo temporal (no commitar)
3. Scan en 3 projects: Architect_compass, level2agent-engine, Agente_facundo → verificar emergen orphans reales

---

## ✅ Listos para Producción - v1.0 Candidate

Tras 20 sesiones de desarrollo incremental, Architect's Compass v1.0 está listo para producción con las siguientes capacidades:

**Core Features**
- Detección stack-agnóstica (Python, JS/TS, PHP, HTML, CSS, JSON)
- Mapeamiento de dependencias con AST (Python) + regex fallback
- Clasificación de archivos: connected (31 promedio), ambiguous (2-6), orphan (vacío - criterios pendientes de definir)
- 5+ entry points detectados por proyecto

**Advanced Features**
- SEM-020: Semantic loader resolution (WordPress enqueue hooks, template functions, path interpolation)
- LOAD-038: Python filesystem loaders (open, json.load, Path.read_text)
- CONS-029: Metadata consolidation (dedup de assets/calls)
- LLM-VIEW-028: Compact atlas (20-30% del size original, schema pooled)
- DASH-042: Dashboard auto-detection (HTML + inline JS + local fetch/websocket)

**CLI & UX**
- CLI-015: 4 subcomandos (scan, symbols, init, graph) + flags globales (--full/--no-diff/--no-history/--no-graph)
- Rich terminal UI con colores y formateo
- HTMLGraph con vis-network (zoom/pan/drag nativos)
- compass.bat launcher portable

**Quality Metrics**
- Architect_compass: 0 orphans / 2 ambiguous / 31 connected / 5 entry_points / 4.1KB compact
- level2agent-engine: 0 / 5 / 24 / 6 / 6.9KB
- Agente_facundo: 0 / 6 / 48 / 7 / 9.1KB
- Cero regresiones en self-scan

---

## 🔄 Pendientes Reales - Sesión 21 onwards

---

## Secuenciación por sesiones de subagente

Agrupación diseñada para evitar conflictos en archivos compartidos. Cada sesión puede asignarse a un subagente independiente. Las sesiones dentro de un mismo nivel son **paralelas entre sí**; los niveles son **secuenciales**.

```
NIVEL 1 ──────────────────────────────────────────────────────────
  Sesión 1 │ MOD-000
           │ Crea el paquete compass/ completo.
           │ Todo lo demás depende de esta estructura.

NIVEL 2 ──────────────────────────────────────────────────────────
  Sesión 2 │ CFG-005 + IGN-016
           │ Ambas tocan mapper_config.json y core.py (load_config_hierarchy).
           │ Deben ir juntas o IGN-016 pisaría el schema recién definido.

NIVEL 3 ──────────────────────────────────────────────────────────
  Sesión 3 │ STK-001 + MST-006
           │ MST-006 extiende el método detect() de STK-001.
           │ Un solo agente: define y extiende en el mismo archivo.

NIVEL 4 ──────────────────────────────────────────────────────────
  Sesión 4 │ RES-002 → SCN-003  (secuencial dentro de la sesión)
           │ SCN-003 consume el PathResolver de RES-002.
           │ Un agente hace los dos en orden: resolver primero, scanner después.
           │ Ambos tocan core.py (analyze) - no paralelizable.

NIVEL 5 ──────────────────────────────────────────────────────────
  Sesión 5 │ DYN-007 + INC-008 + DEF-017
           │ DYN-007 e INC-008 modifican analyze() en core.py.
           │ INC-008 toca el inicio del flujo (fingerprint check).
           │ DYN-007 toca el cierre (clasificación de orphans).
           │ DEF-017 toca mapper_config.json + scanners/regex_fallback.py + scanners/__init__.py.
           │ Overlap controlado: INC-008 agrega reset_cache() y DEF-017 modifica
           │ get_scanner() en scanners/__init__.py - zonas distintas del mismo archivo.
           │ Un solo agente resuelve los tres para evitar conflictos de merge.

NIVEL 5.5 ────────────────────────────────────────────────────────
  Mini-sesión │ HTML-019 + PHP-inbound-019 + GRF-021
              │ Surgió del atlas ETCA post-Sesión 5: HTML 100% orphans,
              │ APIs PHP con __DIR__ . 'path' no resueltos, nodos fantasma
              │ en el grafo (builtins y calls sin target real).
              │ Archivos tocados disjuntos entre los 3 IDs - un solo agente.

NIVEL 5.6 ────────────────────────────────────────────────────────
  Mini-sesión │ FIX-026
              │ (a) Mejorar template compass.local.json con ejemplos fake claros.
              │ (b) Diagnóstico: confirmar por qué APIs de ETCA no tienen inbound
              │     desde HTML/JS (scanner captura, resolver descarta, o external?)
              │ Archivos: compass/core.py (template), compass/path_resolver.py
              │ (diagnóstico), eventual fix chico en resolver JS.

NIVEL 5.7 ────────────────────────────────────────────────────────
  Mini-sesión │ DEF-025
              │ Rediseñar definitions[] de stack-based a language-based.
              │ Eliminar patterns inbound que generan identities falsas
              │ (Tauri, Modern-Web, etc. en proyectos que no los usan).
              │ Agregar guardián de contexto: identity solo si stack_map
              │ del archivo coincide con stack declarado.
              │ Archivos: mapper_config.json, compass/core.py (_scan_file
              │ y tech_scores), compass/scanners/regex_fallback.py.

NIVEL 6 ──────────────────────────────────────────────────────────
  Sesión 6 │ SCR-009 + DIF-010 + CYC-011 + GRF-013 + EDG-023 + AST-024
           │ Todos tocan finalize() y/o la emisión del .dot.
           │ SCR-009: health score descompuesto por dimensiones.
           │ DIF-010: historial + delta entre runs.
           │ CYC-011: detección de ciclos en el grafo.
           │ GRF-013: graph.html con Viz.js leyendo el .dot.
           │ EDG-023: labels semánticos en edges (secuencial a GRF-013).
           │ AST-024: filtrar assets binarios del grafo (secuencial a GRF-013).
           │ Un solo agente - si se vuelve pesado, partir en 6A/6B.

NIVEL 7 ──────────────────────────────────────────────────────────
  Sesión 7 │ FIX-030 + UX-031 + VAL-014
           │ Fixes chicos + cierre de gotchas UX detectados en 2026-04-16
           │ durante el review post-6C contra level2agent-engine.
           │ FIX-030: excluir .env/dotfiles del grafo (basal_rules + filtro
           │          en _is_asset_target / _is_ignored_target).
           │ UX-031:  rename/signaling de `_example_*` vs campos activos en
           │          compass.local.json - evita editar el bloque equivocado.
           │ VAL-014: validación end-of-run de compass.local.json (reporta
           │          `_example_*` divergentes del default como "posible
           │          edición perdida"; cubre el caso UX-031 automáticamente).
           │ Un solo agente - los tres tocan core.py y mapper_config.json
           │ pero en zonas disjuntas. Base para sesiones 8-9.

NIVEL 8 ──────────────────────────────────────────────────────────
  Sesión 8 │ NET-022 + NET-023 + NET-022b
           │ Enriquecimiento de externals - densifica el grafo en proyectos
           │ API-driven (caso detonante: level2agent-engine mostrando todos
           │ los LLM providers colapsados en [EXTERNAL:requests]).
           │ NET-022:  detectar calls HTTP (fetch/axios/requests/wp_remote_*)
           │           y extraer URL literal → nodo [EXTERNAL:host].
           │ NET-023:  auto-promover imports no resueltos a [EXTERNAL:<pkg>]
           │           sin requerir declaración explícita en external_services.
           │ NET-022b: extender `http_loaders` con wrappers custom
           │           (apiReq, apiCall, etc.) - dependiente de NET-022.
           │ Archivos: compass/path_resolver.py, compass/scanners/*.py (extraer
           │ args de calls HTTP), mapper_config.json (http_loaders + match_urls
           │ en external_services), compass/core.py (wiring de promoción).

NIVEL 8.5 ────────────────────────────────────────────────────────
  Mini-sesión │ TIER-035 + GRAPH-036
              │ Puro enhancement visual del grafo HTML - se apoya en los
              │ externals ya densificados por Sesión 8 (NET-022 match_urls,
              │ NET-022b wrappers, NET-023 auto-promoción de imports).
              │ TIER-035:  jerarquía de externals en 4 tiers (stdlib / package
              │            / service / wrapper) - campo `tier` en shape de
              │            external en atlas.json; renderer mapea tier → color.
              │            Depende de NET-022/022b/023.
              │ GRAPH-036: highlight de entry points del proyecto (Python
              │            `if __name__ == '__main__'`, JS `package.json:main`,
              │            PHP `index.php` raíz, refs desde `.bat` raíz).
              │            Nueva metadata `entry_points[]` en atlas.json +
              │            borde dorado / size boost en el renderer.
              │ Archivos: compass/core.py (tier en shape external + detección
              │ entry points en analyze/finalize), compass/scanners/*.py
              │ (detección `if __name__ == '__main__'` en python), mapper_config.json
              │ (detección stdlib-vs-package + `graph.entry_point_size_boost`),
              │ compass/graph_emitter.py + compass/templates/graph.html.tpl
              │ (mapping tier → color + estilo entry point + leyenda opcional).
              │ Zero cambio de layout físico. Ambos IDs son independientes
              │ entre sí; un único agente por afinidad de archivos.

NIVEL 9 ──────────────────────────────────────────────────────────
  Sesión 9 ✅ CERRADA │ INIT-032 + FIX-027 + SEM-020
           │ Densidad interna del grafo - todos extienden PathResolver y/o
           │ scanners para capturar dependencias hoy invisibles.
           │ INIT-032: tracing de re-exports en __init__.py (Python).
           │           Afecta conectividad de level2agent-engine y compass
           │           mismo (paquetes con __init__.py de re-export).
           │ FIX-027:  scanner HTML de inline `<script>` - hoy solo captura
           │           fetch('...') a nivel literal en atributos, no en JS
           │           embebido. Requiere tokenizer/AST JS liviano.
           │ SEM-020:  semantic loader resolution (wp_enqueue_*,
           │           get_template_directory_uri, include ABSPATH.'x').
           │           Elimina necesidad de declarar 31 WP files en
           │           dynamic_deps.
           │ Los tres tocan path_resolver + scanners; un solo agente.

NIVEL 10 ✅ CERRADA ──────────────────────────────────────────────
  Sesión 10 │ CONS-029 + LLM-VIEW-028
            │ Atlas compactor - reduce peso y genera vista LLM-friendly.
            │ CONS-029:     consolidación metadata per-source → global
            │               (dedup de assets/calls/filtered_refs que hoy se
            │               duplican entre archivos). Nuevo helper puro
            │               `compass/consolidator.py` (fuera de core.py para
            │               no invadir REF-033). `atlas.metadata_consolidated`
            │               agregado; per-source intacta.
            │ LLM-VIEW-028: `.map/atlas.compact.json` con schema pooled
            │               (labels/stacks/edge_types/edge_kinds como pools
            │               + nodes/edges como tuples int-indexed). Ratios
            │               compact/full: self 20.5%, ETCA 23.0%, level2 29.7%
            │               (todos <30%). Topología preservada.
            │ Secuencial dentro de la sesión (LLM-VIEW-028 depende de CONS-029).

NIVEL 10.5 ✅ CERRADA ────────────────────────────────────────────
  Mini-sesión │ WP Loader Gaps - 4 fixes sobre SEM-020
              │ (a) `arg: 0` + `path_template` (get_header/get_footer/
              │     get_sidebar/comments_template) → zero-arg calls.
              │ (b) `path_template_with_arg` → variantes `get_header('alt')`.
              │ (c) `accepts_array: true` en `locate_template` → scanner
              │     expande array literal PHP en N sentinels.
              │ (d) Regex de loader ya soporta cuerpos vacíos (no requirió
              │     cambio).
              │ Archivos: `mapper_config.json` + example, `compass/path_resolver.py`,
              │ `compass/scanners/{regex_fallback,treesitter,__init__}.py`.
              │ ETCA: +26 edges a header.php/footer.php (13+13), relevant/total
              │ 82.29%→94.79%. Self +3.46, level2 sin cambios. RES-003
              │ creado como ticket aparte (WP template hierarchy).

NIVEL 11 ✅ CERRADA ──────────────────────────────────────────────
  Sesión 11 │ SYM-004
            │ Archivo nuevo (architect_symbols.py). Independiente del
            │ pipeline de analyze()/finalize(). Output `.map/symbols.json`
            │ con funciones/clases/firmas por archivo - contexto LLM.
            │ Python via stdlib `ast`; JS/TS/PHP via regex fallback
            │ (tree-sitter no estaba instalado). PHP restringido a
            │ bloques `<?php ... ?>` para evitar capturar JS embebido.
            │ Subcomando `compass.bat symbols` agregado al launcher local.

NIVEL 11.5 ───────────────────────────────────────────────────────
  Sesión 11.5 │ REF-033
              │ Refactor PRE-CLI-015 - core.py a ~2000 líneas post-10
              │ es inmanejable para el entry point refactoreado. Partir
              │ en pipeline.py / outbound_resolver.py / template_io.py.
              │ Sin cambio de comportamiento: atlas output byte-a-byte
              │ equivalente pre/post (o diff justificado).
              │ Un agente dedicado - zona hot del código, ningún ID
              │ de feature en paralelo.

NIVEL 12 ─────────────────────────────────────────────────────────
  Sesión 12 │ CLI-015
            │ Modifica architect_compass.py (entry point) y compass.bat.
            │ Último porque envuelve todos los subcomandos ya implementados
            │ (scan, symbols, graph, --full, --no-diff).

NIVEL opcional ───────────────────────────────────────────────────
  Sesión 15           │ BUG-1 (entry points orphans fix) + LOAD-038 refactor
                      │ BUG-1: Entry points ya no marcadas como orphans.
                      │ LOAD-038: loaders universales Python relocados a
                      │           defaults.py (completados S14 + refactor S15).
  
  Sin sesión asignada │ WEB-039, REG-040, RES-003
                      │ Tickets sin nivel fijo - se ejecutan post-CLI-015
                      │ cuando un proyecto concreto los requiera.
                      │ Los 3 son independientes entre sí y no bloquean
                      │ CLI-015 ni REF-033.
                      │ - WEB-039 extiende SEM-020 / RES-002 para frameworks
                      │   Python (Flask / FastAPI / Django) static paths.
                      │ - REG-040 requiere cross-file symbol resolution;
                      │   puede apoyarse en `.map/symbols.json` de SYM-004
                      │   (ya completada).
                      │ - RES-003 cubre WP template hierarchy (jerarquía
                      │   por URL - no son orphans reales).
                      │ Agrupación sugerida: WEB-039 + REG-040 en una
                      │ mini-sesión Python-frameworks cuando agente_facundo /
                      │ level2agent-engine lo demanden; RES-003 en paralelo
                      │ o aparte (toca WP, no Python).
```

### Resumen de archivos por sesión

| Sesión | Archivos que toca |
|--------|-------------------|
| 1 | `architect_compass.py`, crea `compass/*.py`, `compass/scanners/*.py` |
| 2 | `mapper_config.json`, `mapper_config.example.json`, `compass/core.py` (load_config_hierarchy) |
| 3 | `compass/stack_detector.py`, `compass/core.py` (analyze - stack) |
| 4 | `compass/path_resolver.py`, `compass/scanners/*.py`, `compass/core.py` (analyze - scan) |
| 5 | `compass/core.py` (analyze - orphans, fingerprints), `.map/fingerprints.json`, `mapper_config.json`, `compass/scanners/regex_fallback.py`, `compass/scanners/__init__.py` |
| Mini-5.5 | `compass/scanners/html.py` (nuevo), `compass/path_resolver.py` (`_resolve_html` + regex PHP `__DIR__`), `compass/scanners/__init__.py` (registrar html), `mapper_config.json` (stack_markers HTML + definitions HTML + `external_services` + `patterns.outbound` PHP), `compass/core.py` (finalize - 3 categorías + `metadata.calls`), `compass/graph.py` (si existe - shapes/colors external) |
| Mini-5.6 | `compass/core.py` (template `compass.local.json`), `compass/path_resolver.py` (diagnóstico `_resolve_html` / `_resolve_js`) |
| Mini-5.7 | `mapper_config.json` (rediseño `definitions[]` stack→language), `compass/core.py` (`_scan_file`, `tech_scores` - guardián de contexto), `compass/scanners/regex_fallback.py` |
| 6 | `compass/core.py` (finalize), `atlas.json` schema, `.map/graph.html`, `.map/history/`, `compass/scanners/*.py` (edge types para EDG-023), `mapper_config.json` (asset extensions para AST-024) |
| 7 | `compass/core.py` (template `_LOCAL_TEMPLATE`, validación end-of-run, `_is_ignored_target`), `mapper_config.json` (`basal_rules.ignore_patterns` defaults para `.env*`), `compass/graph_emitter.py` (filtro en emisión de nodos) |
| 8 | `compass/path_resolver.py` (promoción a external de imports no resueltos), `compass/scanners/*.py` (extraer URLs de calls HTTP), `mapper_config.json` (`http_loaders`, `external_services.match_urls`), `compass/core.py` (wiring NET-023) |
| Mini-8.5 | `compass/core.py` (`tier` en shape de external + detección de entry points), `compass/scanners/*.py` (detección `if __name__ == '__main__'`), `mapper_config.json` (detección stdlib-vs-package + `graph.entry_point_size_boost`), `compass/graph_emitter.py`, `compass/templates/graph.html.tpl` (mapping tier → color + estilo entry point + leyenda) |
| 9 | `compass/path_resolver.py` (re-exports `__init__.py`, evaluador semántico `path_functions` + `loader_calls`), `compass/scanners/html.py` (inline `<script>` tokenizer), `mapper_config.json` (`path_functions`, `loader_calls`) |
| 10 | `compass/core.py` (consolidación metadata en finalize), `atlas.json` schema (`metadata_consolidated`), nuevo output `atlas.compact.json` |
| 11 | `architect_symbols.py`, `compass.bat` |
| 11.5 | `compass/core.py` (split), `compass/pipeline.py` (nuevo), `compass/outbound_resolver.py` (nuevo), `compass/template_io.py` (nuevo). Zero feature change. |
| 12 | `architect_compass.py`, `compass.bat` |

---

## MOD-000 - Modularización

**Responsabilidad:** Convierte el archivo único `architect_compass.py` en un paquete `compass/` con módulos separados por responsabilidad, dejando el archivo raíz como entry point delgado.

**Cambios en:**
- Nuevo directorio `compass/` con estructura:
  ```
  compass/
  ├── __init__.py
  ├── core.py             ← clase ArchitectCompass (analyze, finalize - pipeline principal)
  ├── stack_detector.py   ← recibe STK-001
  ├── path_resolver.py    ← recibe RES-002
  └── scanners/
      ├── __init__.py     ← dispatcher get_scanner(language) → scanner
      ├── base.py         ← interfaz abstracta Scanner
      ├── python.py       ← Tier 1: ast stdlib
      ├── treesitter.py   ← Tier 2: módulo genérico, acepta grammar como param
      └── regex_fallback.py ← Tier 3: config-driven, para lenguajes sin grammar
  ```
- `architect_compass.py` - queda como entry point: importa `compass.core` y llama `ArchitectCompass().analyze()` seguido de `.finalize()` (match 1-a-1 con el `__main__` del monolito)
- `architect_symbols.py` - permanece en raíz (tool independiente, SYM-004)

**Estimado:** 0 líneas nuevas de lógica (es refactor/mover), ~40 líneas de wiring en `__init__.py` y entry point.

---

## CFG-005 - Config Schema v2

**Responsabilidad:** Reestructura `mapper_config.json` separando sus cuatro concerns actuales (detection, scanning, scoring, graph) en secciones independientes, elimina el acoplamiento entre indicators y patterns dentro de `definitions`, y establece la jerarquía basal → local.

**Cambios en:**
- `mapper_config.json` (basal, versionado en el repo) - nuevo schema:
  ```json
  {
    "basal_rules": {
      "ignore_folders": [...],
      "text_extensions": [...]
    },
    "stack_markers": {
      "WordPress-Development": {
        "lock_files": ["composer.json"],
        "framework_markers": ["wp-config.php", "functions.php"],
        "content_markers": ["Plugin Name:", "Theme Name:"]
      }
    },
    "language_grammars": {
      "php": "tree_sitter_php",
      "javascript": "tree_sitter_javascript",
      "python": "stdlib_ast"
    },
    "scoring": {
      "network_triggers": [...],
      "persistence_triggers": [...],
      "identity_triggers": [...]
    },
    "graph": {
      "unify_external_nodes": [...],
      "ignore_outbound_patterns": [...]
    },
    "definitions": [
      {
        "name": "WordPress-Development",
        "stack": "WordPress-Development",
        "tier": "regex_fallback",
        "patterns": { "inbound": [...], "outbound": [...] }
      }
    ]
  }
  ```
- `mapper_config.example.json` - pasa a ser documentación comentada del schema anterior; se depreca como template funcional
- `compass/core.py` (`load_config_hierarchy`) - genera `[proyecto]/.map/compass.local.json` en primera run si no existe; ese archivo solo contiene overrides, no el schema completo
- `compass.bat` - sin cambios

**Nota:** `stack_markers` separa la detección (STK-001) del scanning (definitions). Los `definitions` quedan exclusivamente para regex fallback (Tier 3) - ya no tienen `indicators`.

**Estimado:** ~30 líneas modificadas en `load_config_hierarchy()`, migración manual de `mapper_config.json` existente.

---

## STK-001 - Stack Detection

**Responsabilidad:** Detecta el stack del proyecto auditado usando una jerarquía determinista (lock files primero, luego framework markers, luego extensión mayoritaria como desempate) para eliminar falsos positivos en la identificación del tipo de proyecto.

**Cambios en:**
- `compass/stack_detector.py` - clase `StackDetector` con método `detect(project_root) → str`
- `compass/core.py` - `analyze()` llama `StackDetector().detect()` en lugar de la lógica actual
- `mapper_config.example.json` - agregar sección `stack_markers` con lock files y markers por definición de lenguaje

**Estimado:** ~60 líneas nuevas en `stack_detector.py`, ~10 líneas modificadas en `core.py`.

---

## STK-001b - Extension hints al config

**Responsabilidad:** Mover el mapping extensión → stack que hoy vive hardcodeado como `_EXTENSION_STACK_HINTS` dentro de `compass/stack_detector.py` a `mapper_config.json`, para que agregar soporte de un nuevo lenguaje genérico (Ruby, Go, Rust, etc.) sea una edición de config y no un cambio de código.

**Decisión del shape de schema:** a criterio del agente, preservando consistencia con el resto de `stack_markers`. Dos opciones válidas:

- **Opción A - un campo más dentro de cada stack en `stack_markers`:**
  ```json
  "stack_markers": {
    "Python":     { "extensions": [".py", ".pyi"] },
    "JavaScript": { "extensions": [".js", ".mjs", ".cjs"] },
    "WordPress-Development": {
      "lock_files": ["composer.json"],
      "framework_markers": ["wp-config.php", "functions.php"],
      "content_markers": ["Plugin Name:", "Theme Name:"]
    }
  }
  ```
- **Opción B - sección top-level separada** (si queda más limpio semánticamente).

**Cambios en:**
- `mapper_config.json` - agregar las entradas de stacks genéricos (Python, JavaScript, TypeScript, PHP-genérico, Ruby, Go, Rust) con sus extensiones conocidas.
- `compass/stack_detector.py` - eliminar el dict hardcoded `_EXTENSION_STACK_HINTS`; leer el mapping desde la config recibida por constructor.
- La capa de "extensión mayoritaria" de la jerarquía de STK-001 debe seguir funcionando igual, solo cambia de dónde saca el mapping.

**Criterio de cierre:** smoke test sobre Compass (detecta `Python` en raíz) y sobre ETCA (detecta `Vanilla-Web-Stack` en raíz + `WordPress-Development` en subdirs) siguen pasando idénticamente a la Sesión 3.

**Estimado:** ~20 líneas modificadas en `stack_detector.py`, ~15 líneas agregadas en `mapper_config.json`.

---

## RES-002 - Path Resolver

**Responsabilidad:** Convierte el string crudo de un import (`'./utils'`, `__DIR__ . '/sub/file.php'`, `@alias/module`) en el path absoluto real del archivo referenciado, usando reglas semánticas específicas por lenguaje y stack detectado.

**Cambios en:**
- `compass/path_resolver.py` - clase `PathResolver` con método `resolve(raw, language, source_file) → str | None`; submétodos `_resolve_php()`, `_resolve_js()`, `_resolve_python()`
- `compass/core.py` - `analyze()` reemplaza llamadas a `_resolve_identity()` por `PathResolver().resolve()`

**Estimado:** ~120 líneas nuevas en `path_resolver.py`, ~20 líneas modificadas en `core.py`.

---

## SCN-003 - Scanner AST / tree-sitter

**Responsabilidad:** Extrae los imports/dependencias de cada archivo usando parsers reales en lugar de regex, eliminando falsos positivos y falsos negativos en la detección de dependencias.

**Cambios en:**
- `compass/scanners/base.py` - interfaz abstracta `Scanner` con método `extract_imports(file) → list[str]`
- `compass/scanners/python.py` - Tier 1: usa `ast` stdlib, cero dependencias
- `compass/scanners/treesitter.py` - Tier 2: módulo genérico; recibe `grammar` como param desde `language_grammars` del config; un solo módulo cubre PHP, JS, TS, Ruby, Go, etc.
- `compass/scanners/regex_fallback.py` - Tier 3: usa `definitions[].patterns` del config para cualquier lenguaje sin grammar
- `compass/scanners/__init__.py` - dispatcher `get_scanner(language, config) → Scanner`; orden: python → treesitter (si instalado) → regex_fallback
- `compass/core.py` - `analyze()` llama al dispatcher con el lenguaje detectado por STK-001

**Nota:** Agregar soporte para un lenguaje nuevo no requiere tocar código - solo instalar la grammar (`pip install tree-sitter-ruby`) y agregar la entrada en `language_grammars` del config. tree-sitter es opt-in: si no está instalado, todos los lenguajes (excepto Python) caen a Tier 3.

**Estimado:** ~80 líneas en scanners, ~30 líneas modificadas en `core.py`.

---

## SYM-004 - Symbol Tool

**Responsabilidad:** Herramienta paralela e independiente que recorre el proyecto auditado y extrae símbolos (funciones, clases, firmas de métodos) para producir un output estructurado útil como contexto para LLMs.

**Cambios en:**
- Nuevo archivo `architect_symbols.py` - clase `SymbolExtractor` independiente de `ArchitectCompass`
- Output: `.map/symbols.json` - formato:
  ```json
  {
    "file/path.py": [
      { "type": "function", "name": "my_func", "signature": "def my_func(a, b)", "line": 12 }
    ]
  }
  ```
- `compass.bat` - subcomando opcional `symbols` para invocarlo por separado

**Estimado:** ~200 líneas en `architect_symbols.py`, ~10 líneas en `compass.bat`.

---

## MST-006 - Multi-stack Detection

**Responsabilidad:** Extiende STK-001 para detectar stacks por subárbol de directorios, permitiendo que un proyecto tenga múltiples stacks activos simultáneamente (ej: WordPress en raíz + React en `admin/` + Python en `api/`).

**Cambios en:**
- `compass/stack_detector.py` - `detect()` devuelve `StackMap: dict[str, str]` en lugar de `str`; mapea cada subdirectorio relevante a su stack detectado
- `compass/core.py` - `analyze()` consulta `StackMap` por archivo (directorio más específico primero) al elegir scanner y resolver
- `mapper_config.json` - `stack_markers` ya soporta múltiples stacks; sin cambios de schema

**Estimado:** ~40 líneas modificadas en `stack_detector.py`, ~20 líneas en `core.py`.

---

## DYN-007 - Dynamic Deps Annotations

**Responsabilidad:** Permite declarar en `compass.local.json` las dependencias que no pueden inferirse estáticamente (autoloaders, WordPress hooks, dynamic requires), marcándolas como `dynamic_declared` en el atlas en lugar de huérfanos falsos.

**Cambios en:**
- `compass.local.json` - nueva sección `dynamic_deps`:
  ```json
  "dynamic_deps": {
    "includes/autoload.php": "loads src/modules/*.php",
    "src/hooks.php": ["src/handlers/save.php", "src/handlers/delete.php"]
  }
  ```
- `compass/core.py` - al calcular orphans, excluir archivos declarados en `dynamic_deps`; marcarlos en atlas como `"orphan_reason": "dynamic_declared"`
- `atlas.json` - nuevo campo `orphan_reason` en nodos relevantes

**Estimado:** ~30 líneas en `core.py`, ~5 líneas en schema de atlas.

---

## INC-008 - Escaneo Incremental

**Responsabilidad:** Evita re-escanear archivos no modificados guardando un fingerprint (SHA-256) por archivo entre runs; solo procesa archivos nuevos o modificados y mergea con caché del atlas previo.

**Cambios en:**
- `.map/fingerprints.json` - nuevo archivo generado por compass; formato `{ "path": "sha256hash" }`
- `compass/core.py` - antes de `analyze()`, comparar fingerprints actuales vs. guardados; solo pasar archivos modificados al scanner; mergear resultados con atlas previo
- `compass/finalize()` - persiste fingerprints actualizados al cierre

**Nota de Sesión 4:** `compass/scanners/__init__.py::get_scanner()` cachea instancias por `(language, id(config))`. INC-008 debe exponer un `reset_cache()` (o invalidarlo al inicio de cada `analyze()`) para evitar servir scanners con patterns obsoletos si la config se recarga en el mismo proceso. Origen del hallazgo: `SESSION_LOG.md` entrada Sesión 4 #5.

**✅ Implementado en Sesión 5:** `reset_cache()` expuesto en `scanners/__init__.py`; `analyze()` lo invoca al inicio de cada run. Propiedad resultante: cambiar `mapper_config.json` o `compass.local.json` entre runs fuerza re-scan con patterns actuales, sin necesidad de flag `--full` ni borrar `fingerprints.json` manualmente (la invalidación es transparente al user).

**Estimado:** ~60 líneas en `core.py`, nuevo archivo `fingerprints.json` generado en runtime.

---

## SCR-009 - Score Breakdown

**Responsabilidad:** Descompone el health score en dimensiones independientes (orphans, connectivity, dead exports, external deps) para que el resultado sea accionable, no solo un número.

**Cambios en:**
- `compass/core.py` (`finalize()`) - calcular sub-scores por dimensión además del total
- `atlas.json` - nuevo campo `score_breakdown`:
  ```json
  "score_breakdown": {
    "total": 73,
    "orphans":      { "score": 60, "count": 12, "files": ["src/old-util.php"] },
    "connectivity": { "score": 80, "avg_inbound": 2.1 },
    "dead_exports": { "score": 75, "count": 5 },
    "external_deps":{ "score": 85 }
  }
  ```

**Estimado:** ~50 líneas nuevas en `finalize()`, cambio de schema en atlas.

**✅ Implementado en Sesión 6A (2026-04-16):**
- Lógica en nuevo módulo `compass/metrics.py::compute_health_score()` - pura, stdlib-only, separada de `core.py` para dejar la superficie de `finalize()` limpia para 6B.
- Schema en `atlas.json`: nuevo campo top-level `"health": { total, weights, orphans:{score,count,files}, connectivity:{score,avg_inbound,total_inbound_edges}, dead_exports:{score,count,files}, external_deps:{score,external_targets,total_targets} }`.
- Pesos por dimensión: `orphans=0.40, connectivity=0.30, dead_exports=0.15, external_deps=0.15`. Total = suma ponderada (0-100).
- Interpretaciones pragmáticas (no había tracking previo de exports ni deps externas):
  - `dead_exports`: archivos con outbound pero cero inbound (y no marcados como `dynamic_declared`). Proxy de módulos "muertos".
  - `external_deps`: ratio 1 - (external_targets / total_targets). Proyecto 100% interno → 100; todo externo → 0.
- Backward-compat: `audit.structural_health` (métrica v1 relevant/total) se preserva intacta. Los consumidores que la leen siguen funcionando. `health.total` es un score adicional, no un reemplazo.
- Cap visual: listas de `files` en `orphans`/`dead_exports` se cortan a 20 items. La lista completa sigue en `atlas.orphans`.

---

## DIF-010 - Diff entre Corridas

**Responsabilidad:** Persiste un snapshot del atlas por cada run en `.map/history/` y al finalizar muestra un delta respecto al run anterior: cambios en score, orphans nuevos/resueltos, archivos agregados/eliminados.

**Cambios en:**
- `.map/history/` - directorio nuevo; cada run guarda `YYYYmmdd_HHmm_[nombre-proyecto].json`; se mantienen las últimas 10, la más antigua se elimina al agregar una nueva
- `compass/core.py` (`finalize()`) - antes de escribir, cargar último snapshot de history; calcular delta; incluirlo en output de consola y en `atlas.json` como campo `"delta"`
- `atlas.json` - nuevo campo opcional `"delta"` presente solo si existe run previo

**Estimado:** ~70 líneas en `finalize()`, estructura de directorio `.map/history/` generada en runtime.

**✅ Implementado en Sesión 6A (2026-04-16):**
- Helpers en `compass/metrics.py`: `load_previous_snapshot()`, `save_snapshot()`, `diff_against_previous()`, `build_snapshot_name()`. `HISTORY_DIR_NAME="history"`, `HISTORY_MAX_ENTRIES=10`.
- Wiring en `core.py::_compute_metrics()` + `_rotate_history()`.
- Nombre de snapshot: `YYYYmmdd_HHMM_<project>.json` (sanitizado para filesystem).
- Rotación: mantiene las últimas 10 snapshots; al escribir la #11 borra la #1 (FIFO por nombre - sort lexicográfico == cronológico gracias al formato de timestamp).
- **Fallback útil en primer run post-6A:** si `.map/history/` está vacío pero existe `.map/atlas.json` de runs pre-6A (típico en proyectos ya auditados como ETCA), se usa ese atlas como snapshot previo para emitir un primer delta. Así el primer run tras la migración a 6A no queda mudo. Defensivo contra self-diff: si `generated_at` coincide entre current y previous, se descarta el previous.
- Shape del delta en `atlas.json`:
  ```json
  "delta": {
    "previous_generated_at": "...",
    "files":   { "added": [...], "removed": [...] },
    "edges":   { "added": [...], "removed": [...], "added_count": N, "removed_count": N },
    "orphans": { "added": [...], "removed": [...] },
    "cycles":  { "added": [...], "removed": [...] },
    "health_delta": { "total": ±, "orphans": ±, "connectivity": ±, "dead_exports": ±, "external_deps": ± }
  }
  ```
- `edges.added/removed` están capados a 50 items; los contadores exactos viven en `_count`.
- Snapshot guardado en history NO contiene el campo `delta` - evita deltas recursivos sobre deltas viejos.

---

## CYC-011 - Detección de Ciclos

**Responsabilidad:** Detecta dependencias circulares en el grafo del atlas usando DFS y las reporta explícitamente, sin penalizar el score (son información arquitectónica, no necesariamente un bug).

**Cambios en:**
- `compass/core.py` (`finalize()`) - DFS sobre grafo de outbound links del atlas; detectar back-edges como ciclos
- `atlas.json` - nuevo campo `"cycles": [["a.php", "b.php", "a.php"], ...]`; vacío si no hay ciclos
- Output de consola - si hay ciclos, listarlos al final del run

**Estimado:** ~40 líneas en `finalize()`, cambio de schema en atlas.

**✅ Implementado en Sesión 6A (2026-04-16):**
- Lógica en `compass/metrics.py::detect_cycles(outbound_edges, repo_paths)` - pura, stdlib-only. DFS clásico con coloración WHITE/GRAY/BLACK; back-edge a nodo GRAY = ciclo.
- Solo considera edges intra-repo (filtra `[EXTERNAL:*]` y targets no presentes en `atlas.files`).
- Dedup por rotación canónica: cada ciclo se rota para arrancar por su nodo mínimo (orden alfabético). Ciclos direccionales - NO se trata `[a,b,a]` y `[b,a,b]` como duplicados (son trayectorias distintas).
- Output en `atlas.json::"cycles"` - lista de listas `[a, b, c, a]` (nodo inicial se repite al final como convención PLAN).
- Output de consola: si hay ciclos, lista los primeros 5 con flechas Unicode `→`; el resto se referencia en atlas.
- **Decisión explícita: los ciclos NO penalizan el health score.** PLAN CYC-011 es claro al respecto ("son información arquitectónica, no necesariamente un bug"). El diff incluye `cycles.added/removed` para trackear cambios entre runs.
- Hallazgo real: corrida sobre ETCA detectó 2 ciclos legítimos (footer nav entre páginas estáticas): `faq.html → nosotros.html → sedes.html → faq.html` y `privacidad.html → terminos.html → privacidad.html`. Son estructurales (navegación mutua), no bugs - confirman que la métrica es info, no penalty.
- Límite conocido: DFS recursivo. Python default recursion limit=1000; proyectos con cadenas de imports >1000 niveles fallarán. Para el uso real (proyectos de Beto tienen árboles de 5-8 niveles máximo) es non-issue. Si en el futuro aparece, convertir a DFS iterativo con stack explícito.

---

## GRF-013 - HTML Graph Viewer

**Responsabilidad:** Genera un archivo `graph.html` en `.map/` que renderiza el grafo usando Viz.js (Graphviz compilado a WebAssembly), produciendo el mismo layout visual que dreampuf/GraphvizOnline pero abriendo directamente en browser sin herramientas externas.

**Cambios en:**
- `compass/core.py` (`finalize()`) - al generar `connectivity.dot`, también generar `graph.html` embebiendo el contenido del `.dot` como string JS
- `.map/graph.html` - lee el `.dot` embebido, lo pasa a Viz.js y renderiza SVG inline; Viz.js se carga desde CDN (`unpkg.com/viz.js`) o desde `viz-standalone.js` local si existe en `.map/`
- `connectivity.dot` - sigue generándose; `graph.html` lo consume y lo reemplaza como output primario para uso humano

**Nota offline:** si `viz-standalone.js` (~1.5MB) existe en `.map/`, el HTML lo usa en lugar del CDN - funciona sin internet. Compass puede descargarlo automáticamente en primera run si hay conexión, o el usuario lo coloca manualmente.

**Estimado:** ~40 líneas en `finalize()`, template HTML de ~30 líneas (Viz.js hace el trabajo pesado).

**✅ Implementado en Sesión 6B (2026-04-16):**
- Emisión extraída a `compass/graph_emitter.py` (nuevo, stdlib-only, espeja `metrics.py`). Funciones puras: `build_dot_content(...)`, `build_graph_html(...)`, `validate_dot_syntax(...)`. `core.py` solo hace I/O.
- `.dot` profesional: clustering por directorio top-level (`subgraph cluster_<dir>`), shape/color por kind de nodo (`normal`=gris, `orphan`=ámbar, `cycle`=rojo, `external`=cilindro rojo), labels + colores por `edge_type` (EDG-023), subgraph `cluster_legend` auto-generado con los tipos realmente presentes.
- Colores configurables vía `graph.edge_colors` y `graph.node_colors` en `mapper_config.json`; defaults razonables en `graph_emitter.py`.
- `graph.html`: HTML standalone que embebe el `.dot` como string JS y lo renderiza con Viz.js (`@viz-js/viz@3.2.4`). Botón "Download SVG", header con stats del run (node_count, edge_count, cycle_count). **Offline-first:** intenta `./viz-standalone.js` local primero, cae a CDN `unpkg.com` si no.
- Validación: `validate_dot_syntax()` como smoke sin Graphviz (balance de `{}`, terminadores `;`). En los tests de 6B: `validate_dot_syntax` → OK en Compass (4/4 braces) y ETCA (7/7 braces, 352 líneas).
- Orden de `finalize()` reordenado: `_compute_metrics()` ahora corre ANTES de `_emit_dot_graph()` - GRF-013 necesita `atlas.cycles` poblado para colorear los nodos en ciclos. Con esto en ETCA los 5 archivos `faq.html/nosotros.html/sedes.html/privacidad.html/terminos.html` salen con fillcolor `#fde0dc` confirmando que los 2 ciclos detectados se visualizan.
- Trade-off: no se descarga automáticamente `viz-standalone.js` en primera run (requeriría `urllib.request` + manejo de errores de red, scope extra). El usuario tiene CDN por defecto y puede drop-in el archivo si quiere offline total.

---

## VAL-014 - Config Validation

**Responsabilidad:** Al final de cada run, reporta en consola cualquier entrada inválida o inconsistente encontrada en `compass.local.json` (archivos declarados que no existen, stacks referenciados sin definición, campos desconocidos). Además detecta artefactos legacy en `.map/` del proyecto auditado (ver más abajo).

**Cambios en:**
- `compass/core.py` - nueva función `_validate_local_config(config, project_root)` que corre antes de `analyze()`; acumula warnings sin abortar el run
- Output de consola al cierre - sección `CONFIG WARNINGS` solo si hay problemas:
  ```
  CONFIG WARNINGS:
  ⚠ dynamic_deps: 'src/handlers/missing.php' no existe en el proyecto
  ⚠ stack_markers: stack 'MyStack' no tiene definición en definitions[]
  ⚠ legacy: '.map/mapper_config.template.json' es del schema v1 - borrar o reemplazar por compass.local.json
  ```

**Detección de legacy:** en proyectos auditados, el contrato post schema v2 es que `.map/` solo contenga `compass.local.json` (además de los outputs: `atlas.json`, `connectivity.dot`, `feedback.log`, `graph.html` a partir de GRF-013). Cualquier archivo `mapper_config*.json` o `compass.local.template.json` residual dispara un warning explícito, porque indica una corrida previa con schema viejo que el usuario olvidó migrar.

**Estimado:** ~40 líneas en `_validate_local_config()`, ~10 líneas en output de cierre, ~10 líneas extra para detección de legacy en `.map/`.

---

## CLI-015 - CLI Flags & Subcommands

**Responsabilidad:** Reemplaza la invocación posicional actual por una CLI estructurada con argparse (o typer), subcomandos explícitos y flags opcionales; es el punto de convergencia con el CLI roadmap existente.

**Cambios en:**
- `architect_compass.py` (entry point) - reemplazar invocación directa por argparse/typer
- Subcomandos:
  - `compass scan [path]` - run principal (equivalente al actual `compass [path]`)
  - `compass symbols [path]` - SYM-004
  - `compass graph [path]` - solo regenerar `graph.html` sin re-escanear
- Flags para `scan`:
  - `--full` - forzar escaneo completo ignorando fingerprints (INC-008)
  - `--no-diff` - omitir delta aunque exista historial (DIF-010)
  - `--config [path]` - apuntar a un `compass.local.json` alternativo
- `compass.bat` - actualizar para pasar `%*` al entry point

**Nota de Sesión 4 (resuelve hallazgo #7 de Sesión 2):** el entry point debe localizar `mapper_config.json` de forma robusta y pasar la ruta absoluta al constructor de `ArchitectCompass`, eliminando el `script_dir = Path(__file__).parent.parent` acoplado al layout que vive hoy en `compass/core.py::__init__`. Estrategia sugerida: buscar hacia arriba desde `Path(__file__)` hasta encontrar `mapper_config.json`, o leer override de `COMPASS_HOME` / flag `--home [path]`. Así `core.py` deja de depender de su profundidad relativa y la sesión futura que mueva el módulo no rompe silenciosamente.

**Estimado:** ~60 líneas en entry point, ~10 líneas en `compass.bat`.

---

## IGN-016 - Ignore Files & Patterns

**Responsabilidad:** Permite excluir archivos individuales y patrones de nombre (glob) del análisis desde `mapper_config.json` o `compass.local.json`, para eliminar ruido de archivos minificados, vendor scripts, y herramientas externas dentro del árbol del proyecto.

**Cambios en:**
- `mapper_config.json` - nuevos campos en `basal_rules`:
  ```json
  "ignore_files": ["scripts/Search-Replace-DB-4.1.4/index.php"],
  "ignore_patterns": ["*.min.js", "*.min.css", "*.bundle.js"]
  ```
- `compass/core.py` (`_index_existing_files()`) - filtrar archivos que matcheen `ignore_files` (path exacto) o `ignore_patterns` (fnmatch glob) antes de indexar
- `compass.local.json` - puede sobreescribir o extender ambas listas por proyecto

**Estimado:** ~20 líneas en `_index_existing_files()`, cambio de schema en config.

---

## DEF-017 - Language filter en `definitions[]`

**Responsabilidad:** Filtrar las patterns de `definitions[]` por lenguaje del archivo escaneado, evitando que una regex pensada para un stack matchee spuriamente contra contenido de otro lenguaje cuando cae al `RegexFallbackScanner` (Tier 3).

**Origen:** Sesión 4 hallazgo #4. Hoy `RegexFallbackScanner` consume todas las outbound patterns de `definitions[]` sin distinguir lenguaje. Funciona porque las patterns actuales son específicas, pero es ruido latente - una regex WP podría matchear un string en un `.js` y generar una edge falsa.

**Cambios en:**
- `mapper_config.json` - agregar campo `language` (string) o `languages` (lista) a cada entry de `definitions[]`:
  ```json
  "definitions": [
    {
      "name": "WordPress-Development",
      "stack": "WordPress-Development",
      "language": "php",
      "tier": "regex_fallback",
      "patterns": { "inbound": [...], "outbound": [...] }
    }
  ]
  ```
- `compass/scanners/regex_fallback.py` - el constructor o el dispatcher filtra las definitions: solo aplica patterns cuyo `language` coincida con el lenguaje del archivo. Si una definition no declara `language`, se asume que aplica a todos (backward-compat).
- `compass/scanners/__init__.py::get_scanner()` - al construir el scanner Tier 3 para un lenguaje, pasar solo las patterns de las definitions filtradas por ese lenguaje.

**Criterio de cierre:** smoke test sobre proyectos que tengan archivos de más de un lenguaje (ej. ETCA con PHP + JS + CSS) confirma que ninguna pattern de una definition PHP aparece aplicada sobre archivos JS, y que el atlas no tiene edges fantasma por matches cross-lenguaje.

**Asignación:** Sesión 5 (junto con DYN-007 + INC-008). Razón: archivos disjuntos del resto de la sesión excepto `scanners/__init__.py`, donde DEF-017 modifica `get_scanner()` mientras INC-008 agrega `reset_cache()` - zonas distintas, resolver con un único agente evita merge conflicts.

**Estimado:** ~10 líneas en `regex_fallback.py`, ~5 líneas en el dispatcher, ~5 líneas por entry en `mapper_config.json`.

---

## EVL-001 - Review schema `extensions` (A vs B)

**Responsabilidad:** Revisar, después de terminar toda la implementación del PLAN y acumular varios usos reales sobre proyectos de Beto, si el shape elegido en STK-001b para `extensions` en `stack_markers` (opción A - co-localizadas dentro de cada entry) sigue siendo la mejor decisión, o conviene migrar a opción B (sección top-level `extension_hints`).

**Contexto de la decisión original (2026-04-15):**
- El agente de STK-001b eligió **A** argumentando "señales del mismo dominio, evitar desincronización silenciosa entre dos secciones".
- Beto cuestionó el argumento; análisis detallado mostró que para sus 3 proyectos reales (etca.com.ar, clases.etca.com.ar, level2agent-engine) **A y B producen el mismo StackMap** porque todos tienen framework markers claros que resuelven en capa 1-2 de la jerarquía, antes de que `extensions` entre en juego.
- B gana en escenarios futuros hipotéticos: (a) overrides por proyecto en `compass.local.json` de "qué stack gana para una extensión"; (b) colisiones de extensión entre stacks declarados (el schema B las vuelve imposibles por construcción de clave única).
- Decisión cerrada: mantener A, diferir la revisión a esta tarea cuando haya evidencia de uso real.

**Evidencia a recolectar antes de decidir:**
- ¿Cuántas veces Beto tuvo que editar `stack_markers` en `mapper_config.json` o `compass.local.json`?
- ¿Apareció alguna colisión real de extensión entre stacks declarados?
- ¿Hubo casos donde un proyecto sin framework markers dependió del desempate por `extensions`, y el resultado fue frágil o incorrecto?
- ¿Los overrides en `compass.local.json` resultaron verbosos o naturales?
- Evidencia inicial ya disponible: `SESSION_LOG.md` Sesión 3b hallazgo #1 documenta que el schema A resuelve colisiones por "order of JSON wins" y que hoy no hay colisiones reales solo porque los stacks framework-like no declaran `extensions` y los genéricos tienen extensiones disjuntas - un equilibrio frágil. Revisar este hallazgo al cerrar EVL-001: si aparece un stack nuevo que rompa esa disjunción, el argumento a favor de B (clave única por construcción) se vuelve concreto.

**Decisión a tomar:**
- Si la evidencia muestra que `extensions` nunca fue relevante en la práctica → mantener A, cerrar EVL-001.
- Si aparecieron colisiones o overrides incómodos → migrar a B como mini-sesión (~15 líneas).

**Estimado si se decide migrar:** ~15 líneas en `stack_detector.py`, ~15 líneas reorganizadas en `mapper_config.json`, refactor puro sin cambio de comportamiento observable.

---

## HTML-019 - Scanner + resolver HTML

**Responsabilidad:** Agrega soporte de primera clase para archivos HTML como nodos y como fuentes de edges: scannea atributos que referencian otros recursos del repo y los resuelve a paths reales, resolviendo el problema actual de que todo `.html` queda 100% huérfano en el atlas.

**Origen:** atlas de ETCA post-Sesión 5 muestra HTML como orphan 100% aunque tiene enlaces reales (`<script src>`, `<link href>`, `<a href="sedes">`). Sin scanner HTML, el tool subestima la conectividad real del proyecto y no puede discriminar páginas huérfanas reales de páginas que sólo el scanner no ve.

**Cambios en:**
- `compass/scanners/html.py` - **nuevo** archivo. Scanner Tier 3 (regex fallback) que extrae referencias de los atributos:
  - `<script src="…">`, `<link href="…">`, `<img src="…">`, `<a href="…">`
  - `<form action="…">`, `<iframe src="…">`, `<video src="…">`, `<source src="…">`
  - Edge cases a ignorar (no emiten outbound): `#anchor` puro, `mailto:…`, `tel:…`, `javascript:…`, `data:…`
  - URLs absolutas (`http://`, `https://`, `//cdn…`) → no se resuelven contra el repo; quedan como `external candidate` para que GRF-021 / NET-022 decida si las emite como `[EXTERNAL:…]`
  - Query strings (`foo.js?v=1`) y fragmentos (`page#section`) → se strippean antes de resolver
  - Rutas sin extensión (`href="sedes"`, `href="/contacto"`) → el resolver intenta `sedes.html`, `sedes/index.html`
- `compass/path_resolver.py` - nuevo submétodo `_resolve_html(raw, source_file, project_root)`:
  - Root-relative (`/assets/x.css`) → `project_root/assets/x.css`
  - Relative (`./x.css`, `../img/x.png`) → resuelve contra dir del source
  - Sin extensión → probar `.html` y `/index.html` en ese orden
- `mapper_config.json`:
  - `stack_markers.HTML` → `"extensions": [".html", ".htm"]`
  - `definitions[]` → entrada `{ "name": "HTML", "language": "html", "tier": "regex_fallback", "patterns": { "outbound": [...] } }` con las regex de atributos listados arriba
  - `language_grammars` → sin cambios (HTML queda en Tier 3; no hace falta grammar)
- `compass/scanners/__init__.py` → registrar `html` en el dispatcher

**Criterio de cierre:** sobre un proyecto estático típico (ETCA), el atlas muestra edges salientes desde `index.html` hacia sus CSS/JS/img referenciados; `orphans_html` cae significativamente respecto a la run previa.

**Estimado:** ~57 líneas nuevas (scanner + resolver + entries de config combinadas).

---

## PHP-inbound-019 - Outbound pattern `__DIR__` PHP

**Responsabilidad:** Agregar una sola regex a `Vanilla-Web-Stack-PHP` (sección `patterns.outbound`) para capturar el idiom `require(_once) __DIR__ . '/subpath'`, que hoy no se captura aunque es el patrón canónico de APIs PHP sin autoloader.

**Origen:** atlas de ETCA post-Sesión 5 - los 10-12 endpoints de `api/*.php` todos arrancan con `require_once __DIR__ . '/../bootstrap.php'` y todos aparecen como huérfanos salientes. El resolver ya sabe resolver el string `/bootstrap.php` correctamente - el problema es que la pattern actual no lo captura. PHP-018 queda diferido porque la mayoría de los "problemas PHP" eran en realidad este pattern faltante.

**Cambios en:**
- `mapper_config.json` → en `definitions[].name == "Vanilla-Web-Stack-PHP"`, `patterns.outbound`:
  ```
  "require(?:_once)?\\s+[A-Z_]+\\s*\\.\\s*'([^']+)'"
  ```
  (captura `require __DIR__ . '/x'`, `require_once __DIR__ . '/y'`, y también cualquier constante mayúscula en lugar de `__DIR__` como `ABSPATH`, `ROOT_DIR`, etc.)
- Ninguna lógica nueva en `path_resolver.py` - `_resolve_php` ya interpreta correctamente el string capturado (`/bootstrap.php` resuelve root-relative al dir del source o al project root según el matcher actual de suffix).

**Criterio de cierre:** corrida sobre ETCA muestra los endpoints `api/*.php` con edge saliente a `bootstrap.php`; cuenta de huérfanos PHP en atlas baja en 10-12.

**Estimado:** +1 línea de regex en `mapper_config.json`. Cero líneas de código nuevas.

---

## GRF-021 - Graph cleanup + External Level 1

**Responsabilidad:** Separa los destinos de edges en 3 categorías explícitas (archivo del repo / servicio externo declarado / builtin-stdlib-lib-local) para eliminar los nodos fantasma que hoy ensucian el grafo (`document.querySelector`, `curl_exec`, `update_post_meta`, `json`, `os`, `re`) y para darle shape/color distinto a los servicios externos SDK-detectables.

**Origen:** Beto, mirando el grafo de ETCA, señaló que el grafo muestra "nodos" que no son archivos ni servicios - son funciones builtin o módulos stdlib. Propuso las 3 categorías. GRF-021 implementa esa partición en la fase de emisión del grafo (finalize).

**Cambios en:**

- `mapper_config.json` - nueva sección `external_services` (Level 1 - SDKs por nombre de import):
  ```json
  "external_services": [
    { "label": "Anthropic",  "match": ["anthropic", "Anthropic\\\\Anthropic", "@anthropic-ai/sdk"] },
    { "label": "OpenAI",     "match": ["openai", "OpenAI\\\\OpenAI", "openai/openai-python"] },
    { "label": "Supabase",   "match": ["supabase", "@supabase/supabase-js"] },
    { "label": "Stripe",     "match": ["stripe", "Stripe\\\\Stripe", "@stripe/stripe-js"] },
    { "label": "OpenRouter", "match": ["openrouter"] },
    { "label": "Gemini",     "match": ["google-generativeai", "@google/generative-ai"] }
  ]
  ```
  (Nota: `match` es lista - cubre variantes PHP/Node/Python del mismo SDK. NET-022 en Sesión X agregará `match_urls` al lado de `match`.)
- `compass/core.py` (`finalize`) - lógica de emisión de nodos/edges por cada raw outbound capturado:
  1. Si el resolver devuelve path existente en el repo → nodo archivo + edge archivo→archivo normal.
  2. Si NO resuelve a archivo del repo **y** matchea algún `external_services[*].match` → nodo `[EXTERNAL:<label>]` con shape distinto (cylinder, color rojo), edge coloreado desde el source. Un único nodo por label (se unifican las edges entrantes).
  3. Resto (builtins, stdlib, lib local del lenguaje, identificadores no resueltos) → **no emite nodo ni edge**. Se acumula en `metadata.calls` del nodo source en `atlas.json`:
     ```json
     { "metadata": { "calls": ["document.querySelector", "curl_exec", "json", "os"] } }
     ```
- `compass/graph.py` (si existe como módulo separado; si no, inline en `finalize`) - al generar el `.dot`, aplicar shape/color por tipo de nodo:
  - archivo repo → shape default
  - `[EXTERNAL:…]` → `shape=cylinder, color=red, fillcolor="#ffcccc", style=filled`
- **Cleanup de config relacionado:** eliminar (o endurecer en el scanner) patterns no-capturantes que hoy generan edges vacíos - ej. `"header\\("` sin grupo de captura `(...)`. Regla: toda pattern en `definitions[].patterns.outbound` debe tener exactamente 1 grupo de captura; si no, el scanner la ignora y emite warning.

**Criterio de cierre:** corrida sobre ETCA y sobre Compass mismo - el `.dot` resultante no tiene nodos `document.querySelector`, `json`, `os`, `re`, `curl_exec`, `update_post_meta`. Si hay imports de Anthropic u OpenAI en algún proyecto, aparecen como nodos cilindro rojos. `metadata.calls` poblado en nodos con llamadas stdlib.

**Estimado:** ~80 líneas - ~15 en config schema, ~50 en `finalize` / `graph.py`, ~15 en validación de patterns.

---

## SEM-020 - Semantic Loader Resolution

**Responsabilidad:** Extiende el `PathResolver` para evaluar semánticamente expresiones de path que involucran llamadas a funciones con resultado conocido (`get_template_directory_uri() . '/css/main.css'`) y para reconocer "loader calls" cuyo argumento representa un path (`wp_enqueue_script('foo', …)`, `get_template_part('template-parts/header')`, `include ABSPATH . 'wp-load.php'`). Elimina la necesidad de declarar archivos de WordPress en `dynamic_deps` uno por uno.

**Origen:** proyecto ETCA WP + portfolio reveló que WordPress y muchos frameworks usan funciones que devuelven paths; sin evaluarlas el resolver falla y termina dependiendo de `dynamic_deps` para declarar 31 archivos WP a mano. No escala.

**Cambios en:**

- `mapper_config.json` - dos secciones nuevas:
  ```json
  "path_functions": {
    "get_template_directory_uri": "{theme_root}",
    "get_template_directory":     "{theme_root}",
    "get_stylesheet_directory_uri": "{theme_root}",
    "plugins_url":                "{plugins_root}",
    "plugin_dir_path":            "{plugins_root}",
    "__dirname":                  "{source_dir}"
  },
  "loader_calls": {
    "wp_enqueue_script":   { "arg": 2, "ext_default": ".js" },
    "wp_enqueue_style":    { "arg": 2, "ext_default": ".css" },
    "wp_register_script":  { "arg": 2, "ext_default": ".js" },
    "wp_register_style":   { "arg": 2, "ext_default": ".css" },
    "get_template_part":   { "arg": 1, "ext_default": ".php", "suffix_slash_index": true },
    "include":             { "arg": 1 },
    "require":             { "arg": 1 },
    "require_once":        { "arg": 1 }
  }
  ```
  Tokens reemplazables en los valores de `path_functions`:
  - `{theme_root}` - dir del tema WP detectado (o `project_root` fallback)
  - `{plugins_root}` - `wp-content/plugins` bajo el root WP detectado
  - `{source_dir}` - dir del archivo que contiene la llamada
- `compass/path_resolver.py` - dos extensiones:
  1. **Evaluador de concatenaciones `func() . 'literal'`:** si el raw capturado contiene `<fn>()` seguido de concatenación, y `<fn>` está en `path_functions`, reemplazar por el valor resuelto (con tokens sustituidos) antes de resolver el resto.
  2. **Detección de loader_calls:** el scanner captura la llamada completa; el resolver extrae el argumento indicado por `arg`, aplica `ext_default` si el string no termina en extensión conocida, resuelve como path relativo al source o al theme_root según el caso.
- `compass/scanners/*.py` - los scanners (tree-sitter y regex fallback) deben emitir el raw conservando la llamada original, no un fragmento. El resolver necesita ver `get_template_directory() . '/inc/foo.php'` completo, no solo `/inc/foo.php`.
- `compass/core.py` - wiring: pasar `theme_root` y `plugins_root` detectados (cuando el stack es WordPress) al `PathResolver`.

**Criterio de cierre:** atlas de un proyecto WP resuelve `wp_enqueue_script('main', get_template_directory_uri() . '/js/main.js')` como edge hacia `{theme_root}/js/main.js`. `dynamic_deps` de WordPress se reduce o se elimina por completo.

**Dependencias:** RES-002 ✅, SCN-003 ✅ (ya completados).

**Estimado:** ~150-200 líneas - ~120 en `path_resolver.py`, ~30 en scanners (preservar raw completo), ~30 en config schema + wiring en core.

---

## NET-022 - Network Externals (Level 2)

**Responsabilidad:** Detecta llamadas HTTP salientes con URL literal (no dinámica) y las emite como nodos `[EXTERNAL:<host>]` del grafo, cubriendo el caso donde un proyecto habla con un servicio externo sin usar un SDK con nombre reconocible (ej. `fetch('https://api.openai.com/v1/…')` en vez de `import { OpenAI } from 'openai'`).

**Origen:** el modelo de 3 categorías acordado con Beto necesita dos niveles de detección externa. Level 1 (GRF-021) cubre SDKs por nombre de import. Level 2 (NET-022) cubre llamadas HTTP directas. Level 3 (URLs dinámicas con variables) queda fuera de alcance - requiere resolución semántica más profunda y se trata como extensión futura de SEM-020.

**Cambios en:**

- `mapper_config.json` - dos adiciones:
  1. Nueva sección `http_loaders` - funciones HTTP cuyo primer argumento es URL:
     ```json
     "http_loaders": {
       "javascript": ["fetch", "axios.get", "axios.post", "axios.put", "axios.delete", "axios.patch"],
       "python":     ["requests.get", "requests.post", "requests.put", "requests.delete", "urlopen", "httpx.get", "httpx.post"],
       "php":        ["wp_remote_get", "wp_remote_post", "wp_remote_request", "curl_init", "file_get_contents"]
     }
     ```
  2. Extender `external_services[*]` con campo opcional `match_urls` (lista de regex de host):
     ```json
     { "label": "Anthropic", "match": ["anthropic", ...], "match_urls": ["api\\.anthropic\\.com"] },
     { "label": "OpenAI",    "match": ["openai", ...],    "match_urls": ["api\\.openai\\.com"] },
     { "label": "Supabase",  "match": ["supabase"],       "match_urls": [".*\\.supabase\\.co"] }
     ```
- `compass/scanners/*.py` - para cada call que matchee un nombre en `http_loaders[language]`, extraer el primer argumento. Si es string literal:
  - parsear host con `urllib.parse.urlparse`
  - si el host matchea algún `external_services[*].match_urls[*]` → usar el `label` configurado
  - si no matchea → usar el host crudo como label (`[EXTERNAL:api.example.com]`)
- Si el argumento no es string literal (es variable, concatenación con variable, template literal con interpolación) → **no emitir nada**. Ese caso es territorio SEM-020 / Level 3, no NET-022.
- `compass/core.py` (`finalize`) - emite el nodo `[EXTERNAL:<label>]` usando la misma lógica de unificación y shape que GRF-021 (cilindro rojo). Un solo nodo por label, múltiples edges entrantes desde distintos sources.

**Criterio de cierre:** sobre un proyecto que haga `fetch('https://api.openai.com/v1/messages', …)` sin SDK, el atlas muestra nodo `[EXTERNAL:OpenAI]` con edge desde el archivo que hace el fetch. Si hay un fetch a un host no configurado (`fetch('https://api.mixpanel.com/…')`), aparece como `[EXTERNAL:api.mixpanel.com]`.

**No cubre (por diseño):** `fetch(API_BASE + '/messages')`, `fetch(\`${baseUrl}/users\`)`, `requests.get(config.api_url)`. Esos casos requieren resolver el valor de la variable - se trata como extensión futura sobre SEM-020.

**Estimado:** ~60 líneas - ~35 en scanners (extracción de arg + parseo de host), ~10 en config schema, ~15 en `finalize` (emisión reutilizando lógica GRF-021).

---

## AST-024 - Asset filtering en grafo

**Responsabilidad:** Descartar del grafo las referencias a assets binarios (imágenes, fonts, media, documentos) para que no aparezcan como nodos del `.dot`; se registran en `metadata.assets` del nodo fuente como información contextual pero no estructural.

**Origen:** uso real de Compass sobre ETCA post-Sesión 5.5 - el grafo mostraba imágenes (`logo.png`, `bg.webp`) como nodos, ensuciando la visualización. Son referencias reales del HTML/CSS, pero no son dependencias estructurales - no cambian según lógica, no se "importan" en sentido de código. Encajan como **categoría 4** del modelo GRF-021 (archivo repo / external-SDK / builtin-stdlib / **asset**).

**Cambios en:**

- `mapper_config.json` - nueva sección `asset_extensions` (lista configurable):
  ```json
  "asset_extensions": [
    ".jpg", ".jpeg", ".png", ".webp", ".svg", ".ico", ".gif", ".bmp",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp4", ".webm", ".mov", ".avi",
    ".mp3", ".wav", ".ogg",
    ".pdf", ".zip", ".tar", ".gz"
  ]
  ```
- `compass/core.py` (`finalize`) - al emitir nodos/edges, si el target resuelve a un archivo con extensión en `asset_extensions`:
  1. **No emite** nodo ni edge en el `.dot`.
  2. Acumula el path en `metadata.assets` del nodo source en `atlas.json`:
     ```json
     { "metadata": { "assets": ["img/logo.png", "fonts/roboto.woff2"] } }
     ```

**Criterio de cierre:** corrida sobre ETCA - el `.dot` no contiene nodos con extensión de asset; `metadata.assets` poblado en los nodos HTML/CSS que los referencian.

**Nota sobre scope de `ignore_*` (hallazgo 2026-04-16):** los campos `ignore_folders`, `ignore_files`, `ignore_patterns` del config filtran SOLO el índice de archivos a escanear (qué archivos pasan por el scanner), pero NO filtran las **referencias outbound** que los scanners emiten. Una imagen llega al grafo porque el HTML la referencia vía `<img src>`, aunque esté en `ignore_patterns`. AST-024 cubre el caso de assets binarios por defecto (extension match automático), pero el fix **completo** requiere que la emisión de nodos/edges en `finalize()` también respete `ignore_patterns` e `ignore_files`: si un target resuelto matchea contra ellos, descartar edge y acumular en `metadata.filtered_refs` del nodo fuente. Ampliar el scope de AST-024 para cubrir esto.

**Estimado:** ~30 líneas - ~10 en config, ~20 en `finalize` (check de extensión + acumulación en metadata). Sumando el fix del scope `ignore_*`: +15 líneas (cruce de target resuelto contra ignore_patterns/ignore_files).

**✅ Implementado en Sesión 6B (2026-04-16):**
- Nueva sección `basal_rules.asset_extensions` en `mapper_config.json` con 25 extensiones por defecto (imágenes, fonts, media, documentos, archivos comprimidos).
- Filtros en `_scan_file::core.py`: si `kind=="file"` y target matchea `asset_extensions` → `metadata.assets`; si matchea `ignore_files`/`ignore_patterns` → `metadata.filtered_refs`. Helpers: `_is_asset_target(rel_path)` y `_is_ignored_target(rel_path)`.
- Ambos filtros se cuentan como unique `(source_file, filtered_target)` pairs para que el reporting sea consistente entre first-run y cached-replay (el cache dedupa por target).
- Cache de fingerprints extendido con `metadata_assets` y `metadata_filtered_refs` por archivo - el replay cacheado restaura ambos metadatos + suma al `_filter_counts` para que el user vea el mismo número de edges filtradas en run #1 vs run #2.
- Atlas expuesto: `atlas.graph_filters = { asset, ignored, self_edge, ignore_outbound, rendered_edges, raw_edges }` - observabilidad completa sin necesidad de parse manual del `.dot`.
- Smoke en ETCA: 63 edges hacia assets filtradas del `.dot`; 270 outbound raw → 207 atlas edges (63 assets escondidos). `metadata.assets` poblado en todos los HTML (`favicon.ico`, `favicon-192.png`, `assets/aula-preview.webp`, etc.).
- En Compass self-scan: 1 edge filtrada por `ignore_patterns` (`compass/scanners/__init__.py` por el pattern `__init__.py` en `basal_rules.ignore_patterns`). El archivo `__init__.py` sigue apareciendo como "ignorado al scanear", pero edges hacia él ya no aparecen en el grafo.
- Nota operativa: el filtro de asset solo aplica a `kind=="file"` (target resuelto al repo). URLs absolutas a imágenes externas (`https://cdn.x.com/img.png`) caen en `kind=="discard"` → `metadata.calls`, no se filtran por este path (son asset y external - PLAN separa esa preocupación para NET-022).

---

## DEF-025 - Definitions cleanup (stack → language)

**Responsabilidad:** Rediseñar `mapper_config.json::definitions[]` para que sean **language-based** (Python, PHP, JavaScript, HTML) y no **stack-based** (WordPress, Tauri, Modern-Web). Los stacks específicos quedan únicamente en `stack_markers` para detección; las patterns inbound/outbound se agrupan por lenguaje para evitar falsos positivos en identity detection.

**Origen:** Sesión 5 + uso real sobre ETCA. El atlas generaba identities como `"Tauri-Desktop-App-JS"` en un proyecto HTML+PHP que **no usa Tauri**. Causa en `core.py:743`: cualquier `definition` cuyo pattern inbound matchee incrementa `tech_scores` sin validar que el stack del archivo sea coherente con el `stack` declarado en la definition. Como las definitions actuales son stack-based, una regex genérica de Tauri/Modern-Web matchea contra JS vanilla y suma puntos a un stack que no aplica.

**Cambios en:**

1. **`mapper_config.json`** - rediseñar `definitions[]`:
   - De ~8 entries stack-based (`WordPress-Development`, `Tauri-Desktop-App-JS`, `Modern-Web`, `Vanilla-Web-Stack-PHP`, etc.)
   - A 4-5 entries language-based:
     ```json
     "definitions": [
       { "name": "Python-Patterns",     "language": "python",     "tier": "regex_fallback", "patterns": { "inbound": [...], "outbound": [...] } },
       { "name": "PHP-Patterns",        "language": "php",        "tier": "regex_fallback", "patterns": { "inbound": [...], "outbound": [...] } },
       { "name": "JavaScript-Patterns", "language": "javascript", "tier": "regex_fallback", "patterns": { "inbound": [...], "outbound": [...] } },
       { "name": "HTML-Patterns",       "language": "html",       "tier": "regex_fallback", "patterns": { "inbound": [...], "outbound": [...] } }
     ]
     ```
   - Patterns específicas de frameworks (WP hooks, Tauri invoke, React imports) se detectan **solo vía `stack_markers`** y/o el detector de stack, NO vía inbound patterns que alimenten `tech_scores`.
2. **`compass/core.py` (`_scan_file` / `tech_scores`)** - agregar **guardián de contexto**: una identity se genera a partir de un inbound match solo si el stack del archivo (según `stack_map`) es compatible con el stack declarado. Si la definition es language-based (no declara stack), el guardián valida por lenguaje. Regla: `tech_scores` no se incrementa si `stack_map[file] ∉ definition.compatible_stacks` (o `definition.language ≠ file_language` para language-based).

   **Nota de uso del guardián (GAP-005, documentado 6C):** si el usuario en `compass.local.json` declara una definition local con campo `stack: "X"` (o lista `stacks: [...]`), el guardián limita esa definition a archivos cuyo `stack_map[rel_path]` matchea X. Caso de uso: patterns scope-restringidas a un subárbol (ej. una carpeta `plugins/` donde el user quiere inbound regex custom del stack X sin contaminar el resto del proyecto). Hoy ninguna definition basal declara `stack` - language-only basta. El hook está disponible para overrides user.
3. **`compass/scanners/regex_fallback.py`** - consumir el nuevo shape language-based (DEF-017 ya filtraba por `language`; refactor aprovecha ese filtro).
4. **Quarantine:** mover el `mapper_config.json` v2 (pre-cleanup) a `.quarantine/.legacy-v1/mapper_config.v2-pre-def-025.json` según la convención del proyecto.

**Criterio de cierre:** atlas de ETCA ya no muestra identities falsas (`Tauri-Desktop-App-JS`, `Modern-Web`) en un proyecto HTML+PHP. Smoke test sobre Compass mismo confirma que `Python-Patterns` sigue detectando outbound/inbound reales.

**Estimado:** ~80 líneas + refactor de config - ~30 en rediseño de `mapper_config.json`, ~30 en `core.py` (guardián en `_scan_file`/`tech_scores`), ~20 en `regex_fallback.py` (adaptar a nuevo shape).

**✅ Implementado en mini-sesión 5.7 (2026-04-16):**
- 5 entries language-based en `definitions[]`: `Python-Patterns`, `PHP-Patterns`, `JavaScript-Patterns`, `TypeScript-Patterns`, `HTML-Patterns`. Outbound patterns consolidadas por lenguaje; inbound vacíos a propósito (ver abajo).
- Decisión no-obvia: **todos los inbound patterns se movieron a vacío**. Los 4 patterns que existían (`invoke\(`, `listen\(`, `emit\(`, `"use client"`, `export default function`, `const ... = ... =>`, `addEventListener`, `function\s+...`, `@app\.route`, `def tool_`, `def skill_`, `add_action`, `register_rest_route`) no son señales de *identity* de lenguaje - son señales de *stack/framework* que ya cubre `stack_markers`. Mantenerlos como inbound language-scope reintroduciría el mismo ruido que DEF-025 vino a resolver (matches cross-stack sumando score a identities equivocadas). Trade-off aceptado: perdemos el canal "regex custom → identity" a cambio de identities limpias. Si en el futuro un stack legítimo necesita inbound regex, se agrega con campo `stack` declarado y el guardián nuevo `_definition_applies_to_stack` lo limita al subárbol correcto.
- **Guardián de contexto** (`compass/core.py`): nueva función `_definition_applies_to_stack(definition, file_stack)` complementa a `_definition_applies_to_language`. Llamada desde `_scan_file` antes de sumar `tech_scores`. Backward-compat total: si una definition local del usuario declara `stack`, sólo aplica a archivos cuyo `stack_map[rel_path]` matchee; si no declara nada, aplica a todos (el filtro de lenguaje sigue activo).
- `regex_fallback.py` **sin cambios** - el shape `patterns.inbound/outbound` ya era consumido igual por el scanner; la consolidación vivió entera en la config + el guardián en `core.py`.
- Quarantine: `mapper_config.json` pre-DEF-025 guardado en `.quarantine/.legacy-v1/mapper_config.v2-pre-def-025.json`.
- Smoke: Compass auto-scan → identity única `Python` (fuente `stack_markers`), 12 outbound edges. ETCA (`c:/.../etca.com.ar`) → identities `Vanilla-Web-Stack` + `WordPress-Development` (ambas `stack_markers`), 270 outbound edges (254 HTML + 12 PHP + 4 JS). **Cero identities falsas** tipo Tauri/Modern-Web.

---

## EDG-023 - Edge labels semánticos

**Responsabilidad:** Etiquetar cada edge del `.dot` con el **tipo de dependencia real** (`require`, `include`, `import`, `src`, `href`, `action`, `fetch`, `enqueue`, `use`) en lugar del label genérico `"calls"` que hoy lleva toda flecha. Opcionalmente, asignar color por tipo para lectura rápida del grafo.

**Origen:** observación de Beto sobre el `.dot` generado de ETCA - todas las flechas con `[label="calls"]`, lo cual desperdicia información semántica que los scanners ya tienen (al capturar `require foo.php` saben que es `require`; al capturar `<img src="bar.png">` saben que es `src`). El label uniforme hace más difícil leer el grafo y diagnosticar patterns.

**Cambios en:**

- `compass/scanners/base.py` - cambio de interfaz: los scanners devuelven **tuplas `(target, edge_type)`** en lugar de solo `str`. Tipos esperados: `require`, `include`, `import`, `src`, `href`, `action`, `fetch`, `enqueue`, `use` (extensible vía config).
- `compass/scanners/python.py` - `extract_imports` devuelve `(module, "import")`.
- `compass/scanners/treesitter.py` - mapear node type → edge_type (PHP: `require_expression` → `"require"`, `include_expression` → `"include"`; JS: `import_statement` → `"import"`, `call_expression` donde callee es `fetch` → `"fetch"`).
- `compass/scanners/regex_fallback.py` - cada pattern en `definitions[].patterns.outbound` declara su `edge_type`. Shape sugerido:
  ```json
  "outbound": [
    { "regex": "require(?:_once)?\\s+[A-Z_]+\\s*\\.\\s*'([^']+)'", "edge_type": "require" },
    { "regex": "wp_enqueue_script\\s*\\(\\s*['\"][^'\"]+['\"]\\s*,\\s*['\"]([^'\"]+)['\"]", "edge_type": "enqueue" }
  ]
  ```
- `compass/scanners/html.py` - mapear atributo capturado → edge_type (`src` → `"src"`, `href` → `"href"`, `action` → `"action"`).
- `compass/core.py` (`finalize`) - al emitir el `.dot`, usar `edge_type` como label de la edge: `"source.php" -> "target.php" [label="require"]`.
- `mapper_config.json` - sección opcional `graph.edge_colors` para colorear edges por tipo:
  ```json
  "graph": {
    "edge_colors": {
      "fetch":   "red",
      "require": "black",
      "src":     "blue",
      "import":  "darkgreen",
      "enqueue": "purple"
    }
  }
  ```

**Criterio de cierre:** `.dot` de ETCA muestra labels semánticos distintos por tipo de edge; si `edge_colors` está configurado, las flechas aparecen coloreadas por tipo en `graph.html`.

**Estimado:** ~60 líneas - ~15 en `scanners/base.py` + adaptación de los 4 scanners (~25), ~10 en `finalize` (usar `edge_type` como label), ~10 en `mapper_config.json` (shape de patterns con `edge_type` + sección `edge_colors` opcional).

**✅ Implementado en Sesión 6B (2026-04-16):**
- Interfaz extendida en `compass/scanners/base.py`: `extract_imports` ahora devuelve `list[str | tuple[str, str]]`. Helper público `normalize_edge_item(item) → (target, edge_type)` + constante `DEFAULT_EDGE_TYPE="use"` para backward-compat con scanners legacy que devuelvan plain strings.
- `PythonScanner`: emite `(target, "import")` (único edge_type posible para Python imports).
- `HtmlScanner`: tabla extendida `_HTML_ATTR_PATTERNS = [(regex, edge_type), ...]` - emite `"src"` para `<script src>`/`<img src>`/`<iframe src>`/`<video src>`/`<audio src>`/`<source src>`, `"href"` para `<link href>`/`<a href>`, `"action"` para `<form action>`, `"fetch"` para `fetch('...')` inline.
- `RegexFallbackScanner`: acepta patterns como `str` (legacy) o `dict {"regex": "...", "edge_type": "..."}` (nuevo). `_extract_pattern_fields(pat)` normaliza. Las 5 definitions de `mapper_config.json` se migraron al shape dict con edge_types explícitos (`include`, `require`, `enqueue`, `import`, `fetch`).
- `TreeSitterScanner`: mapping `_NODE_TYPE_EDGE[lang][node_type] → edge_type` - PHP `require_expression` → `"require"`, JS `import_statement` → `"import"`, etc. Fallback a `DEFAULT_EDGE_TYPE` si un node_type no está mapeado.
- Core: `_register_edge(src, tgt, kind, edge_type=None)` firma extendida; edges viven ahora en `self._edges` como `list[tuple(src, tgt, edge_type, kind)]` en lugar de strings `.dot` pre-formateados. La emisión final al `.dot` se hace en `graph_emitter.build_dot_content` con color por `edge_type` vía `graph.edge_colors` del config.
- Cache incremental extendido con `edge_types: {target: edge_type}` por archivo para replay cacheado sin re-scan.
- Smoke en ETCA: el `.dot` muestra 4 edge_types distintos (`fetch`, `href`, `require`, `src`) con 4 colores distintos vs. el anterior donde todas eran `[label="calls", color="red"]` uniformes. Subgrafo `cluster_legend` auto-listando los tipos realmente presentes.
- Trade-off: edges duplicadas con mismo `(src, tgt, edge_type)` se dedupan en el `.dot` (una sola línea por tripla). Si un mismo par `src→tgt` tiene 2 edge_types distintos (raro - ej. un archivo PHP con `include` y `require` al mismo target), se emiten 2 líneas visualmente distintas. Correcto.

---

## FIX-026 - UX fixes pre-6

**Responsabilidad:** Dos fixes chicos de experiencia de uso descubiertos en la corrida real post-Sesión 5.5, a resolver antes de entrar a Sesión 6.

**Origen:** feedback directo de Beto tras la mini-sesión 5.5.

### Parte (a) - Template UX de `compass.local.json`

El `compass.local.json` autogenerado por `core.py` en la primera run, aunque ya incluye `_comment` y `_ignore_help`, todavía no es suficientemente ilustrativo para que un usuario nuevo sepa cómo usarlo sin leer el PLAN.

**Cambios en:**
- `compass/core.py` (generación del template `compass.local.json`) - agregar **ejemplos fake pero realistas** de cada campo editable, con comentarios `"_example_..."` adyacentes explicando cuándo usarlo. Ejemplo:
  ```json
  {
    "_comment": "Overrides locales de este proyecto. Todo campo debajo puede borrarse si no aplica.",
    "dynamic_deps": {
      "_example_simple": "declara un archivo que se carga dinámicamente y no puede inferirse por regex",
      "_example_entry":  "src/autoload.php -> 'loads src/modules/*.php'",
      "// example": "includes/autoload.php": "loads src/modules/*.php"
    },
    "ignore_files": {
      "_example_when": "archivos individuales a excluir del análisis (vendor específico, tools de terceros)",
      "// example":    ["scripts/vendor/third-party/index.php"]
    },
    "ignore_patterns": {
      "_example_when": "globs para excluir masivamente (minificados, bundles)",
      "// example":    ["*.min.js", "*.bundle.js", "*.map"]
    }
  }
  ```
  Si el shape final no admite claves duplicadas, usar `_example_*` como keys hermanas al campo real en vez de `// example`.

### Parte (b) - Diagnóstico punto 7 (APIs sin inbound)

En el atlas de ETCA, los archivos `api/*.php` no muestran inbound desde el HTML/JS del frontend, aunque existen referencias reales:
- HTML: `<form action="api/admin-login.php">`, `<a href="api/...">`
- JS: `fetch('/api/products.php')`, `fetch('api/cart.php')`

**Tarea de diagnóstico:**
1. Confirmar si el scanner captura estas referencias (revisar `compass/scanners/html.py` y el scanner JS / regex_fallback).
2. Confirmar si llegan al resolver y con qué resultado:
   - ¿Se resuelven al archivo real (`api/products.php`)?
   - ¿Se descartan como root-relative no mappeado?
   - ¿Caen en la categoría `external` de GRF-021 por no matchear nada?
3. Revisar `_resolve_html` (`fetch` literal en HTML no existe, pero `action=` y `href=` sí deberían resolverse).
4. Revisar `_resolve_js` (el `fetch('/api/x.php')` - ¿trata el leading-slash como root-relative al `project_root`?).
5. Revisar `_classify_outbound` en `core.py` (responsable de la partición en 3 categorías GRF-021) - ¿está descartando el resolve válido?

**Posibles causas a verificar:**
- Leading-slash en `/api/x.php` no se está resolviendo a `project_root/api/x.php`.
- La pattern JS de `fetch(…)` no captura el string literal como outbound.
- El `_classify_outbound` aplica un filtro que descarta targets relativos sin chequear si existen en el repo.

**Cambios esperados (a confirmar post-diagnóstico):**
- Fix chico en `compass/path_resolver.py::_resolve_html` o `::_resolve_js` si el resolver descarta un input válido.
- Ajuste en `compass/core.py::_classify_outbound` si la clasificación está mal priorizada (p.ej. external antes que repo file).

**Criterio de cierre:** en el atlas de ETCA, los `api/*.php` muestran inbound desde el HTML (`index.html` → `api/admin-login.php` vía `action`) y desde el JS (archivo que hace `fetch` → `api/products.php` vía `fetch`). Cuenta de huérfanos `api/*` baja a 0.

---

## TIER-035 - Jerarquía visual de externals  - ✅ DONE (Sesión 9 · 2026-04-17)

**Responsabilidad:** Clasificar los nodos `[EXTERNAL:*]` del grafo en 4 tiers semánticos (`stdlib` / `package` / `service` / `wrapper`) para que la visualización transmita jerarquía y naturaleza del external, en vez de ser una bolsa plana con un solo color. Post-Sesión 8, NET-022 + NET-022b + NET-023 densificaron los externals (URLs por host, wrappers HTTP custom, auto-promoción de imports) - la señal ahora está ahí, falta exponerla visualmente.

**Origen:** feedback post-Sesión 8. Con NET-022 cada service externo aparece por host real (`[EXTERNAL:api.openai.com]`, `[EXTERNAL:api.anthropic.com]`), con NET-023 cada SDK (`[EXTERNAL:requests]`, `[EXTERNAL:fs]`, `[EXTERNAL:anthropic]`) se auto-promueve, y con NET-022b se detectan wrappers custom (`apiReq`, `apiCall`). El grafo resultante tiene muchos más nodos externos pero sin jerarquía - un usuario no puede distinguir de un vistazo "built-in del lenguaje" de "servicio de red" de "wrapper interno del proyecto".

**Cambios en:**

- `mapper_config.json` - mecanismo de detección de stdlib vs package:
  - Decisión abierta: heurística basada en archivos de manifiesto (`requirements.txt`, `package.json`, `composer.json`) detectados en la raíz del proyecto; fallback a listas conocidas de stdlib por lenguaje si el manifiesto no está. A resolver en la sesión.
  - Nueva sección `graph.external_tier_colors` (u similar) con mapping tier → color. Defaults propuestos:
    ```json
    "external_tier_colors": {
      "stdlib":  "#9ca3af",  // gris neutro, oculto por default vía external_include_stdlib
      "package": "#60a5fa",  // azul suave (dependencias instaladas)
      "service": "#a78bfa",  // violeta destacado (URLs externas / match_urls)
      "wrapper": "#f59e0b"   // ámbar/distintivo (http_loaders custom)
    }
    ```
- `compass/core.py` (`finalize`) - al emitir nodos `[EXTERNAL:*]`, agregar campo `tier` al shape en `atlas.json`:
  ```json
  { "id": "[EXTERNAL:OpenAI]",    "tier": "service" }
  { "id": "[EXTERNAL:apiReq]",    "tier": "wrapper" }
  { "id": "[EXTERNAL:anthropic]", "tier": "package" }
  { "id": "[EXTERNAL:os]",        "tier": "stdlib" }
  ```
  Lógica de clasificación:
  1. Si el nodo proviene de un match en `external_services[*].match_urls[*]` (NET-022) → `service`.
  2. Si el nodo proviene de una entry en `http_loaders` declarada como wrapper custom (NET-022b) → `wrapper`.
  3. Si el nombre del external (primer segmento del import) está en la lista de stdlib del lenguaje → `stdlib`.
  4. Sino → `package`.
- `compass/graph_emitter.py` + `compass/templates/graph.html.tpl` - mapear `tier` del external a color del nodo. Opcional: leyenda embebida en HTML como panel fijo (top-right) listando los 4 tiers con su color.

**Decisiones abiertas (a resolver en la sesión):**
- ¿Detección de stdlib automática via archivos de manifiesto (confiable, pero agrega I/O en analyze) o listas hardcoded por lenguaje en `mapper_config.json` (simple, pero requiere mantenimiento)?
- ¿Leyenda embebida en HTML siempre visible, togglable, o ausente (colores auto-explicativos con tooltip)?

**Criterio de cierre:** sobre un proyecto con mezcla (ej. level2agent-engine con `requests`, `anthropic`, `api.openai.com`, `apiReq`), el `graph.html` muestra cada external en su color de tier. Filtro `external_include_stdlib=false` (de NET-023 post-fix) sigue funcionando sin cambio. Nodo pintado con tier `service` se distingue visualmente de uno `package` sin ambigüedad.

**No cubre (por diseño):** cambio de layout físico del grafo (forces, agrupamiento por tier) - solo colores y opcional leyenda. El clustering espacial queda para una iteración futura si aparece necesidad.

**Estimado:** ~50 líneas - ~15 en clasificación en `finalize`, ~10 en config schema + defaults, ~25 en renderer (mapping + leyenda opcional).

**Dependencias:** NET-022 (`match_urls` ya implementado), NET-022b (`http_loaders` wrappers ya implementado), NET-023 (auto-promoción ya implementada - aporta la base de nodos `package`).

**Asignación:** NIVEL 8.5, mini-sesión junto a GRAPH-036 (afinidad de archivos: ambos tocan `graph_emitter.py` + template HTML).

---

## GRAPH-036 - Highlight de entry points  - ✅ DONE (Sesión 9 · 2026-04-17)

**Responsabilidad:** Detectar los entry points del proyecto (archivos que son puntos de arranque ejecutables: `if __name__ == '__main__'` en Python, `main`/`bin`/`scripts.start` en `package.json`, `index.php` en raíz de plugin/tema, archivos referenciados desde `.bat` o shell scripts en raíz) y resaltarlos visualmente en el grafo HTML para que destaquen del resto de los nodos.

**Origen:** uso real de Compass - hoy los entry points se renderizan iguales al resto de archivos del repo (mismo color, mismo size, misma forma). En un grafo denso con 50+ nodos, el usuario pierde el punto de entrada y tiene que buscarlo manualmente. Resaltarlo visualmente da al grafo una "estrella polar" inmediata.

**Cambios en:**

- `compass/scanners/*.py` - detección por lenguaje:
  - **Python:** scanner Python marca archivos que contengan el bloque `if __name__ == "__main__":` como entry point. Adicionalmente, archivos referenciados desde un `.bat` o `.sh` en la raíz del proyecto se marcan como entry point por referencia externa.
  - **JavaScript/TypeScript:** leer `package.json` (si existe en raíz) y extraer paths de `main`, `bin` (puede ser string u objeto), y `scripts.start` (si contiene referencia directa a un archivo, ej. `"start": "node server.js"`).
  - **PHP:** archivos `index.php` en la raíz del proyecto (plugin, tema, o proyecto custom). No hacer match sobre `index.php` en subdirectorios - solo raíz.
- `compass/core.py` (`analyze` + `finalize`) - agregar metadata en `atlas.json`:
  ```json
  "entry_points": ["architect_compass.py", "compass.bat", "server.js"]
  ```
- `compass/graph_emitter.py` + `compass/templates/graph.html.tpl` - al emitir un nodo cuyo path aparece en `atlas.entry_points`, aplicar estilo distintivo:
  - borde dorado de 3-4px (vs. 1px default)
  - `size` +1rem respecto al default del tier
  - opcional: símbolo ★ o emoji de corona prefix en la etiqueta del nodo
- `mapper_config.json` - nueva sección `graph.entry_point_size_boost` configurable (default `"1rem"`); borde dorado también configurable vía `graph.entry_point_border_color` (default `"#fbbf24"`).

**Decisiones abiertas (a resolver en la sesión):**
- ¿Un solo entry point destacado (el "principal") o todos los detectados? Propuesta: todos, sin límite - si hay 3 CLI entry points (ej. `compass.bat`, `architect_compass.py`, `architect_symbols.py`), los 3 destacan.
- ¿El size boost es relativo al tier (stdlib/package/service/wrapper si son external) o absoluto? Para entry points solo aplica a archivos del repo (kind="file"), no a externals - no hay cruce con TIER-035.
- ¿Símbolo ★ en la etiqueta, o solo estilo visual (borde + size)? Propuesta: estilo visual default; símbolo configurable vía `graph.entry_point_label_prefix` (default `""`).

**Criterio de cierre:** sobre Architect_compass self-scan, el `graph.html` muestra `architect_compass.py` y `architect_symbols.py` con borde dorado y size boost - se distinguen del resto de los nodos sin necesidad de buscar. Sobre level2agent-engine, `cerbero.py` aparece destacado. Sobre ETCA (WordPress), los `index.php` de raíz de plugin/tema aparecen destacados.

**No cubre (por diseño):** no cambia el layout físico (posición de los nodos en el canvas) - solo estilo visual. La heurística es conservadora: un archivo es entry point solo si hay señal clara (`__main__`, `package.json:main`, `index.php` raíz); no se intenta inferir entry points por topología del grafo.

**Estimado:** ~60 líneas - ~25 en detección en scanners (Python + JS/TS + PHP), ~10 en `finalize` (agregar `entry_points[]` al atlas), ~15 en renderer (estilo visual), ~10 en config schema + defaults.

**Dependencias:** independiente. Puede correr en paralelo con TIER-035 dentro de la mini-sesión 8.5 (tocan los mismos archivos pero zonas distintas: TIER-035 altera shape del external y su color; GRAPH-036 altera shape del file y su border/size).

**Asignación:** NIVEL 8.5, mini-sesión junto a TIER-035 (afinidad de archivos: ambos tocan `graph_emitter.py` + template HTML + `mapper_config.json::graph.*`).

---

## FILTER-037 - Revisar política de filtrado content-vs-functional en HTML

**Responsabilidad:** Revisar y refinar la política hardcoded que Session 8 dejó en `compass/scanners/html.py` - actualmente excluye `<a href>` en todos los casos y emite solo URLs de `<script src>` / `<link href>` / `<img src>` / `<iframe src>` / `form action` / media. La asunción es que `<a href>` es siempre "content" (navegación) y no dependencia estructural. Hay que validar esa premisa con casos reales y decidir si la política necesita ajuste.

**Origen:** cierre de Session 8. El filtro resolvió el ruido inmediato (45 edges externos eliminados en ETCA - linkedin/schema.org/sitemaps.org/whatsapp/instagram) pero la regla "siempre filtrar `<a href>`" es gruesa. Beto dejó explícito: *"la politica de links filtrados en html la vamos a tener que revisar despues"*.

**Escenarios a revisar:**
- **Navegación interna del proyecto:** `<a href="/about">`, `<a href="./dashboard.html">` - son dependencias estructurales reales entre páginas. Hoy se descartan junto con los externos de contenido.
- **Links internos absolutos al mismo dominio:** `<a href="https://etca.com.ar/cursos">` - para un proyecto con subpáginas que se linkean entre sí, saber qué página linkea a qué es topología estructural, no contenido.
- **Anchor tags con `download`/`target`:** `<a href="manual.pdf" download>` - funcional (descarga), no navegación pura.
- **Hrefs que apuntan a APIs/endpoints:** `<a href="/api/export.php">` - funcional.

**Opciones a evaluar en la sesión:**
1. **Distinguir href interno vs externo** - emitir `<a href>` solo si la URL es relativa o del mismo host del proyecto (requiere conocer el host del proyecto, que hoy no está modelado). Descartar hrefs a dominios externos.
2. **Config por extensión/patrón** - `<a href>` emitidos solo si terminan en extensiones listadas (`.php`, `.html`, `.pdf`, sin extensión implica endpoint) o match regex de paths internos.
3. **Flag de config** - `html_scanner.include_anchor_hrefs: false` con opción a activarlo por proyecto para casos donde la navegación importe.
4. **Mantener política actual** - si el overhead de refinar supera el beneficio, dejar como está y documentar la limitación explícitamente.

**Criterio de cierre:** decisión tomada y documentada. Si se implementa, smoke sobre ETCA debe distinguir links internos (que reaparecen como edges funcionales) de links de contenido a sitios externos (que siguen descartados).

**No cubre (por diseño):** no modifica la política de filtrado de `localhost` / RFC 1918 (esa seguirá hardcoded - es dev noise inequívoco).

**Estimado:** ~30 líneas si la decisión es opción 1 o 2. ~5 líneas si es opción 4 (solo doc). Sesión principalmente de análisis + decisión.

**Dependencias:** ninguna técnica. Se puede correr en cualquier momento post-Sesión 8.

**Asignación:** NIVEL post-8, sin slot asignado aún. Candidato natural para mini-sesión después de TIER-035 + GRAPH-036, o bundle con iteración futura de refinamiento de externals.

---

## REF-033 - Factorización de `core.py` (pre-CLI-015)

**Responsabilidad:** Reducir `compass/core.py` de ~2000 líneas (proyectado post-sesión 10) a <800 líneas, separando responsabilidades en módulos hermanos. Pura reorganización - el pipeline público (`analyze()` + `finalize()`) mantiene firma y comportamiento idénticos.

**Motivación:** `core.py` viene creciendo monótonamente desde MOD-000. Cierre de Sesión 7: 1781 líneas (~3× el hard limit del proyecto). Sesiones 8-10 sumarían ~150 líneas más en wiring de NET/CONS. Entrar a CLI-015 con un `core.py` de 2000 líneas complica el refactor del entry point (hay que razonar sobre boundaries que no existen como módulos). Precedentes exitosos de factorización: `compass/metrics.py` (Sesión 6A) y `compass/graph_emitter.py` + `compass/templates/graph.html.tpl` (Sesión 6C) + `compass/validation.py` + `compass/templates/compass.local.md.tpl` (Sesión 7).

**División propuesta (a validar en la sesión):**
- `compass/pipeline.py` - orchestration de `analyze()` y `finalize()`, scan loop, wiring de scanners + path_resolver + stack_detector + metrics + graph_emitter + validation.
- `compass/outbound_resolver.py` - `_classify_outbound`, `_resolve_outbound_node`, `_is_asset_target`, `_is_ignored_target`, lógica de clasificación repo-file / external / builtin.
- `compass/template_io.py` - `_LOCAL_TEMPLATE`, `ensure_local_template()` (ya partido en `_ensure_local_json` + `_ensure_local_help_md`), load/write del template markdown.
- `compass/core.py` (residual) - solo la clase `ArchitectCompass` como fachada que orquesta los módulos anteriores.

**Criterio de cierre:**
- Smoke test sobre Architect_compass self-scan: `atlas.json` pre-refactor === post-refactor byte-a-byte (o diff explicado en el reporte). Mismo número de files, relevant_files, orphans, cycles, health score, edges. Mismos warnings de VAL-014.
- Smoke test sobre level2agent-engine + ETCA: mismos atlas byte-a-byte.
- Ningún archivo de los 4 supera 600 líneas.
- Todos los imports público siguen funcionando (`from compass.core import ArchitectCompass` debe seguir siendo la API pública - si hace falta mantener re-exports, se hace explícito en `core.py`).

**Riesgos conocidos:**
- `core.py` tiene estado compartido entre `analyze()` y `finalize()` (`self.atlas`, `self.files`, `self.nodes`, `self.edges`, etc.). El split por módulos puros implica pasarlos explícitamente o mantener la clase `ArchitectCompass` como propietaria del estado y delegar en funciones top-level. Decisión de la sesión: preferir funciones puras que reciben/devuelven dicts sobre métodos con `self`, salvo cuando el costo de la firma larga supere el beneficio.
- Cache de scanner (`get_scanner()` con `id(config)`) - mantener intacto, no moverlo ni renombrarlo.
- Fingerprint cache (INC-008) - mantener wiring intacto.

**Estimado:** 0 líneas netas nuevas (puro movimiento). Trabajo real: ~50 líneas modificadas para resolver imports cruzados + ajustes de firma de funciones que pasan a puras.

**Asignación:** NIVEL 11.5 (entre SYM-004 y CLI-015). Un único agente, dedicación exclusiva - zona hot del código. Fuera de esta sesión no debe haber ningún ID de feature en paralelo ni commits concurrentes sobre `core.py`.

---

## Sesión 9 - Cierre (2026-04-17)

**TIER-035** - implementado. `_classify_outbound` devuelve ahora `tier` en cada clasificación external; precedencia `service > wrapper > package > stdlib` (con `_tier_rank` para evitar degradación en segundos registros). URL literal → `service` por default (aunque el host no esté en `match_urls` del config - señal de red externa). Imports via `external_services[*].match` → también `service`. Auto-promote (NET-023) y unify legacy → `package`, con check adicional de `_is_python_stdlib` (→ `stdlib`) y `graph.external_wrappers` (→ `wrapper`). Config nueva: `graph.external_tier_colors`, `graph.external_wrappers` (por lenguaje + `any`). Leyenda del HTML se puebla dinámicamente con los tiers realmente presentes en el run.

**GRAPH-036** - implementado. Nuevo método `_detect_entry_points()` corre al final de `analyze()` antes de `run_audit`. Cubre Python (`__main__`), `.bat`/`.sh` en raíz (parseados con regex `_SCRIPT_REF_RE` que captura rutas con extensión conocida), `package.json` en raíz (`main`/`bin`/`scripts.start`), y `index.{php,html,htm}` en raíz (extendí más allá de solo PHP porque ETCA es un sitio HTML estático sin index.php). `atlas.entry_points` es lista ordenada de paths posix.

**Hallazgos / desvíos:**
- **Cache invalidation silencioso** - el cached replay de `_apply_cached_scan` no tenía acceso a la `classification["tier"]` original, y el intento de re-derivar tier desde el display label perdía señal (URL hosts sin match en `external_services.match_urls` caían a `package`). Fix: persistir `self._external_node_tiers` global en `.map/fingerprints.json` y consumirlo en replay (`self._cached_external_tiers`). Esto es information-preserving 100%, no requiere re-derivar.
- **`index.php` → `index.{php,html,htm}`** - la spec original decía solo `index.php` para PHP. Lo extendí a HTML estático (index.html/htm) en root para cubrir ETCA (sitio vanilla sin index.php). El criterio se mantiene conservador: solo raíz, no subdirs.
- **No regresión observada en los 3 proyectos** (ver smoke tests abajo). La "caída" aparente en level2 (62.11 → 55.74) es pre-existente - ocurrió antes de esta sesión (ver snapshot `20260417_0148_level2agent-engine.json` con health=55.74 ya).
- **Líneas netas añadidas** - ~180 en core.py (TIER-035 ~60, GRAPH-036 ~120), ~50 en graph_emitter.py, ~55 en template. Total ~285. Dentro del presupuesto combinado (50+60 estimados → real ~285 por lo bien anidado del cache invalidation + entry point detection across 4 filetypes).

**Smoke tests:**

| Proyecto | health antes | health después | nodes antes/después | entry_points | externals (unique) | tiers distintos | Notas |
|---|---|---|---|---|---|---|---|
| Architect_compass (self) | 73.09 | 73.09 | 15 / 15 | `architect_compass.py` | 1 | 1 (service) | Sin regresión. |
| level2agent-engine | 55.74 | 55.74 | 16 / 17 | `cerbero.py`, `cerbero-setup/dashboard/server.py` | 13 | 2 (package×6, service×7) | +1 file (test_crb103… no relacionado a esta sesión). Health idéntica. |
| etca.com.ar | 60.51 | 60.51 | 96 / 96 | `index.html` | 18 | 1 (service×18 - todos URL literal en HTML) | Sin regresión. |

**No cubre (intencional):** `<a href>` filter policy (FILTER-037, pospuesto por directiva de sesión). El filtro Session 8 queda vigente tal como está.

**Estimado:** parte (a) ~20 líneas de template. Parte (b) diagnóstico (0 líneas, solo análisis) + fix variable 5-40 líneas según causa raíz identificada.

---

## Mini-Sesión 10.5 - WP Loader Gaps (2026-04-17)

**Origen:** Beto corrió `compass --full` sobre ETCA tras S10. SEM-020 captura `wp_enqueue_*` correctamente (29 edges desde `functions.php`), pero `header.php`/`footer.php` quedaron sueltos y varios templates aparecían como orphans. El diagnóstico REDO (`session10-diagnosis-sem020-etca-REDO-20260417.md`) identificó 3 gaps de cobertura SEM-020 + 1 ticket nuevo fuera de scope.

**Fixes implementados (todos retro-compatibles con SEM-020 existente):**

1. **Zero-arg loader calls (`arg: 0` + `path_template`)** - `get_header()`, `get_footer()`, `get_sidebar()`, `comments_template()` se declaran con `arg: 0` + `path_template: "{theme_root}/header.php"` (y similares). El resolver saltea extracción de argumento y usa el template directo con token expansion (`{theme_root}`, `{plugins_root}`, `{source_dir}`).
2. **Variantes con argumento (`path_template_with_arg`)** - las mismas funciones aceptan opcionalmente un string para sufijo (`get_header('alt')` → `header-alt.php`). Se agregó `path_template_with_arg: "{theme_root}/header-{arg}.php"` en el spec: si hay literal string Y existe el template con arg, se sustituye `{arg}` con el valor. Variables o expresiones complejas caen al template por default (conservador).
3. **`locate_template([...])` con array literal (`accepts_array: true`)** - el scanner expande el array al emitir sentinels: un sentinel por cada string del array. Si el array tiene variables o es dinámico, bail out (no se emiten edges - preferimos no adivinar). Soporta sintaxis `[...]` y `array(...)` de PHP.
4. **Regex de loader (`build_loader_call_regex`)** - no requirió cambios. La regex ya matchea cuerpos vacíos (`get_header()`) porque el patrón `(?:[^()]|\([^)]*\)){0,4000}?` acepta 0 caracteres. Verificado inline.

**Archivos tocados:**
- `mapper_config.json` - +4 entries en `loader_calls` (get_header/get_footer/get_sidebar/comments_template) + `accepts_array: true` en locate_template + note extendido.
- `mapper_config.example.json` - sincronizado 1:1.
- `compass/path_resolver.py` - +38 líneas: nueva rama `arg: 0` en `_resolve_loader_call` + helper `_resolve_zero_arg_loader` (maneja `path_template` + `path_template_with_arg`).
- `compass/scanners/regex_fallback.py` - +50 líneas: helper module-level `_expand_loader_body` (expansión de arrays) + parámetro `loader_specs` + wiring en emisión de sentinels.
- `compass/scanners/treesitter.py` - +6 líneas: `self._loader_specs` + import del helper + wiring gemelo en emisión de sentinels.
- `compass/scanners/__init__.py` - +2 líneas: pasar `lang_loaders` al `RegexFallbackScanner` como `loader_specs`.

**Nuevo ticket creado:** `RES-003` (WP Template Hierarchy Auto-detect) para archivos como `index.php`, `front-page.php`, `single-{cpt}.php` que WordPress auto-carga por convención. No es bug de SEM-020 - está fuera de su scope (calls explícitas). Acordado con Beto como ticket independiente, no bloquea CLI-015.

**Smoke tests:**

| Proyecto | health antes | health después | header.php inbound | footer.php inbound | nuevos edges | orphans antes/después | Notas |
|---|---|---|---|---|---|---|---|
| etca.com.ar | 66.53 | 66.10 | 0 → 13 | 0 → 13 | +50 (≈28 de get_header/get_footer + 22 colaterales de revalidación) | 19 → 17 (-2 de temas) | relevant/total saltó 82.29% → 94.79%. El leve -0.43 de health es por dead_exports (header/footer ahora son "nodos live" sin outbound - orphans mejora, dead_exports baja; es el trade-off correcto de mapear correctamente, no regresión). |
| Architect_compass (self) | 74.84 | 78.30 | n/a | n/a | +1 (`compass/scanners/treesitter.py → regex_fallback.py` por nuevo import `_expand_loader_body`) | -1 | +3.46 - side-effect positivo del nuevo import, no regresión. |
| level2agent-engine | 48.69 | 48.69 | n/a | n/a | 0 | 0 | Sin cambios (no tiene WP). |

**Archivos de ETCA sin afectar:** `single-*.php`, `archive-*.php`, `index.php`, `front-page.php`, `page-*.php` siguen como orphans - son los que RES-003 va a cubrir (template hierarchy). Correcto que sigan así hasta implementar ese ticket.

**Hallazgos / desvíos:**
- El archivo `sensei/archive-message.php` tiene 2 edges a header.php (comment + call real). Es un "falso doble" que el regex del scanner captura porque no ignora comentarios PHP. No es regresión (mismo comportamiento que SEM-020 preexistente); eventualmente un tree-sitter PHP más estricto lo resolvería, pero no es scope de S10.5.
- `get_sidebar()` no se usa en ETCA - 0 inbound nuevos. Declarado igual para cobertura WP estándar.
- ETCA no usa `locate_template([...])` hoy; el fix de arrays quedó verificado con test unitario in-process (smoke directo sobre `_expand_loader_body` y `PathResolver._resolve_zero_arg_loader`).

**Líneas netas añadidas:** ~96 (dentro del budget de 60-100).

**No cubre (delegado a RES-003):** jerarquía de templates WP por URL (single/archive/page-slug/taxonomy/home). Issue tracked.

**Cache:** `fingerprints.json` de los 3 proyectos invalidado al correr smoke (`rm -f` antes del full rescan). No se rompió el formato.

---

## Gaps conocidos post-S10.5 - formalizados como tickets

Los 3 gaps informales detectados por Beto revisando grafos post-S10.5 fueron promovidos a tickets con ID formal (sesión 11 post-SYM-004). Ver tabla principal y sección "NIVEL opcional" de la secuenciación:

- **LOAD-038** - Python filesystem loaders (`open` / `json.load` / `Path.read_text`). Afecta level2agent-engine y agente_facundo (JSON sueltos).
- **WEB-039** - Framework static path resolution (Flask / FastAPI / Express static mounts). Afecta agente_facundo (dashboard JS sueltos).
- **REG-040** - Framework dynamic registration (`register_blueprint` / `include_router` / Django `include()`). Afecta agente_facundo (dashboard/api/*.py sueltos).

Los tres son independientes entre sí, no bloquean CLI-015 ni REF-033, y entran en "NIVEL opcional" (ejecutar post-CLI cuando un proyecto concreto los requiera).

---

## Sesión 19 - 18A/18B/18C/18D (2026-04-19)

**Investigación + Refactors**: Agente_facundo diagnostic, BUG-3 (18B), tier ambiguous design (18C), compact JSON design (18D).

**ITEM 1:** Investigación Agente_facundo sin modificar código.
- **1.1 gestor.py:** AMBIGUOUS legítimo. Grep: 0 invocadores. CLI standalone → marcar `tier: ambiguous` en ITEM 3.
- **1.2 dashboard/server.py:** Flask entry point (`if __name__`). 0 invocadores en codebase → AMBIGUOUS.
- **1.3 Patrón genérico:** No implementable sin hardcoding. Tier ambiguous (ITEM 3) lo resuelve.

**ITEM 2 (18B) - COMPLETADO:** Fix `__init__.py` router classification.
- **Bug encontrado:** `_compute_orphans()` en `compass/pipeline.py` línea 479 solo chequeaba si archivo era **target** de edges, no **source**.
- **Impacto:** `compass/__init__.py` (que re-exporta módulos) era orphan aunque emitía 5 edges outbound.
- **Fix:** Incluir AMBOS `internal_sources` Y `internal_targets`. Línea 479: `is_orphan = rel_path not in internal_participants` (donde `internal_participants = internal_sources | internal_targets`).
- **Resultado:** Orphans 26 → 13 (legacy en `.quarantine` intacto). `compass/__init__.py` removido. Health score +9.45 (76.45 → 85.9).
- **Efectos:** Cualquier archivo con outbound edges ahora reconocido como participante (no orphan).

**ITEM 3 (18C) - DISEÑADO:** Tier "ambiguous" classification system.
- **Criterio:** File es ambiguous si (1) sin inbound, (2) no entry_point, (3) escaneado OK, (4) no legacy.
- **Diferencia orphan/ambiguous:** Orphan = "NO participa" (rojo, error). Ambiguous = "no pude determinar" (amarillo, aviso).
- **Casos de uso:** gestor.py, dashboard/server.py (ambos Agente_facundo), split_dashboard.py, log_proyecto.py.
- **Implementación pendiente (próxima sesión):**
  - Nuevo campo `tier: {connected|ambiguous|legacy}` en atlas.json nodes.
  - Lista `summary.ambiguous[]` (paralelo a `orphans[]`, `entry_points[]`).
  - Lógica: `if is_dynamic: tier='dynamic' elif is_participant or is_entry: tier='connected' else: tier='ambiguous'`.
  - HTML graph: colores (ambiguous=naranja, orphan=rojo, connected=verde).
  - Validar en 3 projects.

**ITEM 4 - DISEÑADO:** Cleanup atlas.compact.json para LLM.
- **Problema 1:** Sentinels `@@LOADER@@` leakean a `metadata_consolidated.calls` (ej. `@@LOADER@@open@@LOADER@@"mapper_config.json"`).
  - **Fix:** Transformar a `file_loads: ["mapper_config.json"]` en consolidator.py.
- **Problema 2:** Stdlib imports inundan `calls` (pathlib:Path, typing:Any, os, re, json, __future__:annotations).
  - **Fix:** Filtrar stdlib usando `compass/stdlib_filter.py` existente.
- **Problema 3:** Campos vacíos siempre (ej. `filtered_refs: []` → omitir).
- **Implementación pendiente (próxima sesión):** Transformar sentinels, filtrar stdlib, omitir campos vacíos. Meta: 30-50% reducción sin perder info.

**Archivos modificados:**
- `compass/pipeline.py` - líneas 448-487 (_compute_orphans: fix 18B).

**Archivos nuevos:**
- `SESSION_LOG.md` - reporte completo de Sesión 19 A/B/C/D.

**Próximas sesiones (19B/19C):**
- **19B:** Implementar ITEM 3 (tier ambiguous).
- **19C:** Implementar ITEM 4 (compact JSON cleanup).
- **Validación:** 3 projects → nuevos tiers + medición de reducción compact.

---

# Backlog 2026-06-12 — tickets nuevos (post-S23)

Origen: reporte l2ae (2026-04-21), `feedback_css_dependency_tracking.txt` (2026-05-11), `FEEDBACK_LSP.txt` (2026-05-08, Opción C) y `SPRINT-0B-TREE-SITTER.txt` (2026-06-12, D-106 de normalizacion-claude). El índice de pendientes vive en [roadmap.md](roadmap.md); acá va el detalle.

## TSD-045 — Tree-sitter como tier default (JS/TS/PHP) ✅completada (S24)

- **Origen:** FEEDBACK_LSP.txt Opción C, formalizada como D-106 en normalizacion-claude (Sprint 0.b).
- **Tarea:** invertir la relación actual de tiers: hoy `TreeSitterScanner` es Tier 2 opt-in y regex es el camino normal; pasa a ser **default cuando el binding está instalado**, con `RegexFallbackScanner` como fallback automático ante `ImportError` o grammar faltante (mismo patrón defensivo actual, default invertido).
- **Dependencias opcionales (verificadas en PyPI 2026-06-12):** `tree-sitter` 0.25.2 + `tree-sitter-language-pack` 1.8.1 (sucesor confirmado de tree-sitter-languages, API `get_parser`). **Pin: `tree-sitter-language-pack>=1.4,<2.0`** — D4 (decisión Beto 2026-06-12): hay un rewrite v2 venidero con API nueva; dejar el pin documentado acá como recordatorio para **verificar periódicamente** cuándo sale v2 y portar a conciencia, no que un `pip install` lo levante solo y rompa. La promesa zero-install se mantiene: sin instalar nada, Compass funciona igual que hoy.
- **Piso Python (D1, decisión Beto 2026-06-12):** el tier tree-sitter pide Python ≥3.10 (lo exigen ambos paquetes); el core de Compass sigue 3.8+. En 3.8/3.9 el binding no instala y se cae a regex automáticamente (= comportamiento de hoy). Beto corre 3.11 + 3.13, sin fricción.
- **Defaults universales (D2, decisión Beto 2026-06-12):** mover `language_grammars` de `mapper_config.json` a `compass/defaults.py` (remoción directa, no convivencia) — universales del lenguaje van en código, config solo para opt-in custom (regla `feedback_universal_defaults_vs_optin`).
- **Lenguajes:** JS/TS/PHP primero (hoy regex frágil). Python queda en `ast` (ya riguroso). Go/Rust/Ruby/Kotlin: grammars disponibles, interés futuro no bloqueante.
- **Contexto de diseño (D-109):** NO construir cliente LSP propio — la profundidad semántica puntual (hover/definition/references) la dan los LSPs del harness Claude Code; Compass cubre lo complementario: barrido estructural del repo completo desde cualquier cwd.
- **Archivos:** `compass/scanners/treesitter.py` (queries por lenguaje), `compass/pipeline.py` (dispatch de tiers).
- **Salvedad WordPress (no-regresión):** la capa WP no se ve afectada por el switch — `compass/wordpress.py` (theme roots, template hierarchy, theme-implicit de RES-003) opera por estructura de filesystem y nombres de archivo, no por el scanner PHP. Lo que SÍ hay que preservar son los detectores semánticos sobre contenido PHP (SEM-020 `wp_enqueue`, PHP-018/018b `require/include` con `__DIR__`/variable): tree-sitter reemplaza el camino genérico regex de imports/símbolos, NO esos passes — deben coexistir o portarse. Validación de no-regresión: ETCA en TSD-048.

## TSD-046 — Cobertura HTML/CSS vía tree-sitter ✅completada (S24)

- **Hoy:** CSS se skipea; HTML va por regex (HTML-019).
- **Tarea:** queries tree-sitter para HTML y CSS, integradas al dispatch de TSD-045.
- **Dato clave:** no existe html-lsp en el marketplace oficial de Claude Code — tree-sitter en Compass es la **única vía de análisis estructural HTML del ecosistema**. Diferencial a conservar.
- **Sinergia:** el parseo CSS de este ticket alimenta los edges `@import` de CSS-049 (si TSD-046 llega antes, CSS-049 usa tree-sitter; si no, regex).

## TSD-047 — symbols.json enriquecido ✅completada (S24)

- **Tarea:** cuando tree-sitter está activo, enriquecer `symbols.json` con `kind` (function/method/class/property), ranges exactos y firma textual donde la grammar lo permita.
- **Criterio:** mantener la filosofía anti context-blow del compact (`feedback_llm_compact_no_internal_sentinels`) — enriquecer sin inflar.

## TSD-048 — Validación Sprint 0.b + cierre ✅completada (S24)

> **Resultado S24 (2026-06-12):** validado en 3 testigos con venv 3.11 + binding. cerbero_cli (Python control) 115 edges tier ast sin regresión; ETCA (PHP/HTML) 378 edges tree-sitter-pack (vs 8 roto), SEM-020/PHP-018b/NET-022 intactos; clases.etca (TS) 284 edges (vs 0 antes). Bug del loader (`get_parser` Rust → `get_language`+Parser Python) detectado y corregido en la re-validación. APROBADO sin bloqueantes. **Sprint 0 completo → desbloquea Sprint 1 (beto-agents-core) en normalizacion-claude.**

- **Tarea:** comparar output tree-sitter vs regex actual sobre repos reales del workspace: cerbero_cli (Python de control — no debe cambiar, sigue en ast), etca.com.ar (PHP/HTML), clases.etca.com.ar (TS).
- **Cierre:** al terminar, avisar en sesión de normalizacion-claude para actualizar su ROADMAP/subsistema 11 — Sprint 0 completo, desbloquea Sprint 1 (beto-agents-core).

## CSS-049 — Edges de dependencia CSS (HTML→CSS, CSS→CSS) 🔲pendiente

- **Origen:** `feedback_css_dependency_tracking.txt` (2026-05-11, level2agent-engine post-modularización de dashboard.css en 17 archivos). Evidencia: 36 nodos `.css` en atlas.json, 0 edges `<link`, 0 edges `@import`.
- **Paso 0 — diagnóstico (regla `feedback_validate_plan_vs_filesystem`):** verificar si HTML-019 ya emite el edge `<link rel="stylesheet">` y lo que falla es solo la resolución del path `/static/css/...` (URL servida por framework). En ese caso esa mitad del problema es WEB-039 y este ticket se reduce a `@import` + warnings.
- **Scope:**
  - `@import` CSS→CSS en sus 4 variantes: `url('...')`, `url("...")`, `'...'`, `"..."` — resolución relativa al archivo CSS donde aparece.
  - `<link rel="stylesheet" href="...">` y `<script src="..." [type="module"]>` HTML→recurso — resolución relativa al HTML.
  - Warning para CSS/JS no alcanzado por ningún HTML (candidato a orphan verdadero).
- **Casos borde:** `<style>` inline no trazable (ignorar); `url()` en propiedades (background-image, font-face) NO es `@import`; templates con engine (Jinja): parsear solo `href` literales.
- **Edges:** label `loads` (HTML→recurso) e `imports` (CSS→CSS), consistente con EDG-023.
- **Testigo:** level2agent-engine (`cerbero-setup/dashboard/static/css/` — 17 archivos, cascada de @import).
- **Estimación del reporte:** 4-8 hs.

## SER-050 — Sanitizar sentinels @@LOADER@@ en atlas.json 🔲pendiente

- **Origen:** reporte l2ae — `"@@LOADER@@path_literal@@LOADER@@\".claude/results"` aparece crudo en atlas.json; parece artefacto de parseo intermedio sin limpiar.
- **Tarea:** transformar los sentinels antes de serializar atlas.json — mostrar el path limpio o moverlos a campo aparte `path_literals: [...]`. `atlas.compact.json` ya está limpio desde CMPCT-043; falta aplicar el mismo criterio al atlas completo.

## CLI-051 — Flag --version 🔲pendiente

- **Origen:** reporte l2ae — no hay `--version` en `compass --help`; útil para issues/reports.
- **Tarea:** `--version` en el parser global, con fuente única `compass/__init__.py::__version__`.
- **✅ Resuelto (S24, 2026-06-12):** `__version__ = "0.1.0"` en `compass/__init__.py` (fuente única, exportado en `__all__`); flag `--version` con `action="version"` leyendo de ahí. **Decisión de versión (Beto): 0.1.0, NO 1.0.0** — la herramienta es funcional pero rústica/pre-estable, la banda 0.x comunica eso honestamente. Fix lateral necesario: `_normalize_default_argv` prependeaba `scan` ante `--version` (mandaba `["scan","--version"]` al subparser que no lo conoce) → se sumó `--version` a los flags que el parser principal maneja solo. `compass --version` → `compass 0.1.0`, exit 0.

## CLI-052 — Summary de scope en compass symbols 🔲pendiente

- **Origen:** reporte l2ae — bajar de 988→352 funciones (filtro .venv) es correcto pero el usuario lo lee como regresión.
- **Tarea:** línea de summary al final del subcomando: `scanned N files, excluded X .venv / Y __pycache__ / Z .git`.

## PKG-053 — Colisión de nombre compass/ vs compass.bat 🔲pendiente

- **Origen:** reporte l2ae — en Linux/Mac/Git Bash con el repo en PATH, el directorio `compass/` (paquete Python) se resuelve antes que `compass.bat`, dejando el binario no-invocable.
- **Opciones evaluadas:**
  - (a) Renombrar el paquete (`compass_pkg/`) — invasivo: toca todos los imports, PYTHONPATH y la receta de `feedback_compass_exec_no_bat`.
  - (b) `compass.cmd` para Windows + shim documentado en README para entornos POSIX — barato pero convive con la colisión.
  - (c) Entry point `console_scripts` vía packaging (pip genera el ejecutable `compass` real) — resuelve de raíz y **converge con la iniciativa CLI/PyPI** (memoria `project_roadmap_cli`).
- **Resolución pendiente** — inclinar hacia (c) si la profesionalización a PyPI se activa; mientras tanto (b) como mitigación documentada no cuenta como cierre del ticket.

## INIT-054 — Edge implícito de package-import en Python (`__init__.py` sin re-exports) 🔲pendiente

- **Origen:** hallazgo de Beto (2026-06-12) en level2agent-engine: `cerbero_cli/commands/__init__.py` aparece suelto en el atlas pese a que el paquete se usa intensivamente (`main.py` importa los 11 subcomandos con `from .commands.X import cmd_X`).
- **Causa:** en runtime Python ejecuta `pkg/__init__.py` al importar cualquier submódulo, pero estáticamente el import statement referencia solo al submódulo (`commands/edit.py`), nunca al `__init__.py`. INIT-032 ya traza re-exports (`__init__.py` que exporta símbolos consumidos por otros), pero un `__init__.py` vacío o sin re-exports queda con 0 inbound → suelto.
- **Tarea:** en el resolver de imports Python, al resolver `from a.b.c import x` emitir además edges implícitos importador → `a/__init__.py` y `a/b/__init__.py` (toda la cadena de paquetes — es lo que Python ejecuta realmente). Label sugerido: `package_init` o reutilizar `imports`.
- **Testigo:** level2agent-engine (`cerbero_cli/commands/__init__.py` debe pasar a connected).
- **Estimación:** ~30-60 líneas en el resolver AST Python + validación en los 4 projects testigo.

## QRY-055 — Subcomando `compass impact <archivo>` (blast radius) 🔲pendiente

- **Origen:** research `researcher-graphify-vs-compass-20260609-v2.md` (§6 ventajas, §8 plan de adopción): Graphify tiene un gap documentado (issue #1184) en primitivas de retrieval estructurado para agentes (`callers(X)`/`blast_radius(X)` con JSON). Compass tiene medio camino hecho — el atlas ya guarda `connectivity.outbound` (edges `src -> tgt`) + `symbols.json`. Falta exponer la query. Beto: caso de uso de alto interés (otras herramientas lo tienen; ésta es la que aprovecha la data ya existente).
- **Qué es blast radius:** dado un archivo X, "qué se rompe si lo toco" = el conjunto de archivos que dependen de X, directa y transitivamente (los inbound, recursivo). Inverso del outbound.
- **Tarea:**
  - Subcomando nuevo `compass impact <archivo>` (5º subcomando, junto a scan/symbols/init/graph) — o modo de `graph`.
  - Lee el atlas existente (no re-escanea si hay uno fresco), invierte `connectivity.outbound` para construir el índice inbound, y hace un BFS/DFS transitivo desde X.
  - Salida: lista de dependientes con profundidad (directos = nivel 1, transitivos = niveles 2+), count total. **JSON para agentes** (caso implementer/reviewer evalúa radio antes de editar) + **tabla rich para humano**.
  - Considerar: dirección configurable (`--downstream` = quién depende de X (default, el blast radius clásico) vs `--upstream` = de qué depende X). Manejar ciclos (no loop infinito — reusar la coloración de CYC-011).
- **Estimación:** ~80-150 líneas (subcomando + inversión de índice + traversal + 2 formatters). La data ya existe, es exponer + recorrer.
- **Sinergia:** encaja con el caso "agentes architect/implementer/reviewer" del research §7-B y con la iniciativa CLI/PyPI (`project_roadmap_cli`).

## MCP-056 — Analizar y decidir expansión de Compass a MCP server 🔲pendiente

- **Origen:** research graphify §6 (Graphify tiene MCP server propio) + decisión de Beto (2026-06-12) de evaluarlo formalmente.
- **Naturaleza:** ticket de ANÁLISIS Y DECISIÓN, no de implementación. El entregable es un documento con la decisión (sí/no) y su fundamento.
- **A evaluar:**
  - **A favor:** para el caso agente, un MCP es más eficiente en contexto que el flujo actual (Bash + leer `atlas.compact.json` entero) — el agente pide queries puntuales (`impact X`, `callers X`, `health`) y recibe solo esa respuesta. El costo de contexto del MCP es solo la descripción de tools (nombre+params+1-2 líneas), no la data.
  - **En contra:** choca con **D-107** (normalizacion-claude: "Compass es CLI, no plugin"). Reabrir esa decisión. Mantener dos superficies (CLI + MCP) es más superficie de mantenimiento. El write_bridge ya cubre escritura; ¿hace falta otro MCP solo-lectura?
  - **Punto medio a considerar:** un MCP fino que envuelva el CLI (no reimplementa nada, solo expone `scan`/`impact`/`symbols` como tools que llaman al CLI por debajo) — bajo costo, no duplica lógica.
- **Dependencia:** si la decisión es sí, QRY-055 (blast radius) es la primera tool natural a exponer; conviene cerrarla antes.
- **Decisión:** pendiente. Documentar en una nota cuando se resuelva (igual que D-107/D-109 viven en normalizacion-claude/DECISIONS.md).

## DOC-057 — Sincronizar documentación tras Sprint 0.b 🔲pendiente

- **Origen:** auditoría de doc-sync (2026-06-12) tras cerrar el Sprint 0.b. Reporte: `~/.claude/results/reviewer-compass-doc-sync-audit-20260612-0935.md`. El `--help` del CLI quedó al día; README y docstrings tienen desfases.
- **Desfases a corregir (por severidad):**
  - **ALTA:** README.md documenta `compass --version`, que **NO existe** (es CLI-051, pendiente). Contradicción: o se implementa el flag (cerrar CLI-051) o se saca del README. **Recomendado: resolver DOC-057 junto con CLI-051** — implementar `--version` y dejar el README correcto de una.
  - **MEDIA-1:** README describe la jerarquía tree-sitter como "si está instalado" — ambiguo; el código lo usa como **default/first-choice** cuando el binding está disponible (cambio del Sprint). Reescribir para reflejar default + fallback regex automático.
  - **MEDIA-2:** README no menciona que `symbols.json` subió a **VERSION 1.1** con campos `kind`/`range`/`signature` (TSD-047). Documentar.
  - **BAJA-1:** docstring de `compass/scanners/treesitter.py` — describir el comportamiento nuevo (default cuando hay binding, loader vía `pack.get_language`).
  - **BAJA-2:** docstring de `architect_symbols.py` (raíz) dice "regex fallback (tree-sitter opcional)" — ahora tree-sitter es default, no opcional. Actualizar.
- **Lo que SÍ está al día (no tocar):** el `--help` del CLI (4 subcomandos, flags), instalación zero-install, config jerárquica, outputs a `.map/`, deps opcionales — todos correctos.
- **Estimación:** ~30-60 min de edición de prosa. Si se hace con CLI-051, sumar el flag `--version` (~20 LOC).

## Nota — reconsideraciones futuras del research (NO tickets, decisión estratégica de Beto)

Material del research que NO se convierte en ticket pero queda anotado para decisión futura:

- **MCP server para Compass:** Graphify expone su grafo vía MCP. Para el caso agente sería MÁS eficiente en contexto que el flujo actual (Bash + leer atlas.compact.json entero), porque el agente pediría queries puntuales (`impact X`, `callers X`) recibiendo solo esa respuesta, no todo el atlas. El costo de contexto de un MCP es solo la **descripción de tools** (nombre+params+1-2 líneas), no la data. PERO choca con **D-107** (normalizacion-claude: "Compass es CLI, no plugin"). Reabrir esa decisión es estratégico, no técnico — diferido a criterio de Beto. Si se activa, QRY-055 (blast radius) sería la primera tool natural a exponer.
- **Exports GraphML / Neo4j / Mermaid — DESCARTADOS:** GraphML (visores Gephi/yEd) sería barato pero feature muerta si no se usan esos programas; ya hay `.dot` + `graph.html`. Neo4j (base de datos de grafos) es overkill brutal para un atlas que cabe en JSON. Mermaid es ilegible para grafos densos de dependencias (espagueti) — el `graph.html` interactivo es superior. No construir salvo demanda real.
- **Multimodal / Pass-3 LLM / community detection / Obsidian export / token compression:** fuera de scope deliberado de Compass (territorio Graphify). El research concluye "híbrido con roles diferenciados", no "Compass copia a Graphify". No construir.

## Actualizaciones a tickets preexistentes (2026-06-12)

- **WEB-039:** segundo testigo detectado — level2agent-engine carga `<link href="/static/css/dashboard.css">` servido por el framework; la resolución del prefix `/static/` → filesystem es exactamente este ticket (evidencia en `feedback_css_dependency_tracking.txt`). Se suma a Agente_facundo (dashboard JS).
- **REG-040:** archivado se mantiene (sin testigo real en portfolio); ahora registrado en la sección "Archivados" del roadmap.