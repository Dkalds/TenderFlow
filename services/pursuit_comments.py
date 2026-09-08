"""Hilo de comentarios de una oportunidad: permisos, moderación y forma de salida.

Es el chat del equipo sobre un expediente. Vive aparte del ledger
``pursuit_events`` (auditoría inmutable, v61): aquí sí hay borrado, y quién
puede borrar es la única regla de negocio del módulo — el autor, o un
owner/admin del espacio que modera.
"""

from __future__ import annotations

from typing import Any

from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuit_comments import PursuitCommentRepository
from db.repositories.pursuits import PursuitRepository
from observability.logging import get_logger
from services.organizations import OrganizationPermissionError, resolve_organization
from services.pursuits import PursuitNotFoundError
from shared.dto import PursuitCommentCreate, PursuitCommentListResponse, PursuitCommentOut

_repo = PursuitCommentRepository()
_pursuits = PursuitRepository()
_organizations = OrganizationRepository()

log = get_logger(__name__)

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
    row, created = _repo.create(
        organization_id=resolved_id,
        pursuit_id=pursuit_id,
        author_user_id=user_id,
        body=body.body,
        idempotency_key=idempotency_key,
    )
    # C6.2: las menciones se resuelven **solo al crear**. Un reintento
    # idempotente devuelve el comentario original y no vuelve a resolver: si lo
    # hiciera, alguien que cambió de nombre entre el primer envío y el reintento
    # quedaría mencionado o desmencionado por un corte de red.
    if created:
        _resolver_menciones(resolved_id, int(row["id"]), body.body)
    return _to_out(row, user_id, role)


def _resolver_menciones(organization_id: int, comment_id: int, texto: str) -> list[int]:
    """Resuelve `@nombre` contra los miembros activos y persiste los ids (C6.2).

    Los miembros se piden **acotados a la organización del comentario**, así que
    mencionar a alguien de fuera es imposible por construcción y no por una
    comprobación posterior que se pueda olvidar. Un nombre ambiguo no resuelve a
    nadie (ver `services/pursuit_menciones.resolver`).

    No lanza: el comentario ya está escrito, y perderlo por no poder resolver
    una mención sería el peor intercambio posible.
    """
    from services.pursuit_menciones import resolver

    try:
        miembros = _organizations.list_members(organization_id)
    except Exception:
        log.warning("pursuit_menciones_miembros_failed", exc_info=True)
        return []
    # `list_members` devuelve `user_id` y `status`; el resolutor quiere `id` y
    # solo los **activos**: mencionar a alguien que ya salió del equipo le
    # mandaría una notificación a una cuenta que no debería recibirla.
    activos = [
        {"id": int(m["user_id"]), "display_name": m.get("display_name") or m.get("email")}
        for m in miembros
        if str(m.get("status") or "active") == "active"
    ]
    resolucion = resolver(texto, activos)
    if resolucion.user_ids:
        _repo.guardar_menciones(comment_id, resolucion.user_ids)
    if resolucion.ambiguos:
        # Se registra, no se adivina: saber que el equipo tiene dos «Ana» es lo
        # que permite arreglarlo, y elegir una notificaría a la equivocada.
        log.info(
            "pursuit_menciones_ambiguas",
            comment_id=comment_id,
            ambiguos=resolucion.ambiguos,
        )
    return resolucion.user_ids


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
