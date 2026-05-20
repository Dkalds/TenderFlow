"""Tipos compartidos entre scraper, scheduler, dashboard y API.

Centraliza TypedDicts y alias de tipo que se usan en múltiples módulos,
evitando duplicación y mejorando el type-checking con mypy strict.

Uso:
    from shared.types import UserRow, WatchlistRow, LicitacionRow, JsonDict
"""

from __future__ import annotations

from typing import Any, TypeAlias

# ── Alias genérico ───────────────────────────────────────────────────────
# Usar sólo cuando el shape real no está especificado. Preferir TypedDicts.
JsonDict: TypeAlias = dict[str, Any]


# ── Usuarios ────────────────────────────────────────────────────────────
class UserRow(dict[str, Any]):
    """Dict que representa una fila de la tabla ``users``.

    Campos: id, email, display_name, oauth_provider, oauth_sub,
            is_admin, created_at, last_access (en list_users).
    """


# ── Watchlist ────────────────────────────────────────────────────────────
class WatchlistRow(dict[str, Any]):
    """Dict que representa una fila de ``watchlist_cpv``.

    Campos: id, user_key, cpv_prefix, keyword, min_importe, ccaa,
            email, user_id, frequency, created_at, last_notified_at.
    """


# ── Licitaciones (filas de df) ────────────────────────────────────────────
class LicitacionRow(dict[str, Any]):
    """Dict que representa una fila del DataFrame de licitaciones.

    Campos habituales: expediente, descripcion, organo_contratacion,
    importe_licitacion, fecha_pub, estado_desc, cpv_desc, ccaa, etc.
    """


# ── Notificaciones ────────────────────────────────────────────────────────
class NotificationRow(dict[str, Any]):
    """Dict que representa una fila de la tabla ``notifications``."""


# ── DLQ ──────────────────────────────────────────────────────────────────
class DlqRow(dict[str, Any]):
    """Dict que representa una fila de la tabla ``dlq``."""


# ── KPI snapshot ─────────────────────────────────────────────────────────
class KpiSnapshot(dict[str, Any]):
    """Dict de métricas pre-computadas (kpi_precompute).

    Campos: total, adjudicadas, importe_medio, top_organos, etc.
    """
