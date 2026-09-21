"""Tareas de una oportunidad (C6.1, v122).

Una oportunidad tenía **una** `next_action` con **una** fecha, y preparar una
oferta son cinco o diez acciones con responsables y plazos distintos. Con un
solo campo, el equipo se organiza fuera del producto o pierde todo menos la
siguiente.

`next_action` no se retira: se **deriva** de aquí (`siguiente_accion`), así que
el tablero, la agenda y el ICS siguen leyendo lo que ya leían.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import ambito_agenda_sql, rows_to_dicts
from db.repositories.pursuits import _ESTADOS_TERMINALES_SQL
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

# Tarea abierta con su oportunidad y su licitación, en una sola consulta. Las
# columnas de la oportunidad llevan los mismos nombres que ``_AGENDA_SELECT``
# de ``db/repositories/pursuits.py`` a propósito: el servicio construye la fila
# de agenda de una tarea con el mismo constructor de campos que la del
# pursuit, y un alias distinto sería un campo vacío sin que nada avisara.
_AGENDA_TAREAS_SELECT = (
    "SELECT t.id AS tarea_id, t.titulo AS tarea_texto, t.vence AS tarea_vence, "
    "t.estado AS tarea_estado, t.responsable_user_id AS tarea_responsable_user_id, "
    "p.id AS pursuit_id, p.licitacion_id, "
    "CASE WHEN p.lote_numero IS NULL THEN l.titulo "
    "     ELSE COALESCE(l.titulo, p.licitacion_id) || ' · Lote ' || p.lote_numero "
    "END AS titulo, "
    "l.fecha_limite AS tender_deadline, l.importe AS importe_eur, "
    "l.organo_contratacion AS organo, l.ccaa, l.tecnologia, l.url, "
    "p.responsible_user_id, u.display_name AS responsible_name, "
    "p.status, p.decision, p.next_action, p.next_action_due, p.version "
    "FROM pursuit_tasks t "
    "JOIN pursuits p ON p.id = t.pursuit_id "
    "JOIN licitaciones l ON l.id_externo = p.licitacion_id "
    "LEFT JOIN users u ON u.id = p.responsible_user_id "
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
                _SELECT + " WHERE t.id = %s AND t.organization_id = %s AND t.deleted_at IS NULL",
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
                "AND t.deleted_at IS NULL "
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
                "AND t.deleted_at IS NULL "
                "ORDER BY t.vence IS NULL, t.vence, t.id LIMIT %s",
                (organization_id, max(1, min(int(limit), 500))),
            )
            return rows_to_dicts(cur)

    def agenda_rows(
        self,
        organization_id: int,
        *,
        responsible_user_id: int | None = None,
        tecnologias: Sequence[str] | None = None,
        ccaas: Sequence[str] | None = None,
        limit: int = 500,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Tareas abiertas de pursuits abiertos, con su oportunidad y licitación.

        Es la consulta de la agenda unificada de Mi Pipeline: cada fila lleva la
        tarea y los campos del pursuit al que pertenece, para que el servicio
        no vuelva a la base por cada una. Devuelve ``(filas, truncado)`` con el
        mismo contrato que ``PursuitRepository.agenda_rows``: se pide
        ``limit + 1`` y se recorta, y el servicio declara el corte (ADR-014).

        Solo tareas abiertas (``pendiente``/``en_curso``, no borradas) de
        oportunidades **abiertas**: una tarea pendiente de una oportunidad
        perdida es trabajo que ya nadie tiene que hacer. ``responsible_user_id``
        filtra por el responsable de la **oportunidad**, que es lo que
        significa «solo mías» en el resto de la agenda; el responsable de la
        tarea viaja aparte (``tarea_responsable_user_id``).

        Orden: sin fecha al final, después por vencimiento y por ``id``, como
        :meth:`agenda`.
        """
        clauses = [
            "t.organization_id = %s",
            "t.estado IN ('pendiente', 'en_curso')",
            "p.status NOT IN " + _ESTADOS_TERMINALES_SQL,
        ]
        params: list[Any] = [organization_id]
        if responsible_user_id is not None:
            clauses.append("p.responsible_user_id = %s")
            params.append(responsible_user_id)
        ambito, valores = ambito_agenda_sql("l", tecnologias=tecnologias, ccaas=ccaas)
        clauses.extend(ambito)
        params.extend(valores)
        with connect_read() as c:
            # ``deleted_at`` va en el literal del ``execute`` y no en ``clauses``
            # a propósito: el guardarraíl estructural de v131
            # (``tests/test_pursuit_borrado_logico.py``) lee el AST de esta
            # llamada, y un filtro escondido en una lista de más arriba pasa la
            # revisión sin que nadie lo vea — que es exactamente el olvido que
            # ese test existe para atrapar.
            cur = c.execute(
                _AGENDA_TAREAS_SELECT
                + " WHERE t.deleted_at IS NULL AND "
                + " AND ".join(clauses)
                + " ORDER BY t.vence IS NULL, t.vence, t.id LIMIT %s",
                tuple([*params, limit + 1]),
            )
            rows = rows_to_dicts(cur)
        return rows[:limit], len(rows) > limit

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
                "WHERE id = %s AND organization_id = %s AND deleted_at IS NULL",
                tuple(params),
            )
            if not getattr(cur, "rowcount", 0):
                return None
        return self.get(organization_id, task_id)

    def delete(self, organization_id: int, task_id: int) -> bool:
        """Marca la tarea como borrada (v131). `False` si no existía o ya lo estaba.

        Borrado lógico por lo mismo que en el hilo de comentarios: la tarea es
        trabajo del equipo en un espacio compartido, y un `DELETE` dejaba que un
        compañero la hiciera desaparecer sin que quedara quién ni cuándo.
        """
        with connect() as c:
            cur = c.execute(
                "UPDATE pursuit_tasks SET deleted_at = now() "
                "WHERE id = %s AND organization_id = %s AND deleted_at IS NULL",
                (task_id, organization_id),
            )
            return bool(getattr(cur, "rowcount", 0))

    def siguiente_accion(self, organization_id: int, pursuit_id: int) -> dict[str, Any] | None:
        """La tarea abierta más urgente. Es lo que `next_action` pasa a mostrar."""
        with connect_read() as c:
            cur = c.execute(
                _SELECT + " WHERE t.pursuit_id = %s AND t.organization_id = %s "
                "AND t.estado IN ('pendiente', 'en_curso') AND t.deleted_at IS NULL "
                "ORDER BY t.vence IS NULL, t.vence, t.id LIMIT 1",
                (pursuit_id, organization_id),
            )
            filas = rows_to_dicts(cur)
        return filas[0] if filas else None

    def vencen_en(self, *, fecha: str) -> list[dict[str, Any]]:
        """Tareas abiertas que vencen en ``fecha`` (evento ``pursuit.task_due``).

        Sin filtro de organización a propósito: lo consume el despachador, que
        emite un evento por fila y necesita ver todas. Cada fila lleva su
        `organization_id`, así que el destinatario se resuelve sin volver a la BD,
        y el `licitacion_id` de su oportunidad, que el evento necesita para que
        el aviso enlace al expediente.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT t.id, t.pursuit_id, t.organization_id, t.titulo, "
                "t.responsable_user_id, u.display_name AS responsable_name, "
                "t.vence, t.estado, t.created_at, t.updated_at, p.licitacion_id "
                "FROM pursuit_tasks t "
                "JOIN pursuits p ON p.id = t.pursuit_id "
                "LEFT JOIN users u ON u.id = t.responsable_user_id "
                # El despachador tampoco puede avisar de una tarea borrada:
                # sería un correo sobre trabajo que ya nadie ve en la ficha.
                "WHERE t.vence = %s AND t.estado IN ('pendiente', 'en_curso') "
                "AND t.deleted_at IS NULL "
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
