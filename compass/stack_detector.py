"""Stack detection — placeholder.

TODO (STK-001, NIVEL 3 del PLAN.md):
    Implementar clase StackDetector con método detect(project_root) -> str
    usando jerarquía determinista:
        1. lock files (composer.json, package.json, etc.)
        2. framework markers (wp-config.php, functions.php, etc.)
        3. extensión mayoritaria (desempate)

    Eliminar falsos positivos en la identificación del tipo de proyecto.
    Consumirá stack_markers del mapper_config.json (definido en CFG-005).

    Extendido en MST-006 para devolver StackMap: dict[str, str] por subárbol.
"""