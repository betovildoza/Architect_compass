# Roadmap — Architect's Compass

Acá viven **solo las tareas pendientes**, una oración cada una. El detalle ampliado vive en [PLAN.md](PLAN.md) bajo el mismo código (incluidas las completadas, que no se borran de ahí). Al completar: ✅ acá y en PLAN.md, registrar la sesión en [SESSION_LOG.md](SESSION_LOG.md).

**Estados:** ⬜ pendiente · 🔶 en curso · ✅ hecho
**Numeración:** 3char-3num

**Objetivo actual:** completar el grafo frontend (Fase B, prioridad alta) y absorber los quick wins pendientes.

## Convenciones de sesión

- **Cierre de sesión - archivos deprecados:** al terminar una sesión, cualquier archivo del proyecto que quede obsoleto (schemas viejos, templates reemplazados, artefactos de una implementación anterior que ya no se usa) debe moverse a `.quarantine/` con sufijo `.legacy-vN` o similar. No se borran para respetar el histórico, pero no deben quedar en su ubicación original donde puedan ser cargados por error o generar confusión.
- **Archivos invisibles a búsqueda normal** - los siguientes paths están en `.gitignore` y **no aparecen** en `git status`, `grep` recursivo default, ni tracking de VCS. Si una sesión los necesita, el briefing del subagente debe mencionarlos explícitamente:
  - `.quarantine/` - depósito de obsoletos del proyecto.
  - `compass.bat` - launcher local (NO se versiona; cada instalación lo personaliza).
  - `.claude/` - metadata de Claude Code.
  - `.map/` - outputs del tool (atlas.json, connectivity.dot, feedback.log, compass.local.*).

---

## Fase A — Sprint 0.b: tree-sitter como tier default ✅ COMPLETA (S24)

| Código | Estado | Descripción |
|--------|:------:|-------------|
| TSD-045 | ✅ | Tree-sitter como tier default JS/TS/PHP, regex como fallback (deps opcionales, zero-install intacto). |
| TSD-046 | ✅ | Cobertura HTML/CSS vía tree-sitter (única vía de análisis estructural HTML del ecosistema). |
| TSD-047 | ✅ | `symbols.json` enriquecido con `kind`/`range`/`signature` (VERSION 1.1). |
| TSD-048 | ✅ | Validación en 3 testigos (cerbero_cli control, ETCA PHP/HTML, clases.etca TS). |

## Fase B — Grafo frontend completo 🔴 PRIORIDAD ALTA

Dolor #1 medido (no teórico): el frontend desconectado aparece en level2/ETCA/Agente_facundo con reporte dedicado.

| Código | Estado | Descripción |
|--------|:------:|-------------|
| MARKUP-061 | ✅ | Extraer markup (`<link>`/`<script>`/`<img>`) embebido en templates server-side; **verificado en `.php`** (ETCA: 6 nodos conectan en grafo real) + filtrado transversal de comentarios en HTML/CSS/JS/TS/PHP. `.twig`/`.blade`/`.erb`/`.jsp`/`.ejs` cubiertos por clase, **sin testigo** (no afirmados). |
| MARKUP-062 | ⬜ | Verificar en grafo real las extensiones server-side no-`.php` de MARKUP-061 (`.twig`/`.blade.php`/`.erb`/`.jsp`/`.ejs`) cuando haya proyecto testigo. |
| WEB-039 | ⬜ | Framework static path resolution: prefix URL (`/static/`) → filesystem (Flask/FastAPI/Express). **Ampliado:** colisión multi-app (no last-writer-wins → conservar candidatos + desambiguar por existencia/proximidad); testigo l2ae. |
| JSON-058 | ⬜ | Edges de data/config por path literal (`open`/`json.load`/`require`); testigos: `mapper_config.json` suelto en el self-scan + `public/manifest.json` en clases.etca. |
| TIER-062 | ⬜ | `tier=connected` con inbound=0 ∧ ¬entry_point no debe ser "connected" (el tier mide solo outbound y enmascara huérfanos); páginas/endpoints top-level → entry_point. Incluye decisión-abierta: tratamiento de `*.config.js/ts` (framework_markers leídos por build, no por código). Testigos: ETCA (~22 falsos-connected) + clases.etca (configs Next). |
| GHOST-063 | ⬜ | El resolver de edge-targets debe filtrar destinos que caen en `ignore_folders`/build-dirs (no solo dotfiles, como FIX-030); hoy un `import "./.next/..."` dibuja un nodo-fantasma de carpeta excluida. Testigo: clases.etca (`.next/dev/types/routes.d.ts`). |
| CSS-049 | ⬜ | Edges CSS para archivos `.html`: `@import` CSS→CSS (4 variantes) + `<link>`/`<script>` HTML→recurso. **Presunto-implementado vía TSD-046/HTML-019 pero NO comprobado en grafo real** (solo scanner aislado + casos `.html` relativos/root-relativos en CIF/ETCA). Requiere test de no-regresión end-to-end (cascada `@import` de l2ae) antes de cerrar. |

