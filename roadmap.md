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
| CSS-049 | ⬜ | Edges de dependencia CSS: `@import` CSS→CSS + `<link>` HTML→CSS, warning para CSS/JS no alcanzado. |
| WEB-039 | ⬜ | Framework static path resolution: prefix URL (`/static/`) → filesystem (Flask/FastAPI/Express). |
| JSON-058 | ⬜ | Edges de data/config por path literal (`open`/`json.load`/`require`); testigo: `mapper_config.json` suelto en el self-scan. |

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
| CLI-015b | ⬜ | Kwargs del constructor (`emit_graph`/`rotate_history`/`compute_diff`) en vez del monkeypatch `_apply_finalize_skips`. |
| REF-034 | ⬜ | Factorización post-CLI: `path_resolver.py`, `architect_symbols.py`→`compass/symbols.py`, split de `cli.py` (<600 líneas c/u). |
| FILTER-037 | ⬜ | Revisar política `<a href>` en HTML (¿links internos ameritan edge?). |
| EVL-001 | ⬜ | Review de schema extensions (opción A co-localizada vs B top-level) con evidencia de uso. |

---

> **Archivados / no construir** (reabrir solo con testigo real):
> - **REG-040** — Framework dynamic registration (`register_blueprint(obj)`, `include_router`, `urlpatterns`): sin testigo en el portfolio. Reabrir si aparece FastAPI con `include_router` cross-file o Django con `urlpatterns`.
> - **Cliente LSP propio** — descartado (D-109): la profundidad semántica puntual la dan los LSPs del harness; Compass cubre lo complementario (barrido estructural repo-wide, HTML).
