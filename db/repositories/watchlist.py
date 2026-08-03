"""Repository para watchlist y pending_digests."""

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


class WatchlistRepository:
    """Acceso a las tablas ``watchlist_cpv``, ``watchlist_items`` y ``pending_digests``."""

    def query_licitaciones_since(self, cpv_prefix: str, since_date: str) -> list[dict[str, Any]]:
        """Licitaciones con CPV que empiece por ``cpv_prefix`` desde ``since_date``."""
        pattern = cpv_prefix + "%"
        with connect_read() as c:
            cur = c.execute(
                "SELECT " + _WATCHLIST_LIC_COLS + " FROM licitaciones "
                "WHERE fecha_publicacion >= ? AND cpv LIKE ? "
                "ORDER BY fecha_publicacion DESC",
                (since_date, pattern),
            )
            return rows_to_dicts(cur)

    def query_licitaciones_batch(
        self, entries: list[dict[str, Any]], default_since: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Consulta licitaciones para múltiples entradas watchlist agrupadas por fecha."""
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
                    "SELECT " + _WATCHLIST_LIC_COLS + " FROM licitaciones "
                    "WHERE fecha_publicacion >= ? AND (" + placeholders + ") "
                    "ORDER BY fecha_publicacion DESC",
                    params,
                )
                rows = rows_to_dicts(cur)

                for prefix in cpv_prefixes:
                    result[prefix] = [r for r in rows if (r.get("cpv") or "").startswith(prefix)]

        return result

    def store_pending_digest(
        self,
        *,
        user_key: str,
        recipient: str,
        entry_id: int,
        licitacion_id: str,
        frequency: str,
        matched_at: str,
    ) -> bool:
        """Persiste una coincidencia en ``pending_digests``."""
        try:
            with connect() as c:
                c.execute(
                    "INSERT INTO pending_digests "
                    "(user_key, recipient_email, entry_id, licitacion_id, frequency, matched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(entry_id, licitacion_id) DO NOTHING",
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

    def load_pending_digests(self, frequency: str) -> list[dict[str, Any]]:
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

    def mark_digests_sent(self, digest_ids: list[int]) -> None:
        """Marca los digests como enviados."""
        if not digest_ids:
            return
        with connect() as c:
            placeholders = ",".join("?" for _ in digest_ids)
            c.execute(
                "UPDATE pending_digests SET sent = 1 WHERE id IN (" + placeholders + ")",
                digest_ids,
            )

    def export_by_user_key(self, user_key: str) -> list[dict[str, Any]]:
        """Exporta entradas de watchlist CPV del usuario (GDPR Art. 15/20).

        Histórico: hasta 2026-08 consultaba una tabla ``watchlist`` inexistente
        con el error tragado por un ``except``, así que el export devolvía
        siempre ``[]``. Sin ``except``: si la query falla, el export debe
        fallar, no fingir que el usuario no tiene datos.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT * FROM watchlist_cpv WHERE user_key = ? LIMIT 5000",
                (user_key,),
            )
            return rows_to_dicts(cur)

    def anonymize_by_user_key(self, user_key: str) -> None:
        """Anonimiza la watchlist CPV del usuario (GDPR Art. 17).

        ``watchlist_cpv`` no tiene columna ``name``; la PII real es
        ``email``/``user_id`` (v53) además del propio ``user_key``. Un fallo
        aquí debe propagarse: un borrado GDPR que falla en silencio es
        incumplimiento, no robustez.
        """
        with connect() as c:
            c.execute(
                "UPDATE watchlist_cpv SET user_key = 'DELETED', email = NULL, "
                "user_id = NULL WHERE user_key = ?",
                (user_key,),
            )

    # ------------------------------------------------------------------
    # watchlist_items — favoritos de licitaciones individuales (v45)
    # ------------------------------------------------------------------

    def list_items(
        self,
        user_key: str,
        organization_id: int | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Favoritos del usuario, enriquecidos con datos de la licitación.

        El backend es la fuente de la analítica/join (ADR-014): el frontend
        nunca debe fabricar este enriquecimiento por su cuenta.
        """
        with connect_read() as c:
            sql = (
                "SELECT wi.id, wi.id_externo, wi.created_at, "
                "       wi.organization_id, wi.visibility, "
                "       l.titulo, l.importe, l.estado, l.fecha_publicacion "
                "FROM watchlist_items wi "
                "LEFT JOIN licitaciones l ON l.id_externo = wi.id_externo "
            )
            if organization_id is None:
                sql += "WHERE wi.user_key = ? "
                params: tuple[Any, ...] = (user_key,)
            else:
                sql += (
                    "WHERE wi.organization_id = ? AND "
                    "(wi.visibility = 'organization' OR wi.user_id = ? OR wi.user_key = ?) "
                )
                params = (organization_id, user_id, user_key)
            cur = c.execute(
                sql + "ORDER BY wi.created_at DESC, wi.id DESC",
                params,
            )
            return rows_to_dicts(cur)

    def add_item(
        self,
        user_key: str,
        user_id: int | None,
        id_externo: str,
        organization_id: int | None = None,
        visibility: str = "private",
    ) -> dict[str, Any]:
        """Añade un favorito de forma idempotente.

        Si el par ``(user_key, id_externo)`` ya existe, no duplica ni falla:
        devuelve el registro existente sin tocarlo.
        """
        with connect() as c:
            if organization_id is None:
                c.execute(
                    "INSERT INTO watchlist_items (user_key, user_id, id_externo) "
                    "VALUES (?, ?, ?) ON CONFLICT(user_key, id_externo) DO NOTHING",
                    (user_key, user_id, id_externo),
                )
            else:
                c.execute(
                    "INSERT INTO watchlist_items "
                    "(user_key, user_id, id_externo, organization_id, visibility) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(user_key, id_externo) DO NOTHING",
                    (user_key, user_id, id_externo, organization_id, visibility),
                )
            cur = c.execute(
                "SELECT id, user_key, user_id, id_externo, organization_id, "
                "visibility, created_at "
                "FROM watchlist_items WHERE user_key = ? AND id_externo = ?",
                (user_key, id_externo),
            )
            rows = rows_to_dicts(cur)
        return rows[0] if rows else {}

    def remove_item(
        self,
        user_key: str,
        id_externo: str,
        organization_id: int | None = None,
    ) -> bool:
        """Elimina un favorito propio. ``True`` si borró algo."""
        with connect() as c:
            if organization_id is None:
                cur = c.execute(
                    "DELETE FROM watchlist_items WHERE user_key = ? AND id_externo = ?",
                    (user_key, id_externo),
                )
            else:
                cur = c.execute(
                    "DELETE FROM watchlist_items WHERE organization_id = ? "
                    "AND id_externo = ? AND (visibility = 'organization' OR user_key = ?)",
                    (organization_id, id_externo, user_key),
                )
            return bool(cur.rowcount > 0)

    def export_items_by_user_key(self, user_key: str) -> list[dict[str, Any]]:
        """Exporta los favoritos (watchlist_items) del usuario (GDPR)."""
        with connect_read() as c:
            try:
                cur = c.execute(
                    "SELECT * FROM watchlist_items WHERE user_key = ? LIMIT 5000",
                    (user_key,),
                )
                return rows_to_dicts(cur)
            except Exception:
                return []

    def anonymize_items_by_user_key(self, user_key: str) -> None:
        """Anonimiza (borra) los favoritos del usuario (GDPR).

        A diferencia de ``watchlist`` (que tiene columna ``name`` a anonimizar
        in-place), ``watchlist_items`` no guarda datos personales adicionales
        más allá de ``user_key``/``user_id``; se eliminan las filas para
        cumplir con el derecho al olvido sin dejar remanentes.
        """
        with connect() as c:
            try:
                c.execute(
                    "DELETE FROM watchlist_items WHERE user_key = ?",
                    (user_key,),
                )
            except Exception:
                log.debug("watchlist_items_anonymize_failed", exc_info=True)