## Fase C — Quick wins

| Código | Estado | Descripción |
|--------|:------:|-------------|
| SER-050 | ⬜ | Sanitizar sentinels `@@LOADER@@` en `atlas.json` antes de serializar. |
| CLI-051 | ✅ | Flag `--version` + versionado `0.1.0` (fuente única `compass/__init__.py::__version__`). |
| CLI-052 | ⬜ | Summary de scope en `compass symbols` (scanned N, excluded X .venv / Y __pycache__). |
| PKG-053 | ⬜ | Resolver colisión `compass/` (paquete) vs `compass.bat` (launcher) en PATH POSIX. |
| IGN-059 | ✅ | `.mcp.json` ignorado desde base (`ignore_patterns` de `mapper_config.json`, junto a sus hermanos). |
| INIT-054 | ⬜ | Edge implícito de package-import Python (importador → `__init__.py` de la cadena). |

## Fase D — Semántica de frameworks

| Código | Estado | Descripción |
|--------|:------:|-------------|
| ENDP-044 | ⬜ | Endpoint highlighting por decoradores (`@app.get`, `@blueprint.route`, `@mcp.tool`, `@api_view`). |

## Fase F — Consultas agente-facing

| Código | Estado | Descripción |
|--------|:------:|-------------|
| QRY-055 | ⬜ | Subcomando `compass impact <archivo>` (blast radius: dependientes transitivos, JSON + tabla rich). |
| MCP-056 | ⬜ | Analizar y decidir expansión a MCP server (reabre D-107); entregable = decisión, no implementación. |
| AUDIT-060 | ⬜ | Modo auditoría: lista en texto de nodos no-conectados con contexto (path copiable, tier, sugerencia) — la auditoría visual del HTML no escala ni deja copiar paths. |
| DOC-057 | ✅ | Docs sincronizadas tras Sprint 0.b (README + docstrings: tree-sitter default, symbols v1.1, --version). |

## Fase E — Deuda técnica y diferidos

| Código | Estado | Descripción |
|--------|:------:|-------------|
| CSSFB-001 | ⬜ | **BUG:** el fallback regex de CSS está roto — opt-out `language_grammars: {"css":"regex"}` cae a tier "none" (no construye `CssScanner`). Una red de seguridad que no funciona. Arreglar o documentar como límite con reemplazo. Detectado en review de MARKUP-061 (S25). |
| DEAD-001 | ⬜ | Verificar empíricamente que `_NODE_TYPES_BY_LANGUAGE` (`treesitter.py:83`) es código muerto (¿nadie lo consume en runtime?) y, confirmado, eliminarlo. NO borrar por reporte — comprobar primero. Detectado en review de MARKUP-061 (S25). |
| CLI-015b | ⬜ | Kwargs del constructor (`emit_graph`/`rotate_history`/`compute_diff`) en vez del monkeypatch `_apply_finalize_skips`. |
| REF-034 | ⬜ | Factorización post-CLI: `path_resolver.py`, `architect_symbols.py`→`compass/symbols.py`, split de `cli.py` (<600 líneas c/u). |
| FILTER-037 | ⬜ | Revisar política `<a href>` en HTML (¿links internos ameritan edge?). |
| EVL-001 | ⬜ | Review de schema extensions (opción A co-localizada vs B top-level) con evidencia de uso. |

