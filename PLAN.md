# Plan de implementación - Architect's Compass

---

## CYC-011 - Detección de Ciclos - 🔲pendiente

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

## EVL-001 - Review schema `extensions` (A vs B) - 🔲pendiente

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

## FILTER-037 - Revisar política de filtrado content-vs-functional en HTML - 🔲pendiente

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
## CSS-049 - Edges de dependencia CSS (HTML→CSS, CSS→CSS) - 🔲pendiente

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

---

## SER-050 - Sanitizar sentinels @@LOADER@@ en atlas.json - 🔲pendiente

- **Origen:** reporte l2ae — `"@@LOADER@@path_literal@@LOADER@@\".claude/results"` aparece crudo en atlas.json; parece artefacto de parseo intermedio sin limpiar.
- **Tarea:** transformar los sentinels antes de serializar atlas.json — mostrar el path limpio o moverlos a campo aparte `path_literals: [...]`. `atlas.compact.json` ya está limpio desde CMPCT-043; falta aplicar el mismo criterio al atlas completo.

---

## CLI-051 - Flag --version - 🔲pendiente

- **Origen:** reporte l2ae — no hay `--version` en `compass --help`; útil para issues/reports.
- **Tarea:** `--version` en el parser global, con fuente única `compass/__init__.py::__version__`.
- **✅ Resuelto (S24, 2026-06-12):** `__version__ = "0.1.0"` en `compass/__init__.py` (fuente única, exportado en `__all__`); flag `--version` con `action="version"` leyendo de ahí. **Decisión de versión (Beto): 0.1.0, NO 1.0.0** — la herramienta es funcional pero rústica/pre-estable, la banda 0.x comunica eso honestamente. Fix lateral necesario: `_normalize_default_argv` prependeaba `scan` ante `--version` (mandaba `["scan","--version"]` al subparser que no lo conoce) → se sumó `--version` a los flags que el parser principal maneja solo. `compass --version` → `compass 0.1.0`, exit 0.

---

## CLI-052 - Summary de scope en compass symbols - 🔲pendiente

- **Origen:** reporte l2ae — bajar de 988→352 funciones (filtro .venv) es correcto pero el usuario lo lee como regresión.
- **Tarea:** línea de summary al final del subcomando: `scanned N files, excluded X .venv / Y __pycache__ / Z .git`.

---

## PKG-053 - Colisión de nombre compass/ vs compass.bat - 🔲pendiente

- **Origen:** reporte l2ae — en Linux/Mac/Git Bash con el repo en PATH, el directorio `compass/` (paquete Python) se resuelve antes que `compass.bat`, dejando el binario no-invocable.
- **Opciones evaluadas:**
  - (a) Renombrar el paquete (`compass_pkg/`) — invasivo: toca todos los imports, PYTHONPATH y la receta de `feedback_compass_exec_no_bat`.
  - (b) `compass.cmd` para Windows + shim documentado en README para entornos POSIX — barato pero convive con la colisión.
  - (c) Entry point `console_scripts` vía packaging (pip genera el ejecutable `compass` real) — resuelve de raíz y **converge con la iniciativa CLI/PyPI** (memoria `project_roadmap_cli`).
- **Resolución pendiente** — inclinar hacia (c) si la profesionalización a PyPI se activa; mientras tanto (b) como mitigación documentada no cuenta como cierre del ticket.
- **Vínculo CLI-015 / iniciativa PyPI (S25):** el pendiente "Pyproject/PyPI diferido a sesión futura" que dejó CLI-015 (✅) es Entry Points `pyproject.toml` (`compass = "architect_compass:main"`, eliminar dependencia del `.bat`) — el mismo trabajo que la opción (c) de este ticket. Al activar la profesionalización a PyPI, PKG-053(c) y ese pendiente se resuelven juntos. No es ticket aparte. (Detalle del roadmap CLI/PyPI: ver `cli_roadmap.html` en la raíz del repo.)

---

## INIT-054 - Edge implícito de package-import en Python (`__init__.py` sin re-exports) - 🔲pendiente

