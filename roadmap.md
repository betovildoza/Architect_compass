# Roadmap — Architect's Compass

Acá viven **solo las tareas pendientes**, una oración cada una. El detalle ampliado vive en [PLAN.md](PLAN.md) bajo el mismo código (incluidas las completadas, que no se borran de ahí). Al completar: ✅ acá y en PLAN.md, registrar la sesión en [SESSION_LOG.md](SESSION_LOG.md).

**Estados:** ⬜ pendiente · 🔶 en curso · ✅ hecho
**Numeración:** continúa la serie global de PLAN.md.

**Objetivo actual:** completar el grafo frontend (Fase B, prioridad alta) y absorber los quick wins pendientes.

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
