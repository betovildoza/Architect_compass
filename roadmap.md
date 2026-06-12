# Roadmap — Architect's Compass

Acá viven **solo las tareas pendientes**. Cada tarea tiene un **código** (`XXX-NNN`), un **estado** y una descripción de una oración. La descripción ampliada está en [PLAN.md](PLAN.md) bajo el mismo código — PLAN.md conserva además el detalle de las tareas ya completadas (no se borran de ahí). Al completar una tarea: se marca ✅ aqui y en PLAN.md, se registra la sesión en [SESSION_LOG.md](SESSION_LOG.md) (nuestro changelog) 

**Estados:** ⬜ pendiente · 🔶 en curso
**Numeración:** continúa la serie global de PLAN.md.

**Objetivo del backlog actual:** cerrar Sprint 0.b (tree-sitter como tier default — desbloquea Sprint 1 de normalizacion-claude), completar el grafo frontend (HTML/CSS) y absorber los quick wins del reporte l2ae (2026-04-21).

---

## Fase A — Sprint 0.b: tree-sitter como tier default ✅ COMPLETA (S24, 2026-06-12)

Origen: `FEEDBACK_LSP.txt` (Opción C) + `SPRINT-0B-TREE-SITTER.txt` (D-106 de normalizacion-claude). Sprint 0 completo → desbloquea Sprint 1 (beto-agents-core). Detalle en PLAN.md + SESSION_LOG.md NIVEL 24.

| Código | Estado | Descripción |
|--------|:------:|-------------|
| TSD-045 | ✅ | Invertir el default de scanners: tree-sitter como tier principal para JS/TS/PHP cuando el binding está instalado, regex como fallback automático (deps opcionales `tree-sitter` + `tree-sitter-language-pack`; promesa zero-install intacta). |
| TSD-046 | ✅ | Cobertura HTML/CSS vía tree-sitter — hoy CSS se skipea y HTML va por regex; Compass es la única vía de análisis estructural HTML del ecosistema (no existe html-lsp en el marketplace de Claude Code). |
| TSD-047 | ✅ | Enriquecer `symbols.json` con tree-sitter: `kind`, ranges exactos y firma textual donde la grammar lo permita, manteniendo el criterio anti context-blow del compact. |
| TSD-048 | ✅ | Validación comparativa tree-sitter vs regex sobre testigos reales (cerbero_cli = Python control, etca.com.ar = PHP/HTML, clases.etca.com.ar = TS) + aviso a normalizacion-claude para cerrar Sprint 0 en su ROADMAP/subsistema 11. |

## Fase B — Grafo frontend completo

Origen: `feedback_css_dependency_tracking.txt` (2026-05-11, level2agent-engine). Cierra la brecha "atlas de backend" → "atlas full-stack".

| Código | Estado | Descripción |
|--------|:------:|-------------|
| CSS-049 | ⬜ | Edges de dependencia CSS: `@import` CSS→CSS (4 variantes de sintaxis) + `<link rel="stylesheet">` HTML→CSS con resolución relativa al archivo, y warning para CSS/JS no alcanzado por ningún HTML; paso 0 = diagnosticar si HTML-019 ya emite el edge y solo falla la resolución `/static/` (esa mitad sería WEB-039). |
| WEB-039 | ⬜ | Framework static path resolution: sección `framework_static_mounts` en config mapeando URL prefix → filesystem path (Flask `/static/`, FastAPI StaticFiles, Express static); testigos: Agente_facundo (dashboard JS) y level2agent-engine (CSS `/static/css/`). |

## Fase C — Quick wins (reporte l2ae 2026-04-21)

| Código | Estado | Descripción |
|--------|:------:|-------------|
| SER-050 | ⬜ | Sanitizar sentinels `@@LOADER@@` en `atlas.json` antes de serializar (mostrar el path limpio o campo aparte `path_literals`); `atlas.compact.json` ya está limpio desde CMPCT-043. |
| CLI-051 | ✅ | Flag `--version` en el CLI, fuente única `compass/__init__.py::__version__ = "0.1.0"`. Versionado formalizado: de "v1.0-candidate" (informal) a **0.1.0** semver (banda 0.x = funcional pero pre-estable). `compass --version` → `compass 0.1.0`. (S24, 2026-06-12) |
| CLI-052 | ⬜ | Summary de scope en `compass symbols`: "scanned N files, excluded X .venv / Y __pycache__ / Z .git" para que el filtrado no se lea como regresión (caso 988→352 del reporte). |
| PKG-053 | ⬜ | Resolver la colisión de nombre `compass/` (paquete) vs `compass.bat` (launcher) en PATH de Linux/Mac/Git Bash — evaluar rename del paquete vs `compass.cmd` + shim documentado vs entry point `console_scripts` (converge con la iniciativa CLI/PyPI). |
| INIT-054 | ⬜ | Edge implícito de package-import en Python: `from pkg.sub import X` ejecuta `pkg/__init__.py` — emitir edge importador → `__init__.py` de la cadena de paquetes para que los `__init__` sin re-exports no queden sueltos (testigo: `cerbero_cli/commands/__init__.py` en level2agent-engine). |

