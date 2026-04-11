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
        self.text_extensions = set(self.rules.get("text_extensions", [".py", ".js", ".json", ".css"]))
        
        # Registro para unificar identidades de archivos
        self.file_registry = {}
        self._index_existing_files()
        
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

    def ensure_local_template(self):
        template_path = self.map_dir / "mapper_config.template.json"
        if self.global_config_path.exists() and not template_path.exists():
            try:
                shutil.copy2(self.global_config_path, template_path)
            except Exception as e:
                print(f"⚠️ No se pudo crear el template: {e}")

    def load_config_hierarchy(self):
        # 1. Cargar Global siempre como base
        config = {"basal_rules": {}, "definitions": []}
        if self.global_config_path.exists():
            try:
                with open(self.global_config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except Exception as e:
                print(f"⚠️ Error crítico cargando config global: {e}")

        # 2. Si existe Local, complementar
        if self.local_config_path.exists():
            try:
                with open(self.local_config_path, 'r', encoding='utf-8') as f:
                    local_config = json.load(f)
                    
                    # Unir basal_rules: listas se extienden (dedup), scalars se pisan
                    if "basal_rules" in local_config:
                        for key, val in local_config["basal_rules"].items():
                            if isinstance(val, list) and isinstance(config["basal_rules"].get(key), list):
                                merged = config["basal_rules"][key] + [v for v in val if v not in config["basal_rules"][key]]
                                config["basal_rules"][key] = merged
                            else:
                                config["basal_rules"][key] = val
                    
                    # Unir definitions (extender la lista)
                    if "definitions" in local_config:
                        # Evitamos duplicados por nombre si querés "pisar" una def global
                        global_names = {d["name"]: i for i, d in enumerate(config["definitions"])}
                        for local_def in local_config["definitions"]:
                            if local_def["name"] in global_names:
                                # Reemplaza la global por la local si tienen el mismo nombre
                                config["definitions"][global_names[local_def["name"]]] = local_def
                            else:
                                # Si es nueva, la agrega
                                config["definitions"].append(local_def)
                                
                print("✅ Configuración local cargada y combinada con la global.")
            except Exception as e:
                print(f"⚠️ Error mergeando config local: {e}")
        
        return config

    def _index_existing_files(self):
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in self.ignore_folders]
            for file in files:
                if any(file.endswith(ext) for ext in self.text_extensions):
                    rel_path = os.path.relpath(os.path.join(root, file), self.project_root)
                    normalized_path = rel_path.replace("\\", "/")
                    self.file_registry[normalized_path] = normalized_path
                    
                    path_no_ext = os.path.splitext(normalized_path)[0]
                    self.file_registry[path_no_ext] = normalized_path
                    
                    dot_path = path_no_ext.replace("/", ".")
                    self.file_registry[dot_path] = normalized_path

    def _resolve_identity(self, raw_name):
        """
        Versión original con fix de sufijo para WordPress.
        """
        # Limpieza básica para evitar basura de regex en el match
        clean = re.sub(r'[^a-zA-Z0-9\._\/-]', '', str(raw_name)).strip().strip("'\"").rstrip('.')
        path_style = clean.replace(".", "/")
        
        parts = path_style.split("/")
        for i in range(len(parts), 0, -1):
            candidate = "/".join(parts[:i])
            if candidate in self.file_registry: return self.file_registry[candidate]
            if f"{candidate}.py" in self.file_registry: return self.file_registry[f"{candidate}.py"]
        
        # Fix de sufijo: si no hay match directo, buscar si algún archivo termina con este path
        for registry_path in self.file_registry:
            if registry_path.endswith(clean) and clean != "":
                return self.file_registry[registry_path]
            
        return clean

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
                    
                    # 1. Inicialización y Fix de Relevancia Automática para UI
                    is_relevant = False
                    if any(file.endswith(ext) for ext in [".js", ".css"]):
                        is_relevant = True

                    # 2. Análisis por definiciones
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
                                if not match: continue

                                # 1. Limpieza y Normalización
                                clean_match = str(match).strip("'\"").strip()
                                # Limpieza adicional para unify check: igual que _resolve_identity
                                # Permite que "fetch(" → "fetch" matchee la unify_list correctamente
                                clean_base = re.sub(r'[^a-zA-Z0-9\._\/-]', '', clean_match).rstrip('.')

                                # 2. Lógica de Unificación (Nueva)
                                # Verificamos si el match (en minúsculas) está en nuestra lista de unificables
                                unify_list = self.rules.get("unify_external_nodes", [])
                                if clean_base.lower() in [item.lower() for item in unify_list]:
                                    # Forzamos el nombre a una versión estándar (ej: "anthropic")
                                    final_node = clean_base.lower()
                                else:
                                    # Si no es externo, resolvemos la identidad normal del archivo
                                    final_node = self._resolve_identity(clean_match)
                                
                                # 3. Filtro de exclusión (Nueva)
                                ignore_patterns = self.rules.get("ignore_outbound_patterns", [])
                                if any(re.search(p, final_node, re.I) for p in ignore_patterns):
                                    continue

                                if final_node == rel_path:
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
        total = self.atlas["summary"]["total_files"]
        relevant = self.atlas["summary"]["relevant_files"]
        if total > 0:
            self.atlas["audit"]["structural_health"] = round((relevant / total) * 100, 2)

    def finalize(self):
        # Mantenemos el finalize original sin simplificaciones
        dot_content = "digraph G {\n    rankdir=LR;\n    concentrate=true;\n    node [shape=box, style=rounded, fontname=\"Arial\"];\n"
        for edge in sorted(set(self.dot_edges)):
            dot_content += edge + "\n"
        dot_content += "}"
        
        with open(self.map_dir / "connectivity.dot", "w", encoding="utf-8") as f:
            f.write(dot_content)

        with open(self.map_dir / "atlas.json", "w", encoding="utf-8") as f:
            json.dump(self.atlas, f, indent=4, ensure_ascii=False)

        log_path = self.map_dir / "feedback.log"
        health = self.atlas["audit"]["structural_health"]
        
        new_entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] COMPASS RUN\n"
        new_entry += f"  - Salud Estructural: {health}%\n"
        new_entry += f"  - Archivos: {self.atlas['summary']['total_files']} (Relevantes: {self.atlas['summary']['relevant_files']})\n"
        new_entry += "="*40 + "\n\n"

        old_content = ""
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f: old_content = f.read()
        with open(log_path, "w", encoding="utf-8") as f: f.write(new_entry + old_content)

        print(f"\\n✨ Architect Compass finalizado.")
        print(f"📊 Salud Estructural: {health}%")
        
        if health < 80.0:
            print(" 💡 SUGERENCIA (ES):")
            print(" La salud estructural es baja porque faltan reglas específicas.")
            print(" Configura '.map/mapper_config.json' usando el template")
            print("-" * 30)
            print(" 💡 SUGGESTION (EN):")
            print(" Low structural health. The project needs specific rules.")
            print(" Set up '.map/mapper_config.json' from the template")
            


if __name__ == "__main__":
    compass = ArchitectCompass()
    compass.analyze()
    compass.finalize()