"""
WordPress Template Hierarchy Auto-detect (RES-003).

Detects WordPress projects by markers (style.css headers, functions.php, wp-config.php, wp-content/).
For WP projects, classifies template files as entry points based on WordPress naming conventions.

Templates auto-loaded by WordPress:
- Exact matches: index.php, front-page.php, home.php, 404.php, search.php, singular.php,
                comments.php, header.php, footer.php, sidebar.php, attachment.php
- Glob patterns: single-*.php, archive-*.php, page-*.php, category-*.php, tag-*.php,
                taxonomy-*.php, author-*.php, date-*.php, template-*.php
"""
import fnmatch
from pathlib import Path
from typing import Set, Optional


# WordPress markers that identify a WP project (one is sufficient)
WP_MARKERS = {
    "style.css",          # Theme style file (always contains Theme Name, Author, Version)
    "functions.php",      # Theme functions file
    "wp-config.php",      # WordPress configuration
    "wp-content",         # WordPress content directory
    "wp-includes",        # WordPress core includes directory
}

# Exact basenames that are auto-loaded by WordPress
WP_EXACT_TEMPLATES = {
    "index.php",          # Main template
    "front-page.php",     # Static home page
    "home.php",           # Blog posts page
    "404.php",            # 404 error page
    "search.php",         # Search results
    "singular.php",       # Fallback for singular posts
    "comments.php",       # Comments template
    "header.php",         # Header template
    "footer.php",         # Footer template
    "sidebar.php",        # Sidebar template
    "attachment.php",     # Attachment page
}

# Glob patterns for WordPress templates
WP_GLOB_PATTERNS = [
    "single-*.php",       # Single post types
    "archive-*.php",      # Archive pages
    "page-*.php",         # Page by slug/ID
    "category-*.php",     # Category templates
    "tag-*.php",          # Tag templates
    "taxonomy-*.php",     # Custom taxonomy
    "author-*.php",       # Author archives
    "date-*.php",         # Date archives
    "template-*.php",     # Page templates
]


def detect_wordpress_project(project_root: Path) -> bool:
    """
    Detect if a project is WordPress-based by checking for WP markers.

    Args:
        project_root: Root directory of the project

    Returns:
        True if WP markers detected, False otherwise
    """
    for marker in WP_MARKERS:
        marker_path = project_root / marker
        if marker_path.exists():
            return True
    return False


def is_wp_template(filepath: str) -> bool:
    """
    Check if a PHP file is a WordPress template based on naming conventions.

    Args:
        filepath: Relative path from project root (e.g., "index.php", "single-post.php")

    Returns:
        True if file is a WP template, False otherwise
    """
    basename = Path(filepath).name

    # Check exact matches
    if basename in WP_EXACT_TEMPLATES:
        return True

    # Check glob patterns
    for pattern in WP_GLOB_PATTERNS:
        if fnmatch.fnmatch(basename, pattern):
            return True

    return False


def mark_wp_templates_as_entry_points(
    nodes: dict,
    is_wp_project: bool,
) -> None:
    """
    Mark WordPress template files as entry points in the atlas nodes.

    Args:
        nodes: Dictionary of atlas nodes
        is_wp_project: Whether the project is WordPress-based
    """
    if not is_wp_project:
        return

    for node_id, node in nodes.items():
        rel_path = node.get("path", "")

        # Only process PHP files
        if not rel_path.endswith(".php"):
            continue

        # Check if it's a WP template
        if is_wp_template(rel_path):
            # Mark as entry point with reason
            if "entry_point_reason" not in node:
                node["entry_point_reason"] = "wp_template_hierarchy"
            elif isinstance(node["entry_point_reason"], str):
                # If already has a reason, convert to list
                node["entry_point_reason"] = [node["entry_point_reason"], "wp_template_hierarchy"]
            else:
                node["entry_point_reason"].append("wp_template_hierarchy")