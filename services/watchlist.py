"""Servicio de watchlist — queries para alertas y digests.

Centraliza las queries SQL que usa ``scheduler/watchlist_alerts.py``
para buscar licitaciones y gestionar ``pending_digests``.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

_WATCHLIST_LIC_COLS = (
    "id_externo, titulo, descripcion, organo_contratacion, "
    "cpv, importe, ccaa, estado, fecha_publicacion, url"
)


def query_licitaciones_since(cpv_prefix: str, since_date: str) -> list[dict[str, Any]]:
    """Devuelve licitaciones con ``fecha_publicacion >= since_date`` y CPV que empiece
    por ``cpv_prefix``."""
    pattern = cpv_prefix + "%"
    with connect_read() as c:
        cur = c.execute(
            f"SELECT {_WATCHLIST_LIC_COLS} FROM licitaciones "  # noqa: S608
            "WHERE fecha_publicacion >= ? AND cpv LIKE ? "
            "ORDER BY fecha_publicacion DESC",
            (since_date, pattern),
        )
        return rows_to_dicts(cur)


def query_licitaciones_batch(
    entries: list[dict[str, Any]], default_since: str
) -> dict[str, list[dict[str, Any]]]:
    """Consulta licitaciones para múltiples entradas watchlist en queries agrupadas por fecha."""
    from collections import defaultdict

    by_since: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        raw_since = entry.get("last_notified_at") or default_since
        by_since[str(raw_since)].append(entry)

    result: dict[str, list[dict[str, Any]]] = {}

    with connect_read() as c:
        for since_date, grp_entries in by_since.items():
            cpv_prefixes = [e["cpv_prefix"] for e in grp_entries]
            placeholders = " OR ".join("cpv LIKE ?" for _ in cpv_prefixes)
            params: list[Any] = [since_date] + [p + "%" for p in cpv_prefixes]
            cur = c.execute(
                f"SELECT {_WATCHLIST_LIC_COLS} FROM licitaciones "  # noqa: S608
                f"WHERE fecha_publicacion >= ? AND ({placeholders}) "
                "ORDER BY fecha_publicacion DESC",
                params,
            )
            rows = rows_to_dicts(cur)

            for prefix in cpv_prefixes:
                result[prefix] = [r for r in rows if (r.get("cpv") or "").startswith(prefix)]

    return result


def store_pending_digest(
    user_key: str,
    recipient: str,
    entry_id: int,
    licitacion_id: str,
    frequency: str,
    matched_at: str,
) -> bool:
    """Persiste una coincidencia en ``pending_digests``. Devuelve ``True`` si tuvo éxito."""
    try:
        with connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO pending_digests "
                "(user_key, recipient_email, entry_id, licitacion_id, frequency, matched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_key, recipient, entry_id, licitacion_id, frequency, matched_at),
            )
        return True
    except Exception as exc:
        log.warning(
            "pending_digest_store_failed",
            entry_id=entry_id,
            licitacion_id=licitacion_id,
            error=str(exc),
        )
        return False


def load_pending_digests(frequency: str) -> list[dict[str, Any]]:
    """Carga los digests pendientes (no enviados) para una frecuencia dada."""
    with connect_read() as c:
        cur = c.execute(
            "SELECT pd.id, pd.recipient_email, pd.entry_id, pd.licitacion_id, pd.user_key, "
            "       l.titulo, l.descripcion, l.organo_contratacion, "
            "       l.cpv, l.importe, l.ccaa, l.estado, l.fecha_publicacion, l.url, "
            "       w.cpv_prefix, w.keyword, w.min_importe, w.ccaa AS entry_ccaa "
            "FROM pending_digests pd "
            "LEFT JOIN licitaciones l ON l.id_externo = pd.licitacion_id "
            "LEFT JOIN watchlist_cpv w ON w.id = pd.entry_id "
            "WHERE pd.sent = 0 AND pd.frequency = ? "
            "ORDER BY pd.recipient_email, pd.entry_id",
            (frequency,),
        )
        return rows_to_dicts(cur)


def mark_digests_sent(digest_ids: list[int]) -> None:
    """Marca los digests como enviados."""
    if not digest_ids:
        return
    with connect() as c:
        placeholders = ",".join("?" for _ in digest_ids)
        c.execute(
            f"UPDATE pending_digests SET sent = 1 WHERE id IN ({placeholders})",  # noqa: S608
            digest_ids,
        )
