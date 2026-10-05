"""Fragmentos SQL constantes compartidos entre servicios.

Punto único y auditable para las expresiones SQL que se interpolan en
queries de varios módulos (analytics, competitive, ml). Regla de
composición del proyecto:

- Solo se interpolan con f-string **fragmentos constantes** de este módulo,
  whitelists internas de columnas o helpers como
  ``services.dedupe.exclude_duplicados_sql()`` (que sigue exponiéndose desde
  allí, aunque su definición bajó a ``db/sql_fragments.py``).
- Los valores de usuario van **siempre** con placeholders ``%s``.
- Cada query que interpola lleva ``# noqa: S608`` inline con justificación.

``FECHA_FIN_SQL``/``fecha_fin_sql()``, ``TECHNOLOGY_OBSERVED_SQL``,
``WATCHED_COMPANY_AWARDS_SQL`` y ``round_sql()`` ya no se definen aquí: los
consume también ``db/`` (repositories de renovaciones, adjudicaciones y mercado,
movidos por la ola del ratchet TID251) y ``db/`` no puede importar de
``services/`` (ADR-024). Viven en ``db/sql_fragments.py`` y se reexportan desde
este módulo, que sigue siendo el sitio por el que los busca todo ``services/``.
Ver el docstring de ese módulo para el razonamiento.

Lo mismo vale para la base de comparación de C1.1 / ADR-032
(``SIN_IVA_CONOCIDO_SQL``, ``BASE_DECLARADA_SQL``, ``BASE_COMPARABLE_SQL``,
``BASE_SIN_IVA``, ``BASE_MIXTA``, ``VALID_PAIR_LOTE`` y ``BAJA_PCT_SQL``): bajó
cuando la competencia esperada de la ficha necesitó la baja del ganador desde
``db/repositories/competencia_esperada.py``.
"""

from db.sql_fragments import BAJA_PCT_SQL as BAJA_PCT_SQL
from db.sql_fragments import BASE_COMPARABLE_SQL as BASE_COMPARABLE_SQL
from db.sql_fragments import BASE_DECLARADA_SQL as BASE_DECLARADA_SQL
from db.sql_fragments import BASE_MIXTA as BASE_MIXTA
from db.sql_fragments import BASE_SIN_IVA as BASE_SIN_IVA
from db.sql_fragments import FECHA_FIN_SQL as FECHA_FIN_SQL
from db.sql_fragments import SIN_IVA_CONOCIDO_SQL as SIN_IVA_CONOCIDO_SQL
from db.sql_fragments import TECHNOLOGY_OBSERVED_SQL as TECHNOLOGY_OBSERVED_SQL
from db.sql_fragments import VALID_PAIR_LOTE as VALID_PAIR_LOTE
from db.sql_fragments import WATCHED_COMPANY_AWARDS_SQL as WATCHED_COMPANY_AWARDS_SQL
from db.sql_fragments import fecha_fin_sql as fecha_fin_sql
from db.sql_fragments import round_sql as round_sql

# Condiciones de validez de un par presupuesto/adjudicado. Descarta filas
# sin importes positivos y outliers donde el adjudicado supera el
# presupuesto en más de un 50% (errores de fuente o modificados mal
# atribuidos). Asume alias ``l`` (licitaciones) y ``a`` (adjudicaciones).
#
# Úsese solo cuando la comparación es AGREGADA por licitación (sumar todas
# las adjudicaciones del expediente y comparar contra l.importe) — ahí
# l.importe es el denominador correcto porque ya se sumó todo lo adjudicado.
# Los dos ejemplos que citaba este comentario ya no siguen ese patrón: la
# calibración y la baja real del API (antes
# ``services/ml/scoring.py::_baja_real``) dividen entre el presupuesto efectivo
# del expediente —la suma de los lotes adjudicados cuando todos están
# resueltos— de ``db/repositories/ml_dataset.py`` y
# ``PrediccionesRepository.baja_real_de_expediente``.
# Para comparar UNA fila de adjudicación contra su presupuesto real (v65_lotes:
# el de su lote, si lo tiene) usar VALID_PAIR_LOTE + EFFECTIVE_BUDGET_SQL.
VALID_PAIR = (
    "l.importe > 0 AND a.importe_adjudicado > 0 AND a.importe_adjudicado <= l.importe * 1.5"
)

# Presupuesto real de UNA fila de adjudicación: el de su lote si lo tiene
# (v65_lotes), si no el del expediente completo (lote único implícito).
# Requiere ``LEFT JOIN lotes lo ON lo.id = a.lote_id`` en la query llamadora.
EFFECTIVE_BUDGET_SQL = "COALESCE(lo.importe, l.importe)"

# La base de comparación de C1.1 / ADR-032 (``SIN_IVA_CONOCIDO_SQL``,
# ``BASE_COMPARABLE_SQL``, ``VALID_PAIR_LOTE``, ``BAJA_PCT_SQL``…) se define en
# ``db/sql_fragments.py`` y se reexporta arriba: ver el docstring del módulo.
