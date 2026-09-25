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
"""

from db.sql_fragments import FECHA_FIN_SQL as FECHA_FIN_SQL
from db.sql_fragments import TECHNOLOGY_OBSERVED_SQL as TECHNOLOGY_OBSERVED_SQL
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

# ── C1.1 / ADR-032: la base de comparación ──────────────────────────────────
#
# Una baja es `(presupuesto - adjudicado) / presupuesto`. Si unas filas traen el
# presupuesto CON IVA y otras SIN, la media no es una media de nada: una baja
# del 21 % puede ser exactamente el IVA.
#
# Hasta v113 la fila no decía de qué base era su `importe`. Ahora `importe_tipo`
# lo dice para todo lo ingerido desde entonces, y el histórico anterior queda
# como `desconocido` — no se puede reinterpretar sin volver a parsear el CODICE.
#
# De ahí los dos predicados de abajo, que responden preguntas distintas:

#: Excluye lo que se SABE que lleva IVA. Es la corrección disponible hoy: no
#: recupera el histórico, pero deja de mezclar lo que ya está identificado.
#: Aplicarlo no vacía nada, porque `desconocido` sigue entrando.
SIN_IVA_CONOCIDO_SQL = "COALESCE(l.importe_tipo, 'desconocido') <> 'con_iva'"

#: Solo filas con base sin IVA **declarada**. Es lo que hace verdad un
#: `base: "sin_iva"` en la respuesta, y hoy devuelve poco: `importe_base_sin_iva`
#: se puebla con la re-ingesta, no con la migración. Por eso es opt-in y el
#: default declara `base: "mixta"` — decir "sin IVA" sobre una población mixta
#: sería la misma mentira que el ítem vino a quitar, con otra etiqueta.
BASE_DECLARADA_SQL = "l.importe_tipo = 'sin_iva' AND l.importe_base_sin_iva IS NOT NULL"

#: Presupuesto efectivo prefiriendo la base sin IVA cuando está declarada.
#: El lote manda igual que antes: `lotes.importe` sale del mismo
#: `TaxExclusiveAmount` del lote, así que ya es base sin IVA.
BASE_COMPARABLE_SQL = "COALESCE(lo.importe, l.importe_base_sin_iva, l.importe)"

#: Valores del campo `base` que las respuestas comparativas declaran.
BASE_SIN_IVA = "sin_iva"
BASE_MIXTA = "mixta"

# Equivalente de VALID_PAIR para comparar una fila de adjudicación contra su
# presupuesto real (el del lote, no el del expediente completo). Antes de
# v65_lotes, comparar un lote contra l.importe sobreestimaba sistemáticamente
# la baja de cualquier expediente con más de un lote — db/repositories/
# pricing.py lo parcheaba descartando ratios > 1 en vez de corregir el
# denominador, perdiendo esas filas de la distribución en vez de arreglarlas.
# Usa `BASE_COMPARABLE_SQL` y no `EFFECTIVE_BUDGET_SQL`: prefiere la base sin
# IVA declarada y cae al `importe` histórico cuando no la hay. La diferencia
# solo se nota en las filas re-ingeridas tras v113, que son las únicas que
# tienen ese dato — para el resto es el mismo número.
VALID_PAIR_LOTE = (
    f"({BASE_COMPARABLE_SQL}) > 0 AND a.importe_adjudicado > 0 "
    f"AND a.importe_adjudicado <= ({BASE_COMPARABLE_SQL}) * 1.5"
)

# Baja porcentual de una fila de adjudicación contra su presupuesto real.
# Único punto de esta fórmula fuera de la agregación por licitación — ver
# nota en VALID_PAIR sobre cuál usar según el caso.
BAJA_PCT_SQL = f"(({BASE_COMPARABLE_SQL}) - a.importe_adjudicado) / ({BASE_COMPARABLE_SQL}) * 100"
