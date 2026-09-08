"""Tareas de una oportunidad: permisos y sincronización de la próxima acción (C6.1).

Preparar una oferta no es una acción: son diez, con responsables y fechas
distintas. Hasta 2026-09 el modelo tenía **una** —``pursuits.next_action``, texto
libre— y el resto vivía en un correo.

Este módulo pone las reglas que no son de esquema:

- Toda operación resuelve la organización activa del usuario y trabaja dentro de
  ella. El repositorio ya exige ``organization_id`` en cada ``WHERE``; aquí se
  decide **cuál**.
- ``pursuits.next_action`` pasa a derivarse de las tareas después de cada
  cambio. Es lo que evita que el tablero enseñe una acción que alguien terminó
  hace tres semanas.
"""

from __future__ import annotations

from typing import Any

from db.repositories.pursuit_tasks import PursuitTaskRepository
from db.repositories.pursuits import PursuitRepository
from observability.logging import get_logger
from services.organizations import resolve_organization
from services.pursuits import PursuitNotFoundError
from shared.dto import (
    PursuitTaskAgendaItem,
    PursuitTaskAgendaResponse,
    PursuitTaskCreate,
    PursuitTaskListResponse,
    PursuitTaskOut,
    PursuitTaskUpdate,
)

log = get_logger(__name__)

_repo = PursuitTaskRepository()
_pursuits = PursuitRepository()


class PursuitTaskNotFoundError(LookupError):
    """La tarea no existe dentro de la organización autorizada."""


def _require_pursuit(organization_id: int, pursuit_id: int) -> None:
    if _pursuits.get(organization_id, pursuit_id) is None:
        raise PursuitNotFoundError(f"La oportunidad {pursuit_id} no existe en este espacio.")


def _to_out(fila: dict[str, Any]) -> PursuitTaskOut:
    return PursuitTaskOut(
        id=int(fila["id"]),
        pursuit_id=int(fila["pursuit_id"]),
        organization_id=int(fila["organization_id"]),
        titulo=str(fila["titulo"]),
        responsable_user_id=fila.get("responsable_user_id"),
        vence=fila.get("vence"),
        estado=fila.get("estado") or "pendiente",
        created_at=fila.get("created_at"),
        updated_at=fila.get("updated_at"),
    )


def list_tasks(
    user_id: int,
    pursuit_id: int,
    *,
    organization_id: int | None = None,
    incluir_cerradas: bool = True,
) -> PursuitTaskListResponse:
    """Tareas de la oportunidad: pendientes primero, y por urgencia."""
    resolved_id, _role = resolve_organization(user_id, organization_id)
    _require_pursuit(resolved_id, pursuit_id)
    filas = _repo.listar(
        pursuit_id=pursuit_id,
        organization_id=resolved_id,
        incluir_cerradas=incluir_cerradas,
    )
    return PursuitTaskListResponse(
        pursuit_id=pursuit_id,
        organization_id=resolved_id,
        items=[_to_out(f) for f in filas],
    )


def add_task(
    user_id: int,
    pursuit_id: int,
    body: PursuitTaskCreate,
    *,
    organization_id: int | None = None,
) -> PursuitTaskOut:
    """Crea una tarea y actualiza la próxima acción de la oportunidad."""
    resolved_id, _role = resolve_organization(user_id, organization_id)
    fila = _repo.crear(
        pursuit_id=pursuit_id,
        organization_id=resolved_id,
        titulo=body.titulo,
        responsable_user_id=body.responsable_user_id,
        vence=body.vence.isoformat() if body.vence else None,
        created_by_user_id=user_id,
    )
    if fila is None:
        # El `INSERT … SELECT` no encontró la oportunidad en esta organización.
        # Se responde 404 y no 403 por el mismo motivo que en el resto del
        # espacio: distinguirlos diría si el id existe.
        raise PursuitNotFoundError(f"La oportunidad {pursuit_id} no existe en este espacio.")
    _repo.sincronizar_next_action(pursuit_id=pursuit_id, organization_id=resolved_id)
    return _to_out(fila)


def update_task(
    user_id: int,
    pursuit_id: int,
    task_id: int,
    body: PursuitTaskUpdate,
    *,
    organization_id: int | None = None,
) -> PursuitTaskOut:
    """Cambia una tarea. Los campos ausentes no se tocan; los enviados a ``null`` se borran."""
    resolved_id, _role = resolve_organization(user_id, organization_id)
    enviados = body.model_fields_set
    fila = _repo.actualizar(
        task_id=task_id,
        organization_id=resolved_id,
        titulo=body.titulo,
        responsable_user_id=body.responsable_user_id,
        vence=body.vence.isoformat() if body.vence else None,
        estado=body.estado,
        # `model_fields_set` y no `is not None`: enviar `"responsable_user_id":
        # null` significa desasignar, y compararlo con `None` haría esa
        # operación inexpresable.
        tocar_responsable="responsable_user_id" in enviados,
        tocar_vence="vence" in enviados,
    )
    if fila is None:
        raise PursuitTaskNotFoundError(f"La tarea {task_id} no existe en este espacio.")
    _repo.sincronizar_next_action(pursuit_id=int(fila["pursuit_id"]), organization_id=resolved_id)
    return _to_out(fila)


def agenda(
    user_id: int,
    *,
    organization_id: int | None = None,
    solo_mias: bool = False,
    limite: int = 50,
) -> PursuitTaskAgendaResponse:
    """Tareas pendientes de la organización por urgencia, con su expediente."""
    resolved_id, _role = resolve_organization(user_id, organization_id)
    filas = _repo.agenda(
        organization_id=resolved_id,
        responsable_user_id=user_id if solo_mias else None,
        limite=limite,
    )
    return PursuitTaskAgendaResponse(
        organization_id=resolved_id,
        items=[
            PursuitTaskAgendaItem(
                id=int(f["id"]),
                pursuit_id=int(f["pursuit_id"]),
                id_externo=f.get("id_externo"),
                titulo=str(f["titulo"]),
                responsable_user_id=f.get("responsable_user_id"),
                vence=f.get("vence"),
                estado=f.get("estado") or "pendiente",
            )
            for f in filas
        ],
    )
