"""Endpoints GDPR: export y borrado de datos de usuario.

GET  /api/v1/me/data      — exporta todos los datos del usuario (zip JSON)
DELETE /api/v1/me         — anonimiza todos los datos del usuario
POST /api/v1/auth/logout-all — revoca todas las sesiones activas

Identificación: el usuario se identifica por el ``key_hash`` de la API Key
autenticada. No se hace resolución por nombre/email para evitar colisiones GDPR.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.auth import AuthContext, create_api_key, require_api_key
from api.routes.dual_auth import require_any_auth
from db.audit import log_event
from db.database import now_utc_iso
from db.repositories.api_keys import ApiKeyRepository
from db.sessions import revoke_all_sessions
from observability.logging import get_logger
from services.gdpr import (
    anonymize_user_data,
    export_api_keys,
    export_audit_log,
    export_feedback,
    export_watchlist,
    export_watchlist_items,
    get_key_name_and_scopes,
    get_user_id_from_key_id,
    list_user_keys,
    set_key_expiry,
)

log = get_logger(__name__)

router = APIRouter(tags=["me"])

_key_repo = ApiKeyRepository()


def _get_user_id_from_key_id(key_id: int) -> int | None:
    """Proxy a services.gdpr — compatibilidad interna."""
    return get_user_id_from_key_id(key_id)


@router.get(
    "/me/data",
    summary="GDPR — exportar todos mis datos",
    responses={200: {"content": {"application/zip": {}}}},
)
def export_my_data(ctx: AuthContext = Depends(require_api_key)) -> StreamingResponse:
    """Exporta watchlist, feedback, API keys y audit log en un ZIP JSON.

    La exportación se vincula exclusivamente al ``key_hash`` de la API key
    autenticada, evitando colisiones por nombre de usuario.
    """
    key_name = _key_repo.get_name(ctx.key_hash) or ctx.key_hash[:8]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        api_keys_data = export_api_keys(ctx.key_hash)
        zf.writestr("api_keys.json", json.dumps(api_keys_data, ensure_ascii=False, indent=2))

        watchlist = export_watchlist(ctx.key_hash)
        zf.writestr("watchlist.json", json.dumps(watchlist, ensure_ascii=False, indent=2))

        watchlist_items = export_watchlist_items(ctx.key_hash)
        zf.writestr(
            "watchlist_items.json", json.dumps(watchlist_items, ensure_ascii=False, indent=2)
        )

        feedback = export_feedback()
        zf.writestr("feedback.json", json.dumps(feedback, ensure_ascii=False, indent=2))

        audit = export_audit_log(ctx.key_hash)
        zf.writestr("audit.json", json.dumps(audit, ensure_ascii=False, indent=2))

        meta = {"exported_at": now_utc_iso(), "key_name": key_name}
        zf.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2))

    buf.seek(0)
    log_event(
        event_type="gdpr.export",
        user_key=ctx.key_hash[:8],
        outcome="success",
    )
    log.info("gdpr_export_generated", key_name=key_name)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=my_data_{now_utc_iso()[:10]}.zip"},
    )


@router.delete(
    "/me",
    summary="GDPR — anonimizar y eliminar mis datos",
    status_code=200,
)
def delete_my_data(ctx: AuthContext = Depends(require_api_key)) -> dict[str, Any]:
    """Anonimiza watchlist y feedback; revoca la API key autenticada.

    La identificación es por ``key_hash`` — no por nombre de usuario,
    evitando borrado accidental de datos de otros usuarios con el mismo nombre.
    """
    anonymize_user_data(ctx.key_hash, ctx.key_id)

    log_event(
        event_type="gdpr.delete",
        user_key=ctx.key_hash[:8],
        outcome="success",
        resource=f"api_key:{ctx.key_id}",
    )
    log.info("gdpr_delete_executed", key_id=ctx.key_id)
    return {"status": "ok", "message": "Datos anonimizados y API key revocada."}


@router.post(
    "/auth/logout-all",
    summary="Revocar todas las sesiones activas",
    status_code=200,
)
def logout_all(ctx: AuthContext = Depends(require_api_key)) -> dict[str, Any]:
    """Revoca todas las sesiones server-side del usuario."""
    user_id = _get_user_id_from_key_id(ctx.key_id)
    if user_id:
        n = revoke_all_sessions(user_id)
        log_event(
            event_type="auth.logout_all",
            user_key=ctx.key_hash[:8],
            resource=f"user:{user_id}",
            detail={"sessions_revoked": n},
        )
        log.info("logout_all", user_id=user_id, revoked=n)
        return {"status": "ok", "sessions_revoked": n}
    return {"status": "ok", "sessions_revoked": 0}


@router.get(
    "/me/keys",
    summary="Listar mis API keys (sin el secret — solo prefix y metadatos)",
    responses={401: {"description": "API key inválida"}},
)
def list_my_keys(ctx: dict[str, Any] = Depends(require_any_auth)) -> list[dict[str, Any]]:
    """Devuelve las API keys vinculadas al usuario autenticado.

    Para API key auth: usa ``key_id``. For session auth: usa ``user_id``.
    El ``prefix`` (primeros 8 chars del token original) permite identificar
    la key en logs/soporte sin exponer el secreto completo.
    """
    if ctx.get("auth_method") == "session":
        return _key_repo.get_all_for_user(ctx["user_id"])
    return list_user_keys(ctx["user_id"])


@router.post(
    "/me/keys/rotate",
    summary="Rotar API key — genera una nueva con grace period",
    status_code=201,
    responses={
        201: {"description": "Nueva key generada. La key anterior sigue activa N días."},
        401: {"description": "API key inválida"},
    },
)
def rotate_my_key(
    ctx: AuthContext = Depends(require_api_key),
    grace_days: int = 7,
) -> dict[str, Any]:
    """Genera una nueva API key con los mismos scopes que la actual.

    La key anterior permanece activa durante ``grace_days`` (default 7 días)
    para permitir migración gradual. Después de ese período, se desactiva
    automáticamente (requiere que el scheduler ejecute el job de cleanup).

    El token nuevo solo se devuelve en esta respuesta — guárdalo de forma segura.
    """
    from datetime import UTC, datetime, timedelta

    # Obtener nombre y scopes de la key actual
    key_info = get_key_name_and_scopes(ctx.key_id)
    if not key_info:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="API key no encontrada.")

    name, scopes = key_info

    # Marcar la key actual con expires_at = now + grace_days
    grace_expires = (datetime.now(UTC) + timedelta(days=grace_days)).isoformat()
    set_key_expiry(ctx.key_id, grace_expires)

    # Crear la nueva key
    new_raw = create_api_key(
        name=f"{name} (rotated)",
        scopes=scopes,
        user_id=_get_user_id_from_key_id(ctx.key_id),
    )

    log_event(
        event_type="api_key.rotated",
        user_key=ctx.key_hash[:8],
        resource=f"api_key:{ctx.key_id}",
        detail={"grace_days": grace_days, "old_expires_at": grace_expires},
    )
    log.info("api_key_rotated", key_id=ctx.key_id, grace_days=grace_days)

    return {
        "new_token": new_raw,
        "message": (
            f"Guarda el token — no es recuperable. "
            f"La key anterior expira en {grace_days} días ({grace_expires[:10]})."
        ),
        "old_key_expires_at": grace_expires,
    }
