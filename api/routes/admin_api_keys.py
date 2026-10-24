"""Admin endpoints — las claves de API de toda la instancia.

Requiere autenticación dual (sesión o API key) + ``is_admin``, como el resto de
``/admin``. Hasta 2026-10 no había ninguna superficie desde la que ver las
claves de otros: ``GET /me/keys`` lista las de quien mira, y la tarjeta que
hubo en Ops > Administración también listaba solo las propias, rotuladas como
«de la instancia». En producción se midieron 89 activas sin dueño ni caducidad
(backlog, «Inventariar las claves de API sin dueño») y ningún camino por el que
dejaran de valer: no se revocan al desactivar a nadie, porque no son de nadie.

Aquí se listan —sin hash ni token— y se revocan una a una. Revocar es CRUD
simple: va a ``db`` directo (ADR-024), y se audita con el ``users.id`` de quien
actúa (ADR-030 §D). La auditoría es best-effort, como en todo el producto.

Basta ``require_admin``, sin sesión reciente: es el mismo nivel que pide
desactivar a un usuario, que revoca de golpe todas sus claves.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.concurrency import run_db
from api.routes.dual_auth import require_admin
from db.audit import log_event
from db.repositories.api_keys import ApiKeyRepository
from observability.logging import get_logger
from shared.audit_events import API_KEY_REVOKED
from shared.dto import (
    AdminApiKeyOut,
    AdminApiKeyRevocadaOut,
    AdminApiKeysOut,
    AdminApiKeysResumen,
)

log = get_logger(__name__)

router = APIRouter(prefix="/admin/api-keys", tags=["admin"])

_repo = ApiKeyRepository()


def _id_del_admin(admin: dict[str, Any]) -> int | None:
    """``users.id`` de quien actúa, para ``audit_log.user_id`` (ADR-030 §D)."""
    valor = admin.get("user_id")
    return int(valor) if valor is not None else None


@router.get(
    "",
    response_model=AdminApiKeysOut,
    summary="Listar las claves de API de la instancia (sin hash ni token)",
)
async def listar_claves(
    limit: int = Query(500, ge=1, le=1000),
    _admin: dict[str, Any] = Depends(require_admin),
) -> AdminApiKeysOut:
    """Todas las claves, de cualquier dueño o de ninguno, y su recuento.

    Las vivas primero (ni revocadas ni caducadas) y, dentro, la más reciente
    arriba. ``resumen`` se cuenta sobre la tabla entera, no sobre la página.
    """

    def _leer() -> tuple[list[dict[str, Any]], dict[str, int]]:
        return _repo.list_all(limit=limit), _repo.resumen_instancia()

    filas, resumen = await run_db(_leer)
    return AdminApiKeysOut(
        items=[
            AdminApiKeyOut(
                id=int(fila["id"]),
                name=str(fila["name"]),
                prefix=fila.get("prefix"),
                tier=fila.get("tier"),
                scopes=str(fila.get("scopes") or "*"),
                user_id=int(fila["user_id"]) if fila.get("user_id") is not None else None,
                owner_email=fila.get("owner_email"),
                owner_name=fila.get("owner_name"),
                owner_deactivated=bool(fila.get("owner_deactivated")),
                organization_id=(
                    int(fila["organization_id"])
                    if fila.get("organization_id") is not None
                    else None
                ),
                created_at=str(fila["created_at"]) if fila.get("created_at") else None,
                expires_at=str(fila["expires_at"]) if fila.get("expires_at") else None,
                last_used=str(fila["last_used"]) if fila.get("last_used") else None,
                estado=fila["estado"],
            )
            for fila in filas
        ],
        resumen=AdminApiKeysResumen(**resumen),
        truncado=resumen["total"] > len(filas),
    )


@router.delete(
    "/{key_id}",
    response_model=AdminApiKeyRevocadaOut,
    summary="Revocar una clave de API de cualquier dueño",
    responses={404: {"description": "La clave no existe"}},
)
async def revocar_clave(
    key_id: int,
    admin: dict[str, Any] = Depends(require_admin),
) -> AdminApiKeyRevocadaOut:
    """Apaga la clave al momento. Revocar una ya revocada responde 200."""
    revocada = await run_db(_repo.revoke_by_id, key_id)
    if revocada is None:
        raise HTTPException(status_code=404, detail="Clave no encontrada.")
    await run_db(
        log_event,
        event_type=API_KEY_REVOKED,
        actor=str(admin.get("user_id", "")),
        user_id=_id_del_admin(admin),
        resource=f"api_key:{key_id}",
        detail={"origen": "administracion", "dueno_user_id": revocada["user_id"]},
    )
    log.info("admin_api_key_revoked", key_id=key_id, owner_user_id=revocada["user_id"])
    return AdminApiKeyRevocadaOut(
        id=revocada["id"], name=revocada["name"], user_id=revocada["user_id"]
    )
