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