- **Origen:** hallazgo de Beto (2026-06-12) en level2agent-engine: `cerbero_cli/commands/__init__.py` aparece suelto en el atlas pese a que el paquete se usa intensivamente (`main.py` importa los 11 subcomandos con `from .commands.X import cmd_X`).
- **Causa:** en runtime Python ejecuta `pkg/__init__.py` al importar cualquier submódulo, pero estáticamente el import statement referencia solo al submódulo (`commands/edit.py`), nunca al `__init__.py`. INIT-032 ya traza re-exports (`__init__.py` que exporta símbolos consumidos por otros), pero un `__init__.py` vacío o sin re-exports queda con 0 inbound → suelto.
- **Tarea:** en el resolver de imports Python, al resolver `from a.b.c import x` emitir además edges implícitos importador → `a/__init__.py` y `a/b/__init__.py` (toda la cadena de paquetes — es lo que Python ejecuta realmente). Label sugerido: `package_init` o reutilizar `imports`.
- **Testigo:** level2agent-engine (`cerbero_cli/commands/__init__.py` debe pasar a connected).
- **Estimación:** ~30-60 líneas en el resolver AST Python + validación en los 4 projects testigo.

---

## QRY-055 - Subcomando `compass impact <archivo>` (blast radius) - 🔲pendiente

