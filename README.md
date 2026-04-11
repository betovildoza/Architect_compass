# 🧭 Architect's Compass

[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=flat-square&logo=github&logoColor=white)](https://github.com/betovildoza/Architect_Compass)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Stack-Agnostic](https://img.shields.io/badge/Stack-Agnostic-orange?style=flat-square&logo=atom&logoColor=white)](https://github.com/betovildoza/Architect_Compass)
[![No Install](https://img.shields.io/badge/No%20Install-Required-2ecc71?style=flat-square&logo=checkmarx&logoColor=white)](https://github.com/betovildoza/Architect_Compass)

**Auditoría técnica para proyectos de larga duración y arquitecturas multitecnología.**  
Detecta archivos muertos, mapea dependencias y genera un score de salud estructural — sin tocar tu código.

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

## 📊 Outputs generados

Al ejecutar Compass en la raíz de tu proyecto, se crea la carpeta `.map/` con tres archivos:

**`atlas.json`** — El reporte completo. Incluye:
```json
{
  "generated_at": "2025-06-15 14:32:10",
  "project_name": "mi-proyecto",
  "identities": [{ "tech": "WordPress-Development", "confidence": 90 }],
  "summary": { "total_files": 84, "relevant_files": 31 },
  "connectivity": { "inbound": [...], "outbound": [...] },
  "audit": {
    "structural_health": 87.5,
    "warnings": [
      { "type": "ORPHAN", "file": "utils/old_helper.js", "description": "..." },
      { "type": "AMBIGUITY", "files": ["api.php", "api_v2.php"], "description": "..." }
    ]
  }
}
```

**`connectivity.dot`** — Grafo de dependencias en formato Graphviz. Pegalo en [GraphvizOnline](https://dreampuf.github.io/GraphvizOnline) para visualizarlo.

**`feedback.log`** — Historial de ejecuciones con score y estadísticas por fecha.

---

## 🚀 Instalación

No hay instalación. Solo necesitás Python 3.8+ en tu sistema.

```bash
# Clona o descargá el repo en una carpeta de herramientas
git clone https://github.com/betovildoza/Architect_Compass C:\DevTools\ArchitectCompass

# Copiá el config de ejemplo
cp mapper_config.example.json mapper_config.json
```

Editá `mapper_config.json` para adaptar las definiciones a tu stack (ver sección Configuración).

### Uso rápido

```bash
# Navegá a la raíz del proyecto que querés auditar
cd C:\Projects\mi-proyecto

# Ejecutá el script
python C:\DevTools\ArchitectCompass\architect_compass.py
```

### Automatización con variable de entorno (Windows)

Guardá el siguiente archivo como `compass.bat` en la misma carpeta del script:

```batch
@echo off
set SCRIPT_PATH="C:\DevTools\ArchitectCompass\architect_compass.py"

if exist %SCRIPT_PATH% (
    python %SCRIPT_PATH%
) else (
    echo [ERROR] No se encontro el motor en %SCRIPT_PATH%
    echo Revisa la ruta en compass.bat
)
pause
```

Luego agregá esa carpeta al **PATH** del sistema:  
`Variables de Entorno → Path → Editar → Nuevo → pegar la ruta`

A partir de ahí, desde cualquier terminal en la raíz de un proyecto:

```bash
compass
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

El archivo `mapper_config.example.json` incluye definiciones listas para usar: **PHP Backend**, **Vanilla Frontend** y **WordPress**.

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
├── architect_compass.py       # Motor principal
├── mapper_config.example.json # Configuración de referencia
├── compass.bat                # Launcher para Windows con PATH
└── README.md
```

> **No se incluye `mapper_config.json`** en el repo. Cada instalación mantiene su propia configuración local.

---

## 📜 Licencia

Este software se distribuye bajo licencia MIT.  
Consulta el archivo `LICENSE` para más detalles.

---

> **Dejá de adivinar qué archivos podés borrar. Dejá que la brújula te guíe.**

---

*Mantenido por [Alberto Vildoza](https://github.com/betovildoza).*