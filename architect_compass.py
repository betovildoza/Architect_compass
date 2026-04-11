import os
import json
import re
from pathlib import Path
from datetime import datetime

class ArchitectCompass:
    def __init__(self):
        self.script_dir = Path(__file__).parent.absolute()
        self.config_path = self.script_dir / "mapper_config.json"
        self.project_root = Path.cwd()
        self.map_dir = self.project_root / ".map"
        
        # Cargar configuración y extraer reglas basales
        self.config = self.load_config()
        self.rules = self.config.get("basal_rules", {})
        
        # Parámetros configurables con fallbacks
        self.ignore_folders = set(self.rules.get("ignore_folders", ["__pycache__", "node_modules", ".git"]))
        self.text_extensions = set(self.rules.get("text_extensions", [".py", ".php", ".js", ".json"]))
        
        self.atlas = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "project_name": self.project_root.name,
            "identities": [],
            "summary": {"total_files": 0, "relevant_files": 0},
            "connectivity": {"inbound": [], "outbound": []},
            "audit": {"structural_health": 100, "warnings": []},
            "anomalies": []
        }
        self.dot_edges = []
        self.found_files = []

    def load_config(self):
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"definitions": [], "basal_rules": {}}

    def should_ignore(self, path):
        # Ahora usa la lista cargada desde el JSON
        for part in path.parts:
            if part.startswith('.') and part != '.map': return True
            if part in self.ignore_folders: return True
        return False

    def scan_project(self):
        all_files = []
        for path in self.project_root.rglob('*'):
            try:
                if path.is_file() and not self.should_ignore(path.relative_to(self.project_root)):
                    all_files.append(path)
            except Exception: continue
        self.atlas["summary"]["total_files"] = len(all_files)
        self.found_files = all_files
        return all_files

    def run_audit(self):
        basename_map = {}
        for f in self.found_files:
            rel_path = f.relative_to(self.project_root).as_posix()
            clean_name = re.sub(r'(v\d+[\d._]*|[-_]v\d+)', '', f.name).lower()
            if clean_name not in basename_map: basename_map[clean_name] = []
            basename_map[clean_name].append(rel_path)
        
        for originals in basename_map.values():
            if len(originals) > 1:
                self.atlas["audit"]["warnings"].append({
                    "type": "AMBIGUITY",
                    "files": originals,
                    "description": "Rutas duplicadas o versiones detectadas para el mismo componente."
                })
                self.atlas["audit"]["structural_health"] -= 5

        connected_files = set()
        for conn in self.atlas["connectivity"]["inbound"] + self.atlas["connectivity"]["outbound"]:
            parts = conn.split(' ')
            if parts: connected_files.add(parts[0])

        for f in self.found_files:
            rel_path = f.relative_to(self.project_root).as_posix()
            # Solo auditamos archivos de código (no imágenes o carpetas)
            if f.suffix in {'.py', '.php', '.js', '.ts', '.jsx', '.tsx'} and rel_path not in connected_files:
                if not any(x in f.name.lower() for x in ['index', 'main', 'app', 'wp-config']):
                    self.atlas["audit"]["warnings"].append({
                        "type": "ORPHAN",
                        "file": rel_path,
                        "description": "Componente sin conexiones lógicas detectadas."
                    })
                    self.atlas["audit"]["structural_health"] -= 0.5

        self.atlas["audit"]["structural_health"] = max(0, round(self.atlas["audit"]["structural_health"], 2))

    def analyze(self, files):
        tech_scores = {tech["name"]: 0 for tech in self.config.get("definitions", [])}
        network_triggers = self.rules.get("network_triggers", [])
        
        for path in files:
            rel_path = path.relative_to(self.project_root).as_posix()
            if path.suffix in self.text_extensions:
                self.atlas["summary"]["relevant_files"] += 1
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        for tech in self.config.get("definitions", []):
                            ind = tech.get("indicators", {})
                            if path.name in ind.get("files", []): tech_scores[tech["name"]] += 50
                            if any(folder in rel_path for folder in ind.get("folders", [])):
                                tech_scores[tech["name"]] += 30
                            for pat in ind.get("patterns_in_files", []):
                                if re.search(pat, content, re.I): tech_scores[tech["name"]] += 40

                            patterns = tech.get("patterns", {})
                            for inbound in patterns.get("inbound", []):
                                if re.search(inbound, content, re.I):
                                    self.atlas["connectivity"]["inbound"].append(f"{rel_path} <- {inbound}")
                                    self.dot_edges.append(f'    "EXTERNO" -> "{rel_path}" [label="{inbound}", color="blue"];')
                            for outbound in patterns.get("outbound", []):
                                if re.search(outbound, content, re.I):
                                    self.atlas["connectivity"]["outbound"].append(f"{rel_path} -> {outbound}")
                                    self.dot_edges.append(f'    "{rel_path}" -> "{outbound}" [label="calls", color="red", penwidth=2];')

                        for trigger in network_triggers:
                            if re.search(trigger, content, re.I):
                                self.dot_edges.append(f'    "{rel_path}" -> "{trigger}" [style="dotted", color="gray"];')
                except Exception as e:
                    self.atlas["anomalies"].append(f"{rel_path}: {str(e)}")

        for name, score in tech_scores.items():
            if score >= 50:
                self.atlas["identities"].append({"tech": name, "confidence": min(score, 100)})

        self.atlas["connectivity"]["inbound"] = list(set(self.atlas["connectivity"]["inbound"]))
        self.atlas["connectivity"]["outbound"] = list(set(self.atlas["connectivity"]["outbound"]))
        self.run_audit()

    def finalize(self):
        self.map_dir.mkdir(exist_ok=True)
        with open(self.map_dir / "atlas.json", "w", encoding="utf-8") as f:
            json.dump(self.atlas, f, indent=4, ensure_ascii=False)
        
        with open(self.map_dir / "connectivity.dot", "w", encoding="utf-8") as f:
            f.write("digraph G {\n    rankdir=LR;\n    concentrate=true;\n")
            f.write("    node [shape=box, style=rounded, fontname=\"Arial\"];\n")
            f.writelines("\n".join(list(set(self.dot_edges))))
            f.write("\n}")

        log_path = self.map_dir / "feedback.log"
        new_entry = f"[{self.atlas['generated_at']}] COMPASS RUN\n"
        new_entry += f"  - Salud Estructural: {self.atlas['audit']['structural_health']}%\n"
        new_entry += f"  - Archivos: {self.atlas['summary']['total_files']} (Relevantes: {self.atlas['summary']['relevant_files']})\n"
        new_entry += "="*40 + "\n\n"

        old_content = ""
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                old_content = f.read()
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(new_entry + old_content)

        print(f"✨ Architect Compass finalizado. Salud: {self.atlas['audit']['structural_health']}%")

if __name__ == "__main__":
    compass = ArchitectCompass()
    compass.analyze(compass.scan_project())
    compass.finalize()