- **Origen:** research `researcher-graphify-vs-compass-20260609-v2.md` (§6 ventajas, §8 plan de adopción): Graphify tiene un gap documentado (issue #1184) en primitivas de retrieval estructurado para agentes (`callers(X)`/`blast_radius(X)` con JSON). Compass tiene medio camino hecho — el atlas ya guarda `connectivity.outbound` (edges `src -> tgt`) + `symbols.json`. Falta exponer la query. Beto: caso de uso de alto interés (otras herramientas lo tienen; ésta es la que aprovecha la data ya existente).
- **Qué es blast radius:** dado un archivo X, "qué se rompe si lo toco" = el conjunto de archivos que dependen de X, directa y transitivamente (los inbound, recursivo). Inverso del outbound.
- **Tarea:**
  - Subcomando nuevo `compass impact <archivo>` (5º subcomando, junto a scan/symbols/init/graph) — o modo de `graph`.
  - Lee el atlas existente (no re-escanea si hay uno fresco), invierte `connectivity.outbound` para construir el índice inbound, y hace un BFS/DFS transitivo desde X.
  - Salida: lista de dependientes con profundidad (directos = nivel 1, transitivos = niveles 2+), count total. **JSON para agentes** (caso implementer/reviewer evalúa radio antes de editar) + **tabla rich para humano**.
  - Considerar: dirección configurable (`--downstream` = quién depende de X (default, el blast radius clásico) vs `--upstream` = de qué depende X). Manejar ciclos (no loop infinito — reusar la coloración de CYC-011).
- **Estimación:** ~80-150 líneas (subcomando + inversión de índice + traversal + 2 formatters). La data ya existe, es exponer + recorrer.
- **Sinergia:** encaja con el caso "agentes architect/implementer/reviewer" del research §7-B y con la iniciativa CLI/PyPI (`project_roadmap_cli`).

---

## MCP-056 - Analizar y decidir expansión de Compass a MCP server - 🔲pendiente

- **Origen:** research graphify §6 (Graphify tiene MCP server propio) + decisión de Beto (2026-06-12) de evaluarlo formalmente.
- **Naturaleza:** ticket de ANÁLISIS Y DECISIÓN, no de implementación. El entregable es un documento con la decisión (sí/no) y su fundamento.
- **A evaluar:**
  - **A favor:** para el caso agente, un MCP es más eficiente en contexto que el flujo actual (Bash + leer `atlas.compact.json` entero) — el agente pide queries puntuales (`impact X`, `callers X`, `health`) y recibe solo esa respuesta. El costo de contexto del MCP es solo la descripción de tools (nombre+params+1-2 líneas), no la data.
  - **En contra:** choca con **D-107** (normalizacion-claude: "Compass es CLI, no plugin"). Reabrir esa decisión. Mantener dos superficies (CLI + MCP) es más superficie de mantenimiento. El write_bridge ya cubre escritura; ¿hace falta otro MCP solo-lectura?
  - **Punto medio a considerar:** un MCP fino que envuelva el CLI (no reimplementa nada, solo expone `scan`/`impact`/`symbols` como tools que llaman al CLI por debajo) — bajo costo, no duplica lógica.
- **Dependencia:** si la decisión es sí, QRY-055 (blast radius) es la primera tool natural a exponer; conviene cerrarla antes.
- **Decisión:** pendiente. Documentar en una nota cuando se resuelva (igual que D-107/D-109 viven en normalizacion-claude/DECISIONS.md).

---

## DOC-057 - Sincronizar documentación tras Sprint 0.b - 🔲pendiente

- **Origen:** auditoría de doc-sync (2026-06-12) tras cerrar el Sprint 0.b. Reporte: `~/.claude/results/reviewer-compass-doc-sync-audit-20260612-0935.md`. El `--help` del CLI quedó al día; README y docstrings tienen desfases.
- **Desfases a corregir (por severidad):**
  - **ALTA:** README.md documenta `compass --version`, que **NO existe** (es CLI-051, pendiente). Contradicción: o se implementa el flag (cerrar CLI-051) o se saca del README. **Recomendado: resolver DOC-057 junto con CLI-051** — implementar `--version` y dejar el README correcto de una.
  - **MEDIA-1:** README describe la jerarquía tree-sitter como "si está instalado" — ambiguo; el código lo usa como **default/first-choice** cuando el binding está disponible (cambio del Sprint). Reescribir para reflejar default + fallback regex automático.
  - **MEDIA-2:** README no menciona que `symbols.json` subió a **VERSION 1.1** con campos `kind`/`range`/`signature` (TSD-047). Documentar.
  - **BAJA-1:** docstring de `compass/scanners/treesitter.py` — describir el comportamiento nuevo (default cuando hay binding, loader vía `pack.get_language`).
  - **BAJA-2:** docstring de `architect_symbols.py` (raíz) dice "regex fallback (tree-sitter opcional)" — ahora tree-sitter es default, no opcional. Actualizar.
- **Lo que SÍ está al día (no tocar):** el `--help` del CLI (4 subcomandos, flags), instalación zero-install, config jerárquica, outputs a `.map/`, deps opcionales — todos correctos.
- **Estimación:** ~30-60 min de edición de prosa. Si se hace con CLI-051, sumar el flag `--version` (~20 LOC).

---

## JSON-058 - Edges de data/config referenciada por path literal - 🔲pendiente 🔴 ALTA

- **Origen:** cruce de "límites conocidos vs reportes reales" (2026-06-12). Surge de la memoria `feedback_scanner_limits_preexistentes` punto #1 — gap detectado en S9, nunca ticketizado, confirmado como dolor real al revisar qué afecta a Beto según evidencia (no teoría).
- **Síntoma:** archivos de data/config cargados desde código por path literal quedan **sueltos** en el grafo. Testigo canónico: `mapper_config.json` aparece huérfano en el **self-scan del propio Compass**, aunque `core.py` lo lee con `open()`. También aplica a JSON de config/datos en cualquier proyecto.
- **Segundo testigo (S25):** `public/manifest.json` en clases.etca queda suelto — lo referencia el metadata de Next (`manifest` en `app/layout.tsx` / `<link rel="manifest">`) por path literal a JSON, edge no trazado. Confirma que el patrón aplica multi-stack (Python self-scan + Next/TS), no solo al self-scan.
- **Patrones a detectar (path LITERAL, no construido en runtime):**
  - Python: `open("x.json")`, `json.load(open("x.json"))`, `Path("x.json").read_text()`, `with open("config.json") as f`.
  - JS/TS: `require('./config.json')`, `fs.readFile('x.json')`, `import data from './x.json'`.
- **Enfoque:** extender `loader_calls` de SEM-020 (que ya resuelve `wp_enqueue_style`, `include ABSPATH.'x'`, etc.) para cubrir los loaders de filesystem genéricos con argumento string literal. Reusa la maquinaria semántica existente, no inventa scanner nuevo.
- **Límite respetado:** solo path **literal**. Nombre construido en runtime (`open(f"data_{x}.json")`) sigue siendo el límite intrínseco documentado → `dynamic_deps`. Considerar constant folding de concatenaciones literales como extensión futura (achica el límite C).
- **Prioridad ALTA:** junto con CSS-049/WEB-039, es uno de los dos gaps de cobertura que la evidencia (reportes + memorias) marca como lo que MÁS afecta a Beto — a diferencia de los 5 "límites conocidos" del README, que resultaron mayormente teóricos para su stack.
- **Estimación:** ~40-80 líneas (patterns nuevos en loader_calls + resolución del literal). Validar contra el self-scan (mapper_config.json debe pasar a connected) + level2/ETCA.

---

## AUDIT-060 - Modo auditoría: cola de candidatos en texto - 🔲pendiente

- **Origen:** auditoría visual de Beto (2026-06-12) sobre los graph.html de level2 y Agente_facundo. Detectó a ojo varios nodos sueltos (`log_proyecto.py` deuda real, `split_dashboard.py`/`gestor.py` scripts one-off legítimos, `.mcp.json` tooling, `mcp_servers_default.json` candidato JSON-058). El proceso reveló dos límites de la auditoría visual.
- **Los dos límites que resuelve:**
  1. **No escala:** en un repo de 300+ archivos, el ojo no puede contabilizar ni clasificar los huérfanos visualmente.
  2. **Paths no copiables:** el `graph.html` no permite seleccionar/copiar el texto del path de un nodo (Beto tuvo que transcribir `mcp_servers_default` a mano y lo escribió mal como `mcp_server_default`).
- **Filosofía (de Beto):** el valor de detectar un huérfano NO es limpiarlo/borrarlo — es **ponerlo en foco de auditoría** para que no quede colgado e invisible solo porque ningún reporte lo menciona. Un huérfano detectado es una **pregunta pendiente** (¿deuda? ¿gap? ¿legítimo?), no basura.
- **Tarea:** subcomando/reporte (ej. `compass audit`) que liste los nodos no-conectados (ambiguous + orphans) como **cola accionable en texto**, una fila por nodo con:
  - path (copiable), tier (ambiguous/orphan), inbound count, outbound count.
  - clasificación heurística: `script-standalone` (solo stdlib, 0 inbound, docstring "run manually") / `config-externa` / `posible-deuda` (logger/util sin uso) / `gap-conocido` (cae en patrón de CSS-049/INIT-054/JSON-058).
  - sugerencia de acción (revisar / archivar / candidato a ticket de cobertura).
- **Salida:** consola rich (humano) + `.md`/`.json` (el JSON es consumible por agentes — converge con QRY-055 y el caso agente-facing). NO borra nada; solo lista y clasifica.
- **Distinción crítica a codificar:** separar huérfano REAL (deuda del proyecto) de huérfano APARENTE (gap de cobertura de Compass). No marcar para "limpiar" lo que es un falso positivo (ej. `index.html` vivo que Compass no conecta por CSS-049). Cuanto más se cierren los gaps de cobertura (Fase B), más confiable es la cola de auditoría.
- **Sub-ítem anexado (S25) — auto-clasificación orphan con separador `-`:** `DEFAULT_ORPHAN_PATTERNS.name_suffixes` (en `compass/defaults.py`) usa `_backup`/`_old` (underscore) pero NO matchea `-backup`/`-old` (guion). Testigo: `database-old-backup.ts` en clases.etca queda sin auto-clasificar como orphan pese a su nombre. Extender los suffixes para cubrir ambos separadores (`-` y `_`). Relacionado con AUDIT-060 porque mejora la confiabilidad de la cola de auditoría en origen (huérfano real que hoy no se detecta). El architect puede secuenciar este fix junto con el diseño del modo auditoría. Origen: cruce anti-duplicación S25.
- **Estimación:** ~100-150 líneas (recolección desde el atlas existente + heurísticas de clasificación + 2 formatters). Reusa orphans/ambiguous ya computados.

---

## MARKUP-062 - Verificar extensiones server-side no-php de MARKUP-061 - 🔲pendiente

- **Origen:** MARKUP-061 (✅ S25, registro en SESSION_LOG NIVEL 25). MARKUP-061 implementó el markup-pass por **clase de extensión** (`HTML_BEARING_EXTENSIONS` en `compass/defaults.py`: `.php/.twig/.blade.php/.erb/.jsp/.ejs`) pero solo `.php` se verificó en grafo real (ETCA). Las otras 4 extensiones quedan **cubiertas por código, sin testigo** — no se afirman funcionales (regla canónica: no cerrar sin verificar en grafo real).
- **Tarea:** cuando aparezca un proyecto testigo con `.twig`/`.blade.php`/`.erb`/`.jsp`/`.ejs` que emita `<link>/<script>/<img>` inline, escanearlo y verificar en `connectivity.outbound` que los assets conectan. El código no debería requerir cambios (ya están en la lista por clase) — esto es **verificación**, no implementación. Si la verificación falla, abrir el gap como sub-tarea.
- **Nota técnica heredada (no es deuda, es contexto):** el markup-pass usa HtmlScanner regex, no tree-sitter, porque el AST HTML colapsa sobre templates server-side (markup mezclado con código de template). El regex es robusto a esa mezcla → es el camino correcto también para estas extensiones. Evidencia en SESSION_LOG NIVEL 25.
- **Candidato a testigo en el portfolio actual:** WP-plugin de ETCA (`...\WP-plugin-gestion-etca\etca-dashboard-plugin`) — verificar si usa markup `<link>/<script>` en `.php` no-template (se cruza con la auditoría de assets sueltos del plugin).
- **Prioridad:** baja (sin testigo activo que lo fuerce; el código ya las maneja).

---

## TIER-062 - Tier connected con inbound=0 enmascara huérfanos - 🔲pendiente

- **Origen:** sub-hallazgo del censo ETCA + confirmado en clases.etca (S25). Beto vio `next.config.js`/`tailwind.config.ts` "como huérfanos" en el graph.html — en realidad son `tier=connected` con 0 inbound, colgando de un nodo EXTERNAL.
- **Síntoma:** un nodo que solo tiene edges **salientes** (outbound) queda marcado `connected` aunque nadie lo importe (inbound=0). El tier mide alcanzabilidad outbound, no inbound. Esto (a) oculta huérfanos funcionales, (b) hace que `orphans=0` mienta como señal de salud. Confirmado: ~22 nodos en ETCA (`tienda.php`, `producto.php`, 10×`api/*.php`, hubs `@import` como `_shared.css`) + configs en clases.etca.
- **Causa raíz (confirmada):** `compass/pipeline.py:512` `internal_participants = internal_sources | internal_targets`; L521 `is_participant = rel_path in internal_participants`; L530 `elif is_participant or is_entry_point: tier="connected"`. Un nodo solo-source ya es participante → connected.
- **Tarea:** distinguir "conectado porque lo usan" (tiene inbound) de "conectado porque usa a otros" (solo outbound). Un nodo con inbound=0 ∧ ¬entry_point NO debería ser `connected`. Caso especial correcto: páginas/endpoints top-level servidos directo por URL (`tienda.php`, `api/*.php`, `app/offline/page.tsx` de Next) → deben promoverse a **entry_point** (convención: página servida por URL es punto de entrada), no quedar como ambiguous ni como connected genérico.
- **Decisión CERRADA (Beto, S25) — principio "marker ≠ nodo del grafo":** un archivo que Compass usa para **detectar el stack** (`framework_markers`) NO debe ser parte de las **conexiones del grafo**. Razón de fondo: las conexiones existen para *entender el repo*; un archivo de config de build no aporta a esa comprensión. Por lo tanto la detección de stack y la participación en el grafo son **dos planos separados**: un marker puede detectarse sin ser dibujado como nodo. Aplica a `*.config.js`/`*.config.ts` (`next.config.js`, `tailwind.config.ts`, `postcss.config.js`) y a **todo marker de detección de cualquier stack** — NO es específico de Next. **Alcance ampliado por Beto:** revisar esta separación en todos los stacks que Compass detecta (Flask/FastAPI/WP/Next/etc.) y en el propio funcionamiento de Compass (self-scan). Implementación: el detector de stack lee los markers de una lista propia; esos paths se excluyen de la emisión de nodos del grafo (o se marcan con un tier no-participante explícito), sin que eso ciegue la detección. NO mezclar con `ignore_patterns` genérico si eso rompiera la detección — la lista de markers debe vivir donde el stack_detector la consume. `tsconfig.json`/`package.json` quedan FUERA: IGN-059 prohíbe ignorarlos (el build/código SÍ los usa, aportan a entender el repo — ej. `package.json` define entry points, `tsconfig` define alias `@/`); su tratamiento es solo de tier, no de exclusión. **Esta decisión genera trabajo cross-proyecto, no solo TIER-062** — ver nota de alcance al pie de esta sección.
- **Testigos:** ETCA (~22 falsos-connected) + clases.etca (`next.config.js`, `tailwind.config.ts`, `next-env.d.ts`, `app/offline/page.tsx`).
- **Relación con AUDIT-060:** AUDIT-060 lista no-conectados pero opera sobre ambiguous+orphans — NO detecta el connected-con-inbound-0. TIER-062 corrige el tier en origen; AUDIT-060 consume el tier corregido. Hacer TIER-062 antes hace confiable la cola de auditoría.
- **Nota de alcance cross-proyecto (decisión "marker ≠ nodo"):** la separación markers-de-detección vs nodos-del-grafo no se agota en TIER-062 (que es la corrección del tier). Es un eje de diseño propio: auditar, para cada stack que Compass detecta, qué archivos usa como marker y asegurar que no se dibujen como nodos del grafo de dependencias. Si esto requiere su propio ticket tras el diseño de TIER-062, abrirlo entonces; por ahora queda registrado acá como decisión que origina trabajo, para no perderse.

---

## GHOST-063 - Filtrar edge-targets que caen en carpetas excluidas - 🔲pendiente

- **Origen:** observación de Beto (`.next/dev/types/routes.d.ts` como nodo en el graph.html de clases.etca) → verificación S25.
- **Síntoma:** un archivo escaneado de la app referencia por import un path que cae dentro de una `ignore_folders`/build-dir; el resolver dibuja ese target como nodo-fantasma aunque la carpeta esté excluida del scan. Caso confirmado: `next-env.d.ts:3` (auto-generado por Next, "should not be edited") tiene `import "./.next/dev/types/routes.d.ts"`; el scanner TS traza el outbound, el `outbound_resolver` crea el target. `.next` SÍ está en `ignore_folders` (`mapper_config.json:15`) → no es file escaneado, pero el resolver no filtra el target.
- **Diagnóstico clave (descartar hipótesis falsa):** NO es un gap de scope/scan — `.next` se excluye correctamente, 0 archivos de build-dir en `atlas.json::files`. El fantasma es 100% del **edge-target resolver**, no del file-indexer. Agregar `.next` a ignore (ya está) no cambia nada.
- **Causa raíz:** `compass/outbound_resolver.py` (~L46-56) tiene `_DOTFILE_TARGET_PATTERNS` (defense-in-depth de FIX-030, filtra targets dotfile) pero **no cubre targets que caen en `ignore_folders`/build-dirs**. Es el mismo patrón phantom-node conocido (cf. memorias `feedback_non_capturing_patterns`, `feedback_resolve_identity`).
- **Tarea:** extender el filtro de edge-targets del resolver para descartar destinos cuyo path caiga dentro de una `ignore_folders` (reusar la misma lista que el file-indexer usa en `pipeline.py:_index_existing_files`, no duplicarla). Análogo a FIX-030 pero por carpeta excluida en vez de por dotfile.
- **Testigo:** clases.etca (`.next/dev/types/routes.d.ts` debe dejar de figurar como nodo). Específico de Next.js App Router (`next-env.d.ts` auto-generado).
- **Decisión-abierta menor (sin testigo hoy):** `.turbo` no está en `ignore_folders` — agregar cuando aparezca un proyecto Turborepo.

---

## CSS-049 - REABIERTO: no confirmado funcional (S25) - 🔲pendiente

- **Cambio de estado S25:** vuelve a 🔲pendiente. El diagnóstico inicial de Fase B lo declaró "ya implementado" pero lo probó con **scanner aislado + CSS sintético**, NO en grafo real. Esa metodología es la que falló (ver lección metodológica arriba). Marcar ✅ ahora sería verificación débil — vetado por criterio de Beto.
- **Lo único verificado en grafo real (subconjunto del scope):** `<link>`/`<script>` **relativos desde `.html`** conectan (CIF 4/4) y **root-relativos desde `.html`** conectan (ETCA 8/8). Eso NO cubre el scope completo.
- **Lo NO comprobado:** la cascada `@import` CSS→CSS en un caso real (solo se probó sintético/aislado) y los warnings de CSS/JS no alcanzado. El testigo natural es level2agent-engine (`cerbero-setup/dashboard/static/css/`, 17 archivos en cascada) — el mismo que el ticket nombra desde el origen.
- **Cierre condicionado:** CSS-049 se marca ✅ SOLO cuando un test de no-regresión end-to-end compruebe en grafo real la cascada `@import` + los edges `<link>`/`<script>` desde `.html`. Si la comprobación falla, el testigo ya está identificado.
- **Nota de frontera:** el `<link>` desde `.php` NO es CSS-049 — es MARKUP-061. CSS-049 cubre solo el contenedor `.html`.

---

## CSSFB-001 - Fallback regex de CSS roto - 🔲pendiente (BUG)

- **Origen:** review independiente de MARKUP-061 (S25). Detectado al probar paridad tree-sitter↔regex.
- **Síntoma:** con opt-out `language_grammars: {"css": "regex"}` en config, el branch `if _resolve_grammar("css")` es False → NO se construye `CssScanner` → cae a `RegexFallbackScanner` genérico sin patterns CSS → tier reportado "none". El fallback regex de CSS **no funciona**.
- **Por qué importa (criterio Beto):** es una red de seguridad rota. Si tree-sitter fallara con CSS en algún proyecto, el fallback debería tomar el relevo y no lo hace → no se puede confiar en la promesa de "tree-sitter default + regex fallback" para CSS. Un fallback que no funciona es un bug, no deuda menor.
- **Numeración:** prefijo `CSSFB` nuevo → primera tarea = **001** (correlativo por prefijo, no global).
- **Tarea:** arreglar el branch de construcción del scanner CSS para que el opt-out a regex construya un scanner CSS funcional (con los patterns `@import`), o documentar explícitamente por qué CSS no soporta fallback regex y qué lo reemplaza. Validar: opt-out CSS → `@import` sigue conectando.
- **Relacionado:** bug hermano detectado en la misma sesión — opt-out `language_grammars` desde el config local en `.map/` no cambia el tier reportado (el local no llega al dispatcher o hay precedencia que lo ignora). Verificar si comparten causa al resolver CSSFB-001.

---

## DEAD-001 - Verificar y eliminar código muerto `_NODE_TYPES_BY_LANGUAGE` - 🔲pendiente

- **Origen:** review independiente de MARKUP-061 (S25). El reviewer marcó `_NODE_TYPES_BY_LANGUAGE` (`compass/scanners/treesitter.py:83`) como constante derivada de `_NODE_TYPE_EDGE` que **no se consume** (el scanner usa `self._node_types` construido en `__init__` desde `_edge_map`). Origen del dead code: SCN-003/EDG-023, no de MARKUP-061.
- **CONTRADICCIÓN A RESOLVER (evidencia del log, S25 limpieza):** SESSION_LOG NIVEL 4 (RES-002+SCN-003) hallazgo #6 dice lo OPUESTO — que `_NODE_TYPES_BY_LANGUAGE` en `treesitter.py` **SÍ se usa**: "cubre PHP, JavaScript y TypeScript. Otros lenguajes con grammar instalada (Ruby, Go, Rust) caerían a extracción vacía hasta que se agregue su entrada". O sea, en el diseño original de SCN-003 era la fuente de las queries por lenguaje. El reviewer de S25 dice que ya NO se consume (el scanner pasó a `self._node_types`/`_edge_map`). **Las dos fuentes se contradicen** → puede que la constante haya quedado huérfana tras un refactor posterior (EDG-023 introdujo `_NODE_TYPE_EDGE`/`_edge_map` y la vieja `_NODE_TYPES_BY_LANGUAGE` quedó sin migrar el último consumidor). La verificación empírica de esta tarea debe determinar cuál estado es el actual: ¿sigue siendo la fuente de queries (NIVEL 4) o quedó muerta tras EDG-023 (reviewer S25)?
- **Criterio Beto (NO borrar por reporte):** "si decís que es código muerto, creamos una tarea para verificarlo empíricamente". No eliminar por la afirmación de un subagente — comprobar primero que de verdad nadie lo consume en runtime (grep de usos + ejecución).
- **Numeración:** prefijo `DEAD` nuevo → primera tarea = **001**.
- **Tarea:** (1) verificar empíricamente que `_NODE_TYPES_BY_LANGUAGE` no tiene consumidores (grep repo-wide + confirmar que el scanner usa otra ruta). (2) Si confirmado: eliminar la constante y su derivación. (3) Re-scan de control (self-scan + 1 testigo) para confirmar 0 cambios en el atlas. Si resulta que SÍ se usa, cerrar la tarea documentando dónde (y el reviewer se equivocó).
- **Prioridad:** baja (cosmética, no afecta funcionamiento), pero registrada por política de no-deuda-oculta.

---

## ENDP-044 - Framework endpoint highlighting - 🔲pendiente

Detector de decoradores conocidos que marcan funciones como endpoints públicos de un framework: FastAPI (`@app.get/post/put/delete`, `@router.get/...`), Flask (`@app.route`, `@blueprint.route`), FastMCP (`@mcp.tool()`, `@mcp.resource()`), Django (`@api_view` de DRF), Express (no aplica, usa callbacks). Emite metadata `endpoint: {framework, method, path?}` en el nodo del archivo (o en el symbol si está conectado con SYM-004). Renderer HTML aplica borde distintivo o ícono (igual que GRAPH-036 hizo con entry_points). **Scope:** solo etiquetado semántico, no resolución de registros cross-file (ese es REG-040, archivado). Testigos: mcp-write2 (6 tools `@mcp.tool()` en `server.py`), Agente_facundo (blueprints Flask con `@bp.route`), level2agent-engine (si tiene endpoints). Defaults en `compass/defaults.py` -> constante `FRAMEWORK_ENDPOINT_DECORATORS`. Extensible vía `mapper_config.json` campo `endpoint_decorators` (opt-in, extiende). Surgido Sesión 23 al evaluar REG-040 - el gap real de los frameworks modernos con decoradores estáticos no es conectividad (ya está), es visualización. ~80-120 líneas.

---

## REG-040 - Framework dynamic registration - 🔲pendiente

> Nota de estado: la tabla maestra lo marca 🔲pendiente; roadmap.md lo tiene en "Archivados / no construir". Inconsistencia a resolver fuera de esta run. Contenido replicado de la tabla tal cual.

Detector tipo `loader_calls` para `app.register_blueprint(blueprint_obj)`, `app.include_router(router)` (FastAPI), Django `urlpatterns = [path('foo/', include('app.urls'))]`, y equivalentes en otros frameworks dinámicos (Express `app.use(router)`, Laravel `Route::group(...)`, etc.). Desafío: el argumento es un objeto, no un path - requiere análisis cross-file de símbolos usando `.map/symbols.json` (SYM-004) para resolver exports. **Nota Sesión 21**: caso Agente_facundo (`from .X import bp as X_bp` + `register_blueprint(X_bp)`) queda resuelto por imports estáticos - los 10 blueprints están connected. Pero el ticket cubre casos donde NO hay import estático previo (ej. registro dinámico de routes desde config, blueprints construidos en runtime). Ampliar scope a múltiples frameworks (Flask/FastAPI/Django/Express/Laravel) antes de cerrar.

---

## CLI-015b - Constructor params para flags `--no-*` en lugar de monkeypatch - 🔲pendiente

CLI-015 implementó `--no-graph`/`--no-history`/`--no-diff` vía monkeypatch de instancia sobre `_emit_graph_html`/`_compute_metrics`/`_rotate_history`. Funciona pero es deuda técnica. Refactor: agregar `emit_graph: bool`, `rotate_history: bool`, `compute_diff: bool` como kwargs del `__init__` de `ArchitectCompass` (default True para preservar comportamiento). CLI los pasa según los flags. Mucho más limpio. ~20 líneas de cambio total.

---

## REF-034 - Factorización post-CLI + mover `architect_symbols.py` al paquete - 🔲pendiente

Bundle de refactors pendientes: (a) `path_resolver.py` (1011 líneas - identificado en REF-033), (b) `architect_symbols.py` (~900 líneas, vive en raíz como standalone - moverlo a `compass/symbols.py` para que `compass symbols` no dependa de import cross-paquete), (c) `compass/cli.py` (600 líneas - split en `cli/dispatcher.py` + `cli/handlers.py` si crece más). Ningún archivo debería superar 600 líneas. No bloquea features nuevas; ejecutar cuando alguno de los 3 archivos requiera modificación significativa.

---

## WEB-039 - Framework static path resolution - 🔲pendiente

Extensión de RES-002 con base paths por framework: Flask `/static/<file>` -> `{project_root}/static/<file>`; FastAPI `StaticFiles(directory="static")` -> idem; Express `app.use('/static', express.static('public'))` -> `{project_root}/public/<file>` cuando HTML tiene `<script src="/static/xxx.js">`. Nueva sección `framework_static_mounts` en `mapper_config.json` con entries por framework (detección por lock file / marker) mapeando URL prefix -> filesystem path. Complejidad alta: a veces la config del framework es variable de env, no hardcoded. Afecta: agente_facundo (dashboard JS sueltos). Estimado: ~100-150 líneas. Surgido de "Gaps post-S10.5 (2)".

**AMPLIADO S25 (testigo l2ae):** la causa raíz del frontend desconectado en l2ae NO es mount ausente sino **colisión multi-app** - `framework_mounts.py:157` indexa mounts por URL key (`mounts["/static"]=...`), last-writer-wins entre varias apps Flask; en l2ae gana un fixture de test (`pruebas_cerbero/crb260/static`) que ni existe en disco y pisa el dashboard real, -> `_resolve_html` (path_resolver.py:973-994) resuelve a None y dropea el edge en silencio. Fix robusto (criterio Beto: sin parche, sin hardcode): NO colapsar mounts del mismo URL - conservar candidatos y desambiguar por existencia-en-disco + proximidad del mount al HTML fuente (opción "multi-mount", no el parche "filtrar inexistente + excluir carpetas test"). El cambio toca el contrato del dict de mounts (de `mount->path` a `mount->[paths]`). Ver detalle/evidencia en `~/.claude/results/reviewer-compass-l2ae-html-css-edge-20260614.md` + `architect-compass-web039-clase-analisis-20260614.md`.

**Testigos del prefijo `/static/` (rescatado de "Actualizaciones 2026-06-12"):** level2agent-engine carga `<link href="/static/css/dashboard.css">` servido por el framework (evidencia en `feedback_css_dependency_tracking.txt`) + Agente_facundo (dashboard JS por `/static/`). La resolución del prefix `/static/` -> filesystem es exactamente este ticket.
