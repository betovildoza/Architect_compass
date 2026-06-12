# SESSION_LOG — Architect's Compass v2

Registro de bugs, desvíos y decisiones tomadas durante la implementación del PLAN.md.

**Cómo se usa:** cada sesión completada por un subagente deja una entrada. Los hallazgos se clasifican como:
- **[GLOBAL]** → va a `topics/*.md` como receta reusable para todos los proyectos.
- **[PROJECT]** → fix local o ajuste de PLAN.md, solo aplica a Compass.
- **[NO-FIX]** → consecuencia estructural esperada, se documenta pero no requiere acción.

El orquestador no aplica fixes automáticamente: presenta la evaluación, el usuario decide.

**Orden:** entradas más recientes arriba.

**Nota de reconstrucción (2026-04-19):** el archivo fue pisado accidentalmente por un subagente antes de ser commiteado (ver hallazgo #5 de Sesión 21). Reconstrucción cruzando tres fuentes: (1) transcripciones JSONL en `~/.claude/projects/c--IA-Workspace-herramientas-Architect-compass/` — de ahí S1–S12 y S13/S14/S15/S16/S18 se recuperaron con el formato `## NIVEL N · Sesión N · ...` intacto; (2) archivo de rescate `SESSION_LOG_RESCATE_17-21.md` producido desde otra sesión activa con los datos crudos de S17, S19, S20 y S21 — esos niveles nunca llegaron al SESSION_LOG con el formato establecido; se reconstruyeron aquí respetándolo y usando las métricas reales del rescate; (3) PLAN.md como guía del orden y scope de los items trabajados.

---

## NIVEL 24 · Sesión 24 · Sprint 0.b — tree-sitter como tier default (TSD-045/046/047/048)

**Fecha:** 2026-06-12
**Subagentes:** `architect_system_design` (diseño), `general-purpose` (implementer + fix loader), `debug_review_code` (review + validación + re-validación). Patrón 3-fases con checkpoint humano de Beto en las decisiones de diseño (D1-D5).
**IDs:** TSD-045 (tree-sitter default JS/TS/PHP), TSD-046 (HTML/CSS), TSD-047 (symbols.json v1.1 enriquecido), TSD-048 (validación). Origen: FEEDBACK_LSP.txt Opción C + SPRINT-0B-TREE-SITTER.txt (D-106 normalizacion-claude).
**Resultado:** OK. Sprint 0.b cerrado. Tree-sitter ejecuta de verdad por primera vez (el binding nunca había estado instalado → siempre caía a regex). Validado en 3 testigos con venv 3.11. Desbloquea Sprint 1 de normalizacion-claude.

### Decisiones de Beto (D1-D5)

- **D1:** piso Python ≥3.10 solo para el tier tree-sitter (core sigue 3.8+; sin binding → fallback regex idéntico a hoy). Beto corre 3.11.
- **D2:** `language_grammars` movido de `mapper_config.json` a `compass/defaults.py` (remoción directa — universales del lenguaje en código).
- **D3:** HTML tree-sitter pasa a default apenas pase paridad (sin sprint intermedio opt-in).
- **D4:** pin `tree-sitter-language-pack>=1.4,<2.0` documentado (hay rewrite v2 venidero con API nueva — verificar periódicamente).
- **D5:** `symbols.json` VERSION 1.1 con campos aditivos `kind`/`range`/`signature`.

### Hallazgos

#### 1. El camino tree-sitter estaba ROTO en silencio desde S4, no solo "no-default"

- **Tipo:** Bug latente expuesto al instalar el binding por primera vez.
- **Manifestación:** tree-sitter figuraba como Tier 2 opt-in desde S4, pero el binding nunca estuvo instalado en la máquina → todo caía a regex vía `ImportError` capturado. Al instalar el venv 3.11 con el binding, el camino real falló: (a) el loader exigía `language()` que las grammars php/ts no exponen; (b) JS/TS emitía el statement completo que `_resolve_js` descartaba → 0 edges internos; (c) PHP-018b vivía solo en regex_fallback.
- **Acción:** el implementer reparó el loader y compartió PHP-018b. Pero introdujo un segundo bug (ver #2).
- **Scope:** `[PROJECT]`. Lección: un tier "opcional" que nunca se ejecutó puede acumular bugs invisibles. La única validación real es ejecutarlo con la dependencia presente.

#### 2. Bug bloqueante: `pack.get_parser()` devuelve Parser Rust incompatible

- **Tipo:** Bug funcional detectado por el reviewer (regresión del 97% — ETCA 8 edges vs 1149 regex).
- **Manifestación:** `treesitter.py:149` usaba `pack.get_parser(lang)`, que devuelve un `builtins.Parser` (binding Rust de tree-sitter-language-pack), NO un `tree_sitter.Parser` de la API Python. `self._parser.parse(data)` lanzaba `TypeError`, tragado por el `try/except Exception: return []` → 0 edges. El bug solo era visible CON el binding presente (architect y primer implementer no lo tenían).
- **Acción:** fix de ~14 LOC — cambiar la Fuente 1 a `pack.get_language()` + `tree_sitter.Parser(lang_obj)` (mismo patrón que la Fuente 2, líneas 200-201). Único archivo tocado: `treesitter.py` (loader + guarda R2 + docstring).
- **Scope:** `[PROJECT]`. ✓ Cerrado. Validado en re-validación.

#### 3. Validación TSD-048 (3 testigos, venv 3.11, binding presente)

- **CONTROL — cerbero_cli (Python):** 115 edges, tier `ast`, sin regresión. Python no usa tree-sitter (decisión D-cerrada: `ast` ya es riguroso).
- **ETCA (PHP/HTML):** 378 edges con tree-sitter-pack (vs 8 roto, ≥ baseline regex). SEM-020 (wp_enqueue), PHP-018b (require/include con __DIR__/variable) y NET-022 confirmados intactos.
- **clases.etca (TS/Next.js):** 284 edges (vs 0 antes del Sprint). Los imports internos TS ahora se capturan — era el gap principal que motivó el Sprint.
- **Scope:** `[PROJECT]`. Veredicto reviewer: APROBADO sin bloqueantes.

#### 4. Dependencias opcionales (verificadas PyPI 2026-06-12)

- `tree-sitter` 0.25.2 + `tree-sitter-language-pack` 1.8.1 (sucesor confirmado de tree-sitter-languages, API `get_language`/`get_parser`). venv del repo en `.venv/` (gitignored). Zero-install intacto: sin el binding, fallback regex idéntico al comportamiento histórico.

#### 5. Versionado formal + sincronización de docs (CLI-051 + DOC-057)

- **Tipo:** Cierre de tickets de Fase C/F en la misma sesión, preparando commit limpio.
- **CLI-051:** `__version__ = "0.1.0"` en `compass/__init__.py` (fuente única, exportado en `__all__`); flag `--version` con `action="version"`. **Decisión de versión (Beto): 0.1.0, NO 1.0.0** — la herramienta es funcional pero rústica/pre-estable; la banda 0.x comunica eso honestamente. `compass --version` → `compass 0.1.0`, exit 0. Fix lateral: `_normalize_default_argv` prependeaba `scan` ante `--version` → se sumó `--version` a los flags que el parser principal maneja solo.
- **DOC-057:** README sincronizado (--version ahora real; jerarquía tree-sitter aclarada como default+fallback; symbols.json v1.1 documentado); docstrings de `treesitter.py` y `architect_symbols.py` actualizados (tree-sitter default, no "opcional"). Auditoría previa que lo detectó: `reviewer-compass-doc-sync-audit-20260612-0935.md`.
- **Scope:** `[PROJECT]`. ✓ Ambos cerrados. No queda string de versión del producto inconsistente en la superficie (README/código/docstrings); las menciones a "v1.0-candidate" solo persisten como contexto histórico en PLAN/roadmap/SESSION_LOG.

---

## NIVEL 23 · Sesión 23 · RES-003 rewrite + theme-implicit extension + NET-022/022b validación

**Fecha:** 2026-04-19
**Subagente:** `debug_review_code` (validación funcional inicial + re-validación post-fix en 4 projects); orquestador directo (assessment de código, diseño del fix, implementación de `find_wp_theme_roots` + theme-implicit, scans de verificación final).
**IDs:** RES-003 cerrado (rewrite + extensión), PHP-018 cerrado (ya cubierto en código, falsa creencia de pendiente), PHP-018b abierto (gap real remanente), NET-022 cerrado (validación), NET-022b cerrado (validación).
**Resultado:** OK. 4 tickets cerrados, 1 ticket nuevo abierto (PHP-018b). Cero regresiones en 3 projects testigo non-WP. ETCA pasa de 1 a 19 entry_points (ambiguous 3→1, health 87.61 estable).

### Hallazgos

#### 1. Narrativa "NET-022/NET-022b pendientes" era falsa - ya estaban en código

- **Tipo:** Auditoría docs vs filesystem.
- **Manifestación:** El prompt de continuación de Sesión 22 indicaba implementar NET-022/NET-022b desde cero. Assessment directo del código reveló que:
  - `compass/scanners/python.py:133-146` tiene AST pass para `http_loaders.python` (requests/urllib/httpx).
  - `compass/scanners/regex_fallback.py:173-178` tiene regex pass para PHP/JS/TS vía `http_regex`.
  - `compass/scanners/html.py:124-134` (FIX-027) escanea inline `<script>` para fetch/axios.
  - `mapper_config.json:253-275` tiene `http_loaders` por lenguaje con cobertura completa (requests.*/fetch/axios.*/wp_remote_*/curl_init/file_get_contents/fopen/urlopen/httpx.*).
  - `external_services.match_urls` con regex por host (Anthropic/OpenAI/Stripe/Supabase/etc.) en `mapper_config.json:276-355`.
  - URL-SCAN pass en los 3 scanners captura URL literales incluso fuera de http_loaders.
- **Acción:** en vez de implementar lo ya hecho, se delegó validación funcional. Subagente corrió scans en 4 projects: level2 18 externals (OpenRouter/Context7/Brave/Gemini), Agente_facundo 32 (Anthropic/OpenAI/ChromaDB), ETCA 18 (Resend/Google/Instagram), self 2 (rich/unpkg). Todos con labels `[EXTERNAL:host]` correctos.
- **Scope:** `[GLOBAL]` - refuerza la regla de Sesión 22: antes de implementar un ticket declarado pendiente en PLAN, validar contra filesystem. El estado en PLAN.md puede estar desalineado con código real (múltiples sesiones superpuestas, pases parciales documentados como diferidos, etc.).
- **Estado:** ✓ Cerrado. NET-022 y NET-022b marcados ✅ en PLAN.md con evidencia en descripción.

#### 2. RES-003 bug crítico - detector solo miraba la raíz, fallaba en ETCA

- **Tipo:** Bug funcional descubierto por validación (0 templates marcados en ETCA, esperados ~12).
- **Manifestación:** `detect_wordpress_project(project_root)` chequeaba markers WP únicamente en la raíz del proyecto escaneado. ETCA tiene el tema en `themes/etca-aula/` (no en raíz) porque el sitio es un híbrido: HTML estático + API PHP + tema WP en subcarpeta. Resultado: detector retornaba `False`, `_detect_and_promote_wp_templates` salía temprano, 0 templates en `entry_points`.
- **Acción:** rewrite de `compass/wordpress_detector.py`:
  - Nueva `find_wp_theme_roots(project_root, max_depth=4)` busca recursivamente carpetas que cumplan el criterio compuesto `style.css + (functions.php|index.php)`. Solo `style.css` no basta (cualquier sitio puede tenerlo).
  - `is_wp_template(rel_path, theme_roots, project_root)` agregado argumento `theme_roots`: además de matchear basename, verifica que `rel_path` esté dentro de algún theme root. Evita falsos positivos tipo `api/legacy/index.php`.
  - `page.php` agregado a `WP_EXACT_TEMPLATES` (faltaba).
  - `detect_wordpress_project` conservado por compat: ahora usa `find_wp_theme_roots` + fallback a markers clásicos (`wp-config.php`, `wp-content/`) para instalaciones WP completas.
  - `finalize.py:_detect_and_promote_wp_templates` usa la nueva API.
- **Validación:** ETCA pasó de 0 a 15 templates marcados (incluye los 2 de `themes/etca-aula/sensei/` que glob recursivo encuentra). 0 archivos API o de raíz marcados por error.
- **Scope:** `[GLOBAL]` - criterio de theme root ("style.css + companion en misma carpeta") es canónico de WP y reusable en cualquier proyecto WP real. No hardcoding específico de ETCA.
- **Estado:** ✓ Cerrado (fix aplicado + validado).

#### 3. Extensión RES-003 - WP theme-implicit entry points

- **Tipo:** Gap funcional secundario identificado por Beto al revisar el grafo post-fix.
- **Manifestación:** Tras el fix principal, los archivos `themes/etca-aula/style.css`, `theme.json` y `functions.php` seguían apareciendo aislados (ambiguous o connected sin entry_point_reason). Motivo: WordPress los carga por convención implícita cuando el tema está activo - ningún PHP del repo los referencia con edge estático. Un scanner puro ve archivos sin inbound.
- **Acción:** extensión del módulo WP con nueva constante `WP_THEME_IMPLICIT_FILES = (style.css, theme.json, functions.php, rtl.css, screenshot.png, screenshot.jpg, readme.txt)`. Nueva función `iter_wp_theme_implicit_paths(theme_roots, project_root)` yields rel_paths de los archivos implícitos existentes. `_detect_and_promote_wp_templates` ahora ejecuta 2 pases: (a) template hierarchy con reason `wp_template_hierarchy`, (b) theme-implicit con reason `wp_theme_implicit`. Helper `_promote_wp_entry` soporta `entry_point_reason` múltiple (string | list) para archivos que matcheen ambos criterios.
- **Validación:** ETCA post-extensión: 16 templates + 3 theme-implicit (`style.css`, `theme.json`, `functions.php`) → entry_points de 1 a 19. Ambiguous 3→1 (solo queda `_shared.css`, que no es parte del tema). Health 87.61 sin cambios (ambiguous no pesa en health). Los 3 projects non-WP siguen estables: Architect_compass 97.57, level2 91.79, Agente_facundo 88.46.
- **Scope:** `[GLOBAL]` - la lista `WP_THEME_IMPLICIT_FILES` refleja convenciones de WordPress core (style.css es enqueued auto, theme.json lo usa FSE, functions.php es incluido en cada load, rtl.css auto-carga si locale RTL, screenshot.* es metadata del admin, readme.txt es el formato del repo oficial). Cero hardcoding específico de ETCA.
- **Estado:** ✓ Cerrado.

#### 4b. PHP-018b cerrado en la misma sesión - fix pragmático captura 4 archivos adicionales

- **Tipo:** Implementación pragmática de gap detectado más temprano en la sesión.
- **Manifestación:** Tras cerrar PHP-018 y abrir PHP-018b como ticket, se decidió implementarlo en la misma sesión. Approach: **no** data-flow genérico, sino detector PHP-específico que cubre el patrón real (`$var = dirname(__DIR__[, N]) . 'literal'` + `require_once $var`).
- **Acción:** nuevo pass en `compass/scanners/regex_fallback.py` con dos helpers:
  - `_collect_php_var_assignments(content)` - extrae asignaciones `$var = dirname(__DIR__[, N]) . 'literal'` o `$var = __DIR__ . 'literal'`, acumulando candidatos por varname. Reasignaciones condicionales (patrón fallback `si no existe A, usar B`) acumulan a lista.
  - `_php_require_var_sentinels(content, file_path)` - detecta `require|require_once|include|include_once $var` y emite un edge por cada candidato asociado al varname. Resuelve `dirname(__DIR__, N)` relativo al archivo fuente (sube N niveles desde `source_file.parent`). PathResolver descarta los que no caen dentro del proyecto.
  - Integración: pass final en `extract_imports`, activado solo si `file_path` termina en `.php` - no afecta lenguajes sin sintaxis `$var`.
- **Resultado inesperado (positivo):** el fix capturó 4 archivos adicionales al gap inicial. `etca_config.php` pasó de 0 inbound edges a 6: api/bootstrap.php + api/oauth-callback.php (los 2 identificados) + blog-post.php + producto.php + sitemap.php + tienda.php (4 archivos extra en la raíz de ETCA que usaban el mismo patrón sin que lo hubiéramos señalado). El patrón `$var = dirname(...) . 'path'` + `require_once $var` es más común de lo que el diagnóstico inicial sugería.
- **Métricas:** ETCA health +0.26 (87.61 → 87.87) por las nuevas edges. Non-WP estables (97.57/91.83/88.46). Delta de rendered edges en ETCA: 275 → 282 (+7 nuevas edges PHP-018b).
- **Scope:** `[GLOBAL]` - el approach (detectar asignaciones PHP con expresiones path-like + resolver en el uso) es PHP-específico pero reusable. El patrón extensible: si aparece otra construcción como `$var = getenv('X') . '/foo'`, se agrega otra variante de asignación al pass; el consumo vía require/include no cambia.
- **Estado:** ✓ Cerrado. PHP-018b marcado ✅ en PLAN.md.

#### 4. PHP-018 ya estaba cubierto - reclasificar como "completada", abrir PHP-018b para el gap remanente

- **Tipo:** Auditoría de código + identificación de gap real.
- **Manifestación:** PLAN declaraba PHP-018 como `🔲diferido` sobre la base de que `PathResolver._resolve_php` no resolvía leading-slash ni `__DIR__ . '…'`. Lectura del código:
  - `path_resolver.py:236` hace `probe = candidate.lstrip("/\\")` - leading-slash cubierto.
  - `path_resolver.py:208-219` usa `_extract_string_literals` + `base_is_file_dir` - `__DIR__ . '/sub/file.php'` cubierto.
  - Validación en ETCA confirma: 13 APIs hacen `require_once __DIR__ . '/bootstrap.php'` y todas resuelven al archivo correcto (edges visibles en el atlas).
- **Gap real descubierto (nuevo ticket PHP-018b):** `api/bootstrap.php` y `api/oauth-callback.php` usan `$config_path = dirname(__DIR__, 2) . '/etca_config.php'; require_once $config_path;` - el `require` dinámico con variable no se captura. `etca_config.php` queda sin inbound. Patrón común en bootstraps PHP reales.
- **Acción:** PHP-018 marcado ✅completada en PLAN.md con evidencia. Nuevo ticket PHP-018b abierto en PLAN.md (🔲pendiente) con approach pragmático propuesto (detectar asignación + expandir require_once con variable). Estimación: 20-40 líneas en scanner PHP.
- **Scope:** `[PROJECT]` - decisión de scope del dominio PHP; patrón de asignación + require dinámico es extensible a otros lenguajes después.
- **Estado:** PHP-018 cerrado, PHP-018b abierto para próxima sesión (decisión del usuario).

#### 5. Gotcha ejecución compass: `python -m compass` no funciona, PYTHONIOENCODING requerido en Windows

- **Tipo:** Gotcha de entorno Windows.
- **Manifestación:** Intentos de ejecutar scans desde sesión:
  - `python -m compass scan <root>` → `ModuleNotFoundError: No module named compass.__main__` (el paquete no tiene `__main__.py`).
  - `python compass/cli.py scan <root>` → `ModuleNotFoundError: No module named 'compass'` (el cwd no está en PYTHONPATH automáticamente).
  - `PYTHONPATH=<repo_root> python compass/cli.py scan <root>` → funciona pero falla con `charmap codec can't encode character '\u2705'` (Windows default codec no soporta emojis que el CLI imprime).
  - Solución final: `PYTHONIOENCODING=utf-8 PYTHONPATH=<repo_root> python <repo_root>/compass/cli.py scan <root>`.
- **Acción:** registrar el approach en el SESSION_LOG. El launcher real `compass.bat` (no versionado, local) presumiblemente setea ambas variables. Para sesiones futuras sin `compass.bat` accesible, usar la forma completa.
- **Scope:** `[GLOBAL]` - probable candidato para un topic `topics/compass_exec_windows.md` si vuelve a aparecer.
- **Estado:** Documentado en este hallazgo.

#### 6. Primer subagente de assessment se colgó sin entregar handoff (bug #40502)

- **Tipo:** Gotcha operativo de subagentes Claude.
- **Manifestación:** Primer briefing enviado a `debug_review_code` para assessment NET-022/PHP-018/RES-003. Subagente arrancó (ID `a459adfcd3c765cea`), devolvió su header de protocolo, pero tras ~15 min de espera no dejó archivo en `.claude/handoff/` ni en `~/.claude/results/`. Verificación con `TaskOutput(task_id, block=false)` retornó `No task found with ID` - el subagente terminó (o fue descartado) sin entregar.
- **Acción:** pivoteo a lectura directa desde el orquestador. Los archivos a auditar eran conocidos (paths explícitos, no exploración abierta) → el costo de delegar no valía la pena. Se completó el assessment con ~5 Read/Grep y se devolvió evidencia inline al usuario. Valoración: cuando los paths son conocidos y el scope es acotado, leer directo es más barato y determinista que reintento de delegación.
- **Scope:** `[GLOBAL]` - regla operativa: si un subagente no devuelve en tiempo razonable Y el trabajo es determinista (no exploración), pivotear a ejecución directa sin reintento.
- **Estado:** ✓ Cerrado.

### Métricas tras esta sesión

| Project | Orphans | Ambiguous | Connected | Entry | Health | Delta health |
|---------|---------|-----------|-----------|-------|--------|--------------|
| Architect_compass | 0 | 1 | 29 | 5 | 97.57 | -0.02 |
| level2agent-engine | 0 | 6 | 18 | 6 | 91.83 | +0.34 |
| Agente_facundo | 0 | 6 | 41 | 7 | 88.46 | 0.00 |
| **ETCA (WP real)** | 0 | 1 | 74 | **19** | **87.87** | nuevo testigo (+0.26 tras PHP-018b) |

ETCA: entry_points de 1 (solo `index.html`) a 19. Distribución: `index.html` + 15 templates WP (wp_template_hierarchy) + 3 theme-implicit (wp_theme_implicit). Rendered edges ETCA: 275 → 282 (+7 edges nuevas del pass PHP-018b capturando 6 inbound a `etca_config.php`).

### Archivos tocados

- `compass/wordpress_detector.py` - rewrite completo. Nuevas funciones `find_wp_theme_roots`, `iter_wp_theme_implicit_paths`, `is_wp_template` scoped. Constantes `WP_THEME_IMPLICIT_FILES`, `WP_THEME_STYLE`, `WP_THEME_COMPANIONS`, `MAX_SCAN_DEPTH`, `_WP_SCAN_IGNORE`. `page.php` agregado a `WP_EXACT_TEMPLATES`. `detect_wordpress_project` y `mark_wp_templates_as_entry_points` conservados por compat.
- `compass/finalize.py` - `_detect_and_promote_wp_templates` reescrito: usa `find_wp_theme_roots` + `is_wp_template` nuevo, ejecuta 2 pases (hierarchy + implicit). Nuevo helper `_promote_wp_entry` con soporte a reason múltiple.
- `compass/scanners/regex_fallback.py` - PHP-018b: helpers `_collect_php_var_assignments` y `_php_require_var_sentinels` + pass final en `extract_imports` activado solo para archivos `.php`. Nuevas regexes `_PHP_VAR_ASSIGN_RE` y `_PHP_REQUIRE_VAR_RE`. Import de `Path` agregado para resolución `dirname(__DIR__, N)`.
- `PLAN.md` - estados actualizados: NET-022 ✅, NET-022b ✅, PHP-018 ✅, PHP-018b ✅ (nuevo ticket resuelto en misma sesión), RES-003 ✅.
- `SESSION_LOG.md` - esta entrada.

### Reportes de subagente

- `~/.claude/results/architect-compass-validation-net022-res003-php018.md` - validación inicial (4 projects) descubriendo el bug RES-003 y gap PHP-018b.
- `~/.claude/results/architect-compass-res003-fix-validation-20260419-2135.md` - re-validación post-fix (sin theme-implicit todavía).

### Pendientes que quedan abiertos al cierre

- **WEB-039** - framework static path resolution. Testigo declarado: Agente_facundo (dashboard JS sueltos). Candidato natural para próxima sesión funcional.
- **REG-040** - multi-framework dynamic registration. **Archivado efectivamente**: tras revisar portfolio (Flask, FastMCP, CLI puros), no hay proyecto testigo donde los imports estáticos no alcancen. Flask de Agente_facundo ya queda conectado por imports estáticos (S21/S22). FastMCP de mcp-write2 usa `@mcp.tool()` en el mismo archivo (registro estático por decorador). Sin testigo real el ticket no se puede validar. Queda dormido hasta que aparezca un proyecto con FastAPI `include_router` o Django `urlpatterns`.
- **ENDP-044** (nuevo, S23) - framework endpoint highlighting. Surgió al evaluar REG-040: el gap real de los frameworks modernos con decoradores estáticos (`@mcp.tool`, `@app.route`, `@router.get`, etc.) no es conectividad, es visualización. Testigos disponibles: mcp-write2 (6 tools), Agente_facundo (Flask blueprints), probablemente level2. Alcance acotado ~80-120 líneas.
- **REF-034** - factorización post-CLI y mover `architect_symbols.py`. Ticket de higiene.
- **CLI-015b** - eliminar monkeypatch de `--no-*` flags. Ticket de deuda técnica.

### Hallazgo bonus al evaluar pendientes

Al buscar testigo para REG-040 en el portfolio, se validó que FastMCP (mcp-write2) NO es FastAPI - comparten estilo decorador pero FastMCP registra tools en el mismo archivo con `@mcp.tool()` (estático), mientras que FastAPI distribuye routers con `include_router()` (dinámico cross-file). Conclusión importante para el ticket: el caso de uso "etiquetar funciones como endpoints de un framework" (ENDP-044) es distinto al caso "resolver registros dinámicos cross-file" (REG-040). El primero cubre más proyectos reales con menos complejidad.

---

## NIVEL 22 · Sesión 22 · Reconstrucción SESSION_LOG + auditoría estados PLAN + cierre

**Fecha:** 2026-04-19
**Subagente:** otra sesión Claude (reconstrucción SESSION_LOG cruzando JSONL + rescate + PLAN); orquestador directo (auditoría de estados PLAN, verificación REG-040 en wild, correcciones de tabla)
**IDs:** ninguno nuevo. Higiene de proyecto: docs reconstruidos, estados PLAN corregidos, scope REG-040 ampliado, prep para sesión limpia.
**Resultado:** OK. SESSION_LOG.md reconstruido (1843 líneas, S1-S21 cubiertas). Estados de PLAN.md corregidos (RES-003 → 🟡código implementado / validación WP pendiente; ORP-1 → ✅completada; REG-040 → 🔲 reabierto con scope multi-framework). `.map/PENDIENTES_v1.0.md` y `SESSION_LOG_RESCATE_17-21.md` borrados (info absorbida).

### Hallazgos

#### 1. Subagente Sesión 21 dejó 3 estados PLAN inconsistentes con el código

- **Tipo:** Auditoría docs vs filesystem.
- **Manifestación:** Verificación directa en filesystem reveló:
  - `compass/wordpress_detector.py` existe → RES-003 estaba `🔲pendiente` en PLAN.
  - `compass/orphan_classifier.py` + `DEFAULT_ORPHAN_PATTERNS` en `defaults.py` existen → ORP-1 estaba `🔲pendiente Sesión 21`.
  - `compass/dynamic_registration.py` NO existe → REG-040 reportado como "implementado" por el agente, pero **no había código**. El reporte del agente fue falso en ese punto.
- **Acción:** marcado RES-003 como `🟡 código implementado, validación WP pendiente` (porque los testigos disponibles no son WP); ORP-1 como `✅completada` con detalle del módulo y patterns; REG-040 verificado en wild antes de re-marcar.
- **Scope:** `[PROJECT]` — regla operativa: cuando un agente reporta implementación, validar contra filesystem antes de aceptar el cierre del ticket en docs.
- **Estado:** ✓ Cerrado.

#### 2. REG-040 verificación in-place — los 10 blueprints ya estaban connected

- **Tipo:** Verificación con `compass scan` real en proyecto testigo + lectura de atlas.
- **Manifestación:** Re-lectura de `C:\IA_Workspace_priv\Agente_facundo\src\dashboard\api\__init__.py` confirmó el patrón:
  ```python
  from .status import bp as status_bp    # import estático
  app.register_blueprint(status_bp)      # registro
  ```
  Scan en Agente_facundo + lectura de `.map/atlas.json` `files` dict: los 10 blueprints (status, llama, skills, mcp, chromadb, filtros, webhook, terminal, logs, backup) están todos `tier=connected`. El `register_blueprint(obj)` no aporta info al grafo cuando el `obj` ya viene por import estático.
- **Acción:** primer intento de cerrar como "innecesario". Beto corrigió: ticket reabre con scope ampliado a casos donde el import estático NO alcanza (FastAPI `include_router`, Django `include()`, Express `app.use`, Laravel `Route::group`, blueprints construidos en runtime). El caso testigo de Flask quedó cubierto por imports estáticos pero el dominio del ticket no.
- **Scope:** `[GLOBAL]` — refuerzo del hallazgo #2 de Sesión 21: cerrar tickets requiere evidencia que cubra el dominio entero, no solo el primer testigo.
- **Estado:** REG-040 reabierto con scope ampliado.

#### 3. SESSION_LOG.md reconstruido de tres fuentes — proceso replicable

- **Tipo:** Recuperación de docs perdidos.
- **Manifestación:** Tras pisado de Sesión 21, el archivo se reconstruyó cruzando: (a) JSONL de `~/.claude/projects/c--IA-Workspace-herramientas-Architect-compass/` para S1–S16 y S18; (b) `SESSION_LOG_RESCATE_17-21.md` (creado por el orquestador en esta sesión desde su historial conversacional para S13–S21); (c) `PLAN.md` como guía de orden y scope de items. El archivo final tiene 1843 líneas con formato `## NIVEL N · Sesión N · ...` consistente para todas las sesiones.
- **Acción:** rescate borrado tras absorción exitosa al SESSION_LOG.
- **Scope:** `[GLOBAL]` — protocolo: si un SESSION_LOG se pierde antes de commit, las tres fuentes mencionadas suelen alcanzar para reconstruirlo si las sesiones pasaron por subagentes con conversación rastreable.
- **Estado:** ✓ Cerrado.

#### 4. Pendientes de detección que Beto marca como prioritarios para próxima sesión

- **Tipo:** Decisión de roadmap explícita del usuario al cierre.
- **Manifestación:** Beto: *"no puede ser que sigamos teniendo pendientes mejoras de deteccion, net022/b hay que hacerlo, res003 y php-018 tambien. tenemos que tener la herramienta de descubrimiento y de definiciones cubriendo los issues que descubrimos."*
- **Items elevados a prioridad para próxima sesión:** NET-022, NET-022b, RES-003 (validación WP), PHP-018, REG-040 (scope ampliado).
- **Scope:** `[PROJECT]` — agenda de la próxima sesión limpia.
- **Estado:** Documentado en este SESSION_LOG y en el prompt de continuación que se prepara al cierre.

### Métricas tras esta sesión

Sin cambios de scan (no se modificó código de scanners ni resolvers, solo docs y estados). Se mantiene snapshot post-S21:

| Project | Orphans | Ambiguous | Connected | Entry | Health |
|---------|---------|-----------|-----------|-------|--------|
| Architect_compass | 0 | 2 | 31 | 5 | 97.59 |
| level2agent-engine | 0 | 5 | 24 | 6 | 91.49 |
| Agente_facundo | 0 | 6 | 48 | 7 | 88.46 |

### Archivos tocados

- `SESSION_LOG.md` — reconstruido completo desde 3 fuentes + entrada Sesión 22 (esta).
- `PLAN.md` — estados corregidos (RES-003 🟡, ORP-1 ✅, REG-040 🔲 reabierto multi-framework).
- `.map/PENDIENTES_v1.0.md` — borrado (absorbido al PLAN).
- `SESSION_LOG_RESCATE_17-21.md` — creado y luego borrado tras absorción al SESSION_LOG.

---

## NIVEL 21 · Sesión 21 · Integración PENDIENTES→PLAN + REG-040 investigación + RES-003 (código) + ORP-1

**Fecha:** 2026-04-19
**Subagente:** `debug_review_code` (integración docs + RES-003 + ORP-1), orquestador directo (investigación REG-040 + corrección de scope), agente paralelo (WP detector + orphan classifier)
**IDs:** integración `.map/PENDIENTES_v1.0.md` → `PLAN.md` (cerrado), REG-040 (reabierto con scope ampliado), RES-003 (código implementado, validación WP pendiente), ORP-1 (cerrado)
**Resultado:** OK parcial. Integración docs y ORP-1 cerrados; RES-003 implementado pero validación en proyecto WP real queda pendiente (los 3 proyectos testigo no son WP); REG-040 cerrado como "innecesario" por el agente y luego **reabierto por Beto** con scope ampliado tras verificación. Métricas finales post-S21: Architect_compass 0 orphans / 2 ambiguous / 31 connected / 5 entry / health 97.59; level2agent-engine 0/5/24/6/91.49; Agente_facundo 0/6/48/7/88.46.
**Detalle completo:** Sin reporte dedicado. Archivos: `compass/wordpress_detector.py` (NEW), `compass/orphan_classifier.py` (NEW), `compass/defaults.py` (+`DEFAULT_ORPHAN_PATTERNS`), `compass/pipeline.py` (`_should_be_explicit_orphan`), `compass/finalize.py` (`_detect_and_promote_wp_templates` + llamada), `PLAN.md` (integración PENDIENTES + estados actualizados), `README.md`.

### Hallazgos

#### 1. Integración PENDIENTES_v1.0.md → PLAN.md — scratch doc en mala ubicación

- **Tipo:** Corrección de ubicación + higiene de docs.
- **Manifestación:** Un agente previo había creado `.map/PENDIENTES_v1.0.md` por iniciativa propia. Ubicación incorrecta: `.map/` es output **regenerable** de Compass (atlas/compact/graph) — escribir docs humanos ahí rompe el contrato del directorio. Instrucción: mover al PLAN.md y borrar el archivo original. Se consolidó en PLAN.md con sección "Listos para Producción — v1.0 Candidate" + reorganización de pendientes reales vs diferidos. README.md actualizado para reflejar estado v1.0 (Capacidades Core, Outputs, subcomandos CLI, secciones honestas "Lo que resuelve" vs "Límites conocidos").
- **Scope:** `[GLOBAL]` — regla: `.map/` es salida regenerable; documentos humanos (PLAN, SESSION_LOG, README) viven en la raíz del repo.
- **Estado:** ✓ Cerrado.

#### 2. REG-040 — agente cerró "innecesario", Beto reabrió con scope ampliado

- **Tipo:** Scope corregido por el usuario + lección sobre cerrar tickets con evidencia parcial.
- **Manifestación:** Grep real en proyectos testigo: Agente_facundo tenía 10 casos de `register_blueprint` en `src/dashboard/api/__init__.py`; level2agent-engine tenía 0. Revisión del patrón real:
  ```python
  from .status import bp as status_bp    # ← el import estático YA emite el edge __init__.py → status.py
  app.register_blueprint(status_bp)      # ← redundante para el grafo
  ```
  Verificación post-S20: los 10 blueprints de Agente_facundo ya quedaron `tier=connected` sin REG-040 porque el import estático los conecta. El agente cerró el ticket como "innecesario". **Beto corrigió:** reabrir con scope ampliado a multi-framework dinámicos donde el import estático NO alcanza: FastAPI `include_router`, Django `include()`, Express `app.use`, Laravel `Route::group`. El caso testigo específico está resuelto pero el dominio del ticket no lo está.
- **Scope:** `[GLOBAL]` — lección: cerrar un ticket requiere evidencia en los testigos declarados del ticket, no solo en el proyecto de la sesión; un testigo que resolvió por otro camino no clausura el dominio.
- **Estado:** 🔄 Reabierto (scope ampliado).

#### 3. RES-003 — WordPress Template Hierarchy implementado, validación WP pendiente

- **Tipo:** Implementación con validación incompleta.
- **Manifestación:** Nuevo `compass/wordpress_detector.py`. Detección WP por markers: `style.css` con header WordPress, `functions.php`, `wp-config.php`, carpeta `wp-content/`. Si match, archivos con basenames de la jerarquía se marcan `entry_point_reason: "wp_template_hierarchy"`:
  - Fijos: `index.php`, `front-page.php`, `home.php`, `404.php`, `search.php`, `singular.php`, `comments.php`, `header.php`, `footer.php`, `sidebar.php`, `attachment.php`.
  - Glob: `single-*.php`, `archive-*.php`, `page-*.php`, `category-*.php`, `tag-*.php`, `taxonomy-*.php`, `author-*.php`, `date-*.php`, `template-*.php`.
  Integración en `finalize.py`. Cero falsos positivos en los 3 proyectos testigo (ninguno es WP). **Pendiente:** validar en proyecto WP real (candidato: ETCA en `c:\IA_Workspace\clientes\ETCA\web\etca.com.ar`). Por eso RES-003 **no** queda marcado ✅completada sino "código implementado, validación WP pendiente".
- **Scope:** `[PROJECT]`.
- **Estado:** ⏳ Pendiente — validación en project WP real.

#### 4. ORP-1 — defaults en código + config extiende; validación con archivo temporal

- **Tipo:** Decisión de política + patrón de validación.
- **Manifestación:** `compass/defaults.py` añade `DEFAULT_ORPHAN_PATTERNS` con tres dimensiones: extensiones (`.bak`, `.old`, `.orig`, `.tmp`, `.swp`, `.swo`, `.rej`), sufijos (`_old`, `_bak`, `_backup`, `_deprecated`, `_legacy`, `_orig`, `_tmp`), segmentos de folder (`archive`, `backup`, `deprecated`, `old`, `trash`, `_trash`, `_old`). Nuevo `compass/orphan_classifier.py` con `merge_patterns()` + `is_orphan()`. Integración en `compass/pipeline.py::_should_be_explicit_orphan()`. Criterio (aplicado post-ambiguous): (1) basename con extensión orphan → orphan; (2) nombre pre-extensión con sufijo orphan → orphan; (3) cualquier segmento del path en folder_segments → orphan. Override opt-in en `mapper_config.json` campo `orphan_patterns` (extiende defaults, no reemplaza). **Validación:** archivo temporal `test_old_backup.py` creado en Architect_compass → clasificado orphan correctamente → borrado post-validación (no commiteado).
- **Scope:** `[GLOBAL]` — patrón de validación "crear archivo temporal con el criterio, verificar efecto, borrar" candidato a `topics/pipeline_patterns.md`.
- **Estado:** ✓ Cerrado.

#### 5. Incidente grave — subagente pisó SESSION_LOG.md violando constraint

- **Tipo:** Bug de orquestación / violación de briefing.
- **Manifestación:** El briefing al subagente decía explícitamente "agregar **solo** la entrada de Sesión 21, no tocar sesiones previas". El agente **pisó el archivo completo** recreándolo con su propio formato (sesiones 1-21 mal estructuradas, sin niveles, sin hallazgos clasificados como Tipo/Manifestación/Scope/Estado). Como el SESSION_LOG.md nunca había sido commiteado a git (siempre untracked por ser documento privado — PLAN.md y SESSION_LOG.md viven solo local, repo GitHub es público sin ellos), **no es recuperable por git**. Esta pérdida gatilla toda la reconstrucción actual cruzando JSONL + reportes persistidos + rescate desde otra sesión activa.
- **Scope:** `[GLOBAL]` — lecciones (a) documentos no commiteados son frágiles y requieren briefings extra-defensivos; (b) ante briefing con "no tocar X", hay que verificar antes del Write que el `old_string` contiene exactamente lo que se va a preservar; (c) considerar backup en `~/.claude/results/` post-escritura como salvaguarda — candidato a `topics/subagent_handoff_workaround.md`.
- **Estado:** ✓ Mitigado (reconstrucción manual de S13–S21 en proceso).

---

## NIVEL 20 · Sesión 20 (A/B/C) · TIER-041 + DASH-042 + CMPCT-043 — Tier ambiguous + detector de dashboards stack-agnóstico + compact v2

**Fecha:** 2026-04-19
**Subagente:** `architect_system_design` (diseño tier + compact v2), `debug_review_code` (dashboard detector), orquestador (wiring final)
**IDs:** TIER-041 (cerrado), DASH-042 (cerrado), CMPCT-043 (cerrado)
**Resultado:** OK — 3 checkpoints passed. TIER-041 introduce un tier intermedio `ambiguous` entre `connected` y `orphan` para archivos sin inbound pero sin criterio explícito de descarte (posiciona conservador: ante la duda, no es orphan). `_compute_orphans()` reescrito para emitir 4 tiers: `connected` (source/target de edges), `ambiguous` (sin inbound, sin entry, sin criterio), `orphan` (criterio explícito — VACÍO hoy, ORP-1 en S21), `dynamic` (en `dynamic_deps`). DASH-042 implementa un detector stack-agnóstico de dashboards: HTML que carga script(s) + scripts con `fetch(...)`/`WebSocket(...)` a rutas locales → el HTML se promueve a entry point y queda `connected`. Cero falsos positivos en los 3 proyectos de prueba. CMPCT-043 evoluciona `atlas.compact.json` del schema `compact/1` al `compact/2`: elimina los sentinels `@@LOADER@@:...` convirtiéndolos en campo dict `file_loads` por nodo, filtra imports stdlib (Python) que no aportan al grafo, y omite campos vacíos. Ahorro adicional ~20% sobre v1. Casos Beto validados: `gestor.py`, `split_dashboard.py`, `log_proyecto.py` → `ambiguous` (sin inbound ni criterio). `dashboard/server.py` → `connected` (entry point por DASH-042).
**Detalle completo:** Sin reporte dedicado — trabajo integrado en sesión; cambios visibles en `compass/pipeline.py`, `compass/core.py`, `compass/consolidator.py`, `compass/graph_emitter.py`, `compass/finalize.py`, `compass/templates/graph.html.tpl`, `compass/dashboard_detector.py` (nuevo).

### Hallazgos

#### 1. TIER-041 — tier intermedio `ambiguous` evita falsos orphans

- **Tipo:** Decisión arquitectónica.
- **Manifestación:** Pre-S20, todo archivo sin inbound ni registro como entry point iba a `orphans[]`. Eso incluía archivos legítimos (utilitarios de debug, dashboards no importados, WP templates) que NO son código muerto pero tampoco tienen dep estática. Solución: introducir `ambiguous` como tier intermedio. `orphans[]` queda reservado para casos con criterio explícito (ORP-1 los llenará). El grafo pinta `ambiguous` con color naranja para que el usuario decida.
- **Scope:** `[GLOBAL]` — patrón "categoría intermedia para casos donde el análisis estático no alcanza" es reutilizable.
- **Estado:** ✓ Cerrado.

#### 2. DASH-042 — heurística stack-agnóstica para dashboards

- **Tipo:** Decisión de detección + nuevo módulo.
- **Manifestación:** Existen dashboards en todos los stacks (Flask/FastAPI/WP/Vanilla/Node). El detector es agnóstico: busca **HTML que carga JS propio del proyecto** + **JS con `fetch(...)`/`WebSocket(...)` a endpoints locales** (rutas tipo `/api/...`, `/action/...`). Si ambas condiciones match, el HTML se promueve a entry point con metadata `entry_point_reason: "dashboard_markers"`. Nuevo módulo `compass/dashboard_detector.py` (~195L) + integración `_detect_and_promote_dashboards()` en `compass/finalize.py`. Cero falsos positivos en los 3 proyectos testigo. Validación: en level2agent-engine los dashboards ya estaban connected vía SEM-020 (S17) y mantienen status (idempotente); en Agente_facundo DASH-042 rescata `dashboard/server.py` y `src/dashboard/static/index.html` que no conectaban por SEM-020 solo.
- **Scope:** `[GLOBAL]` — patrón "promoción de entry point por presencia combinada de HTML+JS con red local" es reusable.
- **Estado:** ✓ Cerrado.

#### 3. CMPCT-043 — compact/2 sin sentinels, sin stdlib, sin campos vacíos

- **Tipo:** Evolución de schema LLM-view.
- **Manifestación:** `compact/1` emitía sentinels tipo `@@LOADER@@:path` inline en `outbound` para señalar cargas de filesystem. Funciona pero genera ruido léxico y obliga al LLM consumidor a parsear convenciones propias. En `compact/2` los sentinels migran a un campo dict `file_loads: [...]` separado por nodo. Además: filtro de imports stdlib Python (os/sys/json/re/etc.) y omisión de campos vacíos (no emitir `"inbound": []` si está vacío). Ahorro ~20% de tamaño. Sin cambios en `atlas.json` (fuente de verdad intacta).
- **Scope:** `[GLOBAL]` — patrón "estructura dict > sentinels inline" candidato a `topics/pipeline_patterns.md`.
- **Estado:** ✓ Cerrado.

#### 4. Tier `orphan` queda vacío post-S20

- **Tipo:** Gap intencional a cerrar en S21.
- **Manifestación:** Post-TIER-041, no hay criterio explícito para llenar `orphans[]`. Por diseño se deja vacío hasta que ORP-1 (S21) defina los defaults (`.bak`/`_old`/`archive/`, etc.). Este gap es visible en atlas pero esperado.
- **Scope:** `[PROJECT]`.
- **Estado:** ⏳ Pendiente — asignado a **ORP-1** (cerrado en S21).

---

## NIVEL 19 · Sesión 19 · BUG-3 + investigación Agente_facundo + diseño 18B/18C

**Fecha:** 2026-04-18
**Subagente:** `debug_review_code` (root cause BUG-3 + fix), orquestador directo (investigación Agente_facundo + diseño 18B/18C)
**IDs:** BUG-3 (cerrado, crítico), investigación Agente_facundo (sin código), 18B diseñado (diferido a S20), 18C diseñado (diferido a S20)
**Resultado:** OK — BUG-3 cerrado con fix de **5 líneas** en `compass/pipeline.py:479`. El bug era crítico: la lógica chequeaba si el archivo era **TARGET** de edges cuando debía chequear si era **SOURCE**. Consecuencia: muchas mediciones previas de S15-S18 estaban **infladas** — los números de orphans en esas sesiones contenían artefactos del bug. Ejemplo concreto: Architect_compass pasó de 26 → **13** orphans tras el fix (health 76.45 → 85.9, +9.45). Investigación Agente_facundo: `gestor.py` confirmado como CLI standalone sin invocador detectable → **ambiguous legítimo**; `src/dashboard/server.py` Flask entry point sin importador en el codebase → **ambiguous** (Flask routes no detectables por análisis estático). De la investigación **no emerge detector stack-agnóstico nuevo** (DASH-042 lo cubrirá en S20 con otra heurística). Items 18B y 18C se diseñaron pero no se implementaron — difieren a S20.
**Detalle completo:** Sin reporte dedicado. Archivos: `compass/pipeline.py` (fix BUG-3, 5 líneas), PLAN.md, SESSION_LOG.md.

### Hallazgos

#### 1. BUG-3 — predicado invertido en `_compute_orphans` (crítico)

- **Tipo:** Bug de lógica, regresión silenciosa con impacto retroactivo.
- **Manifestación:** `compass/pipeline.py:479` chequeaba si el archivo era **target** de edges internos cuando el comentario del método decía "es orphan si no es **source** de edges internos". La inversión producía falsos orphans en archivos que importan a otros pero nadie los importa a ellos (caso normal de entry points y muchos scripts). Fix en 5 líneas, alineando el predicado con la definición correcta de orphan.
- **Scope:** `[PROJECT]` — lección **[GLOBAL]**: cuando el nombre de variable o el predicado discrepa del comentario del método, es un smell de bug; leer el comentario + trazar la lógica antes de aceptar el método. Candidato a `topics/code_quality.md`.
- **Estado:** ✓ Cerrado.

#### 2. Mediciones previas de S15-S18 estaban infladas por el bug

- **Tipo:** Consecuencia retroactiva del fix.
- **Manifestación:** Al corregir BUG-3, Architect_compass pasó de 26 → **13 orphans** (health 76.45 → 85.9, +9.45 puntos). Todas las métricas de orphans reportadas en S15, S16, S17, S18 quedan revisadas: los fixes sí funcionaban, pero los deltas absolutos en esas sesiones tenían ruido por el bug arrastrado. Los datos cualitativos (qué archivos pasaron de orphan a connected tras cada fix) siguen siendo correctos; los absolutos debían recomputarse. La métrica "3 orphans post-S18A" en el rescate refleja la cifra pre-BUG-3.
- **Scope:** `[NO-FIX]` — documentado para trazabilidad.
- **Estado:** ✓ Cerrado.

#### 3. `gestor.py` y `src/dashboard/server.py` — ambiguous legítimos

- **Tipo:** Gap de detección de entry points no convencionales.
- **Manifestación:** `gestor.py` en Agente_facundo es un CLI standalone sin invocador detectable por análisis estático (lo ejecuta el autor directamente). `src/dashboard/server.py` es un Flask entry point cuyos handlers se montan via decoradores `@app.route(...)`, que no generan imports hacia él. Ambos son técnicamente ambiguous bajo el análisis actual: no son código muerto (el autor los usa), pero no hay dep estática. Decisión: **no forzar fix automático**. La investigación no produjo un detector stack-agnóstico nuevo — será DASH-042 en S20 la que introduzca una heurística distinta (HTML+fetch) para casos similares.
- **Scope:** `[NO-FIX]` — input para S20.
- **Estado:** ⏳ Diferido — evaluado en S20.

#### 4. Items 18B y 18C diseñados, no implementados

- **Tipo:** Diferimiento planificado.
- **Manifestación:** Durante la sesión se diseñaron dos extensiones (18B y 18C) para profundizar la detección más allá de 18A. Se decidió diferir la implementación a S20 para no mezclar con el trabajo de fix crítico de BUG-3 y para integrarlas junto con TIER-041/DASH-042/CMPCT-043 (cambios que reestructuran la clasificación).
- **Scope:** `[PROJECT]`.
- **Estado:** ⏳ Diferido — absorbido en S20.

---

## NIVEL 18 · Sesión 18 · 18A — Data flow `with open()` + WSGI/ASGI detection + sys.path fallback

**Fecha:** 2026-04-19
**Subagente:** `debug_review_code` (feature implementation)
**IDs:** 18A.1 (data flow `with open() as f`), 18A.2 (WSGI/ASGI + Flask `send_from_directory`), 18A.3 (sys.path fallback resolver)
**Resultado:** OK — 3 extensiones implementadas con ~165 líneas netas. Métricas post-18A (aún con BUG-3 activo, se corrigen en S19): Architect_compass 3 orphans, level2agent-engine 8 orphans (dashboard HTML connected), Agente_facundo 14 orphans (`subagente.py` connected, 16 → 14). Caso `gestor.py` NO se resolvió con sys.path fallback (no tiene invocador detectable — se aborda en S19/S20). Cero regresiones funcionales.
**Detalle completo:** Sin reporte dedicado. Archivos: `compass/scanners/python.py` (+75L), `compass/defaults.py` (+2L), `compass/framework_mounts.py` (+45L), `compass/entry_points.py` (+8L), `compass/path_resolver.py` (+30L).

### Hallazgos

#### 1. 18A.1 — Data flow `with open(path) as f: json.load(f)`, 1 nivel mismo scope

- **Tipo:** Extensión de scanner con límite teórico claro.
- **Manifestación:** Nuevo método en `compass/scanners/python.py` que reconoce el patrón `with open("file.json") as f: data = json.load(f)` dentro de la **misma función o módulo** (1 nivel, scope único del `with`). Loaders soportados dentro del bloque: `json.load(f)`, `yaml.load(f)`, `f.read()`, `f.readlines()`. **Límite teórico declarado:** si `f` se pasa como argumento a otra función (`process(f)`), NO se captura — requeriría data flow interprocedural, fuera de scope.
- **Scope:** `[GLOBAL]` — patrón AST "context manager + loader en el mismo scope" reutilizable en otros scanners.
- **Estado:** ✓ Cerrado.

#### 2. 18A.2 — WSGI/ASGI detection + Flask `send_from_directory`

- **Tipo:** Extensión de detección de entry points + loader adicional.
- **Manifestación:** `compass/framework_mounts.py` gana `detect_server_entry_points(project_root)` que busca `waitress.serve(app, ...)`, `uvicorn.run(app, ...)` / `uvicorn.run("module:app", ...)`, `hypercorn.run(app, ...)`, y el script que contiene el call pasa a entry point (extensión de GRAPH-036, integración via `compass/entry_points.py` como paso 1b). En paralelo, Flask `send_from_directory("static", "index.html")` se añade a `DEFAULT_PYTHON_LOADERS`; el scanner combina ambos args → sentinel `"static/index.html"` → el resolver lo resuelve relativo al archivo fuente. **Resultado medible:** resolución del subgrafo dashboard aislado en level2agent-engine — el dashboard queda conectado al main graph via waitress.
- **Scope:** `[GLOBAL]` — patrón "entry point por invocación a server WSGI/ASGI" es reusable; candidato a `topics/framework_loaders.md`.
- **Estado:** ✓ Cerrado.

#### 3. 18A.3 — sys.path fallback resolver para monorepos `src/` layout

- **Tipo:** Heurística de path resolution "best effort".
- **Manifestación:** Agente_facundo hace `sys.path.insert(0, "/agente/src")` en entry points (`indexar_wiki.py`, `mcp_server.py`, `dashboard_api.py`) y luego importa `from subagente import ...` sin ruta explícita. Compass no resolvía porque buscaba desde project_root, no desde `src/`. Fallback agregado en `_resolve_python()`: tras fallar desde project_root, iterar dirs estándar (`src`, `lib`, `app`, `code`, `source`, `bin`) buscando `module_name.py`. **Resultado:** `src/subagente.py` pasó de orphan a connected (16 → 14 orphans). **Caso no resuelto:** `gestor.py` sigue sin invocador detectable; no aplica sys.path — requiere otro enfoque (se aborda en S19/S20).
- **Scope:** `[GLOBAL]` — el patrón `sys.path.insert(0, "/proyecto/src")` es común en agents/monorepos. Candidato a `topics/python_patterns.md`. Si un proyecto usa dir no estándar, debe declararlo en `dynamic_deps` o extender la lista hardcoded.
- **Estado:** ✓ Cerrado (con caso `gestor.py` diferido).

---

## NIVEL 17 · Sesión 17 · SEM-020 extendido (Flask/FastAPI static mounts) + Path division loader

**Fecha:** 2026-04-18
**Subagente:** `debug_review_code` (implementación de extensiones SEM-020 + path division)
**IDs:** SEM-020 extendido (static mounts, cerrado), path division loader (cerrado, pieza de LOAD-038)
**Resultado:** OK — Dos extensiones con impacto medible. Métricas (pre-BUG-3, revisadas en S19): level2agent-engine health +9.07 — dashboard (`index.html`, `dashboard.js`, `dashboard.css`) connected + 6 JSON files connected vía path division (`agent_preferences.json`, `global_models.json`, `google_models_status.json`, `model_capabilities.json`, `nvidia_models_status.json`, `performance_matrix_progress.json`); Agente_facundo health +9.86, orphans **-12**, `src/dashboard/static/index.html` y `js/mcp.js` connected; Architect_compass +0.22 health (self-scan sin regresiones).
**Detalle completo:** Sin reporte dedicado. Archivos: `compass/framework_mounts.py` (NEW, ~155L), `compass/path_resolver.py` (+150L), `compass/scanners/python.py` (+55L), `compass/defaults.py` (+1L: `"path_literal"`), PLAN.md, SESSION_LOG.md.

### Hallazgos

#### 1. Parte A — Static mounts Flask/FastAPI como hints de framework, no edges sintéticos

- **Tipo:** Decisión arquitectónica + nuevo módulo.
- **Manifestación:** Un mount estático no "importa" archivos: los sirve en runtime. Emitir edges sintéticos desde el archivo del mount a todos los assets generaría ruido proporcional al tamaño (ej. `static/` de ETCA con cientos de archivos). Solución: nuevo módulo `compass/framework_mounts.py` detecta por signals en código — `Flask(__name__, static_folder="...")`, `app.mount("/static", StaticFiles(directory="..."))` — y devuelve mapping **URL prefix → filesystem path absoluto**. Exclusiones: `.venv`, `node_modules`, etc. Integración en `compass/path_resolver.py` con helper nuevo `_find_file_in_parent_chain()` + wiring en `_resolve_html()`: ahora `<link href="/static/css/dashboard.css">` resuelve contra los mounts detectados, conectando el HTML con el asset real sin emitir edges desde el archivo del mount.
- **Scope:** `[GLOBAL]` — patrón "detectar montajes por signals del framework y mapear URL→filesystem" reutilizable para cualquier stack con convención similar.
- **Estado:** ✓ Cerrado.

#### 2. Parte B — Path division loader `VAR = DIR / "file.json"`

- **Tipo:** Extensión de LOAD-038 con pattern Pathlib.
- **Manifestación:** El patrón `VAR = DIR / "file.json"` (uso típico de `pathlib.Path.__truediv__`) no es capturado por el LOAD-038 original (que busca calls tipo `open(...)`). Nuevo método `_try_path_division_assignments()` en `compass/scanners/python.py` detecta AST-nivel asignaciones con `BinOp(op=Div)` sobre Path y emite sentinels `@@LOADER@@path_literal@@LOADER@@"filename"` para **cada literal en la cadena**: `ROOT / "data" / "file.json"` emite 2 sentinels. `"path_literal"` se agrega a `DEFAULT_PYTHON_LOADERS` en `compass/defaults.py`. `PathResolver` gana `_find_file_in_parent_chain()` que busca el literal en los directorios padre desde el archivo fuente (heurística — no data flow interprocedural). Esta extensión es la que habilitó conectar los 6 JSON files en level2agent-engine y explica el salto de health -12 orphans en Agente_facundo.
- **Scope:** `[PROJECT]` con lección **[GLOBAL]**: emitir **un sentinel por literal** en la cadena `/` preserva la info sin forzar reducción; delegar la búsqueda a `_find_file_in_parent_chain()` es simple y robusto.
- **Estado:** ✓ Cerrado.

#### 3. Métricas pre-BUG-3 — los deltas son reales, los absolutos luego se revisan

- **Tipo:** Nota de interpretación.
- **Manifestación:** Las métricas reportadas en esta sesión (health +9.07, +9.86, +0.22; orphans -12 en Agente_facundo) se midieron con la lógica de orphans todavía bugueada (BUG-3 se descubre en S19). Los deltas cualitativos son correctos (los archivos sí pasaron de orphan a connected); los conteos absolutos post-S17 se recomputan en S19 tras el fix. Se documenta para evitar confusión al comparar con métricas post-S19.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

---

## NIVEL 16 · Sesión 16 · BUG-2 — `__init__.py` fuera de `ignore_patterns`

**Fecha:** 2026-04-18
**Subagente:** `debug_review_code` (análisis de causa raíz + fix)
**IDs:** BUG-2 (cerrado)
**Resultado:** OK — Fix validado, 3 archivos salvados de ser orphans (`compass/scanners/python.py`, `compass/scanners/html.py`, `compass/scanners/treesitter.py`). Architect_compass: orphans 6 → 4 (1 nuevo orphan legítimo: `compass/__init__.py`, que efectivamente no es importado por nadie, solo reexporta). Health 87.56 → 92.11 (+4.55). level2agent-engine sin cambios (no tiene estructuras re-exportadas). Zero regresiones.
**Detalle completo:** Sin reporte dedicado.

### Hallazgos

#### 1. `__init__.py` ignorado rompía re-exports

- **Tipo:** Bug de configuración default.
- **Manifestación:** `mapper_config.json` línea 40 incluía `"__init__.py"` en `ignore_patterns`. `_is_ignored()` filtra ANTES de indexar, así que `compass/scanners/__init__.py` (191 líneas de dispatcher real) nunca se indexaba → sus imports no se registraban → los módulos re-exportados (`python.py`, `html.py`, `treesitter.py`) quedaban como orphans. Evidencia recolectada: **0 de 3** `__init__.py` en los proyectos testigo son vacíos — todos tienen código real. La asunción histórica ("`__init__.py` son marcadores vacíos") no aplica en proyectos con packages estructurados.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** Quitar `"__init__.py"` de `ignore_patterns`. Se evaluaron alternativas más elaboradas (distinguir vacío/real, o indexar imports sin emitir nodo) y se descartaron por overkill — la evidencia no justifica la complejidad.
- **Estado:** ✓ Cerrado.

#### 2. Nuevo orphan legítimo `compass/__init__.py`

- **Tipo:** Verificación post-fix.
- **Manifestación:** Tras quitar el ignore, `compass/__init__.py` aparece como orphan. Revisado: el archivo solo reexporta símbolos para conveniencia pero ningún módulo lo importa explícitamente (los scripts importan directamente de `compass.pipeline`, `compass.core`, etc.). Es correcto que aparezca como orphan — es un archivo de conveniencia sin usuarios.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

---

## NIVEL 15 · Sesión 15 · BUG-1 + LOAD-038 (refactor a defaults) — Entry points dejan de ser orphans + loaders universales en código

**Fecha:** 2026-04-18
**Subagente:** Orquestador directo (debug_review_code task ejecutada inline por scope acotado)
**IDs:** BUG-1 (fix), LOAD-038 (refactor a defaults)
**Resultado:** OK — Dos fixes completados sin regresiones. BUG-1: entry points ya no aparecen en `orphans[]`. Architect_compass 8 → 6 orphans (2 entry points removidos: `architect_compass.py`, `compass.py`). level2agent-engine 20 → 15 (5 entry points removidos: `cerbero.py`, `server.py`, `ping_capabilities.py`, `research_capabilities.py`, `run_performance_matrix.py`). Delta health level2agent-engine +7.4 (orphan score 25.93 → 44.44). Atlas byte-identical en ambos proyectos salvo por la lista `orphans[]`. LOAD-038: los 4 patterns universales Python (`open`, `json.load`, `read_text`, `read_bytes`) migran de `mapper_config.example.json` a `compass/defaults.py::DEFAULT_PYTHON_LOADERS`. El scanner los inicializa pre-config; la config extiende/sobreescribe individualmente. Refactor colateral: `_extract_filesystem_loaders` pasa de 6 niveles de anidación a 3 (split en `_try_path_method_call`, `_try_direct_loader_call`, `_emit_loader_sentinel`, `_emit_loader_sentinel_nested`).
**Detalle completo:** Sin reporte dedicado. Archivos tocados: `compass/pipeline.py`, `compass/scanners/python.py`, `compass/defaults.py` (nuevo), `mapper_config.example.json`.

### Hallazgos

#### 1. BUG-1 — orden de fases: entry points antes de orphans

- **Tipo:** Bug de orden en el pipeline.
- **Manifestación:** `compass/pipeline.py:379` ejecutaba `_compute_orphans()` antes que `_detect_entry_points()` (línea 412). Cuando orphans consultaba `atlas["entry_points"]`, aún estaba vacío, así que el filtro "no marcar como orphan si es entry point" no aplicaba. Archivos como `cerbero.py`, `server.py` (5 entry points en level2agent-engine) aparecían como orphans aun siendo scripts ejecutables independientes.
- **Scope:** `[PROJECT]` — lección **[GLOBAL]**: fases que consumen metadata de otras fases deben declarar el orden explícitamente; detectar estos bugs por inspección requiere leer el método consumidor antes de asumir que la metadata está poblada.
- **Acción tomada:** Swap del orden (`_detect_entry_points` → `_compute_orphans`) + filtro explícito en `_compute_orphans` vía `entry_points_set = set(self.atlas.get("entry_points", []))`.
- **Estado:** ✓ Cerrado.

#### 2. LOAD-038 — política "universal va en código, opt-in va en config"

- **Tipo:** Decisión de arquitectura de configuración.
- **Manifestación:** S14 dejó los 4 loaders Python solo en `mapper_config.example.json`. Problema: el `.example` es un template, no runtime; cada usuario debía copiar a `mapper_config.json` para activar comportamiento universal. Violación del principio "batteries included" para features que aplican a todo proyecto Python. Fix: nuevo `compass/defaults.py` con `DEFAULT_PYTHON_LOADERS`; el scanner Python inicializa con defaults y la config extiende. Política documentada en el docstring del módulo: "universal del stack → defaults en código; extensión opt-in custom → config".
- **Scope:** `[GLOBAL]` — regla reutilizable para cualquier feature futura.
- **Estado:** ✓ Cerrado.

#### 3. Refactor `_extract_filesystem_loaders` — 6 niveles → 3

- **Tipo:** Higiene de modularidad.
- **Manifestación:** Beto observó 6 niveles de anidación en el método (if dentro de if dentro de for, etc). Refactor en 4 helpers con guard clauses/early returns: `_try_path_method_call()`, `_try_direct_loader_call()`, `_emit_loader_sentinel()`, `_emit_loader_sentinel_nested()`. Lógica funcional idéntica verificada con test local (`test_loaders.py`) que cubre los 4 patterns. Anidación máxima ahora: 3 niveles.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

---

## NIVEL 14 · Sesión 14 · LOAD-038 — Python Filesystem Loaders (implementación inicial)

**Fecha:** 2026-04-18
**Subagente:** `debug_review_code` (feature implementation)
**IDs:** LOAD-038 (implementación inicial — refactorizado a defaults en S15)
**Resultado:** OK — Implementación end-to-end de soporte para Python filesystem loaders (`open`, `json.load(open(...))`, `Path.read_text`, `Path.read_bytes`). Scanner Python extrae calls vía AST + emite sentinels; PathResolver resuelve paths relativos al project_root. Cero regresiones en Architect_compass (atlas byte-idéntico — ningún archivo del self-scan tiene literales). level2agent-engine no se benefició tampoco (usa variables dinámicas `CERBERO_SETUP_DIR / "config.json"`). Feature correcta pero impacto real diferido a proyectos que usen literales. Stdlib-only. Limitaciones de diseño listadas en hallazgos.
**Detalle completo:** Sin reporte dedicado. Archivos tocados: `compass/scanners/python.py` (+90 líneas), `mapper_config.example.json` (+5 entradas — revertidas en S15).

### Hallazgos

#### 1. AST de `Path("x").read_text()` — método sobre Call, no sobre Name

- **Tipo:** Gotcha de AST Python.
- **Manifestación:** `read_text()` es un `ast.Attribute` cuyo `func.value` es un `Call` (la invocación `Path("x")`), no un `Name`. El helper inicial que extraía `callee_dotted_name` retornaba `None` porque el primer caso esperaba `Name`, causando skip. Fix: reordenar la lógica para chequear methods sobre Attribute antes de intentar callee_name simple. Patrón anotado para reusar en otros scanners.
- **Scope:** `[GLOBAL]` — patrón AST candidato a `topics/python_patterns.md`.
- **Estado:** ✓ Cerrado.

#### 2. Compatibilidad Python 3.8+ — `ast.Constant` vs `ast.Str`

- **Tipo:** Gotcha de compatibilidad.
- **Manifestación:** En Python 3.8+, string literals son `ast.Constant` con `.value` string. En versiones legacy (<3.8) eran `ast.Str` con `.s`. Helper `_constant_string_value(node)` chequea ambos para soportar el baseline del proyecto (3.8+).
- **Scope:** `[GLOBAL]`.
- **Estado:** ✓ Cerrado.

#### 3. Solo literales, no variables — decisión consciente

- **Tipo:** Decisión de scope.
- **Manifestación:** El scanner captura `open("config.json")` pero ignora `open(var)`. Inventar paths dinámicos llevaría a falsos positivos. Resolución dinámica requeriría data flow análisis — diferido a 18A.1 (con `with open() as f`) en S18.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado (con ruta de extensión en S18).

#### 4. level2agent-engine — sin impacto hoy por uso de variables

- **Tipo:** Verificación honesta.
- **Manifestación:** El target esperado era captar `json.load(open("config.json"))` en level2agent-engine. La implementación real del proyecto usa `CERBERO_SETUP_DIR / "config.json"` (variable Path). Cae fuera de scope. La feature es correcta; el proyecto no la ejercita. Proyectos con literales sí se benefician.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

#### 5. Patterns en `.example.json` en vez de defaults — deuda post-entrega

- **Tipo:** Deuda de arquitectura.
- **Manifestación:** Los 4 patterns quedaron en el template `.example`, no en defaults. El usuario debe activarlos manualmente. Detectado post-entrega; se cierra en S15 con refactor a `compass/defaults.py`.
- **Scope:** `[PROJECT]`.
- **Estado:** ⏳ Pendiente — cerrado en **S15 (LOAD-038 refactor)**.

---

## NIVEL 13 · Sesión 13 · NET-023 — Documentation Sync / confirmación de implementación completa

**Fecha:** 2026-04-18
**Subagente:** orquestador directo (audit / documentation update)
**IDs:** NET-023 (status sync a ✅completada)
**Resultado:** OK — Verificación y actualización de documentación. NET-023 fue implementado en **Sesión 8** con el método `_auto_promote_external()` en `compass/outbound_resolver.py` líneas 319-390. Confirmación funcional: level2agent-engine post-scan muestra 15 externals auto-promovidos (`requests`, `flask`, `bs4`, `pathspec`, `html2text`, `rich`, `waitress` como `tier=package`; `Gemini`, `OpenRouter`, etc. como `tier=service`). Stdlib ocultos por default (`external_include_stdlib: false`). Dedup por primer segmento trabajando correctamente (`from django.db import models` → `[EXTERNAL:django]`). PLAN.md actualizado: NET-023 marcada ✅completada. Esta entrada documenta el audit trail.
**Detalle completo:** No hay reporte separado (task puro de status sync).

### Hallazgos

#### 1. NET-023 implementado en Sesión 8, documentación no actualizada

- **Tipo:** Deuda administrativa.
- **Manifestación:** Commit `0d09711 sesion 8 - NET-022 + NET-023 + NET-022b + content filter` contiene la implementación completa de NET-023 (método `_auto_promote_external` con branches para Python/JS/TS), pero PLAN.md nunca se actualizó a ✅completada (quedó 🔲pendiente). S8 cubrió hallazgos de NET-022/NET-022b/content-filter pero no agregó entrada formal para NET-023 porque fue documentada implícitamente en el punto 4 de los hallazgos de S8. Riesgo: futuros orquestadores leen PLAN.md y creen que NET-023 no está hecha.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** PLAN.md línea 52: 🔲pendiente → ✅completada + descripción actualizada. Entrada de S13 agregada para audit trail.
- **Estado:** ✓ Cerrado.

#### 2. Cobertura de lenguajes en `_auto_promote_external`

- **Tipo:** Validación de alcance.
- **Manifestación:** NET-023 cubre Python (imports simples + `from ... import ...` desglosados, stdlib filtrado) y JavaScript/TypeScript (bare specifiers, scoped packages `@scope/pkg`, URLs explícitas descartadas). PHP y otros lenguajes retornan `None` (no aplica hoy). Scope correcto: Python/JS/TS son ~80% de las importaciones en los proyectos testigo. PHP a futuro vía SEM-020 y otros patterns. Decisión explícita de S8, no gap.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

#### 3. Validación de regex `_PY_IDENT_RE` y scoped packages JS

- **Tipo:** Validación de implementación.
- **Manifestación:** Python identifiers validados con `^[a-zA-Z_][a-zA-Z0-9_]*$` (matches stdlib module names correctamente). Scoped JS packages `@scope/pkg` son parseados a `@scope` + `pkg` (línea 379-382, requiere ambos no-vacíos). Casos edge: `@anthropic-ai/sdk` → `@anthropic-ai/sdk` (correcto); `@scope` solo o `@/pkg` rechazados. Head extraction dedup correcto: `anthropic.types`, `anthropic.client` → `[EXTERNAL:anthropic]` una sola vez.
- **Scope:** `[NO-FIX]` — implementación validada.
- **Estado:** ✓ Cerrado.

#### 4. Stdlib filter en config — `external_include_stdlib` default `false`

- **Tipo:** UX de graph density.
- **Manifestación:** Por default, imports stdlib Python (`os`, `sys`, `json`, `re`, `pathlib`, `ast`, etc.) no generan nodos en el grafo (se descartan en `_auto_promote_external` línea 354). Config toggle `external_include_stdlib: true` revierte al comportamiento pre-filtrado. Justificación: stdlib nunca es dep externa real — todos los proyectos Python lo tienen builtin. Filter aplicado solo a Python (JS/TS no tienen stdlib equivalente relevante en este scope).
- **Scope:** `[PROJECT]` — regla global: "cualquier auto-promote debería tener filtro de stdlib opcional" registrado implícitamente.
- **Estado:** ✓ Cerrado.

---


## NIVEL 12 · Sesión 12 · CLI-015 — CLI Flags & Subcommands (argparse + rich)

**Fecha:** 2026-04-18
**Subagente:** `architect_system_design` (implementación), orquestador directo (patch `_HelpfulParser` post-entrega)
**IDs:** CLI-015 (cerrado), REF-034 (nuevo, pendiente), CLI-015b (nuevo, pendiente)
**Resultado:** OK — argparse + rich con 4 subcomandos (`scan`, `symbols`, `init`, `graph`) + flags globales (`-r/-c/-o/-v/-q`) y de scan (`--full/--no-diff/--no-graph/--no-history`). Nuevo dispatcher `compass.py` en raíz + `compass/cli.py` (600 líneas) + `compass/cli_ui.py` (301 líneas, rich UI con fallback `_PlainConsole`). Wrappers legacy intactos (`architect_compass.py`, `architect_symbols.py` siguen operativos). Atlas byte-idéntico pre/post sobre los 3 proyectos (self/level2/ETCA). `requirements.txt` agregado con `rich>=13.0` como única dep runtime nueva. `compass.bat` simplificado a 6 líneas (ruteo único a `compass.py`). Patch post-entrega: subclase `_HelpfulParser` para que cualquier error de uso (subcomando inválido, flag desconocido) muestre `--help` antes del mensaje. Diferido a sesiones futuras: `pyproject.toml`+PyPI (paso 2 del cli_roadmap.html).
**Detalle completo:** `C:\Users\b70_r\.claude\results\cli-015-implementation-20260418.md`

### Hallazgos

#### 1. argparse vs typer — decisión final + por qué

- **Tipo:** Decisión arquitectónica.
- **Manifestación:** Beto preguntó por typer. Análisis: typer es ~2 MB con deps (click + typing-extensions + opcional rich), no es self-contained (vendorearlo cuesta mantenimiento), y typer ya rompe la línea "stdlib-only" del proyecto. argparse cubre el scope (4 subcomandos, ~10 flags) sin esfuerzo extra notable, mantiene auditabilidad de deps (importante para herramienta de auditoría). Decisión: **argparse + rich** (rich solo para UX visual, no para parsing). Beto confirmó "vamos con argparse y si no me gusta lo cambiamos" — migración futura a typer es 1-2 horas si aparece la necesidad.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 2. `_HelpfulParser` — UX de errores con `--help` automático

- **Tipo:** Patch UX post-entrega a pedido de Beto.
- **Manifestación:** argparse default ante comando inválido tira `error: invalid choice: 'foo'` escueto y exit. Beto pidió: "si se usa un comando errado, dispare el `--help`". Fix: subclase `_HelpfulParser(argparse.ArgumentParser)` que sobreescribe `error()` para `print_help(sys.stderr)` antes del mensaje + `sys.exit(2)`. `add_subparsers(parser_class=_HelpfulParser)` propaga el comportamiento a los subcomandos. Bonus: `_normalize_default_argv` ajustado para detectar "tokens que parecen path" (contiene `/`/`\\`, es `.`/`..`, o existe en filesystem) — solo esos disparan el legacy default a `scan`. Tokens que no son comando válido ni path real se dejan pasar a argparse para que dispare el help. Verificado en 4 escenarios: comando inválido / flag inválido / `--help` válido / path real.
- **Scope:** `[GLOBAL]` — el patrón "subclase de ArgumentParser que muestra help antes del error" es reusable en cualquier CLI Python que use argparse. Candidato a `topics/python_script_conventions.md`.
- **Estado:** ✓ Cerrado.

#### 3. compass.bat simplificado de 35 → 6 líneas

- **Tipo:** Decisión de UX + verificación honesta del diff.
- **Manifestación:** El `.bat` viejo tenía: (a) resolución portable de COMPASS_ROOT con `%~dp0` — **preservada**. (b) Routing manual del subcomando `symbols` con loop `:collect` para reconstruir args — **eliminado** (argparse lo hace nativo). (c) Comando `compass help` con echo hardcodeado de la lista de subcomandos — **eliminado** (Beto preguntó si había algo útil; verifiqué que `compass --help` de argparse muestra exactamente lo mismo + auto-actualizado + cubre los 4 subcomandos en vez de los 2 hardcodeados). El `.bat` nuevo: solo resuelve `COMPASS_ROOT` + `python compass.py %*`. Beto cuestionó la simplificación — verificación en ejecución real confirmó que `compass --help` cubre el caso. Lección: cuando reescribís un archivo, listá explícitamente qué se va y qué se queda; no des por obvio que el reemplazo cubre el original.
- **Scope:** `[PROJECT]` — `.bat` está gitignored, cambio local de Beto.
- **Estado:** ✓ Cerrado.

#### 4. `architect_symbols.py` no se movió a `compass/symbols.py` — promovido a REF-034

- **Tipo:** Desvío del plan original + ticket nuevo.
- **Manifestación:** El briefing pedía wrappers delgados para ambos entry points. El agente convirtió `architect_compass.py` (18 → 20 líneas, wrapper a `compass.cli.main_scan()`) pero NO movió `architect_symbols.py` (~900 líneas con AST/regex extractors) al paquete por scope. La CLI nueva (`compass symbols`) hace `import architect_symbols as sym_module` y reusa `build_symbols()` — funciona, pero deja un import cross-paquete inusual. Beto aprobó dejarlo así y crear **REF-034**: bundle de factorizaciones pendientes que incluye (a) `architect_symbols.py` 900 líneas → `compass/symbols.py`, (b) `path_resolver.py` 1011 líneas (identificado en REF-033), (c) `compass/cli.py` 600 líneas si crece más. Hard limit del proyecto: 600 líneas. No bloquea features.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado (decisión); REF-034 🔲pendiente de implementación.

#### 5. Monkeypatch de instancia para `--no-graph`/`--no-history`/`--no-diff` — promovido a CLI-015b

- **Tipo:** Deuda técnica reconocida + ticket nuevo.
- **Manifestación:** Para implementar los flags `--no-*`, el agente eligió monkeypatchar `compass._emit_graph_html = lambda: None` etc. sobre la instancia de `ArchitectCompass` justo antes de invocar `analyze()`/`finalize()`. Funciona perfecto pero es un patrón sucio: mutación de método por instancia, difícil de seguir, frágil ante refactors. Alternativa limpia: 3 booleans (`emit_graph`, `rotate_history`, `compute_diff`) como kwargs del `__init__` con default True. ~20 líneas de cambio total. Beto aprobó posponer: **CLI-015b** agregado al PLAN como ticket independiente. No urge porque el monkeypatch es localizado (vive en `cmd_scan` de `cli.py`) y no contamina el resto del código.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado (decisión); CLI-015b 🔲pendiente.

#### 6. `compass graph` reconstruye edges sin `edge_type`/`kind` — diff cosmético aceptado

- **Tipo:** Limitación documentada y aceptada.
- **Manifestación:** Atlas.json no serializa `edge_type` (import/fetch/require) ni `kind` (color/estilo del trazo) por edge. `compass graph` regenera `graph.html` desde atlas.json + connectivity.dot existentes; tiene que inferir tipos de edge. Resultado: nodos idénticos, conexiones idénticas, layout idéntico, **posibles diffs cosméticos en color/grosor de flechas** vs un `scan` fresco. Para iterar UX visual del grafo no afecta. Persistir edges nativos engordaría `atlas.json` sin beneficio claro. Beto aprobó dejarlo así.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 7. Mejoras UX rich agregadas sin pedido explícito — todas aprobadas

- **Tipo:** UX display-only no en briefing.
- **Manifestación:** El agente sumó 4 cosas no pedidas: (a) tabla con colores semánticos de orphans (rojo >30% del total, amarillo >0, verde =0); (b) header `Compass <subcmd> · root=<path>` antes de cada operación; (c) footer `Outputs en <map_dir> · Xs` post-scan; (d) truncado de paths largos en progress bar (>60 chars → `…lastN`). Las reportó upfront pidiendo aprobación. Beto las dejó todas — son discretas, alineadas con el pedido original ("colores", "tablas", "progress bar"), removibles si molestan. Buen ejemplo de proactividad UX bien manejada (transparente, no sneaky).
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 8. rich agregado como única dep runtime nueva

- **Tipo:** Decisión de dependencias.
- **Manifestación:** Hasta CLI-015 el proyecto era stdlib-only. Beto aclaró que esa "regla cerrada" no era mandato suyo sino observación heredada en el portfolio: "yo no puse esa regla cerrada, quiero que esto funcione no que sea un parche". rich ~3 MB instalado con deps transitivas (`pygments`, `markdown-it-py`, `mdurl`). Auto-detect de no-TTY (redirect a archivo) desactiva colores/animaciones — `compass scan > out.txt` exit 0 sin excepción, verificado. Si rich no está instalado, `cli_ui.py` cae a `_PlainConsole` con regex-strip de markup (exit 0 garantizado, sin features visuales). `requirements.txt` creado con `rich>=13.0`.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

---

## NIVEL 11.5 · Sesión 11.5 · REF-033 — Factorización de `compass/core.py` (2483 → 239 líneas)

**Fecha:** 2026-04-17
**Subagente:** `architect_system_design` (implementación + smoke tests)
**IDs:** REF-033 (cerrado)
**Resultado:** OK — `compass/core.py` factorizado de 2483 líneas a **239 líneas residuales** (fachada `ArchitectCompass` con 6 mixins + shims backward-compat). La división propuesta en el PLAN (3 módulos) se expandió a **8 módulos nuevos** por el hard limit de 600 líneas y por separaciones naturales que emergieron tras leer el código completo. Estrategia de mixins (vs funciones puras): preserva `self.*` + caches + API histórico sin reescribir firmas. Smoke test byte-idéntico en ETCA (46 038 bytes pre=post fuera de `generated_at`) y level2agent-engine (topología idéntica; diff solo en `delta` por previous_snapshot distinto). Self-scan muestra +8 nodos nuevos (los módulos creados) — diff **esperado y deseado**; health +2.09 (77.19 → 84.53) porque la modularización mejora orphans/dead_exports. Ningún archivo nuevo supera 536 líneas. API pública `from compass.core import ArchitectCompass` verificada sin cambios. Working tree limpio, listo para commit manual.
**Detalle completo:** `C:\Users\b70_r\.claude\results\ref-033-refactor-core-20260417.md`

### Hallazgos

#### 1. Split final: 9 módulos (no 3) — criterio duro de 600 líneas

- **Tipo:** Desvío consciente del plan propuesto en PLAN.md.
- **Manifestación:** El PLAN proponía 3 módulos (`pipeline.py`, `outbound_resolver.py`, `template_io.py`). Tras leer los 2483 líneas de `core.py`, el agente detectó que `pipeline.py` llegaba a 864 líneas en la versión 3-módulos, violando el hard limit de 600. Split final: `core.py` (239, fachada) + `template_io.py` (201) + `config_loader.py` (215) + `outbound_resolver.py` (536) + `stdlib_filter.py` (79) + `pipeline.py` (491) + `scan_worker.py` (240) + `entry_points.py` (171) + `finalize.py` (496). Separaciones naturales: `config_loader` se corre en `__init__` (no en `analyze()`), `finalize` es pase end-of-run distinto del scan loop, `stdlib_filter` tenía 70+ strings que no aportaban al lector de `outbound_resolver`. Orden de herencia: `ArchitectCompass(ConfigLoaderMixin, OutboundResolverMixin, AnalyzePipelineMixin, ScanWorkerMixin, EntryPointsMixin, FinalizeMixin)`.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 2. Estrategia de mixins vs funciones puras — preservar `self.*` y API histórico

- **Tipo:** Decisión arquitectónica.
- **Manifestación:** El PLAN sugería "preferir funciones puras que reciben/devuelven dicts sobre métodos con self". El agente eligió el opuesto (mixins que heredan a `ArchitectCompass`) por tres razones: (1) preserva `self.atlas/files/nodes/edges/caches/fingerprints` sin propagar 20+ closures; (2) mantiene el API histórico (`self._scan_file`, `self._classify_outbound`) que `validation.py` y tests futuros consumen; (3) evita un `__init__` gigante. Costo: 8 líneas de shims backward-compat en `core.py` (`_ensure_local_json`, `_ensure_local_help_md` delegan a `template_io`). El criterio duro de equivalencia de comportamiento se cumple holgado.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 3. Smoke test byte-idéntico en externos, diff esperado en self-scan

- **Tipo:** Validación de equivalencia.
- **Manifestación:** ETCA: 46 038 bytes pre=post, solo diff en `generated_at`/`previous_generated_at`. level2agent-engine: topología idéntica (mismos `files`, `connectivity`, `cycles`, `identities`, `stack_map`, `external_tiers`, `orphans`); diff de 64 líneas en bloque `delta` porque el `previous_snapshot` cambió (run reciente post-refactor en vez del snapshot pre-baseline). Self-scan (Architect_compass): 293 líneas de diff — los 8 `.py` nuevos aparecen como nodos, `compass/core.py` pierde ~120 edges outbound (los imports salieron al mixin correspondiente), `delta.files.added` lista 5 archivos nuevos. Health sube +2.09. Este diff es el output **deseado** — compass se scanea a sí mismo y refleja el refactor. Evidencia de determinismo: correr level2 dos veces post-refactor da solo 8 líneas de diff (timestamps).
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 4. Gotchas de imports cruzados — resueltos con imports locales y dirección única

- **Tipo:** Gotcha de refactor.
- **Manifestación:** Aparecieron 3 situaciones de acoplamiento: (a) Ciclo potencial `template_io ↔ finalize`: `_run_config_validation` necesita `_LOCAL_TEMPLATE`. Fix: import local dentro del método (`from compass.template_io import _LOCAL_TEMPLATE`) en lugar de top-level. (b) `_definition_applies_to_stack` vive en `pipeline.py` pero `scan_worker.py` lo necesita: import cross-module directo `from compass.pipeline import _definition_applies_to_stack`; no hay ciclo porque `pipeline` no importa de `scan_worker` (el cableado se hace por herencia en `core.py`). (c) Imports de scanners (`get_scanner`, `normalize_edge_item`) se movieron de `pipeline.py` a `scan_worker.py` porque tras extraer `_scan_file` dejaron de usarse en pipeline. Resultado: sin imports circulares, sin warnings, lint-clean.
- **Scope:** `[GLOBAL]` — el patrón "import local dentro del método para romper ciclos en mixins" es reusable en cualquier refactor que parta una clase grande. Candidato a `topics/python_script_conventions.md` o a un nuevo `topics/refactor_patterns.md`.
- **Estado:** ✓ Cerrado.

#### 5. Cache TIER-035 + INC-008 preservados intactos

- **Tipo:** Constraint del briefing respetada.
- **Manifestación:** `self._external_node_tiers` y `.map/fingerprints.json` permanecen bajo responsabilidad de `FinalizeMixin` (vía `_load_fingerprints`/`_persist_fingerprints`). El estado `self._cached_external_tiers` lo pobla `_load_fingerprints` en `__init__` vía `self.previous_cache = self._load_fingerprints()`. Cache de scanner `get_scanner()` con `id(config)` no se tocó. Verificado con cache-replay: segundo run sin cambios da 0 archivos scaneados, topología idéntica — cero regresión de performance incremental.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 6. `path_resolver.py` (1011 líneas) fuera de scope — candidato a REF-034

- **Tipo:** Deuda técnica identificada.
- **Manifestación:** El briefing excluyó explícitamente `path_resolver.py` del refactor. Post-REF-033 sigue siendo el archivo más grande del paquete (1011 líneas > 600 preferido). No bloquea CLI-015 porque es lógica autocontenida (resolver outbound paths), pero si aparece la necesidad de modificarlo durante CLI-015 o nuevos loaders (LOAD-038/WEB-039), conviene partirlo primero. Candidato natural: `REF-034 — factorización de path_resolver.py` (no urgente, no en la tabla principal del PLAN aún).
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado (identificado, no accionado).

---

## NIVEL 11 · Sesión 11 · SYM-004 + LOAD-038/WEB-039/REG-040 (formalize) + hardcodes audit — Symbol Tool + IDs formalizados + auditoría de outputs

**Fecha:** 2026-04-17
**Subagente:** `architect_system_design` (implementación SYM-004), orquestador directo (formalización IDs), `debug_review_code` (auditoría hardcodes), agente paralelo (fix hardcodes en curso)
**IDs:** SYM-004 (cerrado), LOAD-038 + WEB-039 + REG-040 (formalizados pendiente), hardcodes-fix (en curso)
**Resultado:** OK — SYM-004 implementado como tool paralela en `architect_symbols.py` (~680 líneas, raíz del repo), NO toca `analyze()/finalize()` ni el pipeline principal. Shape `.map/symbols.json` con `functions/classes/constants` por archivo. Python via `ast` stdlib; JS/TS y PHP regex fallback (tree-sitter no instalado). PHP restringido a `<?php...?>` para evitar falsos positivos de JS embebido. Subcomando `compass.bat symbols` agregado (archivo `.gitignore`, local del usuario). Smoke tests: self 14 files/180 funcs/9 classes; level2agent 28/700/103; Agente_facundo 45/457/14; ETCA 53→21 con símbolos (resto HTML puro). Todos <1s. Formalización: 3 gaps informales post-S10.5 promovidos a IDs formales (LOAD-038 Python filesystem loaders, WEB-039 framework static paths, REG-040 framework dynamic registration) — tabla principal + "NIVEL opcional" en secuenciación. Auditoría post-output detectó 10 hardcodes (3 CRÍTICO, 4 ALTO, 3 MEDIO); el más grave: `"root": str(project_root)` en línea 925 emitía path absoluto del autor en el JSON — viola regla dura "cero hardcoded paths en outputs". Fix de hardcodes en curso por agente paralelo.
**Detalle completo:**
- `C:\Users\b70_r\.claude\results\session11-SYM004-20260417.md` (implementación SYM-004)
- `C:\Users\b70_r\.claude\results\session11-formalize-gaps-IDs-20260417.md` (formalización)
- `C:\Users\b70_r\.claude\results\session11-hardcodes-audit-20260417.md` (auditoría)
- `C:\Users\b70_r\.claude\results\session11-hardcodes-FIX-20260417.md` (fix aplicado)

### Hallazgos

#### 1. SYM-004 — Tool paralela, NO invade el pipeline

- **Tipo:** Decisión arquitectónica.
- **Manifestación:** `architect_symbols.py` vive en la raíz del repo, se invoca standalone (`python architect_symbols.py` o `compass.bat symbols`) y escribe a `.map/symbols.json`. Cero modificaciones a `compass/core.py`, `compass/scanners/*`, `compass/path_resolver.py` ni `mapper_config.json`. Reusa `_load_compass_config` + `_merge_local_basal` replicando la lógica del pipeline sin instanciar `ArchitectCompass`. Cero dependencias cruzadas con `finalize()`. Justificación: SYM-004 es un output de consumo LLM paralelo (como `atlas.compact.json` fue para CONS-029/LLM-VIEW-028), no una etapa del análisis de edges. Mantenerlo standalone evita bloat en `core.py` (ya en 1700+ líneas, REF-033 pendiente).
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 2. SYM-004 — Regex fallback para JS/TS/PHP, tree-sitter no instalado

- **Tipo:** Desvío consciente del spec.
- **Manifestación:** Spec original sugería tree-sitter; `import tree_sitter_php/_javascript/tree_sitter` → `ModuleNotFoundError` en el entorno. Regex fallback aceptado por el spec ("regex fallback es aceptable para este primer cut"). Dispatcher en `extract_file` tiene hook limpio para agregar rama tree-sitter cuando esté disponible. **PHP restringido a bloques `<?php...?>`** via `_keep_only_php_blocks` que preserva offsets (reemplaza contenido no-PHP por espacios → line numbers correctos). Sin esta restricción, templates ETCA tipo `blog-post.php` generaban falso positivo: regex de `function` capturaba `function esc(s)` de un script JS embebido.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 3. SYM-004 — Hardcodes detectados post-output, revisión tardía

- **Tipo:** Gotcha de orquestación + deuda técnica.
- **Manifestación:** La auditoría posterior detectó **10 hardcodes** que pasaron desapercibidos durante la implementación. El más grave: línea 925 de `architect_symbols.py` emite `"root": str(project_root)` (path absoluto del filesystem del autor, ej. `C:\IA_Workspace\...`) directamente en `symbols.json`. Esto viola la regla dura del proyecto "cero hardcoded paths en outputs" y filtra info del desarrollador. `compass.bat` línea 5 también hardcodea `C:\IA_Workspace\herramientas\Architect_compass` (fix trivial: `%~dp0`). `_DEFAULT_IGNORE_FOLDERS` desincronizado con `mapper_config.json` (9 vs 17 items). 3 duplicaciones del set de extensiones (`_PYTHON_EXTS`, `_JS_EXTS`, `_PHP_EXTS` redeclarados en 3 lugares).
- **Scope:** `[GLOBAL]` — la **regla** es global: antes de cerrar un ticket, revisar los outputs generados buscando paths absolutos, constantes sospechosas y duplicaciones. Hoy se detecta por auditoría separada, debería ser parte del checklist del agente implementador. Candidato a `topics/post_implementacion.md` (ya existe — extender con sección "revisión de outputs").
- **Acción tomada:** Auditoría completa con plan priorizado Fase 1 (CRÍTICO, ~4 líneas), Fase 2 (ALTO, ~15 líneas refactor), Fase 3 (MEDIO, docs). **Fix aplicado por agente paralelo**: 3 CRÍTICOS (omitir `root` + agregar `project_name` basename + `compass.bat` con `%~dp0`) + 4 ALTO (lectura de `mapper_config.json` con fallback hardcoded) + 3 MEDIO documentados. Smoke test OK en 3/3 proyectos validables (agente_facundo fuera de scope, path externo).
- **Estado:** ✓ Cerrado.

#### 4. Formalización — sin ID no hay trackeo (promoción de gaps a tabla principal)

- **Tipo:** Lección de convención del PLAN.
- **Manifestación:** Los 3 gaps post-S10.5 (Python `open()/json.load()`, framework static paths, blueprint/router auto-registration) vivían en una sección informal "Gaps conocidos post-S10.5" del PLAN, **sin aparecer en la tabla principal con ID**. Beto notó el riesgo: cualquier ticket candidato que no esté en la tabla con estado 🔲 se olvida entre sesiones. Regla: **sin ID formal no hay trackeo**. Promovidos a LOAD-038, WEB-039, REG-040 con filas completas (scope + afectados + estimado). Numeración saltea 037 (coherente con los saltos pre-existentes en 004/012/034). "NIVEL opcional" agregado en la secuenciación para los 4 tickets sin sesión asignada (los 3 nuevos + RES-003).
- **Scope:** `[PROJECT]` — regla de convención específica del PLAN de Compass. El principio "sin ID formal no hay trackeo" podría promoverse a una memoria `feedback_formalize_gaps.md` del proyecto.
- **Acción tomada:** PLAN.md editado — 3 filas nuevas en tabla, sección informal reemplazada por pointer a los IDs, "NIVEL opcional" agregado.
- **Estado:** ✓ Cerrado (formalización); LOAD-038/WEB-039/REG-040 🔲pendientes de implementación.

#### 5. SYM-004 — compass.bat routing por subcomando (sin commit)

- **Tipo:** Cambio local del usuario.
- **Manifestación:** `compass.bat` (en `.gitignore`, launcher local de Beto) ahora soporta `compass symbols [args]` → `architect_symbols.py` además del default `compass` → `architect_compass.py`. Implementado con `setlocal enabledelayedexpansion` + label `:run_symbols` que reconstruye `%*` sin el primer token. Como el archivo no se versiona, si otros desarrolladores replican el setup deben aplicar el mismo patch a su launcher. Uso alternativo sin `.bat`: `python architect_symbols.py [-v] [--root X] [--output Y] [--stdout]`.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 6. SYM-004 — Skip silente de archivos sin símbolos

- **Tipo:** Decisión de diseño.
- **Manifestación:** Si un archivo no produce `functions/classes/constants`, no aparece en `files` del JSON (ej. scripts con puro markup o sin defs). Reduce ruido sin perder info útil. Ejemplo: ETCA scannea 53 archivos pero solo 21 tienen símbolos (resto HTML puro). Stats del JSON registran `files_scanned` vs `files_with_symbols` para mantener la métrica visible.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

---

## NIVEL 10.5 · Mini-sesión post-10 · SEM-020 extensions (WP Loader Gaps) + ticket RES-003 — get_header/get_footer zero-arg + path_template + accepts_array

**Fecha:** 2026-04-17
**Subagente:** `architect_system_design` (diagnóstico REDO), `architect_system_design` (implementación)
**IDs:** SEM-020 (4 extensiones), RES-003 (nuevo, pendiente)
**Resultado:** OK — 4 fixes sobre `loader_calls` shape cerraron los gaps identificados en el diagnóstico REDO de ETCA. Recuperados **26 edges funcionales directos** a `header.php`/`footer.php` (13 cada uno) en ETCA. `relevant/total` saltó **82.29% → 94.79%** (+12.50pp — indicador real del fix). Edges netos +50 en ETCA (26 directos + 24 colaterales). Self-scan side-effect positivo: +3.46pp health por nuevo edge `treesitter.py → regex_fallback.py` (import del helper nuevo). Level2agent-engine sin cambios (no tiene WP). Health score ETCA -0.43pp es artefacto de mapear mejor: `dead_exports` bajó porque header/footer pasaron a ser "live sin outbound funcional", no regresión. Cache incremental intacto — re-run sin borrar `fingerprints.json` → atlas idéntico byte-a-byte. ~96 líneas Python netas (budget 60-100). S10 uncommitted (CONS-029 + LLM-VIEW-028) NO tocado y verificado como no roto (re-run de pipeline completo generó atlas válido).
**Detalle completo:**
- `C:\Users\b70_r\.claude\results\session10-5-wp-loaders-20260417.md` (implementación)
- `C:\Users\b70_r\.claude\results\session10-diagnosis-sem020-etca-REDO-20260417.md` (re-diagnóstico — hallazgo clave `get_header()` zero-arg)
- `C:\Users\b70_r\.claude\results\session10-diagnosis-sem020-etca-20260417.md` (primer diagnóstico, insuficiente)

### Hallazgos

#### 1. Nunca confiar en un solo diagnóstico contra evidencia visual del usuario (lección de orquestación)

- **Tipo:** Gotcha de orquestación + lección cross-proyecto.
- **Manifestación:** El primer subagente de diagnóstico (`session10-diagnosis-sem020-etca-20260417.md`) concluyó "SEM-020 funciona perfecto, los sueltos son auto-load WP que no se puede trazar estáticamente". Beto respondió con **screenshot del grafo** mostrando `header.php` y `footer.php` huérfanos junto con 7 templates sueltos — contradicción directa al diagnóstico. Re-diagnóstico REDO encontró el bug real: `get_header()` sin argumentos (zero-arg) no estaba cubierto por el shape `loader_calls` actual; el resolver miraba `arg: 1` → no había arg → bailout. Fix: agregar `arg: 0` + `path_template: "{theme_root}/header.php"`.
- **Scope:** `[GLOBAL]` — **regla:** cuando el usuario reporta un problema con evidencia gráfica (screenshot, output de tool), el diagnóstico de un solo subagente no basta si contradice la evidencia. Cruzar contra el screenshot antes de cerrar; si el diagnóstico dice "funciona" pero el screenshot muestra lo contrario, re-ejecutar con otro agente o pedir verificación in-situ. Candidato a `topics/comportamiento_general.md` sección "diagnósticos" o `soul/soul_orchestrator.md` sección "verificación de subagentes". Memoria específica de orquestación candidata.
- **Acción tomada:** Re-diagnóstico (REDO) encontró el gap real; implementación posterior cubrió 4 casos.
- **Estado:** ✓ Cerrado (regla para guardar en memoria).

#### 2. SEM-020 — Extensión del shape `loader_calls` con 4 variantes nuevas

- **Tipo:** Extensión de feature.
- **Manifestación:** Shape `loader_calls` ahora admite 4 campos nuevos:
  - **`arg: 0`** — loader sin argumentos. Disparador para resolución por `path_template` fijo.
  - **`path_template: "{theme_root}/X.php"`** — template fijo cuando `arg: 0`. Expandido via `_resolve_path_function_token` existente.
  - **`path_template_with_arg: "{theme_root}/header-{arg}.php"`** — variante con string literal (ej. `get_header('alt')` → `header-alt.php`). Si arg es variable/expresión → fallback a `path_template`.
  - **`accepts_array: true`** — loader que admite array literal (`locate_template(['a.php', 'b.php'])`). Pre-expandido en el scanner (N sentinels, uno por string literal); variables en el array → bail out a body intacto.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** `mapper_config.json` + example + `path_resolver.py` (+38) + `regex_fallback.py` (+50, helper module-level `_expand_loader_body`) + `treesitter.py` (+6, gemelo) + `scanners/__init__.py` (+2, pass `loader_specs`).
- **Estado:** ✓ Cerrado.

#### 3. SEM-020 — `accepts_array` implementado en scanner, no en resolver

- **Tipo:** Decisión de diseño.
- **Manifestación:** Alternativa rechazada: modificar `PathResolver.resolve()` para devolver `list[str]` cuando el body es array. Rechazada porque cambia la firma pública y todos los consumidores (contadores de edges, caches, tests) necesitarían adaptación. Elegido: pre-expandir el array en el scanner antes de emitir sentinels — cada elemento del array genera un sentinel `@@LOADER@@<fn>@@<elem>` independiente, y el resolver lo procesa como una call one-arg normal. Firma pública intacta, contadores sin tocar.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 4. RES-003 — Nuevo ticket: WP Template Hierarchy Auto-detect

- **Tipo:** Ticket abierto, pendiente.
- **Manifestación:** Templates WP que el framework carga por URL (no por llamada explícita): `index.php`, `front-page.php`, `single-{cpt}.php`, `archive-{cpt}.php`, `page-{slug}.php`, `taxonomy-{tax}.php`, `home.php`, `404.php`, `search.php`. No son orphans reales — WP los elige por convención. Similar caso a `style.css` / `theme.json` ya aceptados. Propuesta: nuevo tier visual en el grafo (amarillo/naranja como stdlib) o metadata `framework_loaded: true` en el nodo. Fuera de scope SEM-020 — queda como ticket separado en la tabla principal del PLAN, post-GRAPH-036.
- **Scope:** `[NO-FIX]` por ahora — ticket pendiente, no bloqueante.
- **Estado:** 🔲 Pendiente (RES-003 abierto).

#### 5. SEM-020 — FIX 4 (regex `build_loader_call_regex`) sin cambios de código

- **Tipo:** Verificación.
- **Manifestación:** El fix 4 del plan original apuntaba a extender la regex para capturar calls sin argumento. Smoke inline del regex actual: `(?:[^()]|\([^)]*\)){0,4000}?` — el cuantificador `{0,4000}?` admite 0 caracteres, por lo que `get_header()` ya matchea como `fn_name="get_header", body=""`. No requirió cambios. Decisión documentada en PLAN para evitar confusión futura ("¿por qué FIX 4 no tiene commit?").
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado (verificado).

#### 6. Health score ETCA -0.43pp no es regresión

- **Tipo:** Clarificación métrica.
- **Manifestación:** Score compuesto bajó de 66.53 → 66.10 (-0.43pp). Descompuesto: `dead_exports` bajó de 63.54 → 52.08 porque `header.php`/`footer.php` pasaron a ser "nodos live con inbound pero sin outbound funcional" (no emiten edges ellos mismos, solo reciben). Efecto correcto de mapear bien, no regresión. El indicador real del fix es **`relevant/total`: 82.29% → 94.79%** (+12.50pp) — cobertura estructural del grafo subió fuerte.
- **Scope:** `[NO-FIX]` — artefacto de la métrica, no bug.
- **Estado:** ✓ Cerrado.

---

## NIVEL 10 · Sesión 10 · CONS-029 + LLM-VIEW-028 — consolidación metadata + atlas.compact.json pooled

**Fecha:** 2026-04-17
**Subagente:** `architect_system_design`
**IDs:** CONS-029, LLM-VIEW-028
**Resultado:** OK — 2 IDs implementados. Nuevo módulo `compass/consolidator.py` (~180 líneas, puro stdlib) para no invadir REF-033. CONS-029 invierte metadata per-source `{src: [targets]}` → global `{target: [sources]}` en `atlas.json::metadata_consolidated` (per-source **preservada** intacta). LLM-VIEW-028 emite `atlas.compact.json` con schema pooled: `labels[]` unificado (paths + external labels), `stacks[]`/`edge_types[]`/`edge_kinds[]` separados, `nodes[]`/`externals[]`/`edges[]` como tuples int-indexed. **Pool de labels fue el driver clave**: sin pool ETCA compact = 60% de full; con pool = **23.0%** ✓ (criterio <30%). Ratios finales: self 20.5%, ETCA 23.0%, level2 29.7%. Topología preservada byte-a-byte (mismos nodes/edges únicos/cycles). Cache incremental intacto (ETCA 96/96 reused_from_cache — fingerprints NO se invalidan porque el cache indexa file-level, no atlas top-level). `core.py` sumó solo +~18 líneas (2 métodos + wiring + import).
**Detalle completo:** `C:\Users\b70_r\.claude\results\session10-CONS029-LLMVIEW028-20260417.md`

### Hallazgos

#### 1. Labels pool unificado — driver clave del ratio <30% en ETCA

- **Tipo:** Decisión de diseño + lección reusable.
- **Manifestación:** Primera iteración de compact usaba `dict-of-strings` para nodes/edges (schema "legible"). Ratio ETCA = **60% de full** — insuficiente (spec requería <30%). Debuggeo mostró que los `rel_paths` largos (ej. `assets/fotos/sede-gascon-grupal-azul.jpg`) aparecían 5-10 veces en `edges[]` como strings repetidos. Fix: pool unificado `labels[]` con todos los labels (paths + external names) + edges/nodes referencian por índice entero. Drop de 60% → 23% en ETCA. Pools separados para `stacks`/`edge_types`/`edge_kinds` (dominios disjuntos). Orden estable: edges ordenados por `(src_str, tgt_str, type, kind)` ANTES de poolear → índice de labels determinístico para diff entre runs.
- **Scope:** `[GLOBAL]` — patrón de compactación por deduplicación de strings repetidos en JSON. Aplicable a cualquier output JSON con strings recurrentes (rel_paths, tags, enum types, labels). Candidato a `topics/code_quality.md` sección "JSON compacto para consumo LLM" o topic nuevo `topics/pipeline_patterns.md`.
- **Acción tomada:** Implementado en `consolidator.py::build_compact_atlas`. Separators `(",", ":")` (sin whitespace) adicional para minimizar tokens.
- **Estado:** ✓ Cerrado.

#### 2. Módulo nuevo `compass/consolidator.py` — pre-REF-033

- **Tipo:** Higiene de modularidad.
- **Manifestación:** `core.py` ya en ~1700 líneas (muy sobre hard limit 600). Embeber la lógica de consolidación (~180 líneas) inline lo hubiera empeorado. Decisión: módulo nuevo `compass/consolidator.py` (puro stdlib, sin I/O — solo transformación de dicts) con funciones públicas `build_metadata_consolidated(atlas)` y `build_compact_atlas(atlas, edges, externals, tiers)`. `core.py` solo suma +~18 líneas (imports + 2 métodos wrappers + wiring en `finalize()`). Patrón alineado con `metrics.py`, `graph_emitter.py`, `validation.py` de sesiones previas. Cuando REF-033 arranque, el helper puro mergea limpio a `compass/pipeline.py`.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 3. atlas.json creció >10% — desvío inherente al spec

- **Tipo:** Desvío aceptado.
- **Manifestación:** Criterio blando "atlas.json no debería crecer >10%" no se alcanzó en 2 de 3 proyectos: self +30.3%, ETCA +12.5% (cerca del target), level2 +49.6%. El crecimiento es **inherente al diseño**: CONS-029 agrega campo top-level `metadata_consolidated` aditivo sobre per-source (spec explícito dice **mantener** per-source). El valor absoluto depende del volumen de refs únicas del proyecto. Sería alcanzable solo si moviéramos per-source → consolidated (reemplazo), lo cual el spec prohíbe. ETCA (el proyecto real crítico) igual bajó 12.5% vs baseline y superó el criterio duro de compact <30%.
- **Scope:** `[NO-FIX]` — consecuencia estructural esperada del spec.
- **Estado:** ✓ Cerrado con desvío documentado.

#### 4. orphan_flag encoding con 3 estados — reader del compact debe consultar flag

- **Tipo:** Decisión de schema.
- **Manifestación:** `nodes[*][2]` (orphan_flag) codifica: `0=no orphan`, `1=no_inbound`, `2=dynamic_declared`. Si el reader del compact quiere distinguir orphan real vs dynamic_declared, **debe** consultar el flag — no puede inferir solo por "está en orphans list" porque `dynamic_declared` no se lista en `orphans`. Schema documentado en el reporte.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 5. Cache incremental no invalida con schema change

- **Tipo:** Validación positiva.
- **Manifestación:** Re-run de ETCA post-CONS-029/LLM-VIEW-028 sin borrar `fingerprints.json` → 96/96 files reused_from_cache. Fingerprints indexa a **nivel de archivo** (hash de contenido + mtime), no el schema del atlas top-level. Cambios en shape del output → cache sigue válido. Importante para futuros cambios de schema: mientras no se toque lo que el scanner emite per-file, el cache no requiere invalidation.
- **Scope:** `[PROJECT]` — patrón de diseño del cache; candidato menor a memoria del proyecto.
- **Estado:** ✓ Cerrado.

#### 6. Topología preservada byte-a-byte entre full y compact

- **Tipo:** Validación.
- **Manifestación:** `atlas.connectivity.outbound` (post-dedup) == `compact.edges` en cantidad y contenido: 251 en ETCA, 15 en self, 28 en level2. Cero edges perdidos en la compactación. Cycles, entry_points, health, summary, metadata_consolidated tal cual. `generated_at` compartido (mismo timestamp del run). Hash-diff de contenido semántico = 0.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

---

## NIVEL 9 · Sesión 9 · INIT-032 + FIX-027 + SEM-020 — re-exports `__init__.py` + inline script scan + semantic loader resolution

**Fecha:** 2026-04-17
**Subagente:** `architect_system_design`
**IDs:** INIT-032, FIX-027, SEM-020
**Resultado:** OK — 3 IDs implementados en una sola sesión. Cero regresiones en los 4 proyectos de referencia. SEM-020 aporta el grueso del valor (ETCA: +17 edges internos del tema `etca-aula`, health 60.51 → 66.53, +6.02pp, orphans 68 → 54 / -14). INIT-032 resuelve la cadena de re-exports en level2agent-engine (6 edges nuevos `cerbero.py → engine/{api,tools,provider,diff,log,loop}.py`, health 45.08 → 51.92 / +6.84pp). FIX-027 extiende el scanner HTML a bloques `<script>` inline reutilizando `http_loaders.javascript`+`typescript` — captura `fetch`/`axios`/wrappers custom (ETCA: 42 edges HTML → `[EXTERNAL:host]` nuevos hacia CDN/fonts/umami). Self-scan 73.09 → 73.17 (+0.08pp, +4 edges, dentro tolerancia). `core.py` sumó 47 líneas (helper `_detect_wp_roots`) — REF-033 sigue pendiente y se recomienda arrancarlo antes de CLI-015.
**Detalle completo:** `C:\Users\b70_r\.claude\results\session9-trio-INIT032-FIX027-SEM020-20260417.md`

### Hallazgos

#### 1. SEM-020 — Sentinel protocol `@@LOADER@@<fn>@@<body>` scanner↔resolver

- **Tipo:** Decisión de arquitectura.
- **Manifestación:** SEM-020 necesitaba pasar la **call completa** del loader (`wp_enqueue_script('h', "$dir/x.js", [], false, true)`) desde los scanners al resolver para poder extraer el argumento N, aplicar `ext_default`, resolver `path_functions`, etc. Alternativa rechazada: cambiar la interfaz scanner→resolver a dicts tipados — cascada de refactor inviable dentro del scope (queda para REF-033). Solución: codificar la call como string con formato `@@LOADER@@<fn_name>@@<body>`; el resolver decodifica vía `LOADER_SENTINEL` + `encode_loader_raw(fn, body)`. El string sobrevive limpiezas tipo `strip('\'\"')` (los dobles-at no son quote chars).
- **Scope:** `[GLOBAL]` — patrón reusable para **transportar estructura a través de un pipeline string-based sin cambiar firmas**. Aplicable a cualquier tool donde un layer inferior produce datos estructurados y el superior consume strings (scanners regex, tokenizers, pre-procesadores). Candidato a promoción a `topics/code_quality.md` o a un topic nuevo tipo `topics/pipeline_patterns.md`.
- **Acción tomada:** documentado en el reporte S9 (gotcha #1); memoria propuesta para indexar el patrón.
- **Estado:** ✓ Cerrado.

#### 2. SEM-020 — Helper `_detect_wp_roots` en `core.py` (+47 líneas)

- **Tipo:** Decisión pragmática con deuda técnica explícita.
- **Manifestación:** SEM-020 necesita `theme_root`/`plugins_root` para que `PathResolver` resuelva `get_template_directory_uri()` → `{theme_root}`. `theme_root` no se declara en config: se detecta heurísticamente buscando `functions.php` en 3 ubicaciones (`themes/<X>/`, `wp-content/themes/<X>/`, `<X>/themes/`). Motivo: ETCA tiene layout `themes/etca-aula/` — NO `wp-content/themes/`. Codificar esto en config sería fricción para el usuario. El helper vive en `core.py` aunque "invade" el scope de REF-033 (factorización pendiente). Documentado como deuda consciente — REF-033 lo moverá a `compass/wp_discovery.py` o similar.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** implementado inline; anotado en PLAN (REF-033) para mover post-refactor.
- **Estado:** ✓ Cerrado con deuda documentada.

#### 3. SEM-020 — PHP interpolation aliasing es archivo-local

- **Tipo:** Límite conocido documentado.
- **Manifestación:** `_evaluate_path_function_expr` resuelve aliases PHP (`$dir = get_template_directory_uri()` → `"$dir/css/x.css"`) **solo dentro del mismo archivo**. No resuelve cross-file (ej. `$dir` en `header.php` reusado en `content.php`). Cobertura suficiente para el patrón real de temas WP: cada plantilla re-asigna `$dir` en su scope propio. Si emerge un caso cross-file, extender `_php_interpolation_path` a resolución lineal con index de asignaciones — no priorizado.
- **Scope:** `[NO-FIX]` — límite aceptable, documentado para debug futuro.
- **Estado:** ✓ Cerrado.

#### 4. INIT-032 — Solo re-exports relativos (`level >= 1`)

- **Tipo:** Decisión de scope.
- **Manifestación:** `_trace_reexport` solo procesa `ImportFrom` con `level >= 1` (imports relativos: `from .sub import X`). Los imports absolutos en `__init__.py` NO se tratan como re-exports del paquete (`from anthropic import Client` en `__init__.py` no emite edge interno falso). Evita confusión entre re-export real del paquete y dependencia externa que el paquete consume.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 5. INIT-032 — Desvío del spec: fallback a submódulo directo `pkg/name.py`

- **Tipo:** Desvío menor del PLAN.
- **Manifestación:** Spec original: `from pkg import name` → buscar re-export en `pkg/__init__.py`. Implementación: si el re-export no matchea, fallback a `pkg/name.py` como submódulo directo (shape natural del import en Python). Evita regresión en paquetes donde `__init__.py` está vacío pero los submódulos se importan directos. No rompe ningún otro caso; el orden es re-export primero, submódulo después.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 6. FIX-027 — Loader regex sobre bloques `<script>` inline (sin `src=`)

- **Tipo:** Decisión de diseño.
- **Manifestación:** `html.py` ahora construye `_script_loader_regex` uniendo `http_loaders.javascript` + `typescript` (dedup). `_SCRIPT_BLOCK_RE` captura **solo** bloques `<script>...</script>` **sin atributo `src=`** (los que tienen `src` ya son capturados por el attr regex original). Cero duplicación. El lookahead negativo `\bfetch\b` de `build_http_loader_regex` evita match de `document.querySelector(...fetch...)` como substring. Covertura de wrappers custom (`apiReq`, `apiCall`) queda en manos del usuario vía `http_loaders.javascript` del `compass.local.json` (plumbing ya existente post-NET-022b).
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 7. SEM-020 — Overlap URL-SCAN vs SEM-020 (dedup por `_register_edge`)

- **Tipo:** Interacción de features.
- **Manifestación:** Tanto NET-022 (URL-scan) como SEM-020 (loader resolution) pueden emitir edges `fetch` para la misma call (caso: `wp_enqueue_script('h', 'https://cdn.example.com/x.js', ...)` — URL absoluta en primer arg de un loader WP). El dedup por tupla `(src, target)` en `_register_edge` evita doble conteo. Cuando ambos capturan, SEM-020 tiene menos prioridad porque NET-022 corre primero — el edge final queda como `[EXTERNAL:host]` en lugar de path interno, que es el comportamiento correcto para URL absoluta.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

#### 8. `include`/`require`/`require_once` NO agregados a `loader_calls`

- **Tipo:** Desvío consciente del spec.
- **Manifestación:** El PLAN sugería incluir `include`/`require`/`require_once` en `loader_calls` de SEM-020. No se hizo: ya existen como patterns en `definitions.PHP-Patterns.patterns.outbound` (post-DEF-025) y funcionan. Agregarlos en `loader_calls` duplicaría captura — el dedup ayuda pero inflaría el raw-edges y complicaría debug. SEM-020 se restringe a los casos WP que SÍ necesitan evaluación semántica (`wp_enqueue_*`, `get_template_part`, `locate_template`).
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 9. Zero regressions confirmadas en 4 proyectos

- **Tipo:** Validación.
- **Manifestación:**
  - **self** (Architect_compass): 15 files, 26 → 30 edges (+4), 8 orphans (=), health 73.09 → 73.17 (+0.08pp).
  - **ETCA** (WP theme): 96 files, 272 → 289 edges (+17), 68 → 54 orphans (-14), health 60.51 → 66.53 (+6.02pp). SEM-020 el driver principal: 14 edges nuevos desde `themes/etca-aula/functions.php` a assets CSS/JS del tema.
  - **level2agent-engine**: 23 → 25 files (fresh-scan captura 2 files antes no visibles), 34 → 39 edges (+5), 18 → 19 orphans (+1, explicado abajo), health 45.08 → 51.92 (+6.84pp).
  - **Agente_facundo**: 83 files, 460 edges (=), 76 orphans (=), health 43.42 (=) — sin WP ni `__init__.py` relevantes, ningún ID toca.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

#### 10. level2agent orphans +1 no es regresión (INIT-032 descubre nodos reales)

- **Tipo:** Clarificación métrica.
- **Manifestación:** INIT-032 resuelve targets previamente descartados (`engine.api`, `engine.tools`, etc.) a archivos reales que entran al atlas como nodos nuevos (2 files adicionales). El +1 orphan representa un submódulo que sigue sin inbound aún con re-exports resueltos — NO es regresión. La conectividad mejoró significativamente (+6.84pp health) porque los edges trazados fortalecen `connectivity` + `dead_exports`. Orphans es métrica independiente (PLAN lo acepta).
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

#### 11. Propuesta SEM-020b (ticket candidato, no abierto)

- **Tipo:** Seguimiento.
- **Manifestación:** El reporte sugiere extender `path_functions` a Python para capturar patrones tipo `open(os.path.join(BASE_DIR, 'config.json'))` o `json.load(open(...))` — gap listado en `memory/feedback_scanner_limits_preexistentes.md` (JSON referenciado desde código). Prioridad baja: los patrones Python son más idiosincrásicos que los WP y hay menos presión real. No se abrió ticket — si emerge como pain point tras S10-S11, abrir entonces.
- **Scope:** `[PROJECT]`.
- **Estado:** ⏳ Candidato (no abierto).

---

## NIVEL 8.5 · Mini-sesión post-8 · TIER-035 + GRAPH-036 — jerarquía visual de externals + highlight de entry points

**Fecha:** 2026-04-17
**Subagente:** `architect_system_design`
**IDs:** TIER-035, GRAPH-036
**Resultado:** OK — 2 IDs implementados. Cada nodo `[EXTERNAL:*]` recibe un `tier` semántico (`stdlib` / `package` / `service` / `wrapper`) pintado con color distinto en el HTML de vis-network; leyenda dinámica arma solo los tiers presentes. Nuevo pase `_detect_entry_points()` detecta archivos ejecutables (Python `__main__`, scripts referenciados desde `.bat`/`.sh` en raíz, `package.json::{main,bin,scripts.start}`, `index.{php,html,htm}` en raíz) con borde dorado + size boost + tooltip. Sin regresión funcional en los 3 proyectos de referencia (health/nodos/orphans idénticos pre/post). Líneas netas ~285 (PLAN estimaba ~110) — delta explicado por cache-fix de tiers (+30), detección multi-lenguaje de entry points (+100), leyenda dinámica (+35). No superó umbral de 300, sesión no abortada.
**Detalle completo:** `C:\Users\b70_r\.claude\results\session9-tier035-graph036-20260417.md` (nota: el slug del archivo dice "session9" pero en PLAN es mini-sesión 8.5 — respeta el nombre del PLAN).

### Hallazgos

#### 1. TIER-035 — Cache-replay perdía señal de tier (fix crítico)

- **Tipo:** Bug descubierto durante smoke test.
- **Manifestación:** Primera implementación recomputaba `tier` desde el display label en replay cacheado. Problema: un external como `[EXTERNAL:github.com]` tiene display `github.com` (hostname pelado); `_match_external_by_url` solo matchea si hay regex en `external_services.match_urls` — `github.com` genérico no tiene match. Resultado: tier se degradaba de `service` (primera run, match via URL scan original) a `package` (segunda run, re-clasificado por nombre) tras cache-hit. **Fix:** persistir `external_tiers` completo en `.map/fingerprints.json` y cargarlo en `_cached_external_tiers` para que `_apply_cached_scan` use el valor original. Cero recomputo en replay.
- **Scope:** `[PROJECT]` — pero el **principio** es `[GLOBAL]`: cualquier metadata derivada de señales que no se preservan entre runs debe persistirse en el cache, no recalcularse. Candidato a nota en `topics/code_quality.md` sección caching.
- **Acción tomada:** `_persist_fingerprints` incluye `external_tiers`; `_load_fingerprints` lo lee. Validado con level2agent-engine (13 tiers restaurados exactos en segundo run).
- **Estado:** ✓ Cerrado.

#### 2. GRAPH-036 — Desvío del PLAN: `index.php` extendido a `index.{php,html,htm}`

- **Tipo:** Desvío consciente del spec.
- **Manifestación:** PLAN GRAPH-036 limitaba el heurístico PHP a `index.php`. ETCA es un sitio estático HTML **sin `index.php`** (tiene `index.html` en root). Detectar solo PHP daba 0 entry points en un proyecto donde `index.html` es claramente el entry. Decisión: extender a `index.{php,html,htm}` manteniendo la regla estricta de "solo raíz" (no match en subdirs). Desvío menor, conservador, cubre el caso real de ETCA sin abrir falsos positivos.
- **Scope:** `[PROJECT]` — documentado en PLAN como ajuste a GRAPH-036.
- **Estado:** ✓ Cerrado.

#### 3. TIER-035 — 4 tiers con precedencia `service > wrapper > package > stdlib`

- **Tipo:** Decisión de diseño.
- **Manifestación:** Un mismo external puede ser registrado desde múltiples ramas de `_classify_outbound` (URL match + import auto-promote, ej. `requests` aparece en ambos). `_register_external_node` respeta precedencia: un segundo registro NO degrada un tier ya asignado más alto. Helper `_tier_rank()` + constante `_TIER_RANK` module-level. Motivo: `service` (SDK conocido por `match_urls`) es señal fuerte; degradarlo a `package` por un segundo match posterior perdería información.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 4. GRAPH-036 — Loop del template itera `allNames` (unión), no solo edges

- **Tipo:** Decisión del renderer.
- **Manifestación:** Pre-GRAPH-036 el loop del HTML iteraba solo `src/tgt` de edges. Problema: entry points sin edges inbound Y externals sin edges visibles no aparecerían. Fix: loop sobre `allNames` = unión de (src/tgt de edges ∪ externals ∪ orphans ∪ entry_points). Asegura que entry points se rendericen incluso si el análisis los encuentra aislados (válido para scripts standalone).
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 5. Wrapper tier cableado pero sin casos reales en smoke tests

- **Tipo:** Validación parcial.
- **Manifestación:** `graph.external_wrappers[{any,lang}]` está plumbing-verified (config lee, `_is_external_wrapper` matchea correctamente en fixtures), pero ninguno de los 3 proyectos de smoke declara wrappers custom (`apiReq`/`apiCall`). La visualización real de un nodo `wrapper` queda para cuando un proyecto configure esto vía `compass.local.json`. No es gap — el plumbing es correcto, solo falta consumer real.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

#### 6. Smoke tests — tiers encontrados por proyecto

- **Tipo:** Validación.
- **Manifestación:**
  - **self**: service×1 (`unpkg.com` del CDN de vis-network).
  - **level2agent-engine**: service×7 (Gemini, OpenRouter, nvidia, github, Context7, Brave, DuckDuckGo), package×6 (requests, flask, waitress, pathspec, html2text, bs4).
  - **ETCA**: service×18 (todos URLs literales en HTML: linkedin, fonts.googleapis.com, etc.). Entry point correcto: `index.html` (no tiene `index.php`).
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

---

## NIVEL 8.5-bis · Meta-sesión de diagnóstico post-S8.5 — confirmación de NO-regresión en edges

**Fecha:** 2026-04-17
**Subagente:** `Explore` (elección subóptima — ver hallazgo #2)
**IDs:** ninguno (meta-sesión sin código)
**Resultado:** OK — diagnóstico. Beto reportó tras S8.5 que "varios php/js/css/py/json/html han perdido sus conexiones en el grafo — aparecen como huérfanos cuando deberían tener conexión". Hipótesis de regresión S8.5 **descartada**: self-scan pre-S9 vs post-S9 muestra edges / raw_edges / nodos / orphans / filtros / health **idénticos** (12/26/15/8/(0,1,0,0)/73.09). Los cambios de TIER-035 y GRAPH-036 son aditivos (anotan metadata `tier` + `entry_points`); cero impacto en lógica de edge generation. Conclusión: los nodos sueltos reportados son **límite preexistente del scanner regex pre-SEM-020** — se volvieron más visibles por el nuevo styling del grafo (tiers + entry points highlights), no por pérdida de edges.
**Detalle completo:** `C:\Users\b70_r\.claude\results\session9-edges-diagnosis-20260417.md`

### Hallazgos

#### 1. Los nodos sueltos son límites del scanner regex, no regresión

- **Tipo:** Diagnóstico + decisión de roadmap.
- **Manifestación:** Patrones que el scanner actual NO detecta (documentados en `memory/feedback_scanner_limits_preexistentes.md`):
  1. **JSON referenciado desde código** — `json.load(open(...))`, `fs.readFile('./config.json')`, `require('./config.json')`. No hay ID activo en roadmap; candidato a SEM-020b.
  2. **Sub-grafos internos de temas WP** — `themes/` PHP/CSS/JS entre sí vía `wp_enqueue_style + get_template_directory_uri`. Lo cubre **SEM-020** (Sesión 9 siguiente).
  3. **Inline `<script>` en HTML con fetch/wrapper** — scanner HTML solo ve atributos `src=`, no contenido de `<script>...</script>`. Lo cubre **FIX-027** (Sesión 9).
  4. **Re-exports en `__init__.py`** — `from .sub import X`. Lo cubre **INIT-032** (Sesión 9).
  5. **Imports por símbolo sin path literal** — SYM-004 (Sesión 11, aún pendiente).
- **Scope:** `[GLOBAL]` — regla de diagnóstico: antes de debuggear un nodo "huérfano que debería estar conectado", verificar si el patrón entra en esta lista. Si sí, es deuda conocida del roadmap, no bug. Ya indexado en `memory/feedback_scanner_limits_preexistentes.md`.
- **Acción tomada:** decisión de Beto: "sigamos como está establecido" — roadmap ya contempla la solución (SEM-020+FIX-027+INIT-032 en S9, SYM-004 en S11). NO reordenar prioridades.
- **Estado:** ✓ Cerrado.

#### 2. `Explore` no escribe a disco — elección de subagente subóptima

- **Tipo:** Gotcha de orquestación.
- **Manifestación:** El diagnóstico se delegó a `Explore`, que solo tiene Glob/Grep/Read/WebFetch/WebSearch — sin Write/Edit. Respondió inline cargando ~900 palabras en el contexto del orquestador, rompiendo la regla de "contexto principal liviano". Debió usarse `general-purpose` con instrucción explícita de escribir a `~/.claude/results/[slug]-YYYYMMDD.md` y devolver solo path + resumen 1 línea. El reporte sí se persistió después manualmente.
- **Scope:** `[GLOBAL]` — regla: si el output esperado supera ~300 palabras o necesita ser recuperable en sesiones futuras, NO usar `Explore`. Usar `general-purpose` o skill con write capability. Ya indexado en `memory/feedback_explore_agent_inline.md`; candidato a promoción a `~/.claude/agents/AGENTS.md` o `topics/subagent_base.md`.
- **Estado:** ✓ Cerrado (regla registrada).

---

## NIVEL 8 · Sesión 8 · NET-022 + NET-023 + NET-022b + content filter — URL→host + imports auto-promoted + stdlib hidden + href content filter

**Fecha:** 2026-04-16 / 2026-04-17 (commit `0d09711`)
**Subagente:** `architect_system_design` (reporte formal **no archivado** en `~/.claude/results/` — reconstruido desde commit message + `git show --stat 0d09711` + memory files; nivel de confianza medio-alto en el código, medio en métricas cuantitativas exactas)
**IDs:** NET-022, NET-023, NET-022b, filtro content-vs-functional (aplicado en scope de la sesión, no ID separado)
**Resultado:** OK — 3 IDs + filtro content-vs-functional implementados. Scanners extienden extracción de calls HTTP (`fetch`/`axios`/`requests`/`wp_remote_*`) para capturar URL literal → nodo `[EXTERNAL:host]` con label matcheable vía `external_services.match_urls`. Imports externos no resueltos se auto-promueven a `[EXTERNAL:<pkg>]` (dedup por primer segmento del import). `http_loaders` extensible con wrappers custom del proyecto (NET-022b). Filtro content-vs-functional hardcoded: `<a href>` en HTML se descartan (content de navegación), `<script src>`/`<link href>`/`<img src>`/calls API se mantienen (functional). URLs loopback + RFC 1918 filtradas en URL branch de `_classify_outbound`. Stdlib del lenguaje ocultos por default (config toggle `external_include_stdlib`). Diff del commit: +885 / -103 líneas, principalmente `compass/core.py` (+307), 5 scanners tocados, `mapper_config.{json,example.json}` (+108 combinados).
**Detalle completo:** no hay reporte formal — ver commit `0d09711` + `memory/feedback_content_vs_functional.md` para decisión del filtro.

### Hallazgos

#### 1. Filtro content-vs-functional — `<a href>` descartado, resto mantenido

- **Tipo:** Decisión de semántica del grafo.
- **Manifestación:** Beto definió la regla: "una API es funcional a la estructura, un href es contenido". El grafo debe reflejar dependencias estructurales (carga de assets, calls a backend), NO links de navegación entre páginas. Implementación: `<a href>` se descarta en el scanner HTML; `<script src>`/`<link href>`/`<img src>`/`<form action>`/`<iframe src>` se mantienen; URLs literales en código (Python/JS/PHP) también functional. Efecto concreto en ETCA: health 65.83 → 60.51 post-filtro; 10 orphans nuevos son páginas HTML que solo se alcanzaban vía menú nav — correcto que aparezcan huérfanas ahora desde el punto de vista funcional. NO es regresión, es reclasificación esperada.
- **Scope:** `[PROJECT]` — con caveat: el filtro es hardcoded (no flag de config). **Revisitable vía FILTER-037 pospuesta** si algún proyecto necesita explícitamente incluir `<a href>` como dependencia estructural (ej. sitemap-driven content graph). Indexado en `memory/feedback_content_vs_functional.md`.
- **Acción tomada:** implementado; memoria de contexto creada para explicar caídas de health en proyectos con muchos hrefs.
- **Estado:** ✓ Cerrado (revisable).

#### 2. URLs en código cuentan como functional aunque el mismo host aparezca en `<a href>`

- **Tipo:** Precisión del filtro.
- **Manifestación:** `requests.get("https://linkedin.com")` en un `.py` → edge functional a `[EXTERNAL:linkedin.com]`. El mismo `linkedin.com` si aparece en `<a href="https://linkedin.com">` → descartado. Caso real ETCA: nodos `[EXTERNAL:linkedin.com]`, `[EXTERNAL:schema.org]`, `[EXTERNAL:sitemaps.org]` permanecen en el grafo aún tras el filtro, porque provienen de literales en código / schema.org refs en `<script type="application/ld+json">`, no de hrefs.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 3. NET-022 — URL literal extraction en URL branch, loopback/RFC 1918 filtrados

- **Tipo:** Decisión de alcance NET-022.
- **Manifestación:** `_classify_outbound` URL branch: extrae `host` de URLs literales (`http(s)://<host>/...`) y emite `[EXTERNAL:host]`. Si `external_services.match_urls` tiene regex que matchea el host completo o parte, el label del nodo usa el `service_label` config (ej. `"api.anthropic.com"` → `[EXTERNAL:Anthropic]`). Filtros aplicados: **loopback** (`127.0.0.1`, `localhost`) + **RFC 1918** (`10.x`, `192.168.x`, `172.16-31.x`) — esos NO generan nodo (son refs internas/dev, no externals reales). URLs dinámicas (template literals con `${}`) NO las cubre — sigue siendo territorio SEM-020.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 4. NET-023 — Auto-promoción de imports no resueltos a `[EXTERNAL:<pkg>]`

- **Tipo:** Decisión de scope NET-023.
- **Manifestación:** Si un import no resuelve a archivo interno del repo Y no matchea `external_services`, antes se descartaba silenciosamente. Post-NET-023: se promueve a `[EXTERNAL:<primer_segmento_del_import>]`. Ej. `import anthropic` → `[EXTERNAL:anthropic]`, `from openai.types import X` → `[EXTERNAL:openai]`. Dedup por primer segmento del import (no por nombre canónico del paquete — algún edge case tipo `from django.db import models` → `[EXTERNAL:django]`, lo que es correcto). Elimina la necesidad de que level2agent-engine liste manualmente cada SDK en `external_services`.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 5. NET-022b — `http_loaders` extensible con wrappers del proyecto

- **Tipo:** Punto de extensibilidad.
- **Manifestación:** `http_loaders.{javascript,typescript,python,php}` ahora acepta overrides del usuario vía `compass.local.json`. Un proyecto con wrapper custom `apiReq()` puede agregarlo a `http_loaders.javascript: ["apiReq", ...]` y el scanner lo captura como call HTTP. Dependiente de NET-022 (que define el shape regex compuesto). No cubre automáticamente wrappers genéricos — requiere declaración explícita (señal más limpia que heurística fuzzy).
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 6. Stdlib ocultos por default vía `external_include_stdlib`

- **Tipo:** Decisión de UX del grafo.
- **Manifestación:** Tras NET-023 los imports de stdlib (`import os`, `import sys`, `import json`) se promovían también a `[EXTERNAL:*]` y saturaban el grafo con ruido (ninguna dependencia externa real). Config toggle `external_include_stdlib` (default `false`): cuando `false`, los nombres en una lista `stdlib_modules` por lenguaje (Python: `os`, `sys`, `json`, `pathlib`, `re`, `ast`, ...) se descartan en lugar de promoverse. Usuario que quiera el grafo completo lo puede activar. Decisión: defaults razonables > configurabilidad ruidosa.
- **Scope:** `[GLOBAL]` — patrón reusable: **"auto-promoción debe tener filtro de stdlib opcional por default hidden"**. Candidato a nota en `topics/code_quality.md` o topic nuevo sobre graph tools.
- **Estado:** ✓ Cerrado.

#### 7. Proyecto detonante — level2agent-engine con providers LLM colapsados en `[EXTERNAL:requests]`

- **Tipo:** Motivación / validación.
- **Manifestación:** Pre-S8 level2agent-engine mostraba TODOS los LLM providers (Anthropic, OpenAI, Gemini, OpenRouter, etc.) colapsados en un único nodo `[EXTERNAL:requests]` (nombre del package HTTP). Inútil para ver a qué servicios realmente llama el proyecto. Post-S8 el URL-scan desagrega por host real: aparecen nodos separados para `api.anthropic.com`, `api.openai.com`, `openrouter.ai`, `generativelanguage.googleapis.com`, etc. Caso de uso que motivó NET-022 desde PLAN.
- **Scope:** `[NO-FIX]` — validación de la feature.
- **Estado:** ✓ Cerrado.

#### 8. Archivos tocados (alcance del commit `0d09711`)

- **Tipo:** Métrica.
- **Manifestación:** 14 archivos, +885 / -103 líneas:
  - `compass/core.py` +307 (wiring principal: `_classify_outbound` branches, `_register_external_node`, `_is_stdlib_module`, filtros loopback/RFC1918, content filter para hrefs).
  - `compass/scanners/__init__.py` +20, `base.py` +61, `html.py` +12, `python.py` +71, `regex_fallback.py` +40, `treesitter.py` +55 (extracción de URLs literales en calls HTTP).
  - `mapper_config.json` +76, `mapper_config.example.json` +32 (`http_loaders`, `external_services.match_urls`, `stdlib_modules`, `external_include_stdlib`).
  - `.map/atlas.json`, `.map/graph.html`, `.map/fingerprints.json`, `.map/feedback.log`, `.map/connectivity.dot` — outputs regenerados (no para commit manual, working tree tras scan).
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

---

## NIVEL 7 · Sesión 7 · FIX-030 + UX-031 + VAL-014 — dotfiles ignored + template UX + config validation (+ ajuste md-split pase 2)

**Fecha:** 2026-04-16
**Subagente:** `architect_system_design`
**IDs:** FIX-030, UX-031 (pase 1 + pase 2 md-split), VAL-014
**Resultado:** OK — 3 IDs implementados en orden secuencial (pase 1). level2agent-engine smoke test confirma `.env` ausente del atlas/grafo. Template UX-031 regenerado con orden activo-primero + banner `_WARNING` en cada `_example_*`. VAL-014 agrega 5 checks con acumulación no-abortiva en `atlas.audit.warnings` + sección `CONFIG WARNINGS:` en stdout. **Pase 2 post-review:** todo el contenido `_how_to_*` + `_README` migrado fuera del JSON a un `compass.local.md` paralelo (template en `compass/templates/compass.local.md.tpl`). El JSON queda solo con campos activos + `_example_*`; el MD es la documentación user-facing. `ensure_local_template()` refactor escribe ambos archivos idempotentemente. Health self-scan 71.79 → 73.67 (+1.88pp, dentro tolerancia ± 2pp). Health ETCA 73.95 → 73.80 (-0.15pp). level2agent files 17 → 16 (el `.env` se fue), orphans 12 → 11.
**Detalle completo:** `C:\Users\b70_r\.claude\results\ses-7-fix030-ux031-val014-20260416.md`

### Hallazgos

#### 1. FIX-030 — defense-in-depth hardcoded en `_is_ignored_target` (piso mínimo)

- **Tipo:** Decisión de diseño.
- **Manifestación:** El briefing pidió defense-in-depth: "incluso si alguien override-a ignore_patterns, el grafo no debe mostrar dotfiles de config". Se agregó `_DOTFILE_TARGET_PATTERNS` como tupla de clase con los 9 patterns (`.env`, `.env.*`, `.gitignore`, `.gitattributes`, `.editorconfig`, `.prettierrc`, `.prettierrc.*`, `.eslintrc`, `.eslintrc.*`). Piso mínimo independiente de config: si el user vacía `ignore_patterns`, el grafo igual filtra estos targets.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** No se tocó `_is_ignored` (fase walk/source) — respetamos la config del user ahí, por si quiere explícitamente scanear un `.env` como fuente (raro pero posible).
- **Estado:** ✓ Cerrado.

#### 2. UX-031 — orden del template cambió: activo primero, ejemplo como apéndice

- **Tipo:** Decisión de UX.
- **Manifestación:** El template pre-UX-031 tenía el orden `_how_to_<campo>` → `_example_<campo>` → `<campo>` (activo abajo). Beto editó el `_example_basal_rules.ignore_folders` creyendo que era el activo porque estaba primero. Post-UX-031: `<campo>` activo PRIMERO, `_how_to_<campo>` luego, `_example_<campo>` como apéndice de referencia con banner `_WARNING` interno. Al abrir el archivo, lo primero que se ve es el campo real.
- **Scope:** `[GLOBAL]` — patrón reutilizable para cualquier template JSON sin comentarios nativos: "active first, example as appendix with inline warning".
- **Acción tomada:** `_LOCAL_TEMPLATE` en `compass/core.py` reescrito. `_README` documenta la convención. Template pre-UX-031 exportado a `.quarantine/.legacy-v3/_LOCAL_TEMPLATE.pre-ux031.json`.
- **Estado:** ✓ Cerrado.

#### 3. VAL-014 — lógica en módulo separado `compass/validation.py`

- **Tipo:** Higiene de modularidad.
- **Manifestación:** `core.py` ya estaba en 1702 líneas (muy por encima del hard limit 600). Agregar los ~250 líneas de lógica de validación inline lo hubiera empeorado. Decisión: módulo nuevo `compass/validation.py` (359 líneas) con función pública `validate_local_config(...)` + helpers privados (`_check_*`, `_strip_warning_markers`, `_levenshtein*`). Patrón alineado con `metrics.py` (6A) y `graph_emitter.py` (6B/6C).
- **Scope:** `[PROJECT]`.
- **Acción tomada:** `core.py` solo agrega ~116 líneas (wiring + `_run_config_validation` hook en `finalize`). El trabajo pesado vive en el módulo nuevo.
- **Estado:** ✓ Cerrado.

#### 4. VAL-014 — drift detection con `_strip_warning_markers` para no molestar a users pre-UX-031

- **Tipo:** Iteración de diseño durante el smoke test.
- **Manifestación:** Primer implementación del drift check disparaba 3 warnings espurios en level2agent-engine porque los `_example_*` del user (template pre-UX-031) difieren del default post-UX-031 solo por la adición del `_WARNING`. Solución: `_strip_warning_markers()` remueve los `_WARNING` antes de comparar user vs default. Si al pelar el banner los ejemplos coinciden estructuralmente, NO hay drift real — es solo desincronización cosmética del banner.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** Función implementada y validada contra level2agent-engine (post-fix: 0 warnings falsos) y contra un fixture con edición real de `_example_basal_rules.ignore_folders` (warning dispara correctamente).
- **Estado:** ✓ Cerrado.

#### 5. VAL-014 — check 5 solo dispara si el campo activo está en default/vacío

- **Tipo:** Decisión de precisión del check.
- **Manifestación:** Criterio del briefing: "Solo dispara si también detectamos que el campo activo de ese triplet quedó en default/vacío (señal fuerte de edición equivocada)". Implementado: si el user tiene data tanto en el `_example_*` como en el activo, asumimos que sabe lo que hace (uso como scratchpad) y no warneamos. En level2agent esto es justo lo que pasa con `basal_rules` — Beto corrigió el error copiando los 11 folders al activo, así que post-corrección el warning NO dispara.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 6. VAL-014 — ciclo corre en `finalize()` (no en `analyze()`) para respetar orden de atlas.audit.warnings

- **Tipo:** Decisión de orden de pipeline.
- **Manifestación:** El briefing daba opción "al final de analyze() o al inicio de finalize() — decidí según flujo". Elegido **inicio de `finalize()`** (paso 0 antes de `_attach_metadata_calls`) porque (a) necesita el config merged + `project_root` ya walked, (b) los warnings deben estar en `atlas.audit.warnings` ANTES de que `_write_atlas` persista, (c) `_compute_metrics` podría en el futuro querer leer warnings (aunque hoy no lo hace). Prefijo estable `config:` en los strings de `audit.warnings` para que LLM-VIEW-028 futuro pueda distinguirlos de los de auditoría (stack detection, dot syntax, etc.).
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 7. FIX-030 — `.env` sigue en `text_extensions` del config global

- **Tipo:** Observación.
- **Manifestación:** `mapper_config.json::basal_rules.text_extensions` incluye `.env`. El walk lo levantaría como source si no fuera por el nuevo pattern `.env` en `ignore_patterns`. El briefing dijo: "NO tocar `.env` como source (ya está ignorado por `ignore_folders` en muchos casos); el foco es evitar que aparezcan como target". La realidad: `.env` no estaba ignorado como source (caso level2agent lo demuestra — aparecía en atlas como file). Post-FIX-030: el pattern `.env` filtra tanto en `_is_ignored` (walk/source) como en `_is_ignored_target` (grafo/target). Efecto: `.env` desaparece completamente del atlas.
- **Scope:** `[NO-FIX]` — comportamiento correcto según todos los criterios del briefing (el success criterion 1 pedía ausencia del atlas Y del grafo).
- **Estado:** ✓ Cerrado.

#### 8. Quarantine v3 creado para templates

- **Tipo:** Higiene de cierre.
- **Manifestación:** `_LOCAL_TEMPLATE` pre-UX-031 exportado a `.quarantine/.legacy-v3/_LOCAL_TEMPLATE.pre-ux031.json` como JSON textual (no el código). Respeta la convención `.legacy-vN` y la regla de no borrar artefactos históricos.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 9. Smoke tests consolidados

- **Tipo:** Validación.
- **Manifestación:** 3 proyectos auditados sin falsos positivos ni regresiones significativas:
  - **level2agent-engine** (full rescan): 17 → 16 files (`.env` fuera), 12 → 11 orphans, rendered_edges 10 (igual), 0 warnings falsos, `stack_map` inalterado (`AI-Agent-Framework` + `Vanilla-Web-Stack`).
  - **Architect_compass self** (full rescan): 14 → 15 files (+1 = `validation.py`), health 71.79 → 73.67 (+1.88pp, dentro tolerancia ± 2pp), 0 warnings.
  - **ETCA** (full rescan): health 73.95 → 73.80 (-0.15pp, dentro tolerancia), 2 ciclos detectados (nav footer, conocidos), 59 assets filtrados, 0 warnings.
- **Fixtures de validación controlada:**
  - `dynamic_deps.targets=["no-existe.py"]` → warning 1 dispara ✓
  - `definitions[].stack="StackInexistente"` → warning 2 dispara ✓
  - `campo_desconocido_x`, `dinamic_deps` (typo) → warning 3 dispara, segundo sugiere `dynamic_deps` ✓
  - `.map/mapper_config.template.json` + `.map/mapper_config.old.json` → warning 4 dispara ✓
  - `_example_basal_rules` editado con `basal_rules` vacío → warning 5 dispara ✓
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

#### 10. Líneas netas de la sesión

- **Tipo:** Métrica.
- **Manifestación:** `mapper_config.json` +9 líneas (patterns dotfile). `core.py` +116 líneas (constante `_DOTFILE_TARGET_PATTERNS`, rewrite de `_LOCAL_TEMPLATE` con `_EXAMPLE_WARNING` + reorden, `_run_config_validation` hook, sección `CONFIG WARNINGS` en `_print_summary`, refs a `_raw_local_config`). `compass/validation.py` nuevo: 359 líneas. Total neto código: **+484 líneas** + 9 líneas config. Post pase 2: `core.py` neto pasa a ~+79 líneas (se sacaron ~65 líneas de doc del template JSON); `compass.local.md.tpl` nuevo: 290 líneas MD.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

#### 11. Md-split de help: `_how_to_*` + `_README` migrados a `compass.local.md` paralelo (pase 2)

- **Tipo:** Decisión de UX + patrón de diseño.
- **Manifestación:** Post-review del pase 1, Beto detectó que meter la documentación dentro del JSON (`_README` como array de strings + 4 `_how_to_<campo>` keys) queda mal como UX — JSON no tiene formato real para markdown (listas, code blocks, bold, links). La documentación se lee una vez; el usuario después solo edita el JSON. Decisión: doc a archivo MD paralelo. El JSON mantiene solo datos + `_example_*` con banner `_WARNING` interno. El MD (`compass.local.md`) se genera desde template `compass/templates/compass.local.md.tpl` leído con `pathlib.read_text()` — precedente `graph.html.tpl` de Sesión 6C. `ensure_local_template()` refactor a dos helpers idempotentes (`_ensure_local_json`, `_ensure_local_help_md`) — cada uno chequea su propio archivo antes de escribir. VAL-014 check 5 sigue operando normal (compara `_example_*` con default shipeado pelando `_WARNING`); el mensaje del warning se actualizó a "ver compass.local.md sección 'Bloques _example_*'" (antes apuntaba a `_README` que ya no existe). Drift detection validado en fixture con `_example_basal_rules.ignore_folders` editado + activo vacío — check 5 dispara correctamente con mensaje nuevo.
- **Scope:** `[GLOBAL]` — patrón reusable para cualquier tool que genere JSON template user-facing: **"JSON con datos + MD paralelo con docs"** bate a **"JSON con docs embebidas como arrays de strings"** cuando el contenido necesita code fences, listas anidadas, links, o supera ~30 líneas. El JSON mantiene auto-explicabilidad mínima via `_WARNING` inline en `_example_*`; el MD toma el rol de referencia densa. Complementa el patrón pase 1 "active first, example as appendix" — ahora: "active first, example as appendix, docs as sibling MD".
- **Acción tomada:** `compass/templates/compass.local.md.tpl` creado (290 líneas MD, stdlib-only read). `_LOCAL_TEMPLATE` en `core.py` adelgaza a 10 keys (5 activos + 5 ejemplos). Constantes `LOCAL_HELP_NAME` y `LOCAL_HELP_TEMPLATE` agregadas. `_ensure_local_json` + `_ensure_local_help_md` idempotentes. Pre-md-split JSON ya quedó en `.quarantine/.legacy-v4/_LOCAL_TEMPLATE.pre-md-split.json` (del pase 2 interrumpido por corte eléctrico). Se agregó `stack_markers` al template como 5to campo activo (estaba mencionado en la doc pero no expuesto antes).
- **Decisión (a) vs (b) para el markdown:** opción **(b)** archivo `.tpl` leído con `pathlib.read_text()`. Motivo: el MD quedó en 290 líneas (9970 chars, 5 H3 con code fences por campo) — muy por encima del umbral de 50 líneas del briefing. Mantener `core.py` liviano (1781 líneas → antes 1818; bajaría otras ~290 si el MD fuera constante inline, pero aun así `core.py` ya está >3× hard limit). Precedente directo: `compass/templates/graph.html.tpl` de Sesión 6C maneja template HTML similar.
- **Estado:** ✓ Cerrado.

---

## NIVEL 6C · Mini-sesión post-6B · Fixes dinamismo + viewer vis-network + log catch-up

**Fecha:** 2026-04-16
**Subagente:** `architect_system_design`
**IDs afectados:** GRF-013 (rewrite viewer), EDG-023 (default_edge_type a config), AST-024 (asset_extensions_remove), SCR-009 (health_weights a config), GAP-005/007 (doc + verificación), CONS-029 + LLM-VIEW-028 (nuevos IDs en PLAN)
**Resultado:** OK — 8 bloques ejecutados. 5 hardcodes movidos a config. `graph.html` rewriteado sobre vis-network (zoom/pan/drag nativos, física interactiva, dark theme). Template externalizado a `compass/templates/graph.html.tpl` (~110 líneas fuera de graph_emitter.py). `asset_extensions_remove` implementado. GAP-007 verificado: `metadata.filtered_refs` ya estaba wired correctamente (Compass self-scan muestra 1 ref filtrada real). Smoke tests Compass + ETCA PASS (health 71.79 y 73.95, 207 edges + 2 cycles en ETCA, graph.html 207 edges serializados como JSON embebido).
**Detalle completo:** `C:\Users\b70_r\.claude\results\ses-6c-fixes-dinamismo-logs-20260416.md`

### Hallazgos

#### 1. vis-network vs Viz.js — el usuario quiere interactividad, no SVG estático

- **Tipo:** Decisión de arquitectura del viewer.
- **Manifestación:** El template `graph_test.html` que el user señaló como modelo usa vis-network (physics, zoom/pan/drag/hover nativos). El `graph.html` pre-6C usaba Viz.js → SVG estático. La auditoría 6B lo marcó como blocker UX para grafos >80 nodos. Decisión: adoptar vis-network, serializar edges como JSON embebido en el HTML, descartar el approach de DOT→WASM.
- **Scope:** `[GLOBAL]` — el viewer se emite SIEMPRE para cualquier proyecto (Python, PHP, JS, Rust, Go). Deferred en briefing previo al user como decisión cerrada.
- **Acción tomada:** `build_graph_html()` reescrito para consumir `edges + externals + orphans + cycles` directos (no el DOT). El `.dot` sigue escribiéndose al `.map/connectivity.dot` sin cambios — convive con el viewer.
- **Estado:** ✓ Cerrado.

#### 2. Template HTML externalizado como archivo `.tpl`

- **Tipo:** Decisión de mantenibilidad (opción b del briefing).
- **Manifestación:** El template vis-network ronda las 135 líneas (HTML+CSS+JS) — inline en `graph_emitter.py` explotaría el archivo a >600 líneas violando el hard limit de code_quality. Decisión: `compass/templates/graph.html.tpl` leído con `pathlib` + `.replace()` para placeholders. Stdlib only. Defensivo: fallback minimal si el archivo no existe.
- **Scope:** `[PROJECT]` — patrón interno del tool.
- **Estado:** ✓ Cerrado.

#### 3. 5 hardcodes → config (zero-hardcoding principle)

- **Tipo:** Auditoría 6B acción-to-take.
- **Manifestación:** Identificados en `ses-6b-audit-20260416.md` sección "Fallos no mencionados":
  1. CDN URL → `graph.vis_network_cdn_url` (Viz.js descartado, se usa vis-network CDN).
  2. `rankdir=LR` → `graph.rankdir` (válidos: LR, TB, RL, BT).
  3. Shape por kind → `graph.node_shapes` (dict con normal/orphan/cycle/external).
  4. `DEFAULT_EDGE_TYPE="use"` → `graph.default_edge_type` (con helper `resolve_default_edge_type(config)`).
  5. CSS inline del template → sigue inline DENTRO del `.tpl`. No exteriorizado a config (el CSS es UI, no data; un `theme_css` configurable agregaría complejidad sin beneficio claro — marcado como TODO futuro en bloque 2 punto 4 del briefing).
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado (4 de 5; el CSS se consideró fuera del scope de config-only).

#### 4. Health weights configurables con validación de suma

- **Tipo:** GAP-009 del gap-check.
- **Manifestación:** `_HEALTH_WEIGHTS` era hardcoded en `metrics.py`. Ahora se leen de `scoring_weights.health_weights`. `_resolve_health_weights(config)` valida: 4 keys presentes + suma ∈ [0.99, 1.01]. Si el override es inválido, `compute_health_score` devuelve warning como 3er elemento de la tupla y el caller lo agrega a `atlas.audit.warnings`.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** Signature de `compute_health_score` ahora devuelve `(total, breakdown, warning)`. Backward-compat: `core.py::_compute_metrics` actualizado; cualquier consumidor externo que no pase `config` recibe defaults (config=None → defaults).
- **Estado:** ✓ Cerrado.

#### 5. `asset_extensions_remove` + patrón `*_remove` extensible

- **Tipo:** GAP-003.2 del gap-check (asset removal no soportado).
- **Manifestación:** Merge de listas en `_merge_section_dict` solo extiende. Sesión 6C agrega post-merge paso `_apply_removal_directives(config, local_config)` que procesa `<list_name>_remove: [...]` en `basal_rules` y resta del basal. `_REMOVAL_KEYS` = `("asset_extensions", "ignore_patterns", "ignore_files")` — el patrón es extensible a más listas sin tocar esta función.
- **Scope:** `[PROJECT]`.
- **Verificación:** test con `asset_extensions_remove: [".svg", ".png"]` sobre Compass: set pasa de 24 a 22 entries, `.svg`/`.png` removidos, resto intacto.
- **Estado:** ✓ Cerrado.

#### 6. GAP-007 `metadata.filtered_refs` — verificado, NO necesitaba fix

- **Tipo:** Gap-check verificación.
- **Manifestación:** El gap-check sospechaba que `metadata.filtered_refs` no estaba wired (no se había verificado en 6B). Auditoría directa del atlas post-6C en Compass: `compass/core.py` tiene `metadata.filtered_refs = ["compass/scanners/__init__.py"]`, filtrado por el pattern `__init__.py` de `basal_rules.ignore_patterns`. El wiring completo (scan → `_metadata_filtered_refs` → `_attach_metadata_calls()` → atlas) funciona. En ETCA no aparecen entries porque no hay ignore_patterns que matcheen outbound targets ahí (los 59 edges filtradas son todos assets binarios, correctos vía `metadata.assets`).
- **Scope:** `[NO-FIX]` — feature ya estaba implementada y funcional.
- **Estado:** ✓ Cerrado.

#### 7. CONS-029 — metadata per-source es redundante, escala mal para LLM consumption

- **Tipo:** Regression GAP-G1 del gap-check elevado a ID formal.
- **Manifestación:** Cada HTML/archivo tiene su propio `metadata.assets`/`metadata.calls`/`metadata.filtered_refs`. En ETCA, 30 HTMLs × favicon = 30 entries del mismo asset. Para humanos es correcto (cada HTML "sabe" qué asset referencia); para un LLM que consume el atlas el shape es ruidoso. PLAN marca CONS-029 pendiente como propuesta: mantener per-source (default) + agregar vista consolidada global.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** ID nuevo agregado a PLAN en estado `🔲pendiente` con el shape propuesto.
- **Estado:** ⏳ Pendiente — CONS-029 en PLAN.

#### 8. LLM-VIEW-028 — export compacto del atlas para agentes IA

- **Tipo:** Propuesta nueva, surgió del audit 6B + gap-check.
- **Manifestación:** Atlas humano para proyectos medianos supera 1000 líneas (ETCA post-6C: atlas.json tiene ~15KB comprimido con todos los metadatos). Para feed a LLM agent (siguiente release que quiera auto-análisis del grafo), un `atlas.compact.json` con shape mínimo global consolidado sería útil. Depende de CONS-029 — primero consolidar, luego exportar compacto.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** ID nuevo agregado a PLAN. Estado pendiente; dependencia declarada.
- **Estado:** ⏳ Pendiente — LLM-VIEW-028 en PLAN.

#### 9. Patrón meta a evitar: PLAN marca ID ✅ sin registrar fixes pendientes del audit

- **Tipo:** Proceso.
- **Manifestación:** 6B se marcó `✅completada` cuando la auditoría 6B y el gap-check listaban 9 gaps con severidad media-alta. PLAN no reflejaba "completada pero con ajustes en 6C". Sesión 6C cambia la convención: `6B` ahora dice `✅completada + ajustes en 6C` (nueva convención informal que el PLAN admite caso por caso).
- **Scope:** `[GLOBAL]` — patrón reutilizable. Si una auditoría lista fixes > 0 líneas, el ID NO se marca ✅ sin caveat.
- **Acción tomada:** documentado aquí. Convención propuesta para entries futuras: cerrar un ID con auditoría pendiente = convertir en `🟡completada-con-reservas` o dejar rango `6X.N` explícito.
- **Estado:** ✓ Cerrado (documentado).

#### 10. Líneas netas del 6C

- **Tipo:** Métrica del bloque 8 (reducir líneas donde el trabajo lo permita).
- **Manifestación:** `graph_emitter.py` bajó de 545 → ~310 líneas (−235) gracias a que el template HTML externo se movió. `compass/templates/graph.html.tpl` agrega ~135 líneas (nuevo archivo). Neto código: ~+100 líneas (fixes + feature nuevas, mientras se quitan ~235 líneas del inline). Ver reporte para breakdown.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

---

## NIVEL 6 · Auditoría + Gap-check post-6B — meta-sesión sin código

**Fecha:** 2026-04-16
**Subagente:** `architect_system_design` (2 corridas consecutivas: audit + gap-check)
**IDs auditados:** GRF-013 + EDG-023 + AST-024 (sesión 6B) + revisión 5.7 → 6B
**Resultado:** OK — 2 documentos producidos. La auditoría de 6B identificó 7 "fallos no mencionados" (hardcodes + gaps de dinamismo + zoom ausente). El gap-check cruzó 5.7 → 6A → 6B y detectó 9 gaps con severidad 2-alta / 4-media / 3-baja. 3 top gaps para absorber en 6C: zoom/pan (svg-pan-zoom O vis-network), CDN version hardcoded, asset_extensions sin removal. Reportes:
- `C:\Users\b70_r\.claude\results\ses-6b-audit-20260416.md`
- `C:\Users\b70_r\.claude\results\gap-check-5.7-6b-20260416.md`

### Hallazgos

#### 1. 5 hardcodes en 6B

- **Tipo:** Gap de configurabilidad.
- **Manifestación:** Viz.js CDN version, `rankdir=LR`, shape mapping por kind, `DEFAULT_EDGE_TYPE`, CSS theme — todos hardcoded post-6B. Auditoría proponía moverlos a config como "zero-hardcoding principle".
- **Scope:** `[PROJECT]`.
- **Acción tomada:** los 5 se absorbieron en sesión 6C (bloque 2). Viz.js reemplazado por vis-network; CSS inline sigue en template pero el resto fue a config.
- **Estado:** ✓ Cerrado (vía 6C).

#### 2. GAP-007 `metadata.filtered_refs` — verificación pendiente

- **Tipo:** Promesa no verificada del reporte 6B.
- **Manifestación:** Reporte 6B prometía `metadata.filtered_refs` poblado en atlas, pero no se auditó el output real. El gap-check lo elevó a MEDIA severidad.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** bloque 5 de 6C verificó y confirmó que la feature SÍ está wired. Smoke test sobre Compass muestra 1 filtered_ref real.
- **Estado:** ✓ Cerrado (vía 6C).

#### 3. `metadata.assets/calls/filtered_refs` es per-source → atlas infla linealmente con `files × refs`

- **Tipo:** Potencial scaling issue.
- **Manifestación:** Cada HTML en ETCA reenumera `favicon.ico`, `favicon-192.png` — si hay 30 HTMLs, aparece 30 veces. Para proyectos humanos ok (cada archivo sabe qué referencia); para LLM consumption es ruidoso.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** 6C registró como **CONS-029** en PLAN pendiente.
- **Estado:** ⏳ Pendiente — CONS-029.

#### 4. Ausencia de "vista LLM-friendly" del atlas

- **Tipo:** Feature request latente.
- **Manifestación:** Atlas humano tiene shape rico pero pesado. Un LLM procesando el grafo necesita un resumen compacto (nodos + edges + cycles sin metadata explotada).
- **Scope:** `[PROJECT]`.
- **Acción tomada:** 6C registró como **LLM-VIEW-028** en PLAN pendiente (depende de CONS-029).
- **Estado:** ⏳ Pendiente — LLM-VIEW-028.

#### 5. PLAN marcó 6B ✅ sin reflejar los fixes pendientes de auditoría

- **Tipo:** Proceso / convención.
- **Manifestación:** Auditoría de 6B listaba fixes concretos pero PLAN dijo `✅completada` sin caveat. Riesgo: un futuro agente asume que 6B está done y no consulta la auditoría.
- **Scope:** `[GLOBAL]`.
- **Acción tomada:** 6C actualiza la entrada 6B de PLAN a `✅completada + ajustes en 6C` como convención informal. Documentado como hallazgo #9 de la entry 6C arriba.
- **Estado:** ✓ Cerrado (vía 6C).

---

## NIVEL 6B · Sesión 6B · GRF-013 + EDG-023 + AST-024 — HTML graph viewer + edge labels + asset filtering

**Fecha:** 2026-04-16
**Subagente:** `architect_system_design`
**IDs:** GRF-013 (HTML viewer Viz.js), EDG-023 (edge labels semánticos), AST-024 (asset filtering in grafo)
**Resultado:** ✅ completada (+ ajustes en 6C) — 3 IDs implementados, smoke tests PASS en Compass y ETCA, pero auditoría posterior identificó 5 hardcodes + zoom ausente + GAP-007 no verificado → absorbidos en 6C. `graph.html` pre-6C emitía Viz.js SVG estático; post-6C vis-network con zoom/pan nativos.
**Detalle completo:** `C:\Users\b70_r\.claude\results\ses-6b-dot-graph-filters-20260416.md`

Implementación 6B creó `compass/graph_emitter.py` (nuevo, stdlib-only, espeja `metrics.py`). Funciones puras: `build_dot_content(...)`, `build_graph_html(...)`, `validate_dot_syntax(...)`. Core solo I/O. `.dot` profesional: clustering por directorio top-level, shape/color por kind de nodo, labels + colores por `edge_type`, subgraph `cluster_legend` auto-generado. `graph.html`: HTML standalone embebido con Viz.js. Orden de `finalize()` reordenado para que cycles se computen ANTES del emit del dot. EDG-023: `extract_imports` devuelve `list[str | tuple[str, str]]` con edge_type por item; `RegexFallbackScanner` acepta patterns shape dict `{regex, edge_type}`; `_register_edge(src, tgt, kind, edge_type)` firma nueva. AST-024: `_is_asset_target(rel_path)` + `_is_ignored_target(rel_path)` en core; metadata.assets y metadata.filtered_refs por archivo.

### Hallazgos

#### 1. Scope creep — 850 líneas vs 300 presupuestadas

- **Tipo:** Budget overflow.
- **Manifestación:** 3 IDs interactuando (viewer + edge labels + asset filtering) + cambios de interfaz en scanners + propagación en caché. Auditoría posterior clasificó: 41% inevitables, 41% justificables (template + docstrings densos), 18% evitables.
- **Scope:** `[NO-FIX]` — aceptado en auditoría ("no revertir").
- **Estado:** ✓ Cerrado.

#### 2. Migración de `definitions[]` a shape dict `{regex, edge_type}`

- **Tipo:** Cambio de schema **no declarado explícitamente en briefing**.
- **Manifestación:** Las 5 definitions de `mapper_config.json` (post-DEF-025) fueron migradas de `"outbound": ["regex_str", ...]` a `"outbound": [{"regex": "...", "edge_type": "..."}, ...]` para que EDG-023 tenga label por pattern. Briefing 6B mencionaba "pattern declara su edge_type" pero no explicitaba el cambio de shape. Auditoría posterior validó que la semántica no se rompió y `RegexFallbackScanner::_extract_pattern_fields` acepta ambos shapes (legacy str + nuevo dict).
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado (validado post-facto).

#### 3. `concentrate=false` como trade-off

- **Tipo:** Decisión de rendering.
- **Manifestación:** Graphviz `concentrate=true` fusiona edges paralelos; post-EDG-023 eso escondería edge_types distintos. Trade-off: `concentrate=false` — grafos más "peludos" pero cada edge muestra su tipo correcto.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

#### 4. `cluster_legend` auto-generado solo con edge_types presentes

- **Tipo:** Decisión de UX.
- **Manifestación:** Al principio la leyenda listaba todos los edge_types conocidos (9). Limpieza: solo los que aparecen en el grafo real. Efecto: la leyenda de ETCA muestra 4 tipos (`fetch`, `href`, `require`, `src`); la de Compass muestra 2 (`import`, `use`).
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

#### 5. Offline-first con fallback CDN (pre-6C — descartado en 6C)

- **Tipo:** Decisión 6B revertida en 6C.
- **Manifestación:** 6B implementó "si existe `./viz-standalone.js` usar local, si no CDN". 6C rewrite adopta vis-network y la decisión offline-first se descartó (vis-network solo vía CDN hoy; si es necesario en el futuro, lógica análoga se agrega en el `.tpl`).
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado — superseded por 6C.

---

## NIVEL 6A · Sesión 6A · SCR-009 + DIF-010 + CYC-011 — Score breakdown + diff + ciclos

**Fecha:** 2026-04-16
**Subagente:** `architect_system_design`
**IDs:** SCR-009, DIF-010, CYC-011
**Resultado:** OK — 3 IDs implementados. Nuevo módulo `compass/metrics.py` con funciones puras. `atlas.json` extiende schema con `health`, `cycles`, `delta`. History en `.map/history/` con rotación FIFO a 10 entries. Compass health score 71.79, ETCA 73.95 (consistente pre/post). Ciclos en ETCA: 2 reales detectados (faq↔nosotros↔sedes, privacidad↔terminos) — son nav footer, no bugs.
**Detalle completo:** `C:\Users\b70_r\.claude\results\ses-6a-scoring-diff-cycles-20260416.md`

### Hallazgos

#### 1. Briefing vs PLAN contradicción — ciclos penalizan ¿o no?

- **Tipo:** Divergencia de fuentes de especificación.
- **Manifestación:** El briefing de 6A decía "los ciclos deben penalizar el health score". PLAN CYC-011 dice lo contrario ("son información arquitectónica, no necesariamente un bug"). El subagente decidió seguir PLAN. Auditoría posterior (gap-check) lo catalogó como gap BAJA y ratificó la decisión.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** PLAN CYC-011 se documentará con nota explícita en 6C para evitar futuras confusiones (hallazgo GAP-008 del gap-check).
- **Estado:** ✓ Cerrado.

#### 2. `dead_exports` es proxy (no trackea exports reales)

- **Tipo:** Decisión pragmática.
- **Manifestación:** No hay parser que distinga "function exported" de "function local"; `dead_exports` se aproxima como "archivo que tiene outbound pero no inbound" — proxy de módulo muerto. Documentado en PLAN SCR-009 post-6A.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

#### 3. Budget 535 líneas vs 250 presupuestadas

- **Tipo:** Overflow de presupuesto.
- **Manifestación:** Módulo nuevo `metrics.py` (~395 líneas incluyendo 3 funciones puras + helpers de history) + wiring en core.py (~140 líneas de refactor del `finalize`). Justificado por ser la primera vez que se separa lógica pura de I/O para preparar 6B y por las 3 features independientes.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

#### 4. Fallback útil al atlas.json pre-6A para primer delta

- **Tipo:** Decisión de UX.
- **Manifestación:** Primera run post-6A sobre un proyecto ya auditado (ETCA) tendría `history/` vacío → ningún delta. Solución: si no hay history pero existe `.map/atlas.json` previo, usarlo como snapshot fallback para sembrar el primer delta.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

---

## NIVEL 5.7 · Mini-sesión pre-6 · DEF-025 — Definitions cleanup stack → language

**Fecha:** 2026-04-16
**Subagente:** `architect_system_design`
**IDs:** DEF-025
**Resultado:** OK — `definitions[]` rediseñadas de stack-based (8+ entries: WordPress, Tauri, Modern-Web, Vanilla-Web-Stack-PHP/JS, etc.) a language-based (5 entries: Python, PHP, JavaScript, TypeScript, HTML). Guardián de contexto por stack agregado en `core.py::_definition_applies_to_stack`. Inbound patterns todos vacíos por decisión consciente (las señales inbound que existían eran de stack/framework, no de identity language — mantenerlos reintroduciría los falsos positivos). Compass smoke: identity única `Python`. ETCA smoke: `Vanilla-Web-Stack` + `WordPress-Development` (ambas `stack_markers`), cero identities falsas tipo Tauri/Modern-Web.
**Detalle completo:** `C:\Users\b70_r\.claude\results\def-025-definitions-cleanup-20260416.md`

### Hallazgos

#### 1. Inbound patterns todos vacíos — decisión consciente

- **Tipo:** Trade-off de diseño.
- **Manifestación:** Los patterns inbound originales (invoke(, listen(, emit(, "use client", export default function, addEventListener, @app.route, def tool_, def skill_, add_action, register_rest_route) son señales de *stack/framework*, no de *identity del lenguaje*. Mantenerlos language-scope reintroduciría el ruido DEF-025 vino a resolver (Tauri detectado en HTML+PHP). Trade-off aceptado: perdemos canal "regex custom → identity" a cambio de identities limpias.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** documentado en `_comment` de cada definition + habilitado guardián por stack para overrides user futuros.
- **Estado:** ✓ Cerrado.

#### 2. `_definition_applies_to_stack()` agregado como hook durmiente

- **Tipo:** Feature prospective, implementada ahora para backward-compat.
- **Manifestación:** Ninguna definition actual usa el campo `stack`. El guardián `_definition_applies_to_stack(definition, file_stack)` existe para cuando el usuario en `compass.local.json` declare una definition con `stack: "MyStack"`; sólo aplicará a archivos cuyo `stack_map[rel_path]` matchee. Esto permite overrides scope-restringidos sin contaminar el resto del proyecto.
- **Scope:** `[GLOBAL]`.
- **Acción tomada:** 6C agrega nota aclaratoria en PLAN DEF-025 documentando el use case.
- **Estado:** ✓ Cerrado.

#### 3. 5 stacks legacy consolidados en 5 entries language-based

- **Tipo:** Refactor de schema.
- **Manifestación:** De `Python`, `WordPress-Development`, `Vanilla-Web-Stack-PHP`, `Vanilla-Web-Stack-JS`, `Modern-Web-Stack-JS`, `Modern-Web-Stack-TS`, `Tauri-Desktop-App-JS`, `Tauri-Desktop-App-Rust`, `AI-Agent-Framework` → a `Python-Patterns`, `PHP-Patterns`, `JavaScript-Patterns`, `TypeScript-Patterns`, `HTML-Patterns`. Outbound patterns consolidadas por lenguaje.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 4. Quarantine del schema pre-DEF-025

- **Tipo:** Higiene de cierre.
- **Manifestación:** `mapper_config.json` pre-DEF-025 movido a `.quarantine/.legacy-v1/mapper_config.v2-pre-def-025.json`. Respeta convención del proyecto.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

---

## NIVEL 5.6 · Mini-sesión pre-6 · FIX-026 — Template UX + diagnóstico inbound APIs

**Fecha:** 2026-04-16
**Subagente:** `architect_system_design`
**Resultado:** OK — 2 partes. Parte A: template `compass.local.json` rediseñado con shape `_how_to_<campo>` + `_example_<campo>` + campo real vacío, ejemplos fake-but-realistic cubriendo los 4 campos editables. Parte B: diagnosticado "punto 7" — causa raíz múltiple. Fix chico aplicado (HTML scanner ahora captura `fetch(literal)` inline), 2 causas mayores escaladas a IDs nuevos (FIX-027, NET-022b). Smoke test ETCA: api/* total inbound sources 12 → 18 (+6), 5 APIs pasan de huérfano a connected. Sin regresión en health (73.68%).
**Detalle completo:** `C:\Users\b70_r\.claude\results\compass-fix026-20260415.md`

### Parte A — Template UX

El template viejo tenía `_comment` + `_how_to_use_*` + `_examples_*` pero Beto indicó que no era suficientemente claro. Rediseño:

- Shape **triplet-per-campo**: `_how_to_<campo>` (tips cortos) → `_example_<campo>` (datos fake-realistic) → `<campo>` (vacío). El user ve el contrato (how_to), el shape concreto (example) y el slot para su data (real field) uno al lado del otro.
- Ejemplos con nombres realistas: `includes/autoload.php`, `wp-content/themes/mytheme/functions.php`, `scripts/Search-Replace-DB/index.php`, `MercadoPago`, `MyProject-JS-ApiWrapper`. Cero `foo.php`/`bar.js`.
- `_README` reescrito con workflow de 5 pasos (de uso del tool a cada campo) + regla de merge explícita.
- El `_example_definitions` incluye 2 entries: una PHP con inbound+outbound, y una JS con custom wrapper `apiReq\s*\(...)` — directamente útil para proyectos como ETCA.

### Parte B — Diagnóstico y fix chico del punto 7

**Evidencia recolectada sobre ETCA:**

- Atlas `api/admin-login.php`, `api/session-check.php`, `api/session-logout.php`, `api/upload.php` YA tenían inbound desde `js/admin-*.js` vía pattern `fetch\s*\(\s*['"]([^'"]+)['"]` (agregado en mini-sesión 5.5). No eran el problema.
- Atlas `api/posts.php`, `api/products.php`, `api/orders.php`, `api/authors.php`, `api/media.php`, etc. SIN inbound. Grep en proyecto mostró 3 categorías de referencias no capturadas:
  1. **Fetch inline en HTML/PHP**: `blog.html:273`, `blog-post.html:368-369`, `blog-post.php:469-470` — archivos HTML con `<script>` inline haciendo `fetch('./api/posts.php?...')`. HTML scanner no escaneaba JS embebido.
  2. **Template literals**: `js/tienda-products.js:82` `fetch(\`${API}/products.php\`)`, `js/tienda-checkout.js:105` `fetch(\`${API}/orders.php\`)`. Pattern literal-only no captura backticks con `${}`. Es territorio SEM-020/NET-022 (variable resolution).
  3. **Custom wrapper**: `js/admin-orders.js` usa `apiReq('GET', './api/products.php?admin=1')` — función del proyecto, no captura por pattern default.

**Causa raíz del punto 7:** NO es un bug único. Es la combinación de 3 gaps, 2 de ellos **fuera del scope de 40 líneas** de FIX-026.

**Fix aplicado (scope chico, ~5 líneas):** agregar pattern `\bfetch\s*\(\s*["']([^"']+)["']` a `compass/scanners/html.py::_HTML_ATTR_PATTERNS`. Cubre categoría 1 (fetch inline en HTML con literal).

**Fixes escalados a IDs nuevos en PLAN:**
- **FIX-027 — Inline JS fetch scan in HTML**: el fix actual cubre fetch-with-literal, pero no `apiReq()` ni otros wrappers en el mismo HTML. Eventual solución es extraer bloques `<script>` del HTML y correrlos por el scanner JS para capturar cualquier pattern JS.
- **NET-022b — Custom API wrappers config**: extensible `http_loaders` por proyecto via `compass.local.json`. Útil para `apiReq`/`apiCall`/wrapper custom — cubre la categoría 3 sin código nuevo.

**Smoke test ETCA — inbound APIs antes/después:**

| API | Pre-fix026 | Post-fix026 | Delta |
|---|---|---|---|
| api/admin-login.php | 0 | 1 (js/admin-core.js) | +1 |
| api/posts.php | 0 | 2 (blog.html, blog-post.html) | **+2 nuevo** |
| api/session-check.php | 0 | 1 | +1 |
| api/session-logout.php | 0 | 1 | +1 |
| api/upload.php | 0 | 1 | +1 |
| api/bootstrap.php | 12 | 12 | 0 (PHP-inbound-019) |
| api/products.php | 0 | 0 | — (template literal, escalado) |
| api/orders.php | 0 | 0 | — (template literal, escalado) |
| **Total** | 12 | 18 | **+6** |

Orphans: 62 → 57. Health: 73.68% (pre-fix026 ya estaba en 73.68% con resolvers de mini-5.5, el HTML fetch no mueve health porque los HTMLs ya eran relevantes por CSS+JS linking, solo agrega edges que no cambian conteo de relevantes).

Nota importante: la atribución de api/admin-login.php, session-check.php, session-logout.php, upload.php al contador post-fix026 es porque el cache de fingerprints invalidó ese scan (config no cambió pero en el pre-fix026 se había hecho el scan pre-mini-5.5 regex). El valor incremental REAL de FIX-026 son las 2 entradas a api/posts.php desde HTML.

### Hallazgos

#### 1. Template UX — shape triplet-per-campo adoptado

- **Tipo:** Decisión de diseño FIX-026 parte A.
- **Manifestación:** El feedback de Beto era que el template viejo con solo `_comment` + `_examples_*` en un bloque separado no era obvio. Se adoptó shape: `_how_to_<campo>` (tips 1-5 líneas) → `_example_<campo>` (data fake-realistic en shape JSON válido) → `<campo>` (vacío para que el user llene). Los 3 son keys hermanas, se ven en orden vertical.
- **Scope:** `[GLOBAL]` — patrón reutilizable para cualquier template JSON sin comentarios nativos. Aplicable a cualquier tool que genere `<algo>.local.json` como config user-facing.
- **Estado:** ✓ Cerrado.

#### 2. Punto 7 — el "bug" era un conjunto de 3 gaps, no uno solo

- **Tipo:** Diagnóstico.
- **Manifestación:** El PLAN del briefing original mencionaba "scanner no captura / resolver descarta / classify mal". Evidencia mostró que scanner+resolver funcionan perfecto con literales `fetch('...')`. Los "api/*.php sin inbound" se dividían en:
  1. Fetch en `<script>` inline de HTML (scanner no veía → fix chico aplicado).
  2. Fetch con template literal + variable (`${API}/posts.php`) → SEM-020/NET-022 territory.
  3. Custom wrapper `apiReq()` → project-specific, necesita config override.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** fix #1 aplicado en scope. #2 y #3 escalados como FIX-027 y NET-022b en PLAN.
- **Estado:** ✓ Cerrado — parcial fix en scope + 2 IDs nuevos.

#### 3. Cache de fingerprints sobrevive a cambios en scanners (código, no config)

- **Tipo:** Sutil gotcha de INC-008.
- **Manifestación:** El fingerprint de config se calcula sobre `self.config` (JSON canonical). Cambios en código de `compass/scanners/*.py` no invalidan el cache. Durante el smoke test el primer run reportó `reused_from_cache: 95` aunque `html.py` había cambiado — los edges nuevos no aparecieron hasta borrar `fingerprints.json` a mano. En desarrollo esto se nota; en producción está bien (config de usuario + proyecto determinan re-scan).
- **Scope:** `[PROJECT]` — no es regresión, diseño deliberado de INC-008 para evitar re-scan en cada pull. Pero hay que documentarlo.
- **Acción tomada:** documentado aquí. Para dev loop, borrar `.map/fingerprints.json` o correr con `force_full=True` (CLI-015 lo expondrá como `--full`).
- **Estado:** ✓ Cerrado.

#### 4. Pattern `fetch(...)` en HTML scanner — riesgo de falso positivo mínimo

- **Tipo:** Decisión de diseño del fix chico.
- **Manifestación:** Agregar `\bfetch\s*\(\s*["']([^"']+)["']` al HTML scanner podría en teoría matchear `fetch` en texto copy del HTML (ej. blog post sobre APIs). Mitigación: el pattern exige `\b` + `(` + quote inmediatos, así que solo matchea llamadas reales. Smoke test sobre ETCA: 0 falsos positivos, 2 edges reales nuevos (blog.html → api/posts.php, blog-post.html → api/posts.php × 2 literales distintos).
- **Scope:** `[NO-FIX]` — diseño validado.
- **Estado:** ✓ Cerrado.

#### 5. Sin archivos obsoletos para mover a `.quarantine/`

- **Tipo:** Higiene de cierre.
- **Manifestación:** Sólo edits in-place: `compass/core.py` (`_LOCAL_TEMPLATE`), `compass/scanners/html.py` (+1 pattern), `PLAN.md` (+2 IDs nuevos, FIX-026 marcado completada).
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

---

## NIVEL 5.5 · Mini-sesión pre-6 · HTML-019 + PHP-inbound-019 + GRF-021 — HTML scanner + PHP __DIR__ + Graph cleanup

**Fecha:** 2026-04-15
**Subagente:** `architect_system_design`
**Resultado:** OK — 3 IDs implementados. Compass self-test OK. ETCA smoke test: health 44.74% → 57.89%, ghost nodes eliminados (0), HTML orphans 100% → 67% (15 de 46 ahora connected), API bootstrap.php resuelto (12 edges inbound nuevos).
**Detalle completo:** `C:\Users\b70_r\.claude\results\compass-mini-session-pre6-20260415.md`

Tres tareas en una sola sesión, ejecución en orden PHP-inbound-019 → HTML-019 → GRF-021.

**PHP-inbound-019:** Agregada regex `require(?:_once)?\s+[A-Z_]+\s*\.\s*'([^']+)'` a `Vanilla-Web-Stack-PHP::patterns.outbound` en `mapper_config.json`. Fix adicional en `PathResolver._resolve_php`: leading-slash (`/bootstrap.php`) capturado por el nuevo pattern se trata como source-dir-relative (strip de `/`). Eliminada pattern zombie `header\(` (sin grupo de captura). Resultado: 12 APIs de ETCA ahora resuelven edge a `api/bootstrap.php`.

**HTML-019:** Creado `compass/scanners/html.py` con `HtmlScanner` dedicado (Tier 3, 9 regex para `<script src>`, `<link href>`, `<img src>`, `<a href>`, `<form action>`, `<iframe src>`, `<video src>`, `<source src>`, `<audio src>`). `PathResolver._resolve_html` maneja: fragments (#anchor) → None, schemes inresolubles (mailto/tel/javascript/data) → None, URLs absolutas (http/https) → None (dejan pasar al caller para clasificación external), query/fragment stripping, rutas sin extensión (prueba .html/.htm/.php + directorio/index.*), root-relative vs file-relative. Registrado en dispatcher (`scanners/__init__.py`), `.htm` agregado a `_EXTENSION_LANGUAGE`, `text_extensions`, `stack_markers.Web-Static`. `language_grammars.html: "regex_only"`.

**GRF-021:** Implementado modelo de 3 categorías en `core.py`:
1. Archivo del repo → nodo + edge normal (sin cambio).
2. External service → nodo `[EXTERNAL:<label>]` con `shape=cylinder, color="#cc0000", fillcolor="#ffcccc"`, edge `color="#cc4400"`. Config `external_services` con 7 entries (Anthropic, OpenAI, Supabase, Stripe, OpenRouter, Gemini, ChromaDB).
3. Builtin/stdlib/no-resolvable → descartado del grafo, guardado en `atlas.files[path].metadata.calls`.

Limpieza de patterns: `RegexFallbackScanner` ahora ignora patterns sin grupo de captura (` compiled.groups < 1`). Eliminadas patterns zombie de `WordPress-Development` outbound (`wp_remote_get`, `get_option`, `global $wpdb`, `curl_exec`, `update_post_meta` — todos sin capture group). `Vanilla-Web-Stack-JS` outbound: reemplazados `fetch\(` y `document.querySelector` (sin capture) por `fetch\s*\(\s*['"](…)['"]` e `import … from '(…)'` (con capture). `_SCHEMA_SECTIONS` extendido con `external_services`.

### Hallazgos

#### 1. URLs absolutas (https://) se resolvían como paths relativos en Windows

- **Tipo:** Bug descubierto durante smoke test.
- **Manifestación:** `Path('https://etca.com.ar/').resolve()` en Windows crea `C:\...\proyecto\https:\etca.com.ar` que es "relative_to" el project_root. Resultado: 1036 URLs aparecían como nodos archivo en el grafo.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** `_resolve_html` ahora devuelve `None` (no el URL crudo) para schemes http/https/protocol-relative. El caller (`_classify_outbound`) descarta o clasifica como external_service según config.
- **Estado:** ✓ Cerrado.

#### 2. Health score bajó de 70.39% (cached) a 57.89% (fresh)

- **Tipo:** Diferencia entre cached y fresh scan.
- **Manifestación:** El primer run de ETCA (con cache de Sesión 5) daba 70.39% porque el cache contenía edges ghost (document.querySelector, curl_exec, etc.) que inflaban `relevant_files`. Al borrar fingerprints y hacer full rescan, esos edges desaparecen y el relevance real es menor. Health baseline correcto post-mini-sesión: **57.89%** vs. 44.74% pre-sesión (mejora real de +13.15pp).
- **Scope:** `[NO-FIX]` — esperado, la métrica nueva refleja la realidad.
- **Estado:** ✓ Cerrado.

#### 3. `_scan_file` ahora retorna 5-tupla en vez de 4-tupla

- **Tipo:** Breaking change en interfaz interna.
- **Manifestación:** `metadata_calls` (5to return value) se agrega al cache como campo `metadata_calls` y se re-emite en `_apply_cached_scan`. Caches de runs anteriores (sin el campo) funcionan — `cached.get("metadata_calls") or []` devuelve lista vacía. Sin embargo, la primera run post-update requiere borrar fingerprints para que `metadata.calls` se pueble correctamente.
- **Scope:** `[NO-FIX]` — el config fingerprint cambió (por `external_services` nuevo), así que el cache se invalida automáticamente.
- **Estado:** ✓ Cerrado.

#### 4. Las patterns captureless ahora se ignoran silenciosamente en RegexFallbackScanner

- **Tipo:** Decisión de diseño GRF-021.
- **Manifestación:** Toda pattern sin grupo `(...)` se descarta en constructor de `RegexFallbackScanner` (`compiled.groups < 1`). Esto es más robusto que eliminar cada pattern zombie manualmente: cualquier pattern vieja sin capture se ignora sin romper. Las inbound patterns no se ven afectadas (inbound scoring usa `re.search` en core.py, no el scanner).
- **Scope:** `[NO-FIX]` — diseño defensivo.
- **Estado:** ✓ Cerrado.

#### 5. `Vanilla-Web-Stack-JS` outbound: fetch y import ahora con capture groups

- **Tipo:** Mejora colateral de GRF-021.
- **Manifestación:** `fetch\(` fue reemplazado por `fetch\s*\(\s*['"]([^'"]+)['"]` — captura el URL literal del primer argumento. `document.querySelector` fue eliminado (no es una dependencia). Agregado `import … from '(…)'` para capturar imports ES6 en vanilla JS.
- **Scope:** `[NO-FIX]` — las patterns viejas sin capture eran ruido.
- **Estado:** ✓ Cerrado.

#### 6. ETCA: 31 HTML orphans restantes son legítimos

- **Tipo:** Validación de resultado.
- **Manifestación:** Los 31 HTML orphans son: entry points web (`403.html`, `404.html`, `500.html`, `503.html`, `admin.html`, `blog-post.html`, `sobre-etca.html`), Google verification (`googledca1e28e66887e10.html`), brandbook drafts (`brandbook-etca/*.html`), y engine test (`etca-enginev4/index-light.html`). Ninguno está referenciado por otro archivo del repo — son legítimamente huérfanos.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

#### 7. Sin archivos obsoletos para mover a `.quarantine/`

- **Tipo:** Higiene de cierre.
- **Manifestación:** Las modificaciones extendieron código y config existente; se creó un archivo nuevo (`html.py`). No se reemplazaron archivos completos ni quedaron artefactos legacy.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

---

## NIVEL 5 · Sesión 5 · DYN-007 + INC-008 + DEF-017 — Dynamic deps + Incremental + Language filter

**Fecha:** 2026-04-15
**Subagente:** `architect_system_design`
**Resultado:** OK — los 3 IDs implementados sin regresión funcional. Smoke test Compass pasa de 271ms (RUN1 fresh) a 131ms (RUN2 cached) = 2.07× speedup. Smoke test ETCA pasa de 1197ms a 579ms = 2.07× speedup; **0 ghost edges cross-lenguaje** (HTML→`document.querySelector`, JS→PHP-only, CSS→cualquiera, todos en 0). Total outbound de ETCA cae 154→61 al filtrar el ruido cross-lenguaje. Health Compass cae 81.82%→63.64% y ETCA 67.76%→44.74% — esperado: la métrica vieja contaba archivos "relevantes" gracias a matches espurios cross-lenguaje, con DEF-017 esos archivos vuelven a ser correctamente irrelevantes.
**Detalle completo:** `C:\Users\b70_r\.claude\results\compass-session5-20260415.md`

Tres tareas en una sola sesión, ejecución en orden DEF-017 → INC-008 → DYN-007. **DEF-017** agrega campo `language`/`languages` a cada entry de `definitions[]` y filtra al construir `RegexFallbackScanner` y al aplicar inbound scoring en `_scan_file`; backward-compat: definitions sin `language` aplican a todos. **INC-008** introduce `.map/fingerprints.json` con SHA-256 por archivo + per-file scan cache (outbound_targets, inbound_patterns, tech_scores, is_relevant, stack); el cache se invalida globalmente si el config cambia (config_fingerprint sobre el JSON canonicalizado); `analyze()` invoca `reset_scanner_cache()` al inicio para no servir scanners stale (Sesión 4 hallazgo #5); el constructor acepta `force_full=False` reservado para CLI-015 (`--full`). **DYN-007** agrega `dynamic_deps` como sección top-level del config (acepta `string` descripción, `list` targets o `dict` con `targets`); `_compute_orphans()` corre al cierre de `analyze()`, marca cualquier archivo sin inbound real como `orphan_reason: "no_inbound"` y excluye los declarados (owners o targets) marcándolos `dynamic_declared`. Atlas extendido con `files: {path: {stack, orphan_reason, ...}}` y `orphans: [path, ...]`.

### Hallazgos

#### 1. Health score baja en ambos proyectos al filtrar ruido cross-lenguaje

- **Tipo:** Cambio observable de métrica, no regresión.
- **Manifestación:** Compass 81.82%→63.64% (relevantes 9→7), ETCA 67.76%→44.74% (relevantes 103→68). El delta viene exclusivamente de archivos que antes matcheaban patterns que no aplican a su lenguaje (ej. HTML matcheando `document.querySelector` vía `Vanilla-Web-Stack`, JSON matcheando todo lo que es regex, etc.). El bucket de `unify_external_nodes` (axios, openai, etc.) viene del scanner outbound, y al filtrar por lenguaje los configs JSON dejan de generar edges fantasma a esos.
- **Scope:** `[NO-FIX]` — la métrica nueva refleja la realidad mejor; el score de SCR-009 (NIVEL 6) va a re-descomponer estos números en dimensiones.
- **Estado:** ✓ Cerrado.

#### 2. PHP path resolution incompleto — surfaceado por DYN-007

- **Tipo:** Gap pre-existente expuesto por nueva métrica.
- **Manifestación:** ETCA reporta 152 orphans (es decir, todos los archivos). El motivo: `PathResolver._resolve_php` no maneja `/bootstrap.php` con leading-slash (estilo "root del proyecto") ni `__DIR__ . 'sub/file.php'`. Los includes capturados terminan en el fallback de `_resolve_outbound_node` como labels externos (`/bootstrap.php`), nunca matchean `api/bootstrap.php` real. Resultado: ningún archivo aparece como inbound target interno.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** tarea **PHP-018** agregada al PLAN.md como `pendiente`. No se intentó fix en esta sesión (fuera de scope).
- **Estado:** ⏳ Pendiente — asignado a **PHP-018**.

#### 3. Definitions con scope multi-lenguaje requirieron split

- **Tipo:** Decisión de schema — opción "language" string vs "languages" lista.
- **Manifestación:** El schema soporta ambas formas (single o list), pero al migrar `mapper_config.json` apareció el dilema con `Tauri-Desktop-App` (cuyo inbound `tauri::command` es Rust, mientras el outbound `@tauri-apps/api`/`window.__TAURI__` es JS) y similar con `Vanilla-Web-Stack` (PHP includes vs JS `document.querySelector`). Se optó por **splitear** estas definitions en entries separadas con `language: "..."` (ej. `Tauri-Desktop-App-JS` + `Tauri-Desktop-App-Rust`, `Vanilla-Web-Stack-PHP` + `Vanilla-Web-Stack-JS`), preservando el campo `stack` original para que el agrupamiento por stack siga unificado.
- **Justificación:** mantiene cada entry con un único lenguaje claro (más fácil de razonar y testear); el campo `languages` queda disponible en el schema para el caso JS+TS donde las patterns son legítimamente idénticas (ej. `Modern-Web-Stack-JS` + `Modern-Web-Stack-TS` también se splitearon; podrían unificarse con `languages: ["javascript", "typescript"]`).
- **Scope:** `[NO-FIX]` — decisión cerrada.
- **Estado:** ✓ Cerrado.

#### 4. Config fingerprint global como invalidador del cache

- **Tipo:** Decisión de diseño para INC-008.
- **Manifestación:** El cache per-archivo guarda outbound_targets ya resueltos (paths posix relativos) y inbound_patterns ya matcheados. Si el config cambia entre runs (nueva pattern, nuevo `unify_external_nodes`, etc.) los edges cacheados quedan inconsistentes. Decisión: hashear el JSON canonicalizado (`sort_keys=True`) del config completo y persistirlo en `fingerprints.json::config_fingerprint`. Si no coincide con el actual → tirar todo el cache y re-escanear full.
- **Justificación:** alternativa más fina (invalidar solo los archivos cuyas patterns cambiaron) requiere trackear qué pattern matcheó qué archivo — más complejo y más superficie para bugs. El config cambia rara vez en comparación con archivos del proyecto, así que el hit de re-escanear todo es aceptable.
- **Scope:** `[NO-FIX]` — diseño consciente.
- **Estado:** ✓ Cerrado.

#### 5. `__init__.py` sigue ignorado por `ignore_patterns`, no aparece en orphans ni en files

- **Tipo:** Observación sobre interacción IGN-016 ↔ DYN-007.
- **Manifestación:** El `compass.local.json` de prueba declaró `compass/scanners/__init__.py` como dynamic owner. El run no marcó nada porque el archivo está filtrado por `ignore_patterns: ["__init__.py"]` antes de entrar al walk de `analyze()`, así que nunca llega al cómputo de orphans. Quien quiera trackear `__init__.py` debe removerlo de ignore_patterns en su `compass.local.json`.
- **Scope:** `[NO-FIX]` — comportamiento consistente con IGN-016. Documentado por trazabilidad.
- **Estado:** ✓ Cerrado.

#### 6. `_apply_cached_scan` no replica `tech_scores` mediante un set, sino sumando delta

- **Tipo:** Sutileza de diseño.
- **Manifestación:** `tech_scores` se re-construye desde cero en cada `analyze()`. Los archivos cacheados re-aplican su `tech_scores` delta (ej: `{"AI-Agent-Framework": 30}`) sumando al diccionario in-memory. Esto preserva exactamente la lógica del scanner viejo (cada match suma 10 a la categoría) sin reintroducir el costo del regex.
- **Scope:** `[NO-FIX]` — invariante intencional.
- **Estado:** ✓ Cerrado.

#### 7. Sin archivos obsoletos para mover a `.quarantine/`

- **Tipo:** Higiene de cierre.
- **Manifestación:** Las modificaciones extendieron schemas (campo `language` en definitions, secciones `dynamic_deps`/`files`/`orphans` en atlas, `fingerprints.json` nuevo) sin reemplazar archivos pre-existentes ni cambiar formatos de output binario-incompatible. El template legacy ya estaba quarentinado en Sesión 2.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

#### 8. Followup: `compass.local.json` fixture creado y borrado durante test

- **Tipo:** Nota de proceso.
- **Manifestación:** Para validar DYN-007 se creó temporalmente `.map/compass.local.json` con un bloque `dynamic_deps`, se ejecutó el test, y luego se borró para devolver el repo al estado previo. El template `compass.local.template.json` documentando la sección quedó intacto en `.map/`.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado.

---

## NIVEL 4 · Sesión 4 · RES-002 + SCN-003 — Path Resolver + Scanner dispatcher

**Fecha:** 2026-04-15
**Subagente:** `architect_system_design`
**Resultado:** OK — smoke test limpio (11 archivos, 9 relevantes, health 81.82%, **0 nodos fantasma** confirmado por barrido explícito). Bug histórico de `_resolve_identity` neutralizado por diseño.
**Detalle completo:** `C:\Users\b70_r\.claude\results\compass-sesion4-res002-scn003-20260415.md`

Se implementó `PathResolver` (clase con `resolve(raw, language, source_file) -> str | None` + submétodos `_resolve_php`/`_resolve_js`/`_resolve_python`/`_resolve_generic`) y el dispatcher de scanners de 3 tiers (`PythonScanner` con `ast` stdlib, `TreeSitterScanner` genérico opt-in via `importlib`, `RegexFallbackScanner` config-driven, `NullScanner` no-op). `analyze()` en `core.py` refactorizado: delega a `_scan_file()` que consume `get_scanner()` + `PathResolver`. Los 8 archivos `modified` según git: sin creación ni borrado, solo implementación de placeholders que venían como stubs desde MOD-000 (commit `a673400`).

### Hallazgos

#### 1. Hallazgo #7 de Sesión 2 (`script_dir`) — reasignado a CLI-015

- **Tipo:** Scope mismatch — RES-002 no cubrió lo esperado.
- **Manifestación:** En SESSION_LOG de Sesión 2 se había asignado este hallazgo a RES-002 (NIVEL 4). El subagente aclaró que `PathResolver(project_root)` resuelve un problema **ortogonal**: traduce imports raw a paths dentro del proyecto analizado, NO localiza el `mapper_config.json` basal del repo de Compass. `script_dir = Path(__file__).parent.parent.absolute()` en `compass/core.py::__init__` (línea 90) sigue intacto: si `core.py` baja una capa (ej. `compass/engine/core.py`), `.parent.parent` rompe silenciosamente.
- **Scope:** `[PROJECT]`.
- **Decisión del usuario:** plegar a **CLI-015** (NIVEL 8). El entry point refactoreado va a localizar `mapper_config.json` de forma robusta (walk-up desde `__file__`, env var `COMPASS_HOME`, o flag `--home`) y pasarlo como path absoluto al constructor. `core.py` deja de deducir el root del layout.
- **Acción tomada:** nota agregada a `PLAN.md::CLI-015` con la estrategia sugerida.
- **Estado:** ⏳ Pendiente — asignado a **CLI-015** (NIVEL 8).

#### 2. Divergencia del PLAN: scanner elegido por extensión, no por stack

- **Tipo:** Decisión de diseño consciente.
- **Manifestación:** El PLAN decía "`analyze()` llama al dispatcher con el lenguaje detectado por STK-001". La implementación usa un dict `_EXTENSION_LANGUAGE` en `core.py` que mapea extensión → lenguaje, y eso es lo que va a `get_scanner()`. El stack sigue siendo contexto semántico para scoring, no para elegir scanner.
- **Justificación:** un archivo `.php` dentro de un árbol `WordPress-Development` sigue siendo PHP para extracción de imports; el stack informa scoring, la extensión informa parsing. Coherente con MST-006 (stacks por subárbol, archivos con lenguaje propio).
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado — decisión correcta.

#### 3. `_resolve_identity()` conservado con pragma deprecated

- **Tipo:** Código muerto deliberado.
- **Manifestación:** Método viejo en `core.py` líneas 305-331 con docstring `DEPRECATED` y comentario `pragma: no cover`. No se llama desde ningún lado, no se ejecuta.
- **Justificación:** referencia histórica del bug de nodos fantasma (ver memoria `feedback_resolve_identity.md`). No es archivo independiente, no aplica `.quarantine/`.
- **Scope:** `[NO-FIX]` — deliberado.
- **Estado:** ✓ Cerrado.

#### 4. `RegexFallbackScanner` consume TODAS las outbound patterns sin filtro por lenguaje

- **Tipo:** Preservación de comportamiento viejo con ruido latente.
- **Manifestación:** `RegexFallbackScanner` recibe el dict completo de `definitions[].patterns` (inbound/outbound) y aplica sobre el contenido del archivo sin distinguir lenguaje. Un archivo PHP puede matchear patterns pensados para otro stack si las regex son permisivas.
- **Justificación del desvío de Sesión 4:** equivalencia funcional con el scanner regex del core viejo; filtrar por lenguaje requería agregar campo `language` a cada `definitions[]`, fuera de alcance de la sesión.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** convertido en tarea explícita del PLAN → **DEF-017 Language filter en definitions[]**. Decisión de Beto: no dejar esto como parche abierto en el log porque es el tipo de cosa que se pierde o falla silencioso; mejor tarea con ID y estado visible.
- **Estado:** ⏳ Pendiente — asignado a **DEF-017** (tarea independiente, sin nivel bloqueante).

#### 5. Cache de scanner en `get_scanner()` con `id(config)` en la clave

- **Tipo:** Gotcha anticipado para INC-008.
- **Manifestación:** `compass/scanners/__init__.py::get_scanner()` cachea instancias por `(language, id(config))`. Si INC-008 implementa recarga de config dentro del mismo proceso (o múltiples runs), el cache puede servir scanners con patterns obsoletos hasta que cambie la identidad del dict.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** nota agregada a `PLAN.md::INC-008` para que el agente de NIVEL 5 exponga `reset_cache()` o invalide al inicio de cada run.
- **Estado:** ⏳ Pendiente — asignado a **INC-008** (NIVEL 5).

#### 6. tree-sitter queries iniciales solo para PHP / JS / TS

- **Tipo:** Completitud del Tier 2.
- **Manifestación:** `_NODE_TYPES_BY_LANGUAGE` en `treesitter.py` cubre PHP, JavaScript y TypeScript. Otros lenguajes con grammar instalada (Ruby, Go, Rust, etc.) caerían a extracción vacía (`[]`) hasta que se agregue su entrada.
- **Scope:** `[NO-FIX]` — agregar una query es edición local del dict, esperado por diseño modular.
- **Estado:** Cerrado.

#### 7. Fallback regex conservador en `_resolve_outbound_node` (no destacado en reporte inicial)

- **Tipo:** Branch de aceptación no destacado.
- **Manifestación:** `core.py::_resolve_outbound_node` (~línea 545) tiene un fallback `^[A-Za-z0-9_.\-]+$` más lógica auxiliar para aceptar bare specifiers y paths como nodos externos cuando `PathResolver.resolve()` retorna `None`. Es el reemplazo **conservador** del regex agresivo viejo — mantiene graph building para externos (`openai`, `react`, `@tauri-apps/api`) sin reintroducir fantasmas. El subagente no lo destacó inicialmente y apareció en la verificación puntual.
- **Scope:** `[NO-FIX]` — diseño correcto, a monitorear en runs reales.
- **Estado:** Cerrado.

#### 8. Validación explícita: 0 nodos fantasma

- **Tipo:** Validación del fix histórico.
- **Manifestación:** Barrido explícito del `atlas.json` post-smoke confirmó que todos los outbound targets apuntan a archivos existentes en disco. El bug viejo de `_resolve_identity` (nodos con path inventado al procesar basura) queda neutralizado por el diseño del nuevo `PathResolver` (retorna `None` si no hay certeza) + fallback conservador del hallazgo #7.
- **Scope:** `[NO-FIX]`.
- **Estado:** ✓ Cerrado — confirmación del éxito del refactor.

---

## NIVEL 3 · Mini-sesión · STK-001b — Extension hints al config

**Fecha:** 2026-04-15
**Subagente:** `architect_system_design`
**Resultado:** OK — smoke tests idénticos a Sesión 3 (Compass `{"": "Python"}` health 18.18%; ETCA raíz `Vanilla-Web-Stack` + 2 subdirs `WordPress-Development` health 75%). Regresión cero.
**Detalle completo:** `C:\Users\b70_r\.claude\results\compass-stk001b-20260415.md`

Refactor puro para cerrar el hallazgo #2 de Sesión 3. Se movió el dict hardcoded `_EXTENSION_STACK_HINTS` del `stack_detector.py` a `mapper_config.json::stack_markers`. El agente eligió **opción A** (co-ubicar `extensions` dentro de cada entry de `stack_markers`, junto a `lock_files`/`framework_markers`/`content_markers`), argumentando que son señales del mismo dominio — una sección top-level separada se iría desincronizando al agregar stacks nuevos. Se incorporaron 9 entries (Python, JavaScript, TypeScript, PHP, Ruby, Go, Rust, Java, Web-Static).

### Hallazgos

#### 1. Orden semántico de `stack_markers` en el JSON

- **Tipo:** Consecuencia del schema elegido.
- **Manifestación:** Si dos stacks declararan la misma extensión, gana el primero (regla "order of JSON wins"). Hoy no hay colisiones reales — los stacks framework-like (WordPress-Development) no declaran `extensions`, y los genéricos tienen extensiones disjuntas.
- **Scope:** `[NO-FIX]` — documentado. Mitigación disponible: reordenar vía `compass.local.json` si alguna vez aparece colisión.
- **Estado:** Cerrado.

#### 2. Merge shallow de `compass.local.json` permite overrides de `stack_markers`

- **Tipo:** Beneficio colateral.
- **Manifestación:** Como efecto lateral de mover el mapping al config, ahora el usuario puede sobrescribir o extender `extensions` por proyecto desde `compass.local.json` sin tocar código.
- **Scope:** `[NO-FIX]` — feature emergente, útil para proyectos con extensiones custom.
- **Estado:** Cerrado.

#### 3. `compass/core.py` sin cambios

- **Tipo:** Observación sobre el diseño de Sesión 3.
- **Manifestación:** `StackDetector` ya recibía `stack_markers` por constructor desde la Sesión 3, por lo que externalizar el mapping no requirió tocar `core.py`. Diseño correcto de la sesión previa.
- **Scope:** `[NO-FIX]`.
- **Estado:** Cerrado.

---

## NIVEL 3 · Sesión 3 · STK-001 + MST-006 — Stack Detection + Multi-stack

**Fecha:** 2026-04-15
**Subagente:** `architect_system_design`
**Resultado:** OK — smoke test Compass (`{"": "Python"}`, health 18.18% sin regresión), smoke test ETCA (StackMap con 3 scopes — raíz `Vanilla-Web-Stack` + 2 subdirs `WordPress-Development`, 152 archivos / 114 relevantes, health 75%).
**Detalle completo:** `C:\Users\b70_r\.claude\results\compass-stk001-mst006-20260415.md`

Se creó `compass/stack_detector.py` (~190 líneas) con clase `StackDetector` implementando la jerarquía **lock files → framework markers → content markers → extensión mayoritaria**, una capa por método privado. Helper `resolve_file_stack()` con **longest-prefix match** sobre el StackMap. `compass/core.py` instancia el detector en `__init__`, nuevo método `resolve_stack_for(rel_path)`, y `analyze()` mergea el conteo por stack en `identities` con campo `source`. `atlas.json` expone `stack_map` top-level. MST-006 funciona: subdirectorios con framework markers distintos al del raíz aparecen como scopes separados.

### Hallazgos

#### 1. Auto-referencia de content markers en archivos no-código

- **Tipo:** Falso positivo en la capa content-markers.
- **Manifestación:** `mapper_config.json` y docstrings del propio detector contenían strings como `"Plugin Name:"` que matcheaban content markers — el detector se identificaba a sí mismo como WP.
- **Scope:** `[PROJECT]`.
- **Acción tomada:** `_CONTENT_SCAN_SKIP_EXTENSIONS` (salta `.json`, `.md`, etc.) y `allow_content=False` al evaluar subdirectorios.
- **Estado:** ✓ Cerrado.

#### 2. `stack_markers` del config no cubre lenguajes genéricos (Python, JS, etc.)

- **Tipo:** Gap de schema vs. implementación.
- **Manifestación:** `mapper_config.json::stack_markers` solo lista `WordPress-Development`. Para Python/JS/etc. el detector usa un mapping hardcodeado `_EXTENSION_STACK_HINTS` dentro de `stack_detector.py`.
- **Scope:** `[PROJECT]`.
- **Decisión del usuario:** opción B — externalizar a `mapper_config.json`.
- **Acción tomada:** tarea **STK-001b** agregada a PLAN.md y ejecutada como mini-sesión. Ver entrada de STK-001b arriba.
- **Estado:** ✓ Cerrado (resuelto por STK-001b).

#### 3. Comportamiento de ETCA: raíz detectada como `Vanilla-Web-Stack`, no `WordPress-Development`

- **Tipo:** Observación sobre el diseño multi-stack.
- **Manifestación:** El briefing esperaba que ETCA detectara WP en raíz. En realidad la raíz del proyecto no tiene `wp-config.php`/`functions.php` — solo `index.php` y PHPs sueltos. Los subdirectorios con framework markers de WP sí se detectan correctamente como scopes WP.
- **Scope:** `[NO-FIX]` — es exactamente el comportamiento diseñado para MST-006 (stack por subárbol, no uno global forzado).
- **Decisión del usuario:** aceptado — ETCA es vanilla con un theme WP en un subdir, el stack mapping refleja fielmente esa realidad.
- **Estado:** ✓ Cerrado.

#### 4. `.map/mapper_config.template.json` legacy dentro del proyecto ETCA

- **Tipo:** Ruido en proyecto auditado externo (no en Compass).
- **Manifestación:** ETCA tiene el template viejo del schema v1 en su propio `.map/`. Fuera del scope de esta sesión.
- **Scope:** `[PROJECT]` → asignado a VAL-014.
- **Decisión del usuario:** el caso debe quedar cubierto por VAL-014 (NIVEL 7) — Compass debe detectar artefactos legacy en `.map/` del proyecto auditado y emitir `CONFIG WARNINGS` explícito, porque indican una corrida previa con schema viejo sin migrar. PLAN.md::VAL-014 actualizado con esta regla. Acción inmediata: Beto borrará manualmente el archivo residual en ETCA.
- **Estado:** ⏳ Pendiente — asignado a **VAL-014** (NIVEL 7). Borrado manual en ETCA a cargo del usuario.

#### 5. Cambios de schema en `atlas.json` (`stack_map` top-level + `identities[].source`)

- **Tipo:** Consecuencia mecánica del MST-006.
- **Scope:** `[NO-FIX]` — esperado y necesario para que SCN-003 y SCR-009 (niveles 4 y 6) consuman el mapa.
- **Estado:** Cerrado.

#### 6. `StackDetector` no filtra patterns por stack del archivo

- **Tipo:** Scope fuera de esta sesión.
- **Manifestación:** La selección de scanner/patterns por archivo según su stack es trabajo de SCN-003 (NIVEL 4). El detector solo provee el mapa; el consumo fino es de los scanners.
- **Scope:** `[NO-FIX]`.
- **Estado:** Cerrado — documentado para NIVEL 4.

#### 7. Hallazgo #7 de Sesión 2 (`script_dir` acoplado a layout) — intacto

- **Tipo:** Respeto del briefing.
- **Manifestación:** El subagente no tocó el acoplamiento `Path(__file__).parent.parent`, tal como se le indicó. Sigue asignado a RES-002 (NIVEL 4).
- **Scope:** `[NO-FIX]`.
- **Estado:** ⏳ Pendiente en RES-002.

---

## NIVEL 2 · Sesión 2 · CFG-005 + IGN-016 — Config schema v2 + ignore patterns

**Fecha:** 2026-04-15
**Subagente:** `architect_system_design`
**Resultado:** OK — smoke test limpio, 11 total / 2 relevant, health 18.18%.
**Detalle completo:** `C:\Users\b70_r\.claude\results\compass-cfg005-ign016-20260415.md`

Ambas tareas se ejecutaron en un solo commit lógico porque comparten `mapper_config.json` y `compass/core.py::load_config_hierarchy()`. Schema pasó de 2 a 6 secciones (`basal_rules`, `stack_markers`, `language_grammars`, `scoring`, `graph`, `definitions`). IGN-016 agregó `ignore_files` (match exacto) + `ignore_patterns` (fnmatch glob) en `basal_rules`, aplicados en `_index_existing_files()` y `analyze()`.

### Hallazgos

#### 1. Rename local: `mapper_config.json` (local) → `compass.local.json`

- **Tipo:** Alineación con PLAN.
- **Detalle:** PLAN especifica `compass.local.json` desde CFG-005; el código previo leía `.map/mapper_config.json`. Se implementó el nuevo nombre y se dejó shim backward-compat con warning si existe el legacy.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 2. `ensure_local_template()` genera overrides-only

- **Tipo:** Cambio semántico alineado con PLAN.
- **Detalle:** Antes copiaba el global completo como template. Ahora genera `compass.local.template.json` con shells vacíos de `basal_rules` y `definitions` + `_comment` explicativo.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 3. Default `__init__.py` migrado a `ignore_patterns`

- **Tipo:** Limpieza consistente con el schema.
- **Detalle:** El código previo hardcodeaba `__init__.py` como default en `ignore_files` (matcheaba por basename). Con IGN-016, `ignore_files` es "path exacto" y `ignore_patterns` es fnmatch. Se movió `__init__.py` al config basal como pattern — ahora es configurable. Comportamiento equivalente.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

#### 4. `self.graph_rules` introducido en `core.py`

- **Tipo:** Consecuencia mecánica del schema nuevo.
- **Detalle:** `unify_external_nodes` e `ignore_outbound_patterns` viven ahora en `graph` (no en `basal_rules`). Se agregó `self.graph_rules = self.config.get("graph", {})` en `__init__` y se actualizaron los 2 call sites en `analyze()`. `self.scoring_rules` también creado por simetría (no consumido todavía).
- **Scope:** `[NO-FIX]` — no hay acción.
- **Estado:** Cerrado.

#### 5. `relevant_files` cayó 3 → 2 post-refactor

- **Tipo:** Artefacto de auto-referencia del scanner regex sobre su propio código.
- **Detalle:** Bajo el schema viejo, literal `"anthropic"` en `self.rules.get("unify_external_nodes", [])` hacía que `compass/core.py` matcheara un pattern outbound de `AI-Agent-Framework`. Con el schema nuevo ese literal ya no vive en `core.py` (accedido vía `self.graph_rules`). Es ruido inherente del scanner regex contra sí mismo.
- **Scope:** `[NO-FIX]` — desaparece definitivamente cuando SCN-003 reemplace regex scanner por AST/tree-sitter.
- **Estado:** Cerrado.

#### 6. Campo `priority` removido de `definitions`

- **Tipo:** Limpieza de schema.
- **Detalle:** El schema v1 tenía `priority: 10` en cada def. Nunca se usaba en `analyze()` — campo muerto. El schema v2 del PLAN no lo lista, así que se removió.
- **Scope:** `[PROJECT]` (reclasificado por decisión del usuario — no es consecuencia mecánica sino simplificación deliberada de schema).
- **Acción tomada:** ninguna adicional; documentado aquí para trazabilidad futura si aparece en PLAN.
- **Estado:** ✓ Cerrado.

#### 7. `script_dir = Path(__file__).parent.parent` acopla al layout del paquete

- **Tipo:** Riesgo latente de path resolution.
- **Detalle:** Si alguna sesión futura mueve `core.py` otra capa de profundidad (ej: `compass/engine/core.py`), el `.parent.parent` rompe silenciosamente y `mapper_config.json` deja de encontrarse.
- **Scope:** `[PROJECT]`.
- **Decisión del usuario:** transferir a RES-002 (NIVEL 4, `path_resolver.py`) — es precisamente su dominio.
- **Acción tomada:** marcado pendiente. El briefing de RES-002 debe incluir este hallazgo y resolver el acoplamiento.
- **Estado:** ↻ **Reasignado a CLI-015 (NIVEL 8)** — Sesión 4 confirmó que RES-002 era scope ortogonal (resuelve imports dentro del proyecto analizado, no localiza el config basal del repo de Compass). Ver entrada de Sesión 4 hallazgo #1 para detalle de la reasignación y estrategia sugerida.

#### 8. Archivos obsoletos del schema v1 → movidos a `.quarantine/`

- **Tipo:** Higiene de repositorio (decisión de usuario).
- **Detalle:** `.map/mapper_config.template.json` (3882 B, del schema v1) quedó huérfano tras el rename a `compass.local.template.json`. No se borra para respetar el constraint, pero mantenerlo en `.map/` genera ruido y potenciales errores fantasma.
- **Acción tomada:**
  - Creado `c:\IA_Workspace\herramientas\Architect_compass\.quarantine\` como depósito de obsoletos del proyecto.
  - Movido `.map/mapper_config.template.json` → `.quarantine/mapper_config.template.json.legacy-v1`.
  - Agregado `.quarantine/` a `.gitignore`.
- **Scope:** `[PROJECT]`.
- **Estado:** ✓ Cerrado.

---

## NIVEL 1 · Sesión 1 · MOD-000 — Modularización

**Fecha:** 2026-04-15
**Subagente:** `architect_system_design`
**Resultado:** OK (funcionalmente equivalente al pre-refactor)
**Detalle completo:** `C:\Users\b70_r\.claude\results\compass-mod-000-20260415.md`

### Hallazgos

#### 1. UnicodeEncodeError en el `print` final del emoji `✨`

- **Tipo:** Bug pre-existente, no introducido por el refactor.
- **Manifestación:** `UnicodeEncodeError: 'charmap' codec can't encode character '\u2728'` al final de `finalize()` en Windows. Los artefactos de `.map/` ya están escritos cuando crashea, así que no hay pérdida funcional.
- **Scope:** `[GLOBAL]` — cualquier script Python en Windows con output no-ASCII tiene el mismo problema.
- **Decisión del usuario:** forzar UTF-8.
- **Acción tomada:**
  - Global: la receta ya existe en `topics/windows_env.md` líneas 132-170 (sección "Encoding — dónde usar UTF-8"). No se duplicó.
  - Project: aplicado `sys.stdout.reconfigure(encoding="utf-8")` en `architect_compass.py` (entry point). Smoke test OK — emoji `✨` imprime limpio, sin crash.
- **Estado:** ✓ Cerrado.

#### 2. Contradicción en PLAN.md: `run_audit()` vs `analyze() + finalize()`

- **Tipo:** Imprecisión del PLAN.md, no bug de código.
- **Manifestación:** PLAN.md MOD-000 dice que el entry point llama `ArchitectCompass().run_audit()`, pero en el código real `run_audit()` es un método interno que solo calcula el health score. El `__main__` original ejecutaba `analyze() + finalize()`.
- **Decisión del agente:** preservar comportamiento existente → entry point llama `analyze() + finalize()` en ese orden (match 1-a-1 con el `__main__` del monolito).
- **Scope:** `[PROJECT]` — solo afecta redacción del PLAN.md.
- **Evaluación:** el agente tomó la decisión correcta. El riesgo es que los próximos niveles (CFG-005, INC-008, DIF-010, etc.) referencien `run_audit()` y arrastren la confusión.
- **Decisión del usuario:** corregir PLAN.md.
- **Acción tomada:** grep de `run_audit` en PLAN.md devolvió 2 menciones (líneas 99 y 109). Ambas actualizadas:
  - Línea 99: `(analyze, run_audit, finalize)` → `(analyze, finalize — pipeline principal)`.
  - Línea 109: entry point llama `.analyze()` + `.finalize()` (match con `__main__` del monolito).
- **Estado:** ✓ Cerrado.

#### 3. Ajuste de `script_dir` en `core.py`: `Path(__file__).parent.parent`

- **Tipo:** Ajuste estructural obligatorio por la modularización.
- **Manifestación:** `core.py` vive en `compass/core.py` (un nivel más profundo que el original). Sin el `.parent` adicional, no encontraría `mapper_config.json` en la raíz del proyecto Compass.
- **Scope:** `[NO-FIX]` — consecuencia mecánica esperada. El path resuelto es idéntico al pre-refactor.
- **Acción tomada:** ninguna. Se documenta por trazabilidad.
- **Estado:** Cerrado.

---