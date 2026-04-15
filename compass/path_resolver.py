"""Path resolver — placeholder.

TODO (RES-002, NIVEL 4 del PLAN.md):
    Implementar clase PathResolver con método
        resolve(raw, language, source_file) -> str | None

    Convierte un string crudo de import (ej: './utils', '__DIR__ . "/sub/file.php"',
    '@alias/module') en el path absoluto del archivo referenciado, usando reglas
    semánticas por lenguaje y stack detectado.

    Submétodos planificados:
        _resolve_php(raw, source_file)
        _resolve_js(raw, source_file)
        _resolve_python(raw, source_file)

    Reemplazará las llamadas a _resolve_identity() en compass/core.py::analyze().
"""