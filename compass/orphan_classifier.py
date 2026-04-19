"""
ORP-1 — Orphan classification logic.

Classifies files as tier=orphan based on explicit patterns:
- Extensions: .bak, .old, .orig, .tmp, .swp, .swo, .rej
- Name suffixes: _old, _bak, _backup, _deprecated, _legacy, _orig, _tmp
- Folder segments: archive, backup, deprecated, old, trash, _trash, _old

User can override via mapper_config.json `orphan_patterns` (extends defaults, doesn't replace).
"""
from pathlib import Path
from typing import Dict, List, Set


def merge_orphan_patterns(defaults: Dict, user_config: Dict = None) -> Dict:
    """
    Merge user orphan_patterns with defaults.

    Args:
        defaults: DEFAULT_ORPHAN_PATTERNS from defaults.py
        user_config: orphan_patterns from mapper_config.json (if any)

    Returns:
        Merged patterns (user extends defaults)
    """
    merged = {
        "extensions": set(defaults.get("extensions", [])),
        "name_suffixes": set(defaults.get("name_suffixes", [])),
        "folder_segments": set(defaults.get("folder_segments", [])),
    }

    if user_config:
        merged["extensions"].update(user_config.get("extensions", []))
        merged["name_suffixes"].update(user_config.get("name_suffixes", []))
        merged["folder_segments"].update(user_config.get("folder_segments", []))

    # Convert back to lists for JSON serialization
    return {
        "extensions": list(merged["extensions"]),
        "name_suffixes": list(merged["name_suffixes"]),
        "folder_segments": list(merged["folder_segments"]),
    }


def is_orphan(rel_path: str, orphan_patterns: Dict) -> bool:
    """
    Check if a file matches orphan classification criteria.

    Args:
        rel_path: Relative path from project root (e.g., "backup/old_config.bak")
        orphan_patterns: Merged orphan patterns (from merge_orphan_patterns)

    Returns:
        True if file is classified as orphan, False otherwise
    """
    path_obj = Path(rel_path)

    # Check extension
    ext_list = orphan_patterns.get("extensions", [])
    if path_obj.suffix in ext_list:
        return True

    # Check name suffix (stem = basename without extension)
    # Example: "config_old.json" -> stem="config_old", check if ends with "_old"
    stem_list = orphan_patterns.get("name_suffixes", [])
    stem = path_obj.stem
    for suffix in stem_list:
        if stem.endswith(suffix):
            return True

    # Check folder segments in path
    folder_list = orphan_patterns.get("folder_segments", [])
    path_parts = path_obj.parts
    for part in path_parts:
        if part in folder_list:
            return True

    return False


def classify_orphans(
    ambiguous_files: List[str],
    orphan_patterns: Dict,
) -> tuple[List[str], List[str]]:
    """
    Classify ambiguous files into orphans and remaining ambiguous.

    Args:
        ambiguous_files: List of paths classified as ambiguous
        orphan_patterns: Merged orphan patterns

    Returns:
        (orphans, remaining_ambiguous)
    """
    orphans = []
    remaining = []

    for rel_path in ambiguous_files:
        if is_orphan(rel_path, orphan_patterns):
            orphans.append(rel_path)
        else:
            remaining.append(rel_path)

    return orphans, remaining