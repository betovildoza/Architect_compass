"""entry_points — detección GRAPH-036 de entry points del proyecto.

Extraído de `compass/pipeline.py` (REF-033 sub-split). Heurísticas por
lenguaje para marcar qué archivos son `entry_points` del proyecto y
resaltarlos en el grafo.

Heurísticas:
  - Python: archivo contiene `if __name__ == "__main__":`.
  - Shell/Batch en raíz: archivos `.bat` / `.sh` en el root del proyecto se
    escanean para extraer referencias a scripts `.py/.js/.ts/...` — esos
    scripts referenciados se marcan como entry points (si existen en el
    repo).
  - Node.js: `package.json` en raíz → `main`, `bin` (string u objeto),
    `scripts.start` (si referencia un file directamente).
  - PHP / HTML estático: archivos `index.{php,html,htm}` en la raíz del
    proyecto (no en subdirs — solo raíz).

Se expone como mixin (`EntryPointsMixin`) por consistencia con el resto
del pipeline.
"""

import json
import re
from pathlib import Path
from compass.framework_mounts import detect_server_entry_points


class EntryPointsMixin:
    """Mixin con detección de entry points del proyecto (GRAPH-036)."""

    # GRAPH-036 — regex para `if __name__ == "__main__":` (variantes con
    # comillas simples/dobles + whitespace flexible).
    _PY_MAIN_RE = re.compile(
        r"^\s*if\s+__name__\s*==\s*['\"]__main__['\"]\s*:\s*$",
        re.MULTILINE,
    )

    # GRAPH-036 — regex para extraer paths de .bat/.sh (línea con `python
    # algo.py`, `node algo.js`, o ruta directa tipo `SET SCRIPT_PATH="..."`).
    # Captura cualquier token con extensión .py/.js/.ts/.mjs/.php/.sh/.bat.
    _SCRIPT_REF_RE = re.compile(
        r'''["']?([A-Za-z0-9_./\\:-]+\.(?:py|js|ts|mjs|tsx|jsx|php|sh|bat))["']?''',
        re.IGNORECASE,
    )

    def _detect_entry_points(self):
        """GRAPH-036 — detecta entry points del proyecto y los guarda en
        `atlas.entry_points`.

        Output: lista ordenada de paths posix relativos al project_root,
        todos presentes en `self._all_scanned_files` (o agregados si existen
        pero quedaron fuera del walk — ej. `.bat` que no se indexa por
        extension).
        """
        entry_set = set()
        indexed = set(self._all_scanned_files)

        # 1) Python `__main__` — escaneo directo de los .py indexados.
        for rel_path in self._all_scanned_files:
            if not rel_path.endswith(".py"):
                continue
            try:
                abs_path = self.project_root / rel_path
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue
            if self._PY_MAIN_RE.search(content):
                entry_set.add(rel_path)

        # 1b) 18A.2 — WSGI/ASGI servers (waitress, uvicorn, hypercorn, gunicorn)
        # Detecta archivos que invocan servidores web y los marca como entry points.
        try:
            servers = detect_server_entry_points(self.project_root)
            for rel_path in servers:
                if rel_path in indexed:
                    entry_set.add(rel_path)
        except Exception:
            # Si la detección falla, continuar sin bloquear
            pass

        # 2) Shell/Batch en raíz — leer cada .bat/.sh directamente de disco
        # (no están indexados por `text_extensions` default).
        try:
            for item in self.project_root.iterdir():
                if not item.is_file():
                    continue
                if item.suffix.lower() not in (".bat", ".sh"):
                    continue
                try:
                    content = item.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for m in self._SCRIPT_REF_RE.finditer(content):
                    raw = m.group(1).strip().strip("\"'")
                    if not raw:
                        continue
                    # Normalizar separadores y convertir absoluto → relativo
                    # si cae dentro del proyecto.
                    candidate = self._normalize_entry_candidate(raw)
                    if candidate and candidate in indexed:
                        entry_set.add(candidate)
        except OSError:
            pass

        # 3) package.json en raíz.
        pkg_json_path = self.project_root / "package.json"
        if pkg_json_path.is_file():
            try:
                pkg = json.loads(
                    pkg_json_path.read_text(encoding="utf-8", errors="ignore")
                )
            except (OSError, ValueError):
                pkg = None
            if isinstance(pkg, dict):
                # main
                main = pkg.get("main")
                if isinstance(main, str):
                    cand = self._normalize_entry_candidate(main)
                    if cand and cand in indexed:
                        entry_set.add(cand)
                # bin (string u objeto)
                bin_val = pkg.get("bin")
                if isinstance(bin_val, str):
                    cand = self._normalize_entry_candidate(bin_val)
                    if cand and cand in indexed:
                        entry_set.add(cand)
                elif isinstance(bin_val, dict):
                    for _k, v in bin_val.items():
                        if isinstance(v, str):
                            cand = self._normalize_entry_candidate(v)
                            if cand and cand in indexed:
                                entry_set.add(cand)
                # scripts.start (extraer archivo referenciado si existe)
                scripts = pkg.get("scripts")
                if isinstance(scripts, dict):
                    start_cmd = scripts.get("start")
                    if isinstance(start_cmd, str):
                        for m in self._SCRIPT_REF_RE.finditer(start_cmd):
                            cand = self._normalize_entry_candidate(m.group(1))
                            if cand and cand in indexed:
                                entry_set.add(cand)

        # 4) PHP + HTML estático: index.{php,html,htm} SOLO en raíz.
        #    No matchear `index.*` en subdirs — solo root.
        for candidate in ("index.php", "index.html", "index.htm"):
            p = self.project_root / candidate
            if p.is_file() and candidate in indexed:
                entry_set.add(candidate)

        # Persistir ordenado — estable para diff.
        self.atlas["entry_points"] = sorted(entry_set)

    def _normalize_entry_candidate(self, raw):
        """GRAPH-036 — normaliza un raw path (bat/sh/package.json) a posix
        relativo al project_root si cae dentro. Devuelve None si es externo
        o no se puede mapear.
        """
        if not raw:
            return None
        raw = raw.strip().strip('"').strip("'")
        # Windows vars simples del tipo %FOO% o $FOO — no se pueden resolver.
        if "%" in raw or (raw.startswith("$") and "/" not in raw):
            return None
        # Cleanup separadores.
        p = raw.replace("\\", "/")
        # Quitar prefijos relativos.
        while p.startswith("./"):
            p = p[2:]
        try:
            # Absoluto: intentar re-relativizar.
            candidate_path = Path(raw)
            if candidate_path.is_absolute():
                try:
                    rel = candidate_path.resolve().relative_to(
                        self.project_root
                    ).as_posix()
                    return rel
                except (ValueError, OSError):
                    return None
            # Relativo — asumimos root del proyecto como base.
            return p
        except (ValueError, OSError):
            return None