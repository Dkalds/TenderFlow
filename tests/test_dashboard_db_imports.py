"""Lint test: dashboard modules must not import db.* directly (AGENTS.md §3.8).

Dashboard code should access data only via services/ or db/repositories/.
Direct imports from db.database, db.users, db.dlq, etc. violate ADR-007.

This test scans dashboard/ source files for prohibited imports and reports
violations. Existing violations are tracked in _KNOWN_VIOLATIONS as technical
debt to be retired incrementally — the test ensures the count never grows.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

# Root of the dashboard package
_DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"

# Allowed db.* imports (repositories are OK per the invariant)
_ALLOWED_PREFIXES = ("db.repositories",)

# Known violations (technical debt from before invariant §3.8 was established).
# As files are migrated to services/, remove them from this set.
# The test ensures this list never GROWS.
_KNOWN_VIOLATIONS: set[str] = set()
# data_loader.py and active_learning.py use db.repositories.* which is allowed.


def _find_db_imports(filepath: Path) -> list[str]:
    """Return list of prohibited db.* import strings found in a file."""
    violations: list[str] = []
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            if mod.startswith("db.") or mod == "db":
                if not any(mod.startswith(p) for p in _ALLOWED_PREFIXES):
                    violations.append(f"from {mod} import ...")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("db.") or alias.name == "db":
                    if not any(alias.name.startswith(p) for p in _ALLOWED_PREFIXES):
                        violations.append(f"import {alias.name}")

    # Also check for raw sqlite3 imports
    if re.search(r"^\s*import\s+sqlite3", source, re.MULTILINE):
        violations.append("import sqlite3")

    return violations


def test_no_new_direct_db_imports_in_dashboard() -> None:
    """Ensure no NEW dashboard files import db.* directly (§3.8)."""
    all_violations: dict[str, list[str]] = {}

    for py_file in sorted(_DASHBOARD_DIR.rglob("*.py")):
        violations = _find_db_imports(py_file)
        if violations:
            rel = py_file.relative_to(_DASHBOARD_DIR.parent).as_posix()
            all_violations[rel] = violations

    # Files with violations that are NOT in the known set = new violations
    new_violators = set(all_violations.keys()) - _KNOWN_VIOLATIONS
    if new_violators:
        detail = "\n".join(
            f"  {f}: {', '.join(all_violations[f])}" for f in sorted(new_violators)
        )
        raise AssertionError(
            f"New dashboard files importing db.* directly (violates AGENTS.md §3.8):\n{detail}\n"
            f"Use services/ or db/repositories/ instead."
        )


def test_known_violations_not_stale() -> None:
    """Ensure _KNOWN_VIOLATIONS doesn't list files that have been fixed."""
    for known in sorted(_KNOWN_VIOLATIONS):
        filepath = _DASHBOARD_DIR.parent / known
        if not filepath.exists():
            continue
        violations = _find_db_imports(filepath)
        # This is informational — if a file has been fixed, remove it from the set.
        # We don't fail here to allow gradual cleanup.
