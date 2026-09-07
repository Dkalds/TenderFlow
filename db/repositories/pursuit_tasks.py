"""Tareas de una oportunidad (C6.1, v121).

Una oportunidad tenía **una** `next_action` con **una** fecha, y preparar una
oferta son cinco o diez acciones con responsables y plazos distintos. Con un
solo campo, el equipo se organiza fuera del producto o pierde todo menos la
siguiente.

`next_action` no se retira: se **deriva** de aquí (`siguiente_accion`), así que
el tablero, la agenda y el ICS siguen leyendo lo que ya leían.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

ESTADOS = frozenset({"pendiente", "en_curso", "hecha", "descartada"})

#: Estados que la agenda considera trabajo por hacer.
ESTADOS_ABIERTOS = ("pendiente", "en_curso")

MAX_TITULO = 300

_SELECT = (
    "SELECT t.id, t.pursuit_id, t.organization_id, t.titulo, "
    "t.responsable_user_id, u.display_name AS responsable_name, "
    "t.vence, t.estado, t.created_at, t.updated_at "
    "FROM pursuit_tasks t "
    "LEFT JOIN users u ON u.id = t.responsable_user_id "
)


class PursuitTasksRepository:
    """Acceso a ``pursuit_tasks`` (TID251: el SQL de tareas vive solo aquí)."""

    def create(
        self,
        *,
        pursuit_id: int,
        organization_id: int,
        titulo: str,
        responsable_user_id: int | None = None,
        vence: str | None = None,
    ) -> dict[str, Any] | None:
        """Crea una tarea dentro de una oportunidad **de esa organización**.

        Devuelve ``None`` si el pursuit no pertenece a la organización: el
        chequeo va en el mismo `INSERT ... SELECT` y no en un `SELECT` previo
        para que no exista una ventana entre comprobar y escribir.
        """
        ahora = now_utc_iso()
        with connect() as c:
            cur = c.execute(
                "INSERT INTO pursuit_tasks "
                "(pursuit_id, organization_id, titulo, responsable_user_id, vence, "
                " estado, created_at, updated_at) "
                "SELECT p.id, p.organization_id, %s, %s, %s, 'pendiente', %s, %s "
                "FROM pursuits p WHERE p.id = %s AND p.organization_id = %s "
                "RETURNING id",
                (
                    titulo[:MAX_TITULO],
                    responsable_user_id,
                    vence,
                    ahora,
                    ahora,
                    pursuit_id,
                    organization_id,
                ),
            )
            fila = cur.fetchone()
        if fila is None:
            return None
        return self.get(organization_id, int(fila[0]))

    def get(self, organization_id: int, task_id: int) -> dict[str, Any] | None:
        with connect_read() as c:
            cur = c.execute(
                _SELECT + " WHERE t.id = %s AND t.organization_id = %s",
                (task_id, organization_id),
            )
            filas = rows_to_dicts(cur)
        return filas[0] if filas else None

    def list_by_pursuit(self, organization_id: int, pursuit_id: int) -> list[dict[str, Any]]:
        """Tareas de una oportunidad, las abiertas primero y por vencimiento.

        `vence IS NULL` va al final: una tarea sin fecha no es más urgente que
        una que vence mañana, y el orden por defecto de Postgres para NULL en
        `ASC` es justo el contrario.
        """
        with connect_read() as c:
            cur = c.execute(
                _SELECT + " WHERE t.pursuit_id = %s AND t.organization_id = %s "
                "ORDER BY (t.estado IN ('hecha', 'descartada')), "
                "         t.vence IS NULL, t.vence, t.id",
                (pursuit_id, organization_id),
            )
            return rows_to_dicts(cur)

    def agenda(self, organization_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
        """Tareas abiertas de la organización por urgencia (Mi Pipeline)."""
        with connect_read() as c:
            cur = c.execute(
                _SELECT + " WHERE t.organization_id = %s AND t.estado IN ('pendiente', 'en_curso') "
                "ORDER BY t.vence IS NULL, t.vence, t.id LIMIT %s",
                (organization_id, max(1, min(int(limit), 500))),
            )
            return rows_to_dicts(cur)

    def update(
        self,
        organization_id: int,
        task_id: int,
        *,
        titulo: str | None = None,
        responsable_user_id: int | None = None,
        vence: str | None = None,
        estado: str | None = None,
        limpiar_responsable: bool = False,
        limpiar_vence: bool = False,
    ) -> dict[str, Any] | None:
        """Actualiza los campos dados. `None` significa «no tocar».

        Vaciar un campo necesita un flag propio (`limpiar_*`) porque `None` ya
        significa «no tocar»: sin la distinción, quitarle la fecha a una tarea
        sería imposible o borrar la fecha sería el efecto de no mandarla.
        """
        sets: list[str] = []
        params: list[Any] = []
        if titulo is not None:
            sets.append("titulo = %s")
            params.append(titulo[:MAX_TITULO])
        if limpiar_responsable:
            sets.append("responsable_user_id = NULL")
        elif responsable_user_id is not None:
            sets.append("responsable_user_id = %s")
            params.append(responsable_user_id)
        if limpiar_vence:
            sets.append("vence = NULL")
        elif vence is not None:
            sets.append("vence = %s")
            params.append(vence)
        if estado is not None:
            if estado not in ESTADOS:
                raise ValueError(f"estado inválido: {estado}")
            sets.append("estado = %s")
            params.append(estado)
        if not sets:
            return self.get(organization_id, task_id)

        sets.append("updated_at = %s")
        params.extend([now_utc_iso(), task_id, organization_id])
        with connect() as c:
            cur = c.execute(
                "UPDATE pursuit_tasks SET " + ", ".join(sets) + " "
                "WHERE id = %s AND organization_id = %s",
                tuple(params),
            )
            if not getattr(cur, "rowcount", 0):
                return None
        return self.get(organization_id, task_id)

    def delete(self, organization_id: int, task_id: int) -> bool:
        with connect() as c:
            cur = c.execute(
                "DELETE FROM pursuit_tasks WHERE id = %s AND organization_id = %s",
                (task_id, organization_id),
            )
            return bool(getattr(cur, "rowcount", 0))

    def siguiente_accion(self, organization_id: int, pursuit_id: int) -> dict[str, Any] | None:
        """La tarea abierta más urgente. Es lo que `next_action` pasa a mostrar."""
        with connect_read() as c:
            cur = c.execute(
                _SELECT + " WHERE t.pursuit_id = %s AND t.organization_id = %s "
                "AND t.estado IN ('pendiente', 'en_curso') "
                "ORDER BY t.vence IS NULL, t.vence, t.id LIMIT 1",
                (pursuit_id, organization_id),
            )
            filas = rows_to_dicts(cur)
        return filas[0] if filas else None

    def vencen_en(self, *, fecha: str) -> list[dict[str, Any]]:
        """Tareas abiertas que vencen en ``fecha`` (evento ``pursuit.task_due``).

        Sin filtro de organización a propósito: lo consume el despachador, que
        emite un evento por fila y necesita ver todas. Cada fila lleva su
        `organization_id`, así que el destinatario se resuelve sin volver a la BD.
        """
        with connect_read() as c:
            cur = c.execute(
                _SELECT + " WHERE t.vence = %s AND t.estado IN ('pendiente', 'en_curso') "
                "ORDER BY t.organization_id, t.id",
                (fecha,),
            )
            return rows_to_dicts(cur)

    def anonymize_user_references(self, user_id: int) -> None:
        """Suelta al responsable sin borrar la tarea (ADR-030 §D).

        La tarea es trabajo del equipo: perderla porque alguien borra su cuenta
        sería destruir trabajo ajeno.
        """
        with connect() as c:
            c.execute(
                "UPDATE pursuit_tasks SET responsable_user_id = NULL, updated_at = %s "
                "WHERE responsable_user_id = %s",
                (now_utc_iso(), user_id),
            )
