"""Verifica que los módulos críticos cumplen umbrales de cobertura mínima.

Lee ``coverage.json`` (generado con ``coverage json``) e imprime un informe
por módulo. Falla con código de salida 1 si algún módulo crítico está por
debajo de su umbral.

Uso:
    coverage run -m pytest
    coverage json
    python scripts/check_coverage_per_module.py
    # También: python scripts/check_coverage_per_module.py --coverage-file path/coverage.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ── Umbrales por módulo (prefijo de ruta) ────────────────────────────────
# Los módulos más críticos tienen umbrales altos; el dashboard, más bajo
# porque mezcla código UI y lógica (difícil de cubrir sin Streamlit en test).
MODULE_THRESHOLDS: dict[str, int] = {
    "scraper/": 75,
    "db/": 70,
    "shared/": 80,
    "config/": 80,
    "services/": 70,
    "scheduler/": 60,
    "api/": 65,
    "observability/": 55,
    "dashboard/stats/": 70,
    "dashboard/utils/": 65,
    "dashboard/pages/": 40,  # UI-heavy, difícil cubrir sin browser
}

# Módulos excluidos del chequeo (utilidades generadas, migrations, etc.)
EXCLUDE_PREFIXES: tuple[str, ...] = (
    "db/alembic/",
    "tests/",
    "scripts/",
    "data/",
)


def _prefix_for(path: str) -> str | None:
    """Devuelve el prefijo de módulo que aplica, o None si está excluido."""
    norm = path.replace("\\", "/").lstrip("./")
    for excl in EXCLUDE_PREFIXES:
        if norm.startswith(excl):
            return None
    for prefix in MODULE_THRESHOLDS:
        if norm.startswith(prefix):
            return prefix
    return None


def _pct(covered: int, total: int) -> float:
    return round(covered / total * 100, 1) if total else 100.0


def check(coverage_file: Path) -> int:
    """Carga coverage.json y comprueba umbrales. Devuelve número de fallos."""
    if not coverage_file.exists():
        print(f"[ERROR] No se encontró {coverage_file}. Ejecuta 'coverage json' primero.")
        return 1

    data = json.loads(coverage_file.read_text(encoding="utf-8"))
    files: dict[str, dict[str, Any]] = data.get("files", {})

    # Acumular stats por prefijo
    by_prefix: dict[str, dict[str, int]] = {}
    for file_path, stats in files.items():
        prefix = _prefix_for(file_path)
        if prefix is None:
            continue
        summary = stats.get("summary", {})
        covered = int(summary.get("covered_lines", 0))
        total = int(summary.get("num_statements", 0))
        if total == 0:
            continue
        entry = by_prefix.setdefault(prefix, {"covered": 0, "total": 0})
        entry["covered"] += covered
        entry["total"] += total

    failures: list[str] = []
    print("\n─── Cobertura por módulo ──────────────────────────────────────")
    print(f"{'Módulo':<35} {'Cobertura':>9}  {'Umbral':>6}  {'Estado':>6}")
    print("─" * 62)

    for prefix in sorted(MODULE_THRESHOLDS):
        threshold = MODULE_THRESHOLDS[prefix]
        stats = by_prefix.get(prefix)
        if stats is None:
            print(f"{prefix:<35} {'N/A':>9}  {threshold:>5}%  {'⚠ sin datos':>10}")
            continue
        pct = _pct(stats["covered"], stats["total"])
        status = "✅ OK" if pct >= threshold else "❌ FAIL"
        print(f"{prefix:<35} {pct:>8.1f}%  {threshold:>5}%  {status:>8}")
        if pct < threshold:
            failures.append(
                f"  {prefix}: {pct:.1f}% < {threshold}% (faltan {threshold - pct:.1f} pp)"
            )

    print("─" * 62)

    # Global
    all_covered = sum(v["covered"] for v in by_prefix.values())
    all_total = sum(v["total"] for v in by_prefix.values())
    global_pct = _pct(all_covered, all_total)
    print(f"{'TOTAL':<35} {global_pct:>8.1f}%")

    if failures:
        print("\n[FAIL] Los siguientes módulos NO cumplen el umbral mínimo:")
        for msg in failures:
            print(msg)
        return len(failures)

    print("\n[OK] Todos los módulos cumplen sus umbrales de cobertura.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--coverage-file",
        type=Path,
        default=Path("coverage.json"),
        help="Ruta al fichero coverage.json (default: coverage.json)",
    )
    args = parser.parse_args()
    sys.exit(check(args.coverage_file))


if __name__ == "__main__":
    main()
