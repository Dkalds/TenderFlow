"""SQL de «qué cambió desde tu última visita» (F5.4) y de los avisos F5.1/F5.2.

Tres consultas acotadas por una marca temporal (``desde``) y por lo que el
usuario sigue. Todas llevan ``LIMIT``: la banda del Resumen enseña unas pocas
líneas, y traerse un mes de cambios para pintar cinco sería pagar el coste sin
usarlo.
"""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts

__all__ = ["NovedadesRepository"]


class NovedadesRepository:
    """Lo que ha pasado, desde una fecha, en lo que el usuario sigue."""

    def cambios_en_seguidos(
        self, user_key: str, *, desde_iso: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Cambios registrados en `licitaciones_history` de expedientes seguidos.

        Devuelve el **snapshot anterior y el actual** para que el servicio
        pueda ponerle nombre al cambio (F5.3) sin volver a consultar. Es lo
        que permite que la clasificación viva en un módulo puro.

        Se une por `id_externo` contra `watchlist_items` del usuario: sin esa
        unión la consulta traería los cambios de todo el corpus, que son miles
        al día.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT h.id_externo, h.captured_at, h.changed_fields, h.snapshot_json, "
                "       l.titulo, l.estado, l.fecha_limite, l.importe, l.organo_contratacion "
                "FROM licitaciones_history h "
                "JOIN watchlist_items w ON w.id_externo = h.id_externo "
                "JOIN licitaciones l ON l.id_externo = h.id_externo "
                "WHERE w.user_key = %s AND h.captured_at >= %s "
                "ORDER BY h.captured_at DESC "
                "LIMIT %s",
                (user_key, desde_iso, limit),
            )
            return rows_to_dicts(cur)

    def documentos_nuevos_en_seguidos(
        self, user_key: str, *, desde_iso: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Adjuntos publicados después de ``desde_iso`` en expedientes seguidos.

        La identidad va por ``source_hash`` (v88): sin él, la rotación del
        token en la URL de PLACSP hace parecer nuevo cada día el mismo pliego,
        y el aviso de F5.1 sería ruido diario en vez de una señal. Se agrupa
        por hash y se toma la primera aparición, que es la fecha en que de
        verdad se publicó.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT d.licitacion_id, d.tipo, d.filename, "
                "       MIN(d.created_at) AS publicado_en, l.titulo "
                "FROM documentos d "
                "JOIN watchlist_items w ON w.id_externo = d.licitacion_id "
                "JOIN licitaciones l ON l.id_externo = d.licitacion_id "
                "WHERE w.user_key = %s AND d.created_at >= %s "
                "GROUP BY COALESCE(d.source_hash, d.uri), d.licitacion_id, d.tipo, "
                "         d.filename, l.titulo "
                "ORDER BY publicado_en DESC "
                "LIMIT %s",
                (user_key, desde_iso, limit),
            )
            return rows_to_dicts(cur)

    def recursos_en_seguidos(
        self, user_key: str, *, desde_iso: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Resoluciones de recurso sobre expedientes seguidos (F5.2)."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT r.licitacion_id, r.sentido, r.fecha, r.organo, l.titulo "
                "FROM resoluciones_recurso r "
                "JOIN watchlist_items w ON w.id_externo = r.licitacion_id "
                "JOIN licitaciones l ON l.id_externo = r.licitacion_id "
                "WHERE w.user_key = %s AND r.fecha >= %s "
                "ORDER BY r.fecha DESC "
                "LIMIT %s",
                (user_key, desde_iso, limit),
            )
            return rows_to_dicts(cur)

    def pursuits_movidos(
        self, organization_id: int, *, desde_iso: str, limit: int = 30
    ) -> list[dict[str, Any]]:
        """Oportunidades del equipo que cambiaron de estado desde ``desde_iso``.

        Se lee del ledger (`pursuit_events`) y no de `pursuits.updated_at`:
        lo que interesa es **qué** se movió, y el ledger lo dice; la columna
        sólo diría que algo se tocó.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT e.pursuit_id, e.event_type, e.created_at, e.actor_user_id, "
                "       p.status, p.licitacion_id, l.titulo "
                "FROM pursuit_events e "
                "JOIN pursuits p ON p.id = e.pursuit_id "
                "JOIN licitaciones l ON l.id_externo = p.licitacion_id "
                "WHERE e.organization_id = %s AND e.created_at >= %s "
                "ORDER BY e.created_at DESC "
                "LIMIT %s",
                (organization_id, desde_iso, limit),
            )
            return rows_to_dicts(cur)
