"""Guardrail anti-regresión: dedupe cross-fuente en queries analíticas.

El dedupe cross-fuente (``services/dedupe.py``) marca como ``confirmed`` las
licitaciones duplicadas entre fuentes (PLACSP/TED/PSCP…). Toda consulta
analítica de competencia o ML que agregue sobre ``licitaciones`` o
``adjudicaciones`` **debe** excluir esas filas con ``exclude_duplicados_sql()``;
si no, infla silenciosamente cuota de mercado, HHI, renovaciones y los datasets
de entrenamiento (ADR-009, RFC 20260611-1 §5.2).

Hoy todas las queries relevantes lo aplican. Este test falla si alguien añade
una consulta analítica nueva sobre esas tablas y olvida el filtro — convierte
una regresión silenciosa de correctitud en un fallo de CI ruidoso.

Granularidad: por función. Una función en ``services/competitive/`` o
``services/ml/`` cuyo cuerpo referencia ``FROM/JOIN licitaciones`` o
``adjudicaciones`` debe contener una llamada textual a ``exclude_duplicados_sql``.
Las excepciones legítimas (queries que deliberadamente no deduplican) se
declaran en ``_ALLOWLIST`` con su justificación.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

# Directorios cuyas queries analíticas deben respetar el dedupe.
_SCANNED_DIRS = ("services/competitive", "services/ml")

# Referencia a las tablas canónicas en cláusulas FROM/JOIN.
# ``\b`` tras el nombre evita falsos positivos con ``licitaciones_duplicados``,
# ``licitaciones_history``, etc. (``_`` es carácter de palabra → no hay frontera).
_TABLE_REF = re.compile(
    r"\b(?:FROM|JOIN)\s+(?:licitaciones|adjudicaciones)\b",
    re.IGNORECASE,
)

_GUARD_CALL = "exclude_duplicados_sql"

# Excepciones legítimas: "modulo.funcion" -> motivo.
# Mantener vacío salvo justificación explícita y revisada.
_ALLOWLIST: dict[str, str] = {}

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _iter_functions() -> list[tuple[str, str, str]]:
    """(qualname, source, file) por cada función en los directorios escaneados."""
    out: list[tuple[str, str, str]] = []
    for rel_dir in _SCANNED_DIRS:
        base = _REPO_ROOT / rel_dir
        for py_file in sorted(base.rglob("*.py")):
            if py_file.name == "__init__.py":
                continue
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
            module = py_file.stem
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    segment = ast.get_source_segment(source, node)
                    if segment is None:
                        continue
                    out.append((f"{module}.{node.name}", segment, str(py_file)))
    return out


def test_analytical_queries_exclude_duplicados() -> None:
    """Toda función que consulta las tablas canónicas debe excluir duplicados."""
    violations: list[str] = []
    for qualname, segment, file in _iter_functions():
        if qualname in _ALLOWLIST:
            continue
        if _TABLE_REF.search(segment) and _GUARD_CALL not in segment:
            violations.append(f"{qualname}  ({file})")

    assert not violations, (
        "Funciones que consultan licitaciones/adjudicaciones sin "
        f"{_GUARD_CALL}() (riesgo de inflar métricas competitivas/ML):\n  "
        + "\n  ".join(violations)
        + "\n\nAñadí `AND {exclude_duplicados_sql()}` a la query, o declará la "
        "función en _ALLOWLIST con justificación si NO debe deduplicar."
    )


def test_guardrail_actually_scans_functions() -> None:
    """Meta-test: el escáner encuentra funciones (evita falso verde por path roto)."""
    funcs = _iter_functions()
    assert len(funcs) > 10, f"Escáner solo encontró {len(funcs)} funciones; ¿paths mal?"
    # Y al menos una función realmente referencia las tablas canónicas.
    assert any(_TABLE_REF.search(seg) for _, seg, _ in funcs), (
        "Ninguna función referencia licitaciones/adjudicaciones; regex o paths rotos."
    )
