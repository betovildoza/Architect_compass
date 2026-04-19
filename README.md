# 🧭 Architect's Compass

[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=flat-square&logo=github&logoColor=white)](https://github.com/betovildoza/Architect_Compass)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Stack-Agnostic](https://img.shields.io/badge/Stack-Agnostic-orange?style=flat-square&logo=atom&logoColor=white)](https://github.com/betovildoza/Architect_Compass)
[![No Install](https://img.shields.io/badge/No%20Install-Required-2ecc71?style=flat-square&logo=checkmarx&logoColor=white)](https://github.com/betovildoza/Architect_Compass)


**Auditoría técnica para proyectos de larga duración y arquitecturas multitecnología.** Detecta archivos muertos, mapea dependencias mediante identidad de archivos y genera un score de salud estructural — sin tocar tu código.

---

## Why Architect's Compass?

Cuando gestionás múltiples proyectos simultáneamente — WordPress, Next.js, agentes de IA, APIs — es inevitable que el árbol de archivos se llene de versiones antiguas, backups y componentes sin conexión que nadie sabe si todavía importan.

La respuesta usual es recorrer el proyecto a mano o confiar en la memoria. Ambas opciones escalan mal.

Architect's Compass propone algo diferente: **ejecutás un script y en segundos obtenés un mapa de todo lo que vive, lo que está aislado, y lo que debería eliminarse.**

Funciona completamente en local. No requiere instalación ni dependencias externas. No modifica ningún archivo de tu proyecto — toda la inteligencia se guarda en una carpeta oculta `.map/` que podés ignorar o commitear según prefieras.

A veces, lo más útil es también lo más invisible.

---

## ✨ Características

| Feature | Descripción |
|---|---|
| 🗺️ Atlas JSON | Reporte técnico completo del proyecto en `.map/atlas.json` |
| 💀 Detección de Huérfanos | Identifica archivos sin conexiones lógicas detectadas |
| 🔁 Anti-Duplicados | Detecta versiones del mismo componente (`v1`, `_old`, `_backup`) |
| 📡 Mapa de Conectividad | Grafo `.dot` con flujos inbound/outbound entre componentes |
| 📈 Score de Salud | Métrica de 0–100% basada en la limpieza estructural del proyecto |
| 📓 Log Histórico | Registra la evolución del score en cada ejecución |
| 🧩 Stack-Agnóstico | Motor basado en Regex — funciona con cualquier lenguaje o framework |
| 🪟 Modo Invisible | No genera archivos en tu árbol de trabajo; todo va a `.map/` |

---

## 🔬 Capacidades Core

**🔍 Unificación por Identidad**  
El motor indexa todos los archivos del proyecto antes de analizar imports. Si encuentra `from services.monitor import X`, sabe que se refiere al archivo físico `services/monitor.py` — y usa esa ruta como nodo en el grafo. Sin duplicados, sin nodos fantasma. Incluye resolución semántica: re-exports en `__init__.py`, interpolación PHP (`"$dir/file.css"`), WordPress hooks (`wp_enqueue_*`, `get_template_directory_uri()`) y loaders Python (`open()`, `json.load()`, `Path.read_text()`).

**🛡️ Clasificación Inteligente de Archivos**  
Cada archivo se clasifica en uno de 4 tiers:
- **connected**: tiene inbound/outbound detectada o es entry_point
- **ambiguous**: no tiene conexión detectada, pero es conservador (no asume descarte)
- **orphan**: evidencia explícita de descarte (vacío hasta definir criterios por proyecto)
- **dynamic**: declarado en `dynamic_deps` del config

Visualización en graph.html con colores distintivos. Score de salud (0–100%) calcula relación archivos reales vs connected.

**📂 Configuración Jerárquica**  
Compass acepta un `mapper_config.json` global (en la carpeta de la herramienta) o uno local en `.map/mapper_config.json` dentro de cada proyecto. El local tiene prioridad, permitiendo definiciones de stack por proyecto sin tocar la configuración base. Validación end-of-run si hay inconsistencias.

**🕸️ Exportación Visual Limpia + Dashboard Detection**  
El grafo `.dot` solo contiene lógica de negocio. Las carpetas de entorno (`.venv`, `node_modules`, `__pycache__`) se excluyen por defecto, convirtiendo lo que sería una telaraña de librerías externas en un mapa legible de la arquitectura real. 

Detector stack-agnóstico: HTML que carga JavaScript + ese JS hace fetch/websocket a rutas locales → auto-promovido a entry_point (útil para dashboards).

---

## 📊 Outputs generados

Al ejecutar `compass scan` en la raíz de tu proyecto, se crea la carpeta `.map/` con:

**`atlas.json`** — El reporte completo (humano-amigable):
```json
{
  "generated_at": "2026-04-18 14:32:10",
  "project_name": "mi-proyecto",
  "identities": [{ "tech": "WordPress-Development", "confidence": 90 }],
  "summary": { "total_files": 84, "connected": 31, "ambiguous": 2, "orphan": 0 },
  "entry_points": [{ "path": "index.php", "reason": "root static" }],
  "connectivity": { "nodes": [...], "edges": [...] },
  "metadata_consolidated": { "file_loads": {...}, "calls": {...} },
  "audit": {
    "structural_health": 87.5,
    "warnings": [
      { "type": "AMBIGUOUS", "file": "utils/helper.js", "description": "..." },
      { "type": "DUPLICATE", "files": ["api.php", "api_v2.php"], "description": "..." }
    ]
  }
}
```

**`atlas.compact.json`** — Versión LLM-friendly (20-30% del size). Schema pooled: labels/stacks/edge_types como índices de cadenas; nodes/edges como tuplas.

**`connectivity.dot`** — Grafo Graphviz con clasificación de nodos (connected=azul, ambiguous=naranja, entry_point=dorado). Compatible con [GraphvizOnline](https://dreampuf.github.io/GraphvizOnline).

**`graph.html`** — Visualización interactiva (vis-network): zoom, pan, drag nativos. Compatible con todos los navegadores.

**`symbols.json`** — Funciones, clases, firmas y constantes por archivo (output del subcomando `compass symbols`). Contexto para análisis LLM.

**`feedback.log`** — Historial de ejecuciones con score y estadísticas por fecha.

**`fingerprints.json`** — Hashes por archivo para detección incremental en siguientes scans.
---

## 🚀 Instalación

No hay instalación. Solo necesitás Python 3.8+ en tu sistema.

```bash
# Clona o descargá el repo en una carpeta de herramientas
git clone https://github.com/betovildoza/Architect_compass C:\DevTools\ArchitectCompass
```

Compass viene con `mapper_config.json` basal listo para usar (detectores universales de Python/JS/TS/PHP/HTML + stacks WordPress, Modern-Web, Tauri, etc.). No requiere configuración para empezar.

**Overrides por proyecto** (opcionales): la primera vez que corrés `compass` en un proyecto, se genera `.map/compass.local.json` vacío con bloques `_example_*` de referencia. Editalo para agregar `dynamic_deps`, `external_services` custom, `definitions` propias o excluir ruido — tus overrides se mergean con el basal sin reemplazarlo. Documentación completa del schema en `.map/compass.local.md` (generado junto al JSON).

### Uso rápido

```bash
# Navegá a la raíz del proyecto que querés auditar
cd C:\Projects\mi-proyecto

# Ejecutá un scan
python C:\DevTools\ArchitectCompass\architect_compass.py
# O con la CLI: compass scan --full
```

### CLI Completa (Sesión 12+)

Compass incluye 4 subcomandos principales:

```bash
compass scan                  # Análisis de dependencias (default)
compass scan --full           # Scan sin cache incremental
compass scan --no-graph       # Skip HTML graph generation
compass scan --no-history     # Skip history rotation

compass symbols               # Extrae funciones/clases/firmas a .map/symbols.json
compass init                  # Inicializa mapper_config.json local
compass graph                 # Re-genera graph.html desde atlas.json existente

compass --version             # Muestra versión
compass -h / --help           # Ayuda general
```

### Windows Portable: compass.bat

Guardá el siguiente archivo como `compass.bat` en la carpeta raíz de Compass:

```batch
@echo off
REM compass.bat — launcher portable
REM Ejecuta desde %~dp0 (directorio del script)
set COMPASS_ROOT=%~dp0
python "%COMPASS_ROOT%architect_compass.py" %*
```

Agregá la carpeta al **PATH** del sistema:  
`Variables de Entorno → Path → Editar → Nuevo → pegar ruta de Compass`

A partir de ahí, desde cualquier terminal en la raíz de un proyecto:

```bash
compass scan
compass symbols
compass graph
```

---

## ⚙️ Configuración

La potencia de la herramienta está en `mapper_config.json`. Tiene dos secciones principales:

**`basal_rules`** — Reglas globales que aplican a todos los proyectos:
- `ignore_folders`: carpetas que el scanner omite completamente
- `text_extensions`: extensiones que se analizan en profundidad
- `network_triggers`: patrones que indican llamadas de red
- `persistence_triggers`: patrones que indican acceso a datos persistentes

**`definitions`** — Definiciones de stack por tecnología. Cada entrada permite que Compass identifique el tech y mapee su conectividad:

```json
{
  "name": "Mi-Stack-Custom",
  "priority": 10,
  "indicators": {
    "files": ["config.custom"],
    "folders": ["src/logic"],
    "patterns_in_files": ["mi_init_function\\("]
  },
  "patterns": {
    "inbound": ["on_request\\(", "register_handler\\("],
    "outbound": ["call_external_api\\(", "write_to_db\\("]
  }
}
```

El archivo `mapper_config.json` basal incluye definiciones listas para usar para los stacks más comunes: **Python**, **JavaScript/TypeScript**, **PHP**, **HTML**, **WordPress-Development**, **Modern-Web-Stack**, **Tauri-Desktop-App** y **AI-Agent-Framework**. Para agregar patterns propios de tu proyecto sin tocar el basal, usá `.map/compass.local.json` (ver doc en `.map/compass.local.md`).

---

## 🛠️ Stack Tecnológico

**Runtime**
- Python 3.8+

**Dependencias**
- Librería estándar únicamente (`os`, `json`, `re`, `pathlib`, `datetime`)

**Outputs**
- JSON (atlas)
- Graphviz DOT (grafo de conectividad)
- Plain text (log histórico)

---

## 🗂️ Estructura del Repositorio

```
ArchitectCompass/
├── architect_compass.py       # Motor principal (wrapper legacy)
├── compass.py                 # CLI dispatcher (CLI-015)
├── compass/                   # Paquete del motor
├── mapper_config.json         # Config basal del repo (defaults universales)
├── compass.bat                # Launcher para Windows con PATH
├── PLAN.md                    # Roadmap de features
├── SESSION_LOG.md             # Historial de sesiones de desarrollo
└── README.md
```

Por cada proyecto auditado, Compass genera en `<proyecto>/.map/`:
- `atlas.json` / `atlas.compact.json` (LLM-friendly) — mapa de dependencias
- `connectivity.dot` + `graph.html` — grafo visual
- `compass.local.json` + `compass.local.md` — overrides del proyecto + doc del schema
- `feedback.log` + `history/` — historial de runs

> `.map/` es regenerable: cada run lo reconstruye. No commitear nada ahí.

---

## ✅ Lo que Compass resuelve bien

| Caso | Soporte |
|------|---------|
| **Importes estáticos** — `from x import y`, `import x`, `require('x')`, `<script src>` | ✅ Completo AST/regex |
| **Path resolution** — Rutas relativas, `__DIR__`, path templates | ✅ Semántico por lenguaje |
| **WordPress** — `wp_enqueue_*`, `get_template_directory_uri()`, template hierarchy (parcial) | ✅ SEM-020 |
| **Python loaders** — `open()`, `json.load()`, `Path.read_text()` | ✅ LOAD-038 |
| **Dashboards** — HTML + JS con fetch/websocket local | ✅ DASH-042 |
| **Entry points** — `if __name__`, `package.json:main`, `.bat` en raíz | ✅ Heurística por lenguaje |
| **Framework static mounts** — Flask/FastAPI `/static` → filesystem | 🔲 Pendiente (WEB-039) |
| **Dynamic registration** — `app.register_blueprint()`, Django `include()` | 🔲 Pendiente (REG-040) |

## ⚠️ Límites Conocidos

| Límite | Motivo | Workaround |
|--------|--------|-----------|
| **Imports construidos en runtime** | Requieren evaluación dinámica (ej: `__import__(variable)`) | Declarar en `dynamic_deps` |
| **Reflection y metaprogramación** | Requieren ejecución para resolver (Django models, SQLAlchemy) | Idem `dynamic_deps` |
| **Caracteres especiales en paths** | Regex limpiador elimina `@$~` silenciosamente | Evitar en nombres; charset permitido: `a-zA-Z0-9._/-` |
| **URLs dinámicas en HTTP calls** | `fetch(baseURL + variable)` no se resuelve | NET-022 captura URLs literales |
| **Importes con wildcard** | `import *` se canta pero edges son aproximadas | Scanner detecta; asumir conexión más laxa |

---

## ⚠️ Comportamientos a conocer

### Caracteres especiales en nombres de archivo

El motor de resolución de identidad limpia las rutas capturadas antes de buscarlas en el registro de archivos. El set de caracteres permitidos es: letras, números, `.  / _ -`.

Si el proyecto auditado tiene archivos con caracteres fuera de ese set (ej: `@`, `$`, `~`, espacios), esos caracteres se eliminan silenciosamente y el archivo puede no resolverse correctamente — apareciendo como un nodo sin conexión en el grafo.

**Síntoma:** flechas que apuntan a nombres que no coinciden con archivos reales ("nodos fantasma").  
**Solución:** revisar el regex en `_resolve_identity` dentro de `architect_compass.py` y agregar el carácter necesario al set permitido.

---

### Comportamiento del config local (`.map/mapper_config.json`)

El config local **no reemplaza** al global — los **extiende**:

- `basal_rules`: las claves del local sobreescriben las equivalentes del global.
- `definitions`: si una definición local tiene el **mismo `name`** que una global, la reemplaza completamente. Si tiene un nombre nuevo, se agrega a la lista.

Esto significa que para agregar patrones a una tecnología ya definida globalmente (ej: WordPress), hay que copiar la definición completa al local y modificarla — no alcanza con poner solo los patrones nuevos.

---

## 📜 Licencia

Este software se distribuye bajo licencia MIT.  
Consulta el archivo `LICENSE` para más detalles.

---

> **Dejá de adivinar qué archivos podés borrar. Dejá que la brújula te guíe.**

---

*Mantenido por [Alberto Vildoza](https://github.com/betovildoza).*