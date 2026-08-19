"""Fragmentos SQL constantes compartidos entre servicios.

Punto único y auditable para las expresiones SQL que se interpolan en
queries de varios módulos (analytics, competitive, ml). Regla de
composición del proyecto:

- Solo se interpolan con f-string **fragmentos constantes** de este módulo,
  whitelists internas de columnas o helpers como
  ``services.dedupe.exclude_duplicados_sql()`` (que sigue exponiéndose desde
  allí, aunque su definición bajó a ``db/sql_fragments.py``).
- Los valores de usuario van **siempre** con placeholders ``?``.
- Cada query que interpola lleva ``# noqa: S608`` inline con justificación.

``FECHA_FIN_SQL``/``fecha_fin_sql()`` y ``TECHNOLOGY_OBSERVED_SQL`` ya no se
definen aquí: los consume también ``db/`` (repositories de renovaciones y
adjudicaciones, movidos por la ola del ratchet TID251) y ``db/`` no puede
importar de ``services/`` (ADR-024). Viven en ``db/sql_fragments.py`` y se
reexportan desde este módulo, que sigue siendo el sitio por el que los busca
todo ``services/``. Ver el docstring de ese módulo para el razonamiento.
"""

from db.sql_fragments import FECHA_FIN_SQL as FECHA_FIN_SQL
from db.sql_fragments import TECHNOLOGY_OBSERVED_SQL as TECHNOLOGY_OBSERVED_SQL
from db.sql_fragments import fecha_fin_sql as fecha_fin_sql

# Condiciones de validez de un par presupuesto/adjudicado. Descarta filas
# sin importes positivos y outliers donde el adjudicado supera el
# presupuesto en más de un 50% (errores de fuente o modificados mal
# atribuidos). Asume alias ``l`` (licitaciones) y ``a`` (adjudicaciones).
#
# Úsese solo cuando la comparación es AGREGADA por licitación (sumar todas
# las adjudicaciones del expediente y comparar contra l.importe, patrón de
# services/ml/calibration.py y services/ml/scoring.py::_baja_real) — ahí
# l.importe es el denominador correcto porque ya se sumó todo lo adjudicado.
# Para comparar UNA fila de adjudicación contra su presupuesto real (v65_lotes:
# el de su lote, si lo tiene) usar VALID_PAIR_LOTE + EFFECTIVE_BUDGET_SQL.
VALID_PAIR = (
    "l.importe > 0 AND a.importe_adjudicado > 0 AND a.importe_adjudicado <= l.importe * 1.5"
)

# Presupuesto real de UNA fila de adjudicación: el de su lote si lo tiene
# (v65_lotes), si no el del expediente completo (lote único implícito).
# Requiere ``LEFT JOIN lotes lo ON lo.id = a.lote_id`` en la query llamadora.
EFFECTIVE_BUDGET_SQL = "COALESCE(lo.importe, l.importe)"

# Equivalente de VALID_PAIR para comparar una fila de adjudicación contra su
# presupuesto real (el del lote, no el del expediente completo). Antes de
# v65_lotes, comparar un lote contra l.importe sobreestimaba sistemáticamente
# la baja de cualquier expediente con más de un lote — db/repositories/
# pricing.py lo parcheaba descartando ratios > 1 en vez de corregir el
# denominador, perdiendo esas filas de la distribución en vez de arreglarlas.
VALID_PAIR_LOTE = (
    f"({EFFECTIVE_BUDGET_SQL}) > 0 AND a.importe_adjudicado > 0 "
    f"AND a.importe_adjudicado <= ({EFFECTIVE_BUDGET_SQL}) * 1.5"
)

# Baja porcentual de una fila de adjudicación contra su presupuesto real.
# Único punto de esta fórmula fuera de la agregación por licitación — ver
# nota en VALID_PAIR sobre cuál usar según el caso.
BAJA_PCT_SQL = f"(({EFFECTIVE_BUDGET_SQL}) - a.importe_adjudicado) / ({EFFECTIVE_BUDGET_SQL}) * 100"

TECHNOLOGY_OBSERVED_L2_SQL = (
    "COALESCE(l2.analysis_universe, 'technology_observed') = 'technology_observed'"
)
WATCHED_COMPANY_AWARDS_SQL = "l.analysis_universe = 'watched_company_awards_observed'"


def round_sql(expr: str, ndigits: int) -> str:
    """``ROUND`` para expresiones sobre columnas de coma flotante.

    Postgres no tiene ``round(double precision, int)`` (solo ``round(numeric,
    int)``), así que las columnas ``real`` (p. ej. ``importe``) rompen con un
    ``UndefinedFunction``. Redondeamos casteando a ``numeric`` y devolvemos el
    resultado como ``FLOAT`` (``double precision``). El cast final es importante: sin él Postgres devuelve
    ``Decimal``, que Pydantic v2 serializa como *string* en JSON y rompe el
    frontend (``value.toFixed is not a function``). Solo debe recibir
    fragmentos SQL constantes/whitelisted (nunca input de usuario).
    """
    return f"CAST(ROUND(CAST({expr} AS numeric), {ndigits}) AS FLOAT)"
