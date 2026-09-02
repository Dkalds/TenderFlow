"""Hilo de comentarios de una oportunidad: permisos, moderación y forma de salida.

Es el chat del equipo sobre un expediente. Vive aparte del ledger
``pursuit_events`` (auditoría inmutable, v61): aquí sí hay borrado, y quién
puede borrar es la única regla de negocio del módulo — el autor, o un
owner/admin del espacio que modera.
"""

from __future__ import annotations

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
    """Publica un comentario. Un ``viewer`` no escribe: el rol es de solo lectura."""
    resolved_id, role = resolve_organization(user_id, organization_id, write=True)
    _require_pursuit(resolved_id, pursuit_id)
    row, _created = _repo.create(
        organization_id=resolved_id,
        pursuit_id=pursuit_id,
        author_user_id=user_id,
        body=body.body,
        idempotency_key=idempotency_key,
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
    return PursuitCommentOut.model_validate({**row, "can_delete": _can_delete(row, user_id, role)})
