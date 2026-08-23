"""Base helpers compartidos por todos los repositories."""

from __future__ import annotations

import re
from typing import Any

# Identificadores SQL que se pueden interpolar: los nombres de tabla y columna
# viajan concatenados (no admiten placeholder), así que se validan antes.
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_ALLOWED_TABLES = frozenset(
    {
        "licitaciones",
        "adjudicaciones",
        "ml_feedback",
        "webhooks",
        "api_keys",
        "audit_log",
        "users",
        "watchlist",
        "sessions",
        "webhook_deliveries",
        "idempotency_keys",
    }
)


def csv_values(value: str | None) -> list[str]:
    """Trocea un filtro multi-valor (``"Madrid,Cataluña"``) en sus valores.

    La barra de ámbito del frontend permite marcar varias CCAAs, estados o
    tecnologías y las manda unidas por comas (``web/src/lib/filters.ts``:
    ``ccaas.join(",")``). Vive aquí y no en un repository concreto porque es la
    misma codificación para los dos que la reciben —``aggregates`` (analytics) y
    ``licitaciones`` (el listado)—, y que ambos la lean igual es justo lo que
    evita que la tabla y los KPIs de al lado midan universos distintos.

    Un valor suelto devuelve una lista de uno, así que los llamadores que pasan
    un único valor no cambian de comportamiento.
    """
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def rows_to_dicts(cursor: Any) -> list[dict[str, Any]]:
    """Convierte todas las filas de un cursor en lista de dicts."""
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row, strict=False)) for row in cursor.fetchall()]


def count_where(conn: Any, table: str, where: str, params: tuple[Any, ...]) -> int:
    """SELECT COUNT(*) con cláusula WHERE opcional. Tabla whitelisted."""
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Tabla no permitida: {table!r}")
    sql = "SELECT COUNT(*) FROM " + table
    if where:
        sql += " WHERE " + where
    row = conn.execute(sql, params).fetchone()
    return int(row[0] if row else 0)


def _check_identifiers(table: str, col: str) -> None:
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Tabla no permitida: {table!r}")
    if not _SAFE_IDENTIFIER_RE.match(col):
        raise ValueError(f"Columna no permitida: {col!r}")


def _loose_scan_cte(table: str, col: str, *, seed: str) -> str:
    """CTE recursivo que salta de un valor distinto al siguiente por el btree.

    El *loose index scan* sustituye al ``SELECT DISTINCT``, que recorre el
    índice entero —1,64 M entradas para devolver 19 CCAA— y con el visibility
    map incompleto acaba bajando al heap de 972 MB: 39 s de media medidos en
    producción. Aquí cada paso pide "el primero mayor que el anterior", que el
    btree resuelve con un ``LIMIT 1``, así que el coste es una descensión por
    valor distinto y no por fila: 41,8 ms para ``ccaa``.

    ``seed`` decide el primer valor y con él qué cuenta como distinto, que es
    la única diferencia entre los dos consumidores (ver más abajo).
    """
    return (
        "WITH RECURSIVE saltos AS ("
        f"    {seed}"
        "  UNION ALL "
        f"    SELECT (SELECT l.{col} FROM {table} l "
        f"            WHERE l.{col} > saltos.v ORDER BY l.{col} LIMIT 1) "
        "     FROM saltos WHERE saltos.v IS NOT NULL"
        ")"
    )


def loose_distinct_strings(conn: Any, table: str, col: str) -> list[str]:
    """Valores distintos no vacíos de ``col``, ordenados.

    Semilla ``col > ''``: es la forma sargable de "ni NULL ni cadena vacía"
    —el btree arranca en el primer valor útil en vez de filtrar fila a fila— y
    deja fuera la cadena vacía desde el principio, que es lo que quiere un
    selector de filtros. Asume colación determinista, igual que el ``DISTINCT``
    al que sustituye.
    """
    _check_identifiers(table, col)
    seed = f"(SELECT {col} AS v FROM {table} WHERE {col} > '' ORDER BY {col} LIMIT 1)"
    rows = conn.execute(
        _loose_scan_cte(table, col, seed=seed)
        + " SELECT v FROM saltos WHERE v IS NOT NULL AND v <> '' ORDER BY v"
    ).fetchall()
    return [str(r[0]) for r in rows]


def loose_distinct_count(conn: Any, table: str, col: str) -> int:
    """Número de valores distintos de ``col``, equivalente a ``COUNT(DISTINCT col)``.

    Semilla ``MIN(col)`` y no ``col > ''`` como en
    :func:`loose_distinct_strings`: ``COUNT(DISTINCT)`` cuenta la cadena vacía
    como un valor más (solo ignora NULL), así que arrancar en el primer valor
    estrictamente mayor que ``''`` devolvería uno menos en cuanto el corpus
    tenga una fila con la columna vacía. ``MIN`` también resuelve por índice.
    """
    _check_identifiers(table, col)
    seed = f"(SELECT MIN({col}) AS v FROM {table})"
    row = conn.execute(
        _loose_scan_cte(table, col, seed=seed) + " SELECT COUNT(*) FROM saltos WHERE v IS NOT NULL"
    ).fetchone()
    return int(row[0] if row else 0)
