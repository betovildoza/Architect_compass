# compass.local.json — Overrides por proyecto

Este archivo vive en `.map/compass.local.json` y contiene **solo tus overrides**
del `mapper_config.json` basal que trae Architect's Compass. Se crea vacío la
primera vez que corrés `compass` en un proyecto — a partir de ahí, lo editás
vos directamente.

**¿Cuándo editarlo?**
- Cuando Compass reporta falsos huérfanos (archivos que SÍ se cargan, pero vía
  autoloader, hook o require dinámico que el scanner estático no resuelve).
- Cuando querés excluir ruido del análisis (carpetas generadas, bundles,
  minificados).
- Cuando tu proyecto usa un framework custom con patterns propios.
- Cuando hablás con un SDK externo que querés ver como nodo en el grafo.

Este archivo (`compass.local.md`) es la **documentación** del JSON. Lo leés
una vez para entender el shape; después solo tocás el `.json`.

---

## Regla de merge

Tus entradas **se suman** al basal — no lo reemplazan. La jerarquía es:

1. `mapper_config.json` del repo de Compass → basal (lo que viene de fábrica).
2. `.map/compass.local.json` → tus overrides del proyecto.

Reglas específicas por tipo de campo:

- **`basal_rules`** (`ignore_folders`, `ignore_files`, `ignore_patterns`, …):
  las listas del local se **concatenan con dedup** al basal. No podés sacar
  entries del basal desde el local, solo sumar. Para restar explícitamente,
  usá los sufijos `_remove` (ver "Sintaxis avanzada" abajo).

- **`dynamic_deps`**: dict de owners → targets. El local **extiende** el dict
  del basal. Si repetís una key de owner, tu value pisa al del basal.

- **`definitions`**: lista de recetas regex. Las entries del local se agregan
  al final. **Si una entry local tiene el mismo `name` que una del basal,
  la reemplaza completa** (cuidado con los nombres — si querés solo agregar
  patterns, usá un `name` distinto).

- **`stack_markers`** y **`external_services`**: dicts — el local extiende
  (keys nuevas se agregan, keys repetidas se pisan).

Campos vacíos o ausentes en el local **no sacan nada** del basal. Solo omiten
tus overrides para esa sección.

---

## Campos activos

Son los 5 campos que Compass lee del local. Todos son opcionales — empezás
con el archivo casi vacío y vas agregando solo lo que necesitás.

### `basal_rules`

Reglas de scanning — qué archivos/carpetas/patterns excluir del análisis.

**Sintaxis:**

```json
"basal_rules": {
  "ignore_folders": ["node_modules", "vendor", "dist"],
  "ignore_files": ["scripts/legacy-admin.php"],
  "ignore_patterns": ["*.min.js", "*.bundle.js"]
}
```

- `ignore_folders` — nombre **exacto** de carpeta, matchea a cualquier
  profundidad del walk. No es path — usá `vendor`, no `src/vendor`.
- `ignore_files` — path relativo **posix exacto** desde la raíz del proyecto.
- `ignore_patterns` — globs `fnmatch` que se prueban contra el basename
  Y contra el rel_path de cada archivo. Ejemplo: `*.min.js` matchea
  `foo.min.js` a cualquier profundidad.

**Casos típicos:**
- Excluir `vendor/`, `node_modules/`, `dist/` → `ignore_folders`.
- Excluir un archivo específico (script one-off, legacy) → `ignore_files`.
- Excluir patterns (minificados, bundles, maps) → `ignore_patterns`.

**Sintaxis avanzada — removal directives** (Sesión 6C):
Podés restar entries del basal con sufijo `_remove`. Ejemplo para sacar
`.svg` del default `asset_extensions`:

```json
"basal_rules": {
  "asset_extensions_remove": [".svg"]
}
```

Soporta `_remove` sobre `asset_extensions`, `ignore_patterns`, `ignore_files`.

### `dynamic_deps`

Declarás archivos que el scanner NO puede resolver estáticamente
(autoloaders, hooks WP, includes con variables, plugins reflexivos). Los
marcados acá **dejan de aparecer como huérfanos** — se reportan con
`orphan_reason: "dynamic_declared"`.

**Sintaxis:** la key es el **owner** (el archivo que carga cosas). El value
puede ser uno de tres formatos:

```json
"dynamic_deps": {
  "includes/autoload.php": "carga src/modules/*.php via spl_autoload_register",

  "src/hooks.php": [
    "src/handlers/save-post.php",
    "src/handlers/delete-post.php"
  ],

  "wp-content/themes/mytheme/functions.php": {
    "description": "enqueues vía wp_enqueue_script — el scanner WP no resuelve get_template_directory_uri() (SEM-020)",
    "targets": [
      "wp-content/themes/mytheme/js/main.js",
      "wp-content/themes/mytheme/css/style.css"
    ]
  }
}
```

- **String** → sólo declarás el owner con una nota (no sabés targets).
- **Lista** → lista de targets concretos que carga.
- **Dict** → `{ description, targets }` si querés ambos.

Paths siempre relativos posix desde la raíz del proyecto.

**Casos típicos:**
- WordPress `functions.php` con `wp_enqueue_script` y URLs dinámicas.
- PHP autoloaders (`spl_autoload_register`, PSR-4 via Composer).
- Hooks/action-dispatchers con includes por nombre de evento.
- Plugin loaders que escanean un directorio y hacen `require` con variable.

### `definitions`

Recetas regex Tier 3 para scanning de patterns por lenguaje. Cada entry
representa un **dialect o framework**: patterns *inbound* (suman tech_score
al archivo que matchea) y *outbound* (generan edges del grafo).

