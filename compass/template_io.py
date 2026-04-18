"""template_io — shipment del template `compass.local.json` + help MD.

Se extrae de `compass/core.py` (REF-033) para que la fachada quede enfocada
en orquestación. El template se mantiene como diccionario module-level por
dos razones:
  - lo lee `compass.validation.validate_local_config` (warning 5 — drift vs
    default shipeado).
  - lo lee `ArchitectCompass._ensure_local_json` para sembrar `.map/`.

Contrato (usado por core.py y validation.py):
    _LOCAL_TEMPLATE        — dict canónico del shape del compass.local.json
    _EXAMPLE_WARNING       — banner que aparece dentro de `_example_*`
    LOCAL_CONFIG_NAME      — nombre del archivo activo
    LEGACY_LOCAL_CONFIG_NAME — nombre legacy (`mapper_config.json`)
    LOCAL_TEMPLATE_NAME    — alias (hoy == LOCAL_CONFIG_NAME)
    LOCAL_HELP_NAME        — nombre del MD de ayuda
    LOCAL_HELP_TEMPLATE    — nombre del template del MD en `compass/templates/`
    ensure_local_template(map_dir, script_dir) — idempotente; crea ambos.
"""

import json


LOCAL_CONFIG_NAME = "compass.local.json"
LEGACY_LOCAL_CONFIG_NAME = "mapper_config.json"
LOCAL_TEMPLATE_NAME = "compass.local.json"
LOCAL_HELP_NAME = "compass.local.md"
LOCAL_HELP_TEMPLATE = "compass.local.md.tpl"


# ------------------------------------------------------------------
# UX-031 + md-split (Sesión 7, pase 2) — shape del template por campo:
#   1. <campo>             — el campo ACTIVO (vacío, para editar). PRIMERO.
#   2. _example_<campo>    — shape de referencia con _WARNING banner
#                            explícito. Va como APÉNDICE inmediatamente
#                            después del activo.
# La documentación larga ("cuándo usar", sintaxis, casos típicos, workflow)
# se migró a un archivo paralelo `compass.local.md` al lado del JSON,
# generado desde `compass/templates/compass.local.md.tpl`. El JSON queda
# solo con datos + ejemplos; el user lee el MD una vez para entender el
# shape y después solo toca el JSON.
#
# El _WARNING dentro de cada _example_<campo> es la señal redundante:
# si alguien edita ahí, VAL-014 (warning 5) lo detecta al cierre del run
# comparando con el default shipeado (pelando _WARNING antes de comparar).
# ------------------------------------------------------------------

_EXAMPLE_WARNING = (
    "⚠ ESTE ES UN EJEMPLO DE REFERENCIA. NO EDITAR AQUÍ. "
    "Copiá la estructura al campo activo de arriba (mismo nombre sin "
    "el prefijo '_example_'). Ediciones en '_example_*' NO tienen efecto "
    "y Compass emite un warning al detectar drift vs el default shipeado."
)


_LOCAL_TEMPLATE = {
    # ---- basal_rules ------------------------------------------------
    "basal_rules": {
        "ignore_folders": [],
        "ignore_files": [],
        "ignore_patterns": []
    },
    "_example_basal_rules": {
        "_WARNING": _EXAMPLE_WARNING,
        "ignore_folders": ["node_modules", "vendor", "dist", ".serena", "brandbook-legacy"],
        "ignore_files": [
            "scripts/Search-Replace-DB/index.php",
            "docs/third-party/legacy-admin.php",
            "assets/sede-fake.jpg"
        ],
        "ignore_patterns": ["*.min.js", "*.min.css", "*.bundle.js", "*.map", "*.backup.php"]
    },

    # ---- dynamic_deps -----------------------------------------------
    "dynamic_deps": {},
    "_example_dynamic_deps": {
        "_WARNING": _EXAMPLE_WARNING,
        "includes/autoload.php": "carga dinámicamente src/modules/*.php via spl_autoload_register",
        "src/hooks.php": [
            "src/handlers/save-post.php",
            "src/handlers/delete-post.php",
            "src/handlers/publish-post.php"
        ],
        "wp-content/themes/mytheme/functions.php": {
            "description": "enqueues vía wp_enqueue_script/style — el scanner WP no resuelve get_template_directory_uri() todavía (ver SEM-020)",
            "targets": [
                "wp-content/themes/mytheme/js/main.js",
                "wp-content/themes/mytheme/css/style.css",
                "wp-content/themes/mytheme/inc/custom-taxonomies.php"
            ]
        }
    },

    # ---- definitions ------------------------------------------------
    "definitions": [],
    "_example_definitions": [
        {
            "_WARNING": _EXAMPLE_WARNING
        },
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
        },
        {
            "name": "MyProject-JS-ApiWrapper",
            "stack": "MyProject",
            "language": "javascript",
            "tier": "regex_fallback",
            "patterns": {
                "inbound": [],
                "outbound": [
                    "apiReq\\s*\\(\\s*['\"][A-Z]+['\"]\\s*,\\s*['\"]([^'\"]+)['\"]"
                ]
            }
        }
    ],

    # ---- stack_markers ----------------------------------------------
    "stack_markers": {},
    "_example_stack_markers": {
        "_WARNING": _EXAMPLE_WARNING,
        "MiFramework-Custom": {
            "files": ["mi-framework.lock", "mfw.config.js"],
            "folders": ["mfw-core"],
            "extensions": [".mfw"]
        }
    },

    # ---- external_services ------------------------------------------
    "external_services": {},
    "_example_external_services": {
        "_WARNING": _EXAMPLE_WARNING,
        "my_internal_api": {
            "label": "Mi-API-Interna",
            "match": ["my-internal-sdk", "@mycompany/api-client"]
        },
        "legacy_erp": {
            "label": "ERP-Legacy",
            "match": ["LegacyErp\\\\Client", "legacy_erp_connect"]
        },
        "mercadopago": {
            "label": "MercadoPago",
            "match": ["mercadopago", "@mercadopago/sdk-js", "MercadoPago\\\\SDK"]
        }
    }
}


def ensure_local_template(map_dir, script_dir):
    """Crea `compass.local.json` + `compass.local.md` en `map_dir` la primera vez.

    Idempotente: si alguno ya existe, no lo pisa (el user puede haberlo
    editado). Los dos archivos se manejan independientes — faltando uno,
    solo se regenera ese.

    Parámetros:
        map_dir: `Path` a `.map/` del proyecto (ya existe).
        script_dir: `Path` a la raíz del repo de Compass (para localizar
            `compass/templates/compass.local.md.tpl`).
    """
    _ensure_local_json(map_dir)
    _ensure_local_help_md(map_dir, script_dir)


def _ensure_local_json(map_dir):
    template_path = map_dir / LOCAL_TEMPLATE_NAME
    if template_path.exists():
        return
    try:
        with open(template_path, "w", encoding="utf-8") as f:
            json.dump(_LOCAL_TEMPLATE, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ No se pudo crear el template local: {e}")


def _ensure_local_help_md(map_dir, script_dir):
    help_path = map_dir / LOCAL_HELP_NAME
    if help_path.exists():
        return
    source = script_dir / "compass" / "templates" / LOCAL_HELP_TEMPLATE
    try:
        content = source.read_text(encoding="utf-8")
        help_path.write_text(content, encoding="utf-8")
    except FileNotFoundError:
        print(
            f"⚠️ Template de ayuda no encontrado: {source} "
            "(se omite compass.local.md)"
        )
    except Exception as e:
        print(f"⚠️ No se pudo crear compass.local.md: {e}")