"""Base helpers compartidos por todos los repositories."""

from __future__ import annotations

from typing import Any

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