**Sintaxis:**

```json
"definitions": [
  {
    "name": "MyFramework-PHP-Endpoints",
    "stack": "MyFramework",
    "language": "php",
    "tier": "regex_fallback",
    "patterns": {
      "inbound": [
        "@Route\\(",
        "register_endpoint\\s*\\("
      ],
      "outbound": [
        "call_service\\s*\\(\\s*['\"]([^'\"]+)['\"]",
        "include_template\\s*\\(\\s*['\"]([^'\"]+)['\"]"
      ]
    }
  }
]
```

**Campos por entry:**
- `name` — único. **Si coincide con uno del basal, lo pisa completo.**
- `stack` — (opcional) nombre del stack al que pertenece (sólo doc).
- `language` — (`php` | `javascript` | `python` | `html` | …). **Obligatorio**.
  Las patterns sólo corren contra archivos de ese lenguaje.
- `tier` — `regex_fallback` (único soportado hoy).
- `patterns.inbound[]` — regex **sin capture group**. Match → suma score.
- `patterns.outbound[]` — regex **con un capture group**. El grupo 1 es el
  target de la dependencia que se resuelve a path.

**Casos típicos:**
- Framework custom PHP/JS con endpoints o wrappers API propios.
- DSL interno con funciones `include_template()`, `load_partial()` etc.
- Extender el scanning de un stack ya detectado con patterns específicos
  de tu codebase (usá un `name` nuevo, no pises el basal).

### `stack_markers`

Pistas adicionales para que el `StackDetector` reconozca tu stack custom.
Normalmente no necesitás tocarlo — el basal cubre los stacks conocidos
(WordPress, React, Next.js, Django, etc.). Editalo solo si trabajás con
un framework interno que tiene archivos marker propios.

**Sintaxis:**

```json
"stack_markers": {
  "MiFramework-Custom": {
    "files": ["mi-framework.lock", "mfw.config.js"],
    "folders": ["mfw-core"],
    "extensions": [".mfw"]
  }
}
```

### `external_services`

SDKs externos. Cuando el scanner captura un import/require que matchea
alguno de los `match` strings, el grafo emite un nodo `[EXTERNAL:<label>]`
(cilindro rojo) en vez de buscar un archivo del repo.

**Sintaxis:**

```json
"external_services": {
  "my_internal_api": {
    "label": "Mi-API-Interna",
    "match": ["my-internal-sdk", "@mycompany/api-client"]
  },
  "mercadopago": {
    "label": "MercadoPago",
    "match": ["mercadopago", "@mercadopago/sdk-js", "MercadoPago\\\\SDK"]
  }
}
```

- El `id` de la key es interno (sólo para vos, no se muestra).
- `label` es lo que aparece en el grafo.
- `match` es lista de needles case-insensitive. Compara por igualdad,
  por prefijo `<needle>/`, o por primer segmento de paquete scoped.

**Casos típicos:**
- SDKs privados de tu empresa que el basal no conoce.
- Servicios externos específicos del proyecto (pasarela de pagos custom,
  API interna de un cliente).

---

## Bloques `_example_*`

En paralelo a cada campo activo, el template incluye un bloque
`_example_<campo>` con un shape de referencia. **Son solo documentación
viva — NO los edites.**

- Los bloques `_example_*` **no tienen efecto** en el análisis. Compass
  ignora cualquier key top-level que empiece con `_`.
- Si los editás por error, VAL-014 te avisa al final del run con un
  warning de tipo `drift`. El warning detecta que tu `_example_*` difiere
  del default que viene shipeado, lo que generalmente significa que
  quisiste editar el campo activo de arriba pero tocaste el ejemplo.
- Cada bloque `_example_*` lleva adentro un campo `_WARNING` con el
  mensaje explícito. Si editás, dejalo intacto — VAL-014 lo pela antes
  de comparar para evitar falsos positivos puramente cosméticos.

**Si querés usar un ejemplo:** copiá el shape al campo activo de arriba
(mismo nombre sin el prefijo `_example_`) y editalo ahí.

---

## Workflow de edición

1. **Primera corrida — dejá el archivo vacío.** Corré `compass` sin
   tocar nada. Mirá los huérfanos, ruido, stacks detectados.

   ```bash
   compass
   ```

2. **Si hay falsos huérfanos** (archivos que SÍ se cargan pero vía
   mecanismo dinámico) → agregalos a `dynamic_deps`:

   ```json
   "dynamic_deps": {
     "includes/autoload.php": ["src/foo.php", "src/bar.php"]
   }
   ```

3. **Si hay ruido** (minificados, bundles, carpetas generadas) →
   agregalos a `basal_rules`:

   ```json
   "basal_rules": {
     "ignore_folders": ["dist", "build"],
     "ignore_patterns": ["*.min.js", "*.bundle.js"]
   }
   ```

4. **Si usás un framework custom** → agregá una entry a `definitions`
   con `language` obligatorio y patterns inbound/outbound. Elegí un
   `name` que NO colisione con el basal (si colisiona, lo pisás entero).

5. **Corré `compass` de nuevo y compará health score.** El `.map/history/`
   guarda las últimas 10 corridas; el diff aparece al final del run.
   Iterá hasta que los huérfanos sean reales y el ruido esté filtrado.

Todo lo que empieza con `_` (incluido `_example_*` y este archivo de
ayuda) es ignorado por Compass. Podés borrar los ejemplos del JSON sin
afectar el análisis.