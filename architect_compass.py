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
        
        # 1. Cargar configuración con jerarquía: Local > Global
        self.config = self.load_config_hierarchy()
        self.rules = self.config.get("basal_rules", {})
        
        # 2. Inicializar carpetas de mapa y generar template si es necesario
        self.map_dir.mkdir(exist_ok=True)
        self.ensure_local_template()
        
        # Parámetros configurables
        self.ignore_folders = set(self.rules.get("ignore_folders", ["__pycache__", "node_modules", ".git"]))
        self.text_extensions = set(self.rules.get("text_extensions", [".py", ".php", ".js", ".json", ".ts", ".tsx"]))
        
        self.atlas = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "project_name": self.project_root.name,
            "identities": [],
            "summary": {"total_files": 0, "relevant_files": 0},
            "connectivity": {"inbound": [], "outbound": []},
            "audit": {"structural_health": 100.0, "warnings": []},
            "anomalies": []
        }
        self.dot_edges = []
        self.found_files = []

    def load_config_hierarchy(self):
        """Carga el config de la raíz si existe, sino usa el global del script."""
        target_path = self.local_config_path if self.local_config_path.exists() else self.global_config_path
        
        if target_path.exists():
            with open(target_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"definitions": [], "basal_rules": {}}

    def ensure_local_template(self):
        """Si no existe un config local, crea un template en .map/ basado en el global."""
        template_path = self.map_dir / "mapper_config.template.json"
        if not self.local_config_path.exists() and self.global_config_path.exists():
            shutil.copy(self.global_config_path, template_path)

    def should_ignore(self, path):
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
        # Auditoría de Ambigüedad
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

        # Auditoría de Huérfanos
        connected_files = set()
        for conn in self.atlas["connectivity"]["inbound"] + self.atlas["connectivity"]["outbound"]:
            parts = conn.split(' ')
            if parts: connected_files.add(parts[0])

        for f in self.found_files:
            rel_path = f.relative_to(self.project_root).as_posix()
            if f.suffix in {'.py', '.php', '.js', '.ts', '.jsx', '.tsx'} and rel_path not in connected_files:
                if not any(x in f.name.lower() for x in ['index', 'main', 'app', 'wp-config']):
                    self.atlas["audit"]["warnings"].append({
                        "type": "ORPHAN",
                        "file": rel_path,
                        "description": "Componente sin conexiones lógicas detectadas."
                    })
                    self.atlas["audit"]["structural_health"] -= 0.5

        self.atlas["audit"]["structural_health"] = max(0.0, round(float(self.atlas["audit"]["structural_health"]), 2))

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
        health = self.atlas["audit"]["structural_health"]
        
        # Guardar Atlas y DOT
        with open(self.map_dir / "atlas.json", "w", encoding="utf-8") as f:
            json.dump(self.atlas, f, indent=4, ensure_ascii=False)
        
        with open(self.map_dir / "connectivity.dot", "w", encoding="utf-8") as f:
            f.write("digraph G {\n    rankdir=LR;\n    concentrate=true;\n")
            f.write("    node [shape=box, style=rounded, fontname=\"Arial\"];\n")
            f.writelines("\n".join(list(set(self.dot_edges))))
            f.write("\n}")

        # Guardar Feedback Log
        log_path = self.map_dir / "feedback.log"
        new_entry = f"[{self.atlas['generated_at']}] COMPASS RUN\n"
        new_entry += f"  - Salud Estructural: {health}%\n"
        new_entry += f"  - Archivos: {self.atlas['summary']['total_files']} (Relevantes: {self.atlas['summary']['relevant_files']})\n"
        new_entry += "="*40 + "\n\n"

        old_content = ""
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f: old_content = f.read()
        with open(log_path, "w", encoding="utf-8") as f: f.write(new_entry + old_content)

        # Output final con sugerencia inteligente
        print(f"\n✨ Architect Compass finalizado.")
        print(f"📊 Salud Estructural: {health}%")
        
        if health < 80.0:
            print(f"\n[!] AVISO: La salud detectada es baja ({health}%).")
            print(f"    Esto puede deberse a un stack no reconocido o reglas de importación faltantes.")
            print(f"    TIP: Edita el template en '.map/mapper_config.template.json' y muévelo a la raíz como 'mapper_config.json'.")
        
        if self.local_config_path.exists():
            print(f"✅ Usando configuración local del proyecto.")
        else:
            print(f"🌐 Usando configuración global.")

if __name__ == "__main__":
    compass = ArchitectCompass()
    compass.analyze(compass.scan_project())
    compass.finalize()