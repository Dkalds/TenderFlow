"""Base del importe de las filas PSCP ya guardadas con lo adjudicado (ADR-032).

Hasta el 2026-11-07, ``scraper.connectors.pscp._importes`` marcaba
``desconocido`` la fila cuyo único importe era el adjudicado: las publicaciones
agregadas de contratos menores (``AGR``) y algunas fases de adjudicación o
ejecución. Ese importe sale de ``import_adjudicacio_sense``, que es sin IVA, y
el parser ya lo declara así. Este módulo lleva la misma regla a las filas
guardadas, sin volver a leer los ~2 millones de filas del dataset de Socrata.

Una fila se corrige solo si su ``importe`` es el ``importe_adjudicado`` de
alguna de sus adjudicaciones —las dos columnas salen del mismo campo— y no
tiene presupuesto, importe con IVA ni valor estimado. Lo que quede (filas sin
adjudicación guardada, o con importe distinto) espera a la re-ingesta.

Lo orquesta ``scripts/backfill_importe_tipo_pscp.py``.
"""

from __future__ import annotations

from db.connection import connect, connect_read

__all__ = ["aplicar_lote", "contar_candidatas"]

# shortcut: el importe pudo salir de `import_adjudicacio_amb_iva` si la fila no
# traía el `_sense` (4 de ~2 millones en el dataset el 2026-11-07), y aquí se
# marcaría `sin_iva`; si esa cifra crece, re-ingerir PSCP en vez de este pase.

#: Filas que el pase corrige. ``abs`` y no ``=``: ``importe`` y
#: ``importe_adjudicado`` fueron ``real`` antes de ``v156`` y conservan ese
#: redondeo, pero cada uno el suyo.
_CANDIDATAS = (
    "FROM licitaciones l "
    "WHERE l.fuente = 'pscp' "
    "  AND l.importe_tipo = 'desconocido' "
    "  AND l.importe IS NOT NULL "
    "  AND l.importe_base_sin_iva IS NULL "
    "  AND l.importe_con_iva IS NULL "
    "  AND l.valor_estimado IS NULL "
    "  AND EXISTS (SELECT 1 FROM adjudicaciones a "
    "              WHERE a.licitacion_id = l.id_externo "
    "                AND abs(a.importe_adjudicado - l.importe) < 0.005)"
)

_SQL_CONTAR = (
    f"SELECT COALESCE(l.estado, '-') AS estado, count(*) {_CANDIDATAS} GROUP BY 1 ORDER BY 2 DESC"
)

# El UPDATE saca la fila del conjunto (deja de ser `desconocido`): repetir el
# lote avanza solo, sin cursor, y un pase ya hecho no escribe nada.
_SQL_APLICAR = (
    "UPDATE licitaciones SET importe_tipo = 'sin_iva' "
    "WHERE id_externo IN ("
    f"  SELECT l.id_externo {_CANDIDATAS} "
    "  ORDER BY l.id_externo LIMIT %s FOR UPDATE OF l SKIP LOCKED)"
)


def contar_candidatas() -> dict[str, int]:
    """Filas que :func:`aplicar_lote` corregiría, por ``estado``. No escribe."""
    with connect_read(statement_timeout_ms=120_000) as c:
        return {str(estado): int(n) for estado, n in c.execute(_SQL_CONTAR).fetchall()}


def aplicar_lote(tamano: int, *, lock_timeout_ms: int = 2000) -> int:
    """Corrige hasta ``tamano`` filas en una transacción. Devuelve cuántas.

    ``SKIP LOCKED`` y ``lock_timeout`` corto: una fila que la ingesta tiene
    bloqueada se salta y la recoge el siguiente lote, en vez de esperarla.
    """
    with connect() as c:
        c.execute(f"SET LOCAL lock_timeout = {int(lock_timeout_ms)}")
        c.execute(_SQL_APLICAR, (tamano,))
        return max(int(c.rowcount), 0)
