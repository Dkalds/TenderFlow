"""Persistencia del hilo de comentarios de cada oportunidad (``pursuit_comments``)."""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

# El nombre visible del autor se resuelve aquí y no en el frontend: los
# miembros de un espacio ya ven el correo de sus compañeros en
# ``/organizations/{id}/members``, así que usarlo de respaldo cuando no hay
# ``display_name`` no expone nada nuevo.
_COMMENT_SELECT = (
    "SELECT c.id, c.pursuit_id, c.organization_id, c.author_user_id, "
    "COALESCE(NULLIF(u.display_name, ''), u.email) AS author_name, "
    "c.body, c.created_at "
    "FROM pursuit_comments c "
    "LEFT JOIN users u ON u.id = c.author_user_id "
)


class PursuitCommentRepository:
    """Queries del hilo, siempre acotadas por ``organization_id`` y ``pursuit_id``."""

    def list_for_pursuit(
        self,
        organization_id: int,
        pursuit_id: int,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Página de comentarios **desde el más reciente**, más el total del hilo.

        Se pagina desde el final porque es lo que un chat necesita: la primera
        página son los últimos mensajes, no los primeros. La página vuelve en
        orden descendente; el servicio la invierte para presentarla en orden
        cronológico.
        """
        with connect_read() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) FROM pursuit_comments "
                "WHERE organization_id = %s AND pursuit_id = %s",
                (organization_id, pursuit_id),
            ).fetchone()
            cur = conn.execute(
                _COMMENT_SELECT + "WHERE c.organization_id = %s AND c.pursuit_id = %s "
                "ORDER BY c.id DESC LIMIT %s OFFSET %s",
                (organization_id, pursuit_id, limit, offset),
            )
            items = rows_to_dicts(cur)
        return items, int(total_row[0] if total_row else 0)

    def get(self, organization_id: int, pursuit_id: int, comment_id: int) -> dict[str, Any] | None:
        with connect_read() as conn:
            return self._get_scoped(conn, organization_id, pursuit_id, comment_id)

    def create(
        self,
        *,
        organization_id: int,
        pursuit_id: int,
        author_user_id: int,
        body: str,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Inserta el comentario; reintentar con la misma clave devuelve el original.

        Mismo contrato que ``pursuit_events`` (índice único parcial sobre
        ``(pursuit_id, idempotency_key)``): un cliente que reenvía tras un corte
        de red no duplica el mensaje. Devuelve ``(fila, creado)``.
        """
        now = now_utc_iso()
        with connect() as conn:
            if idempotency_key:
                existing = self._by_idempotency_key(conn, pursuit_id, idempotency_key)
                if existing is not None:
                    return existing, False
            inserted = conn.execute(
                "INSERT INTO pursuit_comments "
                "(pursuit_id, organization_id, author_user_id, body, idempotency_key, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING RETURNING id",
                (pursuit_id, organization_id, author_user_id, body, idempotency_key, now),
            ).fetchone()
            if inserted is None:
                # Carrera entre dos reintentos con la misma clave: gana el primero.
                existing = self._by_idempotency_key(conn, pursuit_id, str(idempotency_key))
                if existing is None:
                    raise RuntimeError("No se pudo guardar el comentario.")
                return existing, False
            row = self._get_scoped(conn, organization_id, pursuit_id, int(inserted[0]))
            if row is None:
                raise RuntimeError("No se pudo guardar el comentario.")
            return row, True

    def delete(self, organization_id: int, pursuit_id: int, comment_id: int) -> bool:
        """Borra el comentario; ``False`` si no existía dentro del scope."""
        with connect() as conn:
            cur = conn.execute(
                "DELETE FROM pursuit_comments "
                "WHERE organization_id = %s AND pursuit_id = %s AND id = %s",
                (organization_id, pursuit_id, comment_id),
            )
            return int(getattr(cur, "rowcount", 0) or 0) > 0

    def export_for_user(self, user_id: int) -> list[dict[str, Any]]:
        """Comentarios escritos por el usuario (portabilidad RGPD)."""
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT id, pursuit_id, organization_id, author_user_id, body, created_at "
                "FROM pursuit_comments WHERE author_user_id = %s ORDER BY id LIMIT 5000",
                (user_id,),
            )
            return rows_to_dicts(cur)

    def anonymize_author(self, user_id: int) -> None:
        """Desvincula la autoría; el texto sigue siendo trabajo del equipo.

        Mismo criterio que ``PursuitRepository.anonymize_user_references``: se
        borra el vínculo personal, no el registro corporativo.
        """
        with connect() as conn:
            conn.execute(
                "UPDATE pursuit_comments SET author_user_id = NULL WHERE author_user_id = %s",
                (user_id,),
            )

    # ── Menciones (C6.2, v123) ───────────────────────────────────────────

    def guardar_menciones(self, comment_id: int, user_ids: list[int]) -> int:
        """Persiste a quién menciona un comentario. Devuelve cuántas se guardaron.

        Se guardan los **ids**, no el nombre resuelto: congelar el nombre dentro
        del texto significa que cuando la persona cambia su `display_name`, el
        comentario menciona a alguien que ya no se llama así y sin forma de saber
        a quién apuntaba.

        No lanza: un fallo aquí no puede tumbar el comentario, que ya está
        escrito. Perder la mención degrada la notificación; perder el comentario
        pierde el trabajo.
        """
        if not user_ids:
            return 0
        try:
            with connect() as conn:
                for user_id in user_ids:
                    conn.execute(
                        "INSERT INTO pursuit_comment_mentions (comment_id, user_id, created_at) "
                        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (comment_id, int(user_id), now_utc_iso()),
                    )
        except Exception:
            log.warning("pursuit_menciones_insert_failed", comment_id=comment_id, exc_info=True)
            return 0
        return len(user_ids)

    def menciones_de(self, comment_ids: list[int]) -> dict[int, list[int]]:
        """`{comment_id: [user_id]}` para un lote de comentarios.

        Por lote y no de uno en uno: el hilo se pinta entero y una consulta por
        comentario sería una tormenta de consultas por carga de pantalla.
        """
        if not comment_ids:
            return {}
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT comment_id, user_id FROM pursuit_comment_mentions "
                "WHERE comment_id = ANY(%s) ORDER BY comment_id, id",
                (list(comment_ids),),
            )
            filas = rows_to_dicts(cur)
        salida: dict[int, list[int]] = {}
        for f in filas:
            salida.setdefault(int(f["comment_id"]), []).append(int(f["user_id"]))
        return salida

    def menciones_de_usuario(self, user_id: int, *, limit: int = 50) -> list[dict[str, Any]]:
        """En qué comentarios se ha mencionado a alguien, del más reciente atrás.

        Es la consulta del destinatario, y la que alimenta la notificación
        cuando exista el outbox de v2 S4.1. Va acotada por el `organization_id`
        del propio comentario: una mención solo existe dentro de la organización
        donde se escribió, así que no hace falta un filtro extra que alguien
        pueda olvidar.
        """
        with connect_read() as conn:
            cur = conn.execute(
                "SELECT m.comment_id, c.pursuit_id, c.organization_id, c.body, "
                "       c.created_at, c.author_user_id "
                "FROM pursuit_comment_mentions m "
                "JOIN pursuit_comments c ON c.id = m.comment_id "
                "WHERE m.user_id = %s ORDER BY m.id DESC LIMIT %s",
                (user_id, max(1, min(int(limit), 200))),
            )
            return rows_to_dicts(cur)

    @staticmethod
    def _get_scoped(
        conn: Any, organization_id: int, pursuit_id: int, comment_id: int
    ) -> dict[str, Any] | None:
        cur = conn.execute(
            _COMMENT_SELECT + "WHERE c.organization_id = %s AND c.pursuit_id = %s AND c.id = %s",
            (organization_id, pursuit_id, comment_id),
        )
        rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    @staticmethod
    def _by_idempotency_key(
        conn: Any, pursuit_id: int, idempotency_key: str
    ) -> dict[str, Any] | None:
        cur = conn.execute(
            _COMMENT_SELECT + "WHERE c.pursuit_id = %s AND c.idempotency_key = %s",
            (pursuit_id, idempotency_key),
        )
        rows = rows_to_dicts(cur)
        return rows[0] if rows else None
