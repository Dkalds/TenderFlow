"""Tareas de una oportunidad: permisos y forma de salida (C6.1).

El SQL está en `db/repositories/pursuit_tasks.py`. Aquí vive quién puede qué y
la derivación de `next_action`, que sigue siendo el campo que leen el tablero,
la agenda y el ICS.
"""

from __future__ import annotations

from typing import Any

from db.repositories.pursuit_tasks import ESTADOS, PursuitTasksRepository
from db.repositories.pursuits import PursuitRepository
from observability.logging import get_logger
from services.organizations import require_active_member, resolve_organization
from services.pursuits import PursuitNotFoundError

log = get_logger(__name__)

_repo = PursuitTasksRepository()
_pursuits = PursuitRepository()


class PursuitTaskNotFoundError(LookupError):
    """La tarea no existe dentro de la oportunidad autorizada."""


def _require_pursuit(organization_id: int, pursuit_id: int) -> None:
    if _pursuits.get(organization_id, pursuit_id) is None:
        raise PursuitNotFoundError("Oportunidad no encontrada.")


def list_tasks(
    user_id: int, pursuit_id: int, *, organization_id: int | None = None
) -> list[dict[str, Any]]:
    resolved_id, _role = resolve_organization(user_id, organization_id)
    _require_pursuit(resolved_id, pursuit_id)
    return _repo.list_by_pursuit(resolved_id, pursuit_id)


def create_task(
    user_id: int,
    pursuit_id: int,
    *,
    titulo: str,
    responsable_user_id: int | None = None,
    vence: str | None = None,
    organization_id: int | None = None,
) -> dict[str, Any]:
    """Crea una tarea. Un `viewer` no escribe: el rol es de solo lectura.

    Si se asigna responsable, tiene que ser **miembro activo** de la
    organización. Sin esa comprobación, se le podría asignar trabajo a alguien
    que ya se fue —o de otra organización— y la agenda mostraría una tarea que
    nadie va a ver.
    """
    resolved_id, _role = resolve_organization(user_id, organization_id, write=True)
    _require_pursuit(resolved_id, pursuit_id)
    if responsable_user_id is not None:
        require_active_member(resolved_id, responsable_user_id)
    fila = _repo.create(
        pursuit_id=pursuit_id,
        organization_id=resolved_id,
        titulo=titulo,
        responsable_user_id=responsable_user_id,
        vence=vence,
    )
    if fila is None:
        raise PursuitNotFoundError("Oportunidad no encontrada.")
    _sincronizar_next_action(resolved_id, pursuit_id)
    return fila


def update_task(
    user_id: int,
    pursuit_id: int,
    task_id: int,
    *,
    organization_id: int | None = None,
    **cambios: Any,
) -> dict[str, Any]:
    resolved_id, _role = resolve_organization(user_id, organization_id, write=True)
    _require_pursuit(resolved_id, pursuit_id)
    responsable = cambios.get("responsable_user_id")
    if responsable is not None:
        require_active_member(resolved_id, int(responsable))
    estado = cambios.get("estado")
    if estado is not None and estado not in ESTADOS:
        raise ValueError(f"estado inválido: {estado}")
    fila = _repo.update(resolved_id, task_id, **cambios)
    if fila is None:
        raise PursuitTaskNotFoundError("Tarea no encontrada.")
    _sincronizar_next_action(resolved_id, pursuit_id)
    return fila


def delete_task(
    user_id: int, pursuit_id: int, task_id: int, *, organization_id: int | None = None
) -> None:
    resolved_id, _role = resolve_organization(user_id, organization_id, write=True)
    _require_pursuit(resolved_id, pursuit_id)
    if not _repo.delete(resolved_id, task_id):
        raise PursuitTaskNotFoundError("Tarea no encontrada.")
    _sincronizar_next_action(resolved_id, pursuit_id)


def agenda(
    user_id: int, *, organization_id: int | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    resolved_id, _role = resolve_organization(user_id, organization_id)
    return _repo.agenda(resolved_id, limit=limit)


def _sincronizar_next_action(organization_id: int, pursuit_id: int) -> None:
    """Deja `next_action` reflejando la tarea abierta más urgente.

    `next_action` **no se retira** (el tablero, la agenda y el ICS lo leen): se
    convierte en una vista derivada. Se recalcula tras cada escritura y no al
    leer porque los consumidores son muchos y las escrituras pocas; recalcular
    al leer haría que cada carga del tablero escribiera en `pursuits`.

    Fail-open: si la sincronización falla, la tarea ya está guardada y el campo
    derivado se corrige en la siguiente escritura. Perder la tarea por no poder
    actualizar un campo que se puede recalcular sería el peor intercambio.
    """
    try:
        siguiente = _repo.siguiente_accion(organization_id, pursuit_id)
        _pursuits.set_next_action_derivada(
            organization_id,
            pursuit_id,
            titulo=(siguiente or {}).get("titulo"),
            vence=(siguiente or {}).get("vence"),
        )
    except Exception:
        log.warning(
            "pursuit_next_action_sync_failed",
            pursuit_id=pursuit_id,
            organization_id=organization_id,
            exc_info=True,
        )
