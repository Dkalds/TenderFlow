"""Limpieza de artefactos de desarrollo, portable en Windows/Linux/macOS."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directorios de cache comunes en el repo.
CACHE_DIRS = [
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
]

# Archivos temporales comunes que generan scripts/CI local.
TEMP_FILES = [
    "cov80.txt",
    "full_cov.txt",
    "_test_summary.txt",
    "pytest-run.txt",
]


def _safe_rmtree(path: Path) -> None:
    if path.exists() and path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _safe_unlink(path: Path) -> None:
    if path.exists() and path.is_file():
        path.unlink(missing_ok=True)


def _remove_pycache_dirs(root: Path) -> None:
    for pycache in root.rglob("__pycache__"):
        if pycache.is_dir():
            shutil.rmtree(pycache, ignore_errors=True)


def main() -> int:
    _remove_pycache_dirs(ROOT)

    for rel in CACHE_DIRS:
        _safe_rmtree(ROOT / rel)

    for rel in TEMP_FILES:
        _safe_unlink(ROOT / rel)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
