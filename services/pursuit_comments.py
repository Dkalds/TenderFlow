"""Hilo de comentarios de una oportunidad: permisos, moderación y forma de salida.

Es el chat del equipo sobre un expediente. Vive aparte del ledger
``pursuit_events`` (auditoría inmutable, v61): aquí sí hay borrado, y quién
puede borrar es la única regla de negocio del módulo — el autor, o un
owner/admin del espacio que modera.
"""

from __future__ import annotations

import json
from typing import Any

from db.repositories.pursuit_comments import PursuitCommentRepository
from db.repositories.pursuits import PursuitRepository
from services.organizations import OrganizationPermissionError, resolve_organization
from services.pursuits import PursuitNotFoundError
from shared.dto import PursuitCommentCreate, PursuitCommentListResponse, PursuitCommentOut

_repo = PursuitCommentRepository()
_pursuits = PursuitRepository()

# Roles que pueden borrar comentarios ajenos.
_MODERATOR_ROLES = frozenset({"owner", "admin"})


class PursuitCommentNotFoundError(LookupError):
    """El comentario no existe dentro del hilo autorizado."""


def list_comments(
    user_id: int,
    pursuit_id: int,
    *,
    organization_id: int | None = None,
    limit: int = 200,
    offset: int = 0,
) -> PursuitCommentListResponse:
    """Página del hilo en orden cronológico, paginada desde el más reciente."""
    resolved_id, role = resolve_organization(user_id, organization_id)
    _require_pursuit(resolved_id, pursuit_id)
    rows, total = _repo.list_for_pursuit(resolved_id, pursuit_id, limit=limit, offset=offset)
    return PursuitCommentListResponse(
        pursuit_id=pursuit_id,
        organization_id=resolved_id,
        items=[_to_out(row, user_id, role) for row in reversed(rows)],
        total=total,
        limit=limit,
        offset=offset,
    )


def add_comment(
    user_id: int,
    pursuit_id: int,
    body: PursuitCommentCreate,
    *,
    organization_id: int | None = None,
    idempotency_key: str | None = None,
) -> PursuitCommentOut:
    """Publica un comentario. Un ``viewer`` no escribe: el rol es de solo lectura.

    Las menciones ``@nombre`` se resuelven **contra los miembros activos de esta
    organización** (C6.2), así que una mención no puede notificar fuera de ella
    ni a quien todavía no ha aceptado la invitación. Lo ambiguo no resuelve: con
    dos «Ana» en el equipo, `@ana` no notifica a ninguna — elegir una es peor que
    no elegir.
    """
    from db.repositories.organizations import OrganizationRepository
    from services.menciones import notificar, resolver

    resolved_id, role = resolve_organization(user_id, organization_id, write=True)
    _require_pursuit(resolved_id, pursuit_id)
    miembros = OrganizationRepository().list_members(resolved_id)
    mencionados = resolver(body.body, miembros)
    row, created = _repo.create(
        organization_id=resolved_id,
        pursuit_id=pursuit_id,
        author_user_id=user_id,
        body=body.body,
        idempotency_key=idempotency_key,
        mentions=mencionados,
    )
    # Sólo en la creación real: un reintento con la misma clave de idempotencia
    # devuelve el comentario original y no debe volver a avisar a nadie.
    if created and mencionados:
        notificar(
            mencionados=mencionados,
            autor_user_id=user_id,
            organization_id=resolved_id,
            pursuit_id=pursuit_id,
            comment_id=int(row["id"]),
        )
    return _to_out(row, user_id, role)


def delete_comment(
    user_id: int,
    pursuit_id: int,
    comment_id: int,
    *,
    organization_id: int | None = None,
) -> None:
    """Borra un comentario propio; owner y admin pueden borrar cualquiera."""
    resolved_id, role = resolve_organization(user_id, organization_id, write=True)
    _require_pursuit(resolved_id, pursuit_id)
    row = _repo.get(resolved_id, pursuit_id, comment_id)
    if row is None:
        raise PursuitCommentNotFoundError("Comentario no encontrado.")
    if not _can_delete(row, user_id, role):
        raise OrganizationPermissionError(
            "Solo el autor, o un owner o admin del espacio, puede borrar un comentario."
        )
    if not _repo.delete(resolved_id, pursuit_id, comment_id):
        raise PursuitCommentNotFoundError("Comentario no encontrado.")


def _require_pursuit(organization_id: int, pursuit_id: int) -> None:
    if _pursuits.get(organization_id, pursuit_id) is None:
        raise PursuitNotFoundError("Oportunidad no encontrada.")


def _can_delete(row: dict[str, Any], user_id: int, role: str) -> bool:
    author = row.get("author_user_id")
    return (author is not None and int(author) == user_id) or role in _MODERATOR_ROLES


def _to_out(row: dict[str, Any], user_id: int, role: str) -> PursuitCommentOut:
    return PursuitCommentOut.model_validate(
        {
            **row,
            "mentions": _menciones(row.get("mentions_json")),
            "can_delete": _can_delete(row, user_id, role),
        }
    )


def _menciones(crudo: Any) -> list[int]:
    """`mentions_json` a lista de ids. Una fila corrupta no rompe el hilo.

    Los comentarios anteriores a `v124` traen `NULL` y salen como `[]`: la
    distinción entre «no había» y «nadie las buscó» importa en la base para
    poder reprocesar, no en el contrato que lee la interfaz.
    """
    if not crudo:
        return []
    if isinstance(crudo, list):
        return [int(x) for x in crudo if isinstance(x, int | str) and str(x).isdigit()]
    try:
        datos = json.loads(str(crudo))
    except (TypeError, ValueError):
        return []
    return [int(x) for x in datos if isinstance(x, int)] if isinstance(datos, list) else []
