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

from db.database import is_postgres_backend

# Condiciones de validez de un par presupuesto/adjudicado. Descarta filas
# sin importes positivos y outliers donde el adjudicado supera el
# presupuesto en más de un 50% (errores de fuente o modificados mal
# atribuidos). Asume alias ``l`` (licitaciones) y ``a`` (adjudicaciones).
VALID_PAIR = (
    "l.importe > 0 AND a.importe_adjudicado > 0 AND a.importe_adjudicado <= l.importe * 1.5"
)

# Fecha de fin efectiva del contrato, con prioridad:
# 1. ``licitaciones.fecha_fin`` explícita (solo ~6% de las filas).
# 2. ``fecha_inicio + duracion`` (unidades CODICE: ANN/MON/DAY).
# 3. ``fecha_adjudicacion + duracion`` como último recurso.
# substr(x, 1, 10) normaliza timestamps ISO a fecha pura; CAST a INT porque
# duracion_valor es REAL y el modificador de date() exige entero. Asume
# alias ``l`` (licitaciones) y ``a`` (adjudicaciones).
#
# Backend-dependiente (ADR-016): SQLite/Turso usa date(); Postgres no tiene
# esa función, así que la rama Postgres usa aritmética de INTERVAL y
# to_char() para devolver el mismo formato TEXT 'YYYY-MM-DD' en ambos casos
# (necesario para que las comparaciones lexicográficas con date('now') /
# CURRENT_DATE sean equivalentes). Usar fecha_fin_sql(), no la constante,
# en código nuevo — la constante se mantiene por compatibilidad (asume SQLite).
FECHA_FIN_SQL = """
COALESCE(
    substr(l.fecha_fin, 1, 10),
    CASE l.duracion_unidad
        WHEN 'ANN' THEN date(substr(COALESCE(l.fecha_inicio, a.fecha_adjudicacion), 1, 10),
                             '+' || CAST(l.duracion_valor AS INTEGER) || ' years')
        WHEN 'MON' THEN date(substr(COALESCE(l.fecha_inicio, a.fecha_adjudicacion), 1, 10),
                             '+' || CAST(l.duracion_valor AS INTEGER) || ' months')
        WHEN 'DAY' THEN date(substr(COALESCE(l.fecha_inicio, a.fecha_adjudicacion), 1, 10),
                             '+' || CAST(l.duracion_valor AS INTEGER) || ' days')
    END
)
"""

_FECHA_FIN_SQL_POSTGRES = """
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
    """Fragmento SQL de fecha de fin efectiva, correcto para el backend activo."""
    return _FECHA_FIN_SQL_POSTGRES if is_postgres_backend() else FECHA_FIN_SQL


def round_sql(expr: str, ndigits: int) -> str:
    """``ROUND`` cross-backend para expresiones sobre columnas de coma flotante.

    Postgres no tiene ``round(double precision, int)`` (solo ``round(numeric,
    int)``), así que las columnas ``real`` (p. ej. ``importe``) rompen con un
    ``UndefinedFunction``. Redondeamos casteando a ``numeric`` y devolvemos el
    resultado como ``FLOAT`` (``double precision`` en Postgres, afinidad
    ``REAL`` en SQLite). El cast final es importante: sin él Postgres devuelve
    ``Decimal``, que Pydantic v2 serializa como *string* en JSON y rompe el
    frontend (``value.toFixed is not a function``). Solo debe recibir
    fragmentos SQL constantes/whitelisted (nunca input de usuario).
    """
    return f"CAST(ROUND(CAST({expr} AS numeric), {ndigits}) AS FLOAT)"
