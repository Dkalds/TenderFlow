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

__all__ = ["AvisosSeguidosRepository", "NovedadesRepository"]


#: Predicado de identidad dual sobre ``watchlist_items w`` (v129, ADR-030 fase
#: 2). Parámetros: ``(user_id, user_key, user_id)``; con ``user_id=None`` se
#: reduce a ``w.user_key = %s``. Ver ``db/repositories/watchlist.py``.
_IDENT_W = "(w.user_id = %s OR (w.user_key = %s AND (w.user_id IS NULL OR %s::int IS NULL)))"


class NovedadesRepository:
    """Lo que ha pasado, desde una fecha, en lo que el usuario sigue."""

    def cambios_en_seguidos(
        self, user_key: str, *, desde_iso: str, limit: int = 50, user_id: int | None = None
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
                f"WHERE {_IDENT_W} AND h.captured_at >= %s "
                "ORDER BY h.captured_at DESC "
                "LIMIT %s",
                (user_id, user_key, user_id, desde_iso, limit),
            )
            return rows_to_dicts(cur)

    def documentos_nuevos_en_seguidos(
        self, user_key: str, *, desde_iso: str, limit: int = 50, user_id: int | None = None
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
                f"WHERE {_IDENT_W} AND d.created_at >= %s "
                "GROUP BY COALESCE(d.source_hash, d.uri), d.licitacion_id, d.tipo, "
                "         d.filename, l.titulo "
                "ORDER BY publicado_en DESC "
                "LIMIT %s",
                (user_id, user_key, user_id, desde_iso, limit),
            )
            return rows_to_dicts(cur)

    def recursos_en_seguidos(
        self, user_key: str, *, desde_iso: str, limit: int = 20, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Resoluciones de recurso sobre expedientes seguidos (F5.2)."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT r.licitacion_id, r.sentido, r.fecha, r.organo, l.titulo "
                "FROM resoluciones_recurso r "
                "JOIN watchlist_items w ON w.id_externo = r.licitacion_id "
                "JOIN licitaciones l ON l.id_externo = r.licitacion_id "
                f"WHERE {_IDENT_W} AND r.fecha >= %s "
                "ORDER BY r.fecha DESC "
                "LIMIT %s",
                (user_id, user_key, user_id, desde_iso, limit),
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


#: Un expediente «seguido» a efectos de los avisos del outbox: favorito de
#: alguien u oportunidad abierta de alguna organización. Es el mismo criterio
#: que ``db.events.seguidores_de_licitacion``, expresado como ``EXISTS`` para
#: poder filtrar en la consulta de candidatos en vez de preguntar fila a fila.
_SEGUIDO = (
    "(EXISTS (SELECT 1 FROM watchlist_items w WHERE w.id_externo = {col}) "
    " OR EXISTS (SELECT 1 FROM pursuits p WHERE p.licitacion_id = {col} "
    "            AND p.status NOT IN ('won', 'lost', 'withdrawn')))"
)


class AvisosSeguidosRepository:
    """Candidatos de los avisos F5.1 y F5.2 del outbox, por cursor de id.

    El productor (``services/avisos_outbox.py``) guarda el último id visto en
    ``ingestion_cursors`` y pide lo que llegó después **hasta un tope fijado al
    empezar** (``hasta_id``): así el cursor puede avanzar hasta el tope aunque
    la mayoría de filas nuevas sean de expedientes que no sigue nadie y por
    eso no vuelvan en la consulta.
    """

    def max_documento_id(self) -> int:
        with connect_read() as c:
            row = c.execute("SELECT COALESCE(MAX(id), 0) FROM documentos").fetchone()
        return int(row[0]) if row else 0

    def documentos_nuevos_seguidos(
        self, *, desde_id: int, hasta_id: int, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Adjuntos con ``desde_id < id <= hasta_id`` de expedientes seguidos.

        Un adjunto cuyo ``source_hash`` ya existía en el mismo expediente con
        un id anterior **no** es nuevo: es el mismo pliego con el token de la
        URL rotado (v88). Sin ese corte, el aviso de F5.1 sería ruido diario.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT d.id AS documento_id, d.licitacion_id, d.tipo, d.filename, "
                "       d.created_at, l.titulo "
                "FROM documentos d "
                "JOIN licitaciones l ON l.id_externo = d.licitacion_id "
                "WHERE d.id > %s AND d.id <= %s "
                "  AND NOT EXISTS ("
                "    SELECT 1 FROM documentos d2 "
                "    WHERE d2.licitacion_id = d.licitacion_id AND d2.id < d.id "
                "      AND d.source_hash IS NOT NULL AND d2.source_hash = d.source_hash"
                "  ) "
                f"  AND {_SEGUIDO.format(col='d.licitacion_id')} "
                "ORDER BY d.id "
                "LIMIT %s",
                (desde_id, hasta_id, limit),
            )
            return rows_to_dicts(cur)

    def max_resolucion_id(self) -> int:
        with connect_read() as c:
            row = c.execute("SELECT COALESCE(MAX(id), 0) FROM resoluciones_recurso").fetchone()
        return int(row[0]) if row else 0

    def recursos_seguidos(
        self, *, desde_id: int, hasta_id: int, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Resoluciones con ``desde_id < id <= hasta_id`` sobre expedientes seguidos.

        Sólo las que ya vienen enlazadas a un expediente (``licitacion_id``):
        una resolución que se enlaza **después** de entrar no avisa, porque el
        cursor ya la dejó atrás. Es el límite conocido del cursor por id.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT r.id AS resolucion_id, r.licitacion_id, r.sentido, r.fecha, "
                "       r.tribunal, r.numero_resolucion, l.titulo "
                "FROM resoluciones_recurso r "
                "JOIN licitaciones l ON l.id_externo = r.licitacion_id "
                "WHERE r.id > %s AND r.id <= %s AND r.licitacion_id IS NOT NULL "
                f"  AND {_SEGUIDO.format(col='r.licitacion_id')} "
                "ORDER BY r.id "
                "LIMIT %s",
                (desde_id, hasta_id, limit),
            )
            return rows_to_dicts(cur)