---

> **Archivados / no construir** (reabrir solo con testigo real):
> - **REG-040** — Framework dynamic registration (`register_blueprint(obj)`, `include_router`, `urlpatterns`): sin testigo en el portfolio. Reabrir si aparece FastAPI con `include_router` cross-file o Django con `urlpatterns`.
> - **Cliente LSP propio** — descartado (D-109): la profundidad semántica puntual la dan los LSPs del harness; Compass cubre lo complementario (barrido estructural repo-wide, HTML).

---

# Para analizar (movido desde PLAN.md en limpieza S25)

Bloques de texto que vivían sueltos en PLAN.md (que es solo para descripción detallada de tareas). Movidos acá para evaluarlos: convertir en tarea formal, cerrar, o descartar.

## Irregulares rescatados en limpieza de PLAN (S25) — evaluar en segunda vuelta

Tareas que NO eran "completadas limpias": tienen un límite vivo, trade-off no resuelto, decisión abierta, o estado dudoso. Rescatadas al borrar su sección original de PLAN (cuyo registro de implementación ya vive en SESSION_LOG). Decidir por cada una: convertir en tarea formal del roadmap, cerrar, o documentar como límite asumido.

- **GRF-013 — límite offline vivo.** El `graph.html` se renderiza con vis-network (post-6C), que **solo carga vía CDN** (`unpkg.com`) → el grafo HTML **depende de internet, no funciona offline**. El offline-first de 6B (`viz-standalone.js` local) se descartó en 6C al cambiar de librería, sin reemplazo offline. El log (NIVEL 6B hallazgo #5) lo marcó "Cerrado — superseded", pero el límite funcional (no-offline) sigue existiendo. Evaluar: ¿agregar carga local de vis-network para offline, o documentar como límite asumido?

## Evidencia de campo S25 (graph.html ETCA + WP-plugin)

Observaciones directas de Beto sobre `graph.html` de etca.com.ar (scan 2026-06-15, nodes=134/edges=1222) y el WP-plugin. NO se derivaron a tickets todavía (pese al título original) — pendiente: distribuir cada pieza a su ticket destino, o convertir en tarea de diagnóstico. El diagnóstico de prioridad #3 (ANTES de WEB-039) trabajará sobre esta evidencia.

- **`themes/etca-aula/functions.php` ambiguous y aislado del cluster principal** (cluster derecho separado, `functions.php` naranja con ~14 edges `enqueue` a CSS/JS del tema, sin tocar el sitio). → candidato **TIER-062** (loader/página top-level que emite edges pero no es "usado por nadie" → debería ser entry_point) **+ posible interacción con RES-003** (theme-implicit debería promover `functions.php` a entry_point; verificar por qué no aplica).

- **`.vscode/settings.json` aparece como nodo** (en etca.com.ar Y aula.etca.com.ar). → candidato clase **IGN-059** (config de tooling/editor externo que no debe ser nodo). `.vscode/` no está en `ignore` hoy. Verificar: ¿no está en `ignore_folders`/`ignore_patterns`, o es nodo-fantasma vía edge-target (**GHOST-063**)? El fix difiere según cuál sea. `aula.etca.com.ar` es proyecto irregular, solo testigo de este caso.

- **Sueltos en etca.com.ar: `sidebar.php`, `scripts/gen-hash.php`, `themes/etca-aula/style.css`, `server.js`** → candidato **AUDIT-060** (huérfano-real vs gap). `gen-hash.php` ya clasificado huérfano-real (script CLI); `server.js` es Node http server = entry_point no detectado (revisar detección de entry para servers Node); `style.css` del tema = huérfano theme-implicit (RES-003, ¿se promueve?); `sidebar.php` es NUEVO — `.php` suelto, verificar si cae en MARKUP-061 (include no trazado?) o gap de cobertura.

- **WP-plugin `etca-dashboard-plugin`: CSS/JS de `assets/` sin conectar salvo `tutor-form.js` (dudoso)** — path `C:\IA_Workspace\clientes\ETCA\app\WP-plugin-gestion-etca\etca-dashboard-plugin\assets`. → candidato testigo **MARKUP-061 + SEM-020**. Verificar: (a) ¿assets por `wp_enqueue` (SEM-020) o markup PHP inline (MARKUP-061)?; (b) ¿por qué `tutor-form.js` conectó y los demás no — correcto o falso positivo?

## Regla canónica (Beto, S25) — cierre de tareas SOLO con verificación

Ninguna tarea se marca ✅ sin **verificación en grafo real** (no scanner aislado, no fixture sintético, no "el código existe"). Aplicado ya a CSS-049 (reabierto por haberse declarado funcional sin comprobar). Es criterio permanente del proyecto, no de un ticket puntual: el estado ✅ exige evidencia de `connectivity.outbound` del atlas tras resolución, en el testigo declarado. *(Analizar si va a roadmap o a un lugar de criterios permanentes.)*

## Lección metodológica S25 (canónica)

Para edges HTML→asset la verdad está en `connectivity.outbound` del atlas TRAS la resolución, NUNCA en el output del scanner aislado. El primer diagnóstico de Fase B declaró CSS-049 "ya implementado" probando el scanner suelto; la observación de Beto sobre ETCA lo refutó. Toda afirmación de "conecta" debe verificarse en grafo real. *(Criterio permanente — analizar destino final.)*

## Actualizaciones a tickets preexistentes (2026-06-12) — redundante, verificar antes de descartar

- **WEB-039:** segundo testigo — level2agent-engine carga `<link href="/static/css/dashboard.css">` servido por framework (evidencia `feedback_css_dependency_tracking.txt`) + Agente_facundo (dashboard JS). *Ya rescatado a la sección WEB-039 viva de PLAN — confirmar y descartar este duplicado.*
- **REG-040:** archivado se mantiene (sin testigo). *Ya en sección "Archivados" del roadmap — duplicado.*

## Nota — reconsideraciones futuras del research (NO tickets, decisión estratégica de Beto)

Material del research que NO se convierte en ticket pero queda anotado para decisión futura:

- **MCP server para Compass:** Graphify expone su grafo vía MCP. Para el caso agente sería MÁS eficiente en contexto que el flujo actual (Bash + leer atlas.compact.json entero), porque el agente pediría queries puntuales (`impact X`, `callers X`) recibiendo solo esa respuesta, no todo el atlas. El costo de contexto de un MCP es solo la **descripción de tools** (nombre+params+1-2 líneas), no la data. PERO choca con **D-107** (normalizacion-claude: "Compass es CLI, no plugin"). Reabrir esa decisión es estratégico, no técnico — diferido a criterio de Beto. Si se activa, QRY-055 (blast radius) sería la primera tool natural a exponer.
- **Exports GraphML / Neo4j / Mermaid — DESCARTADOS:** GraphML (visores Gephi/yEd) sería barato pero feature muerta si no se usan esos programas; ya hay `.dot` + `graph.html`. Neo4j es overkill brutal para un atlas que cabe en JSON. Mermaid es ilegible para grafos densos (espagueti) — el `graph.html` interactivo es superior. No construir salvo demanda real.
- **Multimodal / Pass-3 LLM / community detection / Obsidian export / token compression:** fuera de scope deliberado de Compass (territorio Graphify). El research concluye "híbrido con roles diferenciados", no "Compass copia a Graphify". No construir.

## Trazabilidad de origen — Backlog 2026-06-12 (headers divisorios movidos desde PLAN)

Los tickets post-S23 (CSS-049, SER-050, CLI-052, PKG-053, INIT-054, QRY-055, MCP-056, DOC-057, JSON-058, AUDIT-060, etc.) se originaron en: reporte l2ae (2026-04-21), `feedback_css_dependency_tracking.txt` (2026-05-11), `FEEDBACK_LSP.txt` (2026-05-08, Opción C) y `SPRINT-0B-TREE-SITTER.txt` (2026-06-12, D-106 de normalizacion-claude). *(Nota de trazabilidad — el header divisorio "# Backlog 2026-06-12" se quitó de PLAN; los tickets quedan como secciones sueltas.)*
