"""Tareas de una oportunidad (C6.1).

Hasta 2026-09 una oportunidad tenía **una** próxima acción y era texto libre
(``pursuits.next_action``). Preparar una oferta son diez tareas con responsables
y fechas distintas; el equipo llevaba las otras nueve en un correo.

El esquema lo crea ``v122``, y su docstring explica por qué ``organization_id``
está denormalizado y por qué una tarea se cancela en vez de borrarse.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

#: Vocabulario cerrado, espejo del `CHECK` de `v122`.
ESTADOS = ("pendiente", "hecha", "cancelada")
ESTADO_ABIERTO = "pendiente"

_COLUMNAS = (
    "id, pursuit_id, organization_id, titulo, responsable_user_id, vence, "
    "estado, created_by_user_id, created_at, updated_at"
)


class PursuitTaskRepository:
    """Acceso a ``pursuit_tasks``.

    **Toda** consulta lleva ``organization_id`` en el ``WHERE``, incluidas las
    que ya filtran por ``pursuit_id``. Un id de oportunidad se puede enumerar, y
    sin esa condición bastaría con acertar un número para leer —o cerrar— las
    tareas de otro equipo.
    """

    def crear(
        self,
        *,
        pursuit_id: int,
        organization_id: int,
        titulo: str,
        responsable_user_id: int | None = None,
        vence: str | None = None,
        created_by_user_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Crea una tarea. Devuelve ``None`` si la oportunidad no es de esa organización.

        La comprobación va en el mismo ``INSERT … SELECT``: hacerla antes, en
        una consulta aparte, deja una ventana entre el permiso y la escritura.
        """
        titulo_limpio = " ".join((titulo or "").split())
        if not titulo_limpio:
            return None
        ahora = now_utc_iso()
        with connect() as c:
            fila = c.execute(
                "INSERT INTO pursuit_tasks "
                "(pursuit_id, organization_id, titulo, responsable_user_id, vence, "
                " estado, created_by_user_id, created_at, updated_at) "
                "SELECT p.id, p.organization_id, %s, %s, %s, %s, %s, %s, %s "
                "FROM pursuits p WHERE p.id = %s AND p.organization_id = %s "
                f"RETURNING {_COLUMNAS}",
                (
                    titulo_limpio,
                    responsable_user_id,
                    vence,
                    ESTADO_ABIERTO,
                    created_by_user_id,
                    ahora,
                    ahora,
                    pursuit_id,
                    organization_id,
                ),
            ).fetchone()
            if fila is None:
                return None
            columnas = [d[0] for d in c.description] if c.description else []
        return dict(zip(columnas, fila, strict=False))

    def listar(
        self, *, pursuit_id: int, organization_id: int, incluir_cerradas: bool = True
    ) -> list[dict[str, Any]]:
        """Tareas de una oportunidad.

        Orden: primero las pendientes, y dentro de ellas por fecha de
        vencimiento con las **sin fecha al final** (`NULLS LAST`). Sin eso, una
        tarea sin plazo encabeza la lista en Postgres, que ordena los `NULL`
        primero en orden ascendente — y lo primero que se ve sería lo que menos
        corre prisa.
        """
        filtro = "" if incluir_cerradas else "AND estado = 'pendiente' "
        with connect_read() as c:
            return rows_to_dicts(
                c.execute(
                    f"SELECT {_COLUMNAS} FROM pursuit_tasks "
                    "WHERE pursuit_id = %s AND organization_id = %s "
                    f"{filtro}"
                    "ORDER BY CASE estado WHEN 'pendiente' THEN 0 ELSE 1 END, "
                    "vence ASC NULLS LAST, id ASC",
                    (pursuit_id, organization_id),
                )
            )

    def agenda(
        self,
        *,
        organization_id: int,
        responsable_user_id: int | None = None,
        limite: int = 50,
    ) -> list[dict[str, Any]]:
        """Tareas pendientes de la organización por urgencia, con su expediente.

        Es lo que alimenta la agenda de Mi Pipeline. Trae el título de la
        oportunidad y su ``id_externo`` porque una lista de tareas sin decir de
        qué expediente son obliga a abrir cada una para saber si importa.
        """
        condiciones = ["t.organization_id = %s", "t.estado = 'pendiente'"]
        params: list[Any] = [organization_id]
        if responsable_user_id is not None:
            condiciones.append("t.responsable_user_id = %s")
            params.append(responsable_user_id)
        params.append(max(1, min(int(limite), 500)))
        with connect_read() as c:
            return rows_to_dicts(
                c.execute(
                    "SELECT t.id, t.pursuit_id, t.titulo, t.responsable_user_id, "
                    "t.vence, t.estado, p.licitacion_id AS id_externo "
                    "FROM pursuit_tasks t JOIN pursuits p ON p.id = t.pursuit_id "
                    f"WHERE {' AND '.join(condiciones)} "
                    "ORDER BY t.vence ASC NULLS LAST, t.id ASC LIMIT %s",
                    params,
                )
            )

    def actualizar(
        self,
        *,
        task_id: int,
        organization_id: int,
        titulo: str | None = None,
        responsable_user_id: int | None = None,
        vence: str | None = None,
        estado: str | None = None,
        tocar_responsable: bool = False,
        tocar_vence: bool = False,
    ) -> dict[str, Any] | None:
        """Actualiza una tarea. ``None`` si no existe o no es de esa organización.

        ``tocar_responsable``/``tocar_vence`` distinguen «no lo toques» de
        «ponelo a ``NULL``»: sin ese par de banderas, desasignar una tarea o
        quitarle la fecha sería imposible de expresar.
        """
        if estado is not None and estado not in ESTADOS:
            return None
        campos: list[str] = []
        params: list[Any] = []
        if titulo is not None:
            limpio = " ".join(titulo.split())
            if not limpio:
                return None
            campos.append("titulo = %s")
            params.append(limpio)
        if tocar_responsable:
            campos.append("responsable_user_id = %s")
            params.append(responsable_user_id)
        if tocar_vence:
            campos.append("vence = %s")
            params.append(vence)
        if estado is not None:
            campos.append("estado = %s")
            params.append(estado)
        if not campos:
            return None
        campos.append("updated_at = %s")
        params.extend([now_utc_iso(), task_id, organization_id])
        with connect() as c:
            fila = c.execute(
                f"UPDATE pursuit_tasks SET {', '.join(campos)} "
                f"WHERE id = %s AND organization_id = %s RETURNING {_COLUMNAS}",
                params,
            ).fetchone()
            if fila is None:
                return None
            columnas = [d[0] for d in c.description] if c.description else []
        return dict(zip(columnas, fila, strict=False))

    def proxima_pendiente(self, *, pursuit_id: int, organization_id: int) -> dict[str, Any] | None:
        """La tarea pendiente más próxima a vencer, o ``None``."""
        with connect_read() as c:
            filas = rows_to_dicts(
                c.execute(
                    "SELECT titulo, vence FROM pursuit_tasks "
                    "WHERE pursuit_id = %s AND organization_id = %s AND estado = 'pendiente' "
                    "ORDER BY vence ASC NULLS LAST, id ASC LIMIT 1",
                    (pursuit_id, organization_id),
                )
            )
        return filas[0] if filas else None

    def sincronizar_next_action(self, *, pursuit_id: int, organization_id: int) -> None:
        """Deja ``pursuits.next_action`` igual a la tarea pendiente más próxima.

        ``next_action`` se conserva (``v83``) porque lo leen el tablero, el ICS
        y la agenda; lo que cambia es que **ya no se escribe a mano**. Un campo
        que hay que mantener sincronizado a mano se desincroniza, y entonces el
        tablero enseña una acción que alguien terminó hace tres semanas.

        Sin tareas pendientes se pone a ``NULL``: «no hay próxima acción» es una
        respuesta, y dejar la última es enseñar algo falso.
        """
        proxima = self.proxima_pendiente(pursuit_id=pursuit_id, organization_id=organization_id)
        with connect() as c:
            c.execute(
                "UPDATE pursuits SET next_action = %s, next_action_due = %s, updated_at = %s "
                "WHERE id = %s AND organization_id = %s",
                (
                    (proxima or {}).get("titulo"),
                    (proxima or {}).get("vence"),
                    now_utc_iso(),
                    pursuit_id,
                    organization_id,
                ),
            )

    def vencen_en(self, *, organization_id: int, fecha: str) -> list[dict[str, Any]]:
        """Tareas pendientes que vencen exactamente ese día.

        Es la consulta del evento ``pursuit.task_due`` (ADR-027): el despachador
        pregunta una vez al día y emite un evento por tarea.
        """
        with connect_read() as c:
            return rows_to_dicts(
                c.execute(
                    "SELECT t.id, t.pursuit_id, t.titulo, t.responsable_user_id, t.vence, "
                    "p.licitacion_id AS id_externo "
                    "FROM pursuit_tasks t JOIN pursuits p ON p.id = t.pursuit_id "
                    "WHERE t.organization_id = %s AND t.estado = 'pendiente' AND t.vence = %s "
                    "ORDER BY t.id",
                    (organization_id, fecha),
                )
            )
