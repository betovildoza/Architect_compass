import os
import json
import re
import shutil
from pathlib import Path
from datetime import datetime

class ArchitectCompass:
    def __init__(self):
        self.script_dir = Path(__file__).parent.absolute()
        self.global_config_path = self.script_dir / "mapper_config.json"
        self.project_root = Path.cwd()
        self.map_dir = self.project_root / ".map"
        self.local_config_path = self.project_root / ".map/mapper_config.json"
        
        self.config = self.load_config_hierarchy()
        self.rules = self.config.get("basal_rules", {})
        
        self.map_dir.mkdir(exist_ok=True)
        self.ensure_local_template()
        
        self.ignore_folders = set(self.rules.get("ignore_folders", []))
        self.ignore_files = set(self.rules.get("ignore_files", ["__init__.py"]))
        self.text_extensions = set(self.rules.get("text_extensions", [".py", ".js", ".json"]))
        
        # [AGREGADO] Registro para unificar identidades de archivos (Opción 1)
        self.file_registry = {}
        self._index_existing_files()
        
        self.atlas = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "project_name": self.project_root.name,
            "identities": [],
            "summary": {"total_files": 0, "relevant_files": 0},
            "connectivity": {"inbound": [], "outbound": []},
            "anomalies": [],
            "audit": {"structural_health": 0.0, "warnings": []}
        }
        self.dot_edges = []

    # [AGREGADO] Método aditivo para indexar archivos reales
    def _index_existing_files(self):
        for p in self.project_root.rglob("*"):
            if p.is_file() and p.suffix in [".py", ".js", ".ts", ".tsx"]:
                rel_path = p.relative_to(self.project_root).as_posix()
                self.file_registry[rel_path] = rel_path
                self.file_registry[rel_path.rsplit('.', 1)[0]] = rel_path

    # [AGREGADO] Método aditivo para resolver nombres y evitar duplicados
    def _resolve_identity(self, raw_name):
        clean = re.sub(r'[^a-zA-Z0-9\._\/]', '', str(raw_name)).strip().rstrip('.')
        path_style = clean.replace(".", "/")
        
        parts = path_style.split("/")
        for i in range(len(parts), 0, -1):
            candidate = "/".join(parts[:i])
            if candidate in self.file_registry: return self.file_registry[candidate]
            if f"{candidate}.py" in self.file_registry: return self.file_registry[f"{candidate}.py"]
            
        return clean

    def load_config_hierarchy(self):
        if self.local_config_path.exists():
            with open(self.local_config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"basal_rules": {}, "definitions": []}

    def ensure_local_template(self):
        if not self.local_config_path.exists():
            template = {
                "basal_rules": {
                    "ignore_folders": ["__pycache__", "node_modules", "dist", "build", "venv", ".git", ".map"],
                    "ignore_files": ["__init__.py"],
                    "text_extensions": [".py", ".js", ".json"]
                },
                "definitions": []
            }
            with open(self.local_config_path, "w", encoding="utf-8") as f:
                json.dump(template, f, indent=4)

    def analyze(self):
        relevant_extensions = self.text_extensions
        tech_scores = {}

        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in self.ignore_folders]
            
            for file in files:
                if file in self.ignore_files or not any(file.endswith(ext) for ext in relevant_extensions):
                    continue

                self.atlas["summary"]["total_files"] += 1
                file_path = Path(root) / file
                rel_path = file_path.relative_to(self.project_root).as_posix()

                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    is_relevant = False
                    for df in self.config.get("definitions", []):
                        patterns = df.get("patterns", {})
                        
                        for inbound in patterns.get("inbound", []):
                            if re.search(inbound, content, re.I):
                                self.atlas["connectivity"]["inbound"].append(f"{rel_path} <- {inbound}")
                                tech_scores[df["name"]] = tech_scores.get(df["name"], 0) + 10
                                is_relevant = True

                        for outbound in patterns.get("outbound", []):
                            matches = re.findall(outbound, content, re.I)
                            for match in matches:
                                if isinstance(match, tuple): match = match[0]
                                
                                # [MODIFICADO] Solo usamos el resolvedor de identidad aquí
                                final_node = self._resolve_identity(match)
                                
                                if final_node == rel_path or final_node.lower() in ["self", "none"]:
                                    continue

                                self.atlas["connectivity"]["outbound"].append(f"{rel_path} -> {final_node}")
                                self.dot_edges.append(f'    "{rel_path}" -> "{final_node}" [label="calls", color="red"];')
                                is_relevant = True

                    if is_relevant:
                        self.atlas["summary"]["relevant_files"] += 1

                except Exception as e:
                    self.atlas["anomalies"].append(f"{rel_path}: {str(e)}")

        for name, score in tech_scores.items():
            self.atlas["identities"].append({"tech": name, "confidence": min(score, 100)})

        self.run_audit()

    def run_audit(self):
        relevant = self.atlas["summary"]["relevant_files"]
        total = self.atlas["summary"]["total_files"]
        health = (relevant / total * 100) if total > 0 else 0
        self.atlas["audit"]["structural_health"] = round(health, 2)

    def finalize(self):
        # 1. Generar DOT
        dot_content = "digraph G {\n    rankdir=LR;\n    concentrate=true;\n    node [shape=box, style=rounded, fontname=\"Arial\"];\n"
        for edge in sorted(set(self.dot_edges)):
            dot_content += edge + "\n"
        dot_content += "}"
        
        with open(self.map_dir / "connectivity.dot", "w", encoding="utf-8") as f:
            f.write(dot_content)

        # 2. Guardar Atlas
        with open(self.map_dir / "atlas.json", "w", encoding="utf-8") as f:
            json.dump(self.atlas, f, indent=4, ensure_ascii=False)

        # 3. Log de Feedback
        log_path = self.map_dir / "feedback.log"
        health = self.atlas["audit"]["structural_health"]
        new_entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] COMPASS RUN\n"
        new_entry += f"  - Salud Estructural: {health}%\n"
        new_entry += f"  - Archivos: {self.atlas['summary']['total_files']} (Relevantes: {self.atlas['summary']['relevant_files']})\n"
        new_entry += "="*40 + "\n\n"

        old_content = ""
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f: 
                old_content = f.read()
        
        with open(log_path, "w", encoding="utf-8") as f: 
            f.write(new_entry + old_content)

        # 4. Feedback visual en consola
        print(f"\n✨ Architect Compass finalizado.")
        print(f"📊 Salud Estructural: {health}%")
        
        # --- LÓGICA DE SUGERENCIAS ACUMULATIVA ---
        if health < 80.0:
            # [TU MENSAJE ORIGINAL INTACTO] Problemas graves de reglas
            print("\n" + "!" * 50)
            print(" 💡 SUGERENCIA (ES):")
            print(" La salud estructural es baja porque faltan reglas específicas.")
            print(" Configura '.map/mapper_config.json' usando el template")
            print(" para que el Compass entienda mejor este stack.")
            print("-" * 30)
            print(" 💡 SUGGESTION (EN):")
            print(" Low structural health. The project needs specific rules.")
            print(" Set up '.map/mapper_config.json' from the template")
            print(" so Compass can better understand this tech stack.")
            print("!" * 50 + "\n")
            
        elif health < 90.0:
            # [EL MENSAJE NUEVO AGREGADO] Problemas leves de duplicidad de nodos
            print("\n" + "!" * 50)
            print(" 💡 SUGERENCIA (ES):")
            print(" El sistema ahora intenta unificar nodos (ej: ui.theme -> ui/theme.py).")
            print(" Si ves duplicados, revisa las rutas en '.map/mapper_config.json'.")
            print("-" * 30)
            print(" 💡 SUGGESTION (EN):")
            print(" Nodes are now being unified by file identity.")
            print(" If you see duplicates, check paths in '.map/mapper_config.json'.")
            print("!" * 50 + "\n")

if __name__ == "__main__":
    compass = ArchitectCompass()
    compass.analyze()
    compass.finalize()