## Fase D — Semántica de frameworks

| Código | Estado | Descripción |
|--------|:------:|-------------|
| ENDP-044 | ⬜ | Endpoint highlighting por decoradores (`@app.get/post`, `@blueprint.route`, `@mcp.tool()`, `@api_view`): metadata `endpoint: {framework, method, path?}` en el nodo + borde distintivo en graph.html; solo etiquetado semántico, sin resolución cross-file (eso es REG-040); testigos: mcp-write2, Agente_facundo, level2agent-engine. |

## Fase F — Consultas agente-facing

Origen: research `researcher-graphify-vs-compass-20260609-v2.md` (§6/§8) — Graphify tiene un gap documentado (issue #1184) en primitivas de retrieval estructurado para agentes; Compass ya tiene el grafo + symbols.json, falta exponer las queries.

| Código | Estado | Descripción |
|--------|:------:|-------------|
| QRY-055 | ⬜ | Subcomando `compass impact <archivo>` (blast radius): recorre transitivamente los inbound (quién depende de X, recursivo) y responde "qué se rompe si toco X" — lista de dependientes directos + transitivos, con profundidad. Reusa `connectivity.outbound` del atlas (invertir índice). Salida JSON para agentes + tabla rich para humano. Caso de uso: agente implementer/reviewer evalúa radio de impacto antes de editar. |
| MCP-056 | ⬜ | **Analizar y decidir** si Compass se expande a MCP server (reabre D-107 "Compass es CLI"). Trade-offs: eficiencia de contexto para agentes (queries puntuales vs leer atlas entero) vs complejidad/decisión cerrada. Entregable = decisión documentada (sí/no + por qué), NO implementación. Si es sí, QRY-055 sería la primera tool a exponer. |
| DOC-057 | ✅ | Docs sincronizadas tras Sprint 0.b. README: `--version` ahora real, jerarquía tree-sitter (default+fallback) clarificada, symbols.json v1.1 documentado. Docstrings de treesitter.py y architect_symbols.py actualizados (tree-sitter default, no "opcional"). Hecho junto a CLI-051. (S24, 2026-06-12) |

## Fase E — Deuda técnica y diferidos

| Código | Estado | Descripción |
|--------|:------:|-------------|
| CLI-015b | ⬜ | Reemplazar el monkeypatch `_apply_finalize_skips` por kwargs del constructor (`emit_graph`, `rotate_history`, `compute_diff`). |
| REF-034 | ⬜ | Factorización post-CLI: `path_resolver.py` (1011 líneas), `architect_symbols.py` → `compass/symbols.py`, split de `cli.py` en dispatcher + handlers; ningún módulo >600 líneas — activar cuando alguno requiera modificación significativa. |
| FILTER-037 | ⬜ | Revisar la política `<a href>` en HTML (hoy se filtra todo como contenido): decidir si links internos ameritan edge — diseñado en Sesión 8, sin implementar. |
| EVL-001 | ⬜ | Review de schema extensions (opción A co-localizada vs B top-level) con evidencia de uso real acumulada. |

---

> **Archivados / no construir** (reabrir solo con testigo real):
> - **REG-040** — Framework dynamic registration (`register_blueprint(obj)`, `include_router`, `urlpatterns`): sin testigo en el portfolio (FastMCP ≠ FastAPI; los blueprints de Agente_facundo ya conectan por imports estáticos). Reabrir si aparece FastAPI con `include_router` cross-file o Django con `urlpatterns`.
> - **Cliente LSP propio** — descartado formalmente (D-109 normalizacion-claude): la profundidad semántica puntual la dan los LSPs del harness (pyright/ts/php); Compass cubre lo complementario (barrido estructural repo-wide, cualquier cwd, HTML).
