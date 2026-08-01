"""Ratchet: la fórmula de baja por-fila vive solo en services/sql_fragments.py.

Contexto (docs/IMPROVEMENT_BACKLOG.md): antes de v65_lotes, comparar el
importe adjudicado de UNA fila contra ``l.importe`` (el presupuesto del
expediente completo, no el del lote) sobreestimaba la baja de cualquier
procedimiento con más de un lote. ``services/competitive/bajas.py`` y
``db/repositories/pricing.py`` reinventaban la fórmula cada uno por su
cuenta -- este test evita que un fichero nuevo (o uno de estos dos, tras un
refactor descuidado) vuelva a hacerlo en vez de importar
``services.sql_fragments.BAJA_PCT_SQL``/``EFFECTIVE_BUDGET_SQL``.

No es un parser SQL real (mismo espíritu que el ratchet TID251 o
``test_user_key_sql_isolation.py``): busca los literales de texto que
constituían la fórmula rota -- "(l.importe - a.importe_adjudicado)" y
"a.importe_adjudicado) / l.importe" -- en cualquier .py del árbol de
producción, con dos excepciones documentadas y auditadas a mano:

- ``services/sql_fragments.py``: dueño legítimo de la fórmula.
- ``db/repositories/pricing.py``: duplica ``EFFECTIVE_BUDGET_SQL`` porque
  ``db/`` no debe depender de ``services/`` (capa superior, ADR-024) -- su
  fórmula ya usa ``COALESCE(lo.importe, l.importe)``, no ``l.importe`` a
  secas, así que no matchea el patrón roto de todas formas.
- ``db/domain_truth_audit.py``: calcula la fórmula rota A PROPÓSITO, para
  medir el delta contra la agregada por-licitación (Ola 0, ``make
  audit-truth``) -- es una herramienta de medición de un solo uso, no un
  camino de producción que alimente un endpoint.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

_SCAN_DIRS = ("api", "db", "scheduler", "scraper", "services")

_ALLOWED_FILES = frozenset(
    {
        "services/sql_fragments.py",
        "db/domain_truth_audit.py",
    }
)

# La fórmula rota: resta/divide directamente contra l.importe (el
# presupuesto del EXPEDIENTE), no contra el presupuesto efectivo del lote.
_BROKEN_PATTERNS = (
    re.compile(r"\(\s*l\.importe\s*-\s*a\.importe_adjudicado\s*\)"),
    re.compile(r"a\.importe_adjudicado\s*\)?\s*/\s*l\.importe\b"),
)


def _iter_production_py_files() -> list[Path]:
    files: list[Path] = []
    for d in _SCAN_DIRS:
        base = _REPO_ROOT / d
        if base.exists():
            files.extend(sorted(base.rglob("*.py")))
    return files


def test_no_file_reinvents_the_broken_per_row_baja_formula() -> None:
    violations: list[str] = []
    for path in _iter_production_py_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in _ALLOWED_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in _BROKEN_PATTERNS:
            if pattern.search(text):
                violations.append(rel)
                break
    assert not violations, (
        "Fórmula de baja por-fila reinventada fuera de services/sql_fragments.py "
        f"(usa BAJA_PCT_SQL/EFFECTIVE_BUDGET_SQL en su lugar): {violations}"
    )


def test_bajas_py_uses_the_shared_fragment() -> None:
    """Confirma que el consumidor conocido de la fórmula rota ya usa la compartida."""
    text = (_REPO_ROOT / "services/competitive/bajas.py").read_text(encoding="utf-8")
    assert "BAJA_PCT_SQL" in text
    assert "VALID_PAIR_LOTE" in text


def test_pricing_repository_uses_effective_budget() -> None:
    """El repositorio de pricing compara contra el presupuesto del lote, no
    del expediente completo -- ver docstring del módulo."""
    text = (_REPO_ROOT / "db/repositories/pricing.py").read_text(encoding="utf-8")
    assert "COALESCE(lo.importe, l.importe)" in text
    for pattern in _BROKEN_PATTERNS:
        assert not pattern.search(text)
