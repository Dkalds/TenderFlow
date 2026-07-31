"""Fragmentos SQL constantes compartidos entre servicios.

Punto único y auditable para las expresiones SQL que se interpolan en
queries de varios módulos (analytics, competitive, ml). Regla de
composición del proyecto:

- Solo se interpolan con f-string **fragmentos constantes** de este módulo,
  whitelists internas de columnas o helpers como
  ``services.dedupe.exclude_duplicados_sql()`` (que vive allí porque lleva
  lógica de dominio propia).
- Los valores de usuario van **siempre** con placeholders ``?``.
- Cada query que interpola lleva ``# noqa: S608`` inline con justificación.
"""

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

# Universo por defecto de los agregados del radar. Las filas anteriores al
# linaje se consideran legado del radar porque el único pipeline histórico
# filtraba tecnología; las nuevas fuentes deben declarar su universo y quedan
# fuera salvo que una métrica las solicite expresamente.
TECHNOLOGY_OBSERVED_SQL = (
    "COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'"
)
TECHNOLOGY_OBSERVED_L2_SQL = (
    "COALESCE(l2.analysis_universe, 'technology_observed') = 'technology_observed'"
)
WATCHED_COMPANY_AWARDS_SQL = "l.analysis_universe = 'watched_company_awards_observed'"

# Fecha de fin efectiva del contrato, con prioridad:
# 1. ``licitaciones.fecha_fin`` explícita (solo ~6% de las filas).
# 2. ``fecha_inicio + duracion`` (unidades CODICE: ANN/MON/DAY).
# 3. ``fecha_adjudicacion + duracion`` como último recurso.
# substr(x, 1, 10) normaliza timestamps ISO a fecha pura; CAST a INT porque
# duracion_valor es REAL y el CAST a INTEGER es necesario para la aritmética
# de INTERVAL. Asume alias ``l`` (licitaciones) y ``a`` (adjudicaciones).
#
# Devuelve TEXT 'YYYY-MM-DD' (via to_char) y no un date, para que las
# comparaciones lexicográficas contra las columnas de fecha —que son TEXT en
# este esquema— sean equivalentes.
FECHA_FIN_SQL = """
COALESCE(
    substr(l.fecha_fin, 1, 10),
    CASE l.duracion_unidad
        WHEN 'ANN' THEN to_char(substr(COALESCE(l.fecha_inicio, a.fecha_adjudicacion), 1, 10)::date
                             + (CAST(l.duracion_valor AS INTEGER) * INTERVAL '1 year'), 'YYYY-MM-DD')
        WHEN 'MON' THEN to_char(substr(COALESCE(l.fecha_inicio, a.fecha_adjudicacion), 1, 10)::date
                             + (CAST(l.duracion_valor AS INTEGER) * INTERVAL '1 month'), 'YYYY-MM-DD')
        WHEN 'DAY' THEN to_char(substr(COALESCE(l.fecha_inicio, a.fecha_adjudicacion), 1, 10)::date
                             + (CAST(l.duracion_valor AS INTEGER) * INTERVAL '1 day'), 'YYYY-MM-DD')
    END
)
"""


def fecha_fin_sql() -> str:
    """Fragmento SQL de fecha de fin efectiva.

    Envoltorio de :data:`FECHA_FIN_SQL`. Existía para elegir dialecto entre los
    dos motores; desde ADR-021 hay uno solo, pero se conserva porque es el
    accessor que usan los call-sites y mantiene el punto único de cambio.
    """
    return FECHA_FIN_SQL


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
