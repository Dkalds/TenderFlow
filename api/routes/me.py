"""Endpoints GDPR: export y borrado de datos de usuario.

GET  /api/v1/me/data      — exporta todos los datos del usuario (zip JSON)
DELETE /api/v1/me         — anonimiza todos los datos del usuario
POST /api/v1/auth/logout-all — revoca todas las sesiones activas

Autenticación dual (F13·C3.1, plan Pliegos+RAG): ``/me/data`` y ``/me`` aceptan
sesión OAuth o API key (``require_any_auth``) — antes solo funcionaban con API
key, dejando fuera de la exportación/borrado autoservicio a los usuarios que
solo tienen sesión web (la mayoría — ver GDPR UI en mi-perfil, C3.3b).

Identificación de los datos "de usuario" (watchlist/reglas/perfil/notificaciones):
``user_key`` — la misma clave opaca ``sha256(email o key_hash)[:16]`` que usan
``watchlist_rules``/``watchlist_items``/``competitive``/``user_profiles``, NO el
``key_hash`` crudo (ver ``services/gdpr.py`` para el detalle del bug que esto
corrige). La identificación de API keys/audit log sigue siendo específica del
método de autenticación de la request (no se resuelve por nombre/email para
evitar colisiones GDPR).
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.auth import create_api_key
from api.routes.dual_auth import require_any_auth, require_recent_session
from api.tenancy import require_organization, resolve_organization_ctx
from db.audit import log_event
from db.database import now_utc_iso
from db.repositories.api_keys import ApiKeyRepository
from db.sessions import revoke_all_sessions
from observability.logging import get_logger
from services.gdpr import (
    anonymize_user_data,
    export_audit_log,
    export_collaboration_data,
    export_feedback,
    export_user_notifications,
    export_user_profile,
    export_watchlist,
    export_watchlist_items,
    export_watchlist_rules,
    get_key_name_and_scopes,
    get_user_id_from_key_id,
    revoke_all_api_keys_for_user,
    set_key_expiry,
)

log = get_logger(__name__)

router = APIRouter(tags=["me"])

_key_repo = ApiKeyRepository()


class DeleteMyDataRequest(BaseModel):
    """Explicit confirmation prevents a forged or accidental destructive call."""

    confirmation: Literal["DELETE"]


def _get_user_id_from_key_id(key_id: int) -> int | None:
    """Proxy a services.gdpr — compatibilidad interna."""
    return get_user_id_from_key_id(key_id)


def _user_key(ctx: dict[str, Any]) -> str:
    """Clave opaca y estable por usuario.

    ``require_any_auth`` (sesión o API key) siempre adjunta ``user_key`` al
    contexto vía ``shared.identity.user_key_from_email`` — es la única
    derivación canónica. Antes esta función tenía un fallback local con una
    fórmula distinta (sin ``.strip().lower()``, usando ``key_hash`` en vez de
    ``user_id`` como semilla alternativa) que nunca se ejercitaba en la
    práctica pero podía divergir silenciosamente si algún día lo hiciera.
    """
    return str(ctx["user_key"])


def _actor_key(ctx: dict[str, Any]) -> str:
    """Identificador corto para audit log — misma convención que feedback.py."""
    return str(ctx.get("key_hash") or ctx.get("email") or "session")[:8]


@router.get(
    "/me/data",
    summary="GDPR — exportar todos mis datos",
    responses={200: {"content": {"application/zip": {}}}},
)
def export_my_data(ctx: dict[str, Any] = Depends(require_any_auth)) -> StreamingResponse:
    """Exporta watchlist, reglas, perfil, notificaciones, feedback, API keys y
    audit log en un ZIP JSON. Funciona con sesión OAuth o API key.
    """
    user_key = _user_key(ctx)
    api_keys_data = _key_repo.get_all_for_user(ctx["user_id"])
    key_name = str(ctx.get("email") or ctx["user_id"])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("api_keys.json", json.dumps(api_keys_data, ensure_ascii=False, indent=2))

        watchlist = export_watchlist(user_key)
        zf.writestr("watchlist.json", json.dumps(watchlist, ensure_ascii=False, indent=2))

        watchlist_items = export_watchlist_items(user_key)
        zf.writestr(
            "watchlist_items.json", json.dumps(watchlist_items, ensure_ascii=False, indent=2)
        )

        watchlist_rules = export_watchlist_rules(user_key)
        zf.writestr(
            "watchlist_rules.json", json.dumps(watchlist_rules, ensure_ascii=False, indent=2)
        )

        profile = export_user_profile(user_key)
        zf.writestr("perfil_scoring.json", json.dumps(profile, ensure_ascii=False, indent=2))

        notifications = export_user_notifications(user_key)
        zf.writestr("notificaciones.json", json.dumps(notifications, ensure_ascii=False, indent=2))

        feedback = export_feedback(int(ctx["user_id"]))
        zf.writestr("feedback.json", json.dumps(feedback, ensure_ascii=False, indent=2))

        audit = export_audit_log(_actor_key(ctx))
        zf.writestr("audit.json", json.dumps(audit, ensure_ascii=False, indent=2))

        collaboration = export_collaboration_data(int(ctx["user_id"]))
        for filename, rows in collaboration.items():
            zf.writestr(
                f"{filename}.json",
                json.dumps(rows, ensure_ascii=False, indent=2),
            )

        meta = {
            "exported_at": now_utc_iso(),
            "key_name": key_name,
            "auth_method": ctx.get("auth_method"),
        }
        zf.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2))

    buf.seek(0)
    log_event(
        event_type="gdpr.export",
        user_key=_actor_key(ctx),
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
def delete_my_data(
    body: DeleteMyDataRequest,
    ctx: dict[str, Any] = Depends(require_recent_session()),
) -> dict[str, Any]:
    """Anonimiza watchlist/reglas/perfil/notificaciones y revoca credenciales.

    Requiere una sesión de navegador autenticada recientemente; una API key
    no puede ejecutar la operación.  Anonimiza la cuenta (RGPD Art.17 —
    ``db.users.anonymize_user``), revoca todas las sesiones activas y
    desactiva todas las API keys que el usuario tuviera creadas.
    """
    user_key = _user_key(ctx)
    key_id = ctx.get("api_key_id")
    user_id = int(ctx["user_id"])
    anonymize_user_data(user_key, key_id, user_id=user_id)

    from db.users import anonymize_user

    resource = f"user:{user_id}"
    anonymize_user(user_id)
    revoke_all_sessions(user_id)
    revoke_all_api_keys_for_user(user_id)

    log_event(
        event_type="gdpr.delete",
        user_key=_actor_key(ctx),
        outcome="success",
        resource=resource,
    )
    log.info("gdpr_delete_executed", auth_method=ctx.get("auth_method"))
    return {"status": "ok", "message": "Datos anonimizados y credenciales revocadas."}


@router.post(
    "/auth/logout-all",
    summary="Revocar todas las sesiones activas",
    status_code=200,
)
def logout_all(ctx: dict[str, Any] = Depends(require_any_auth)) -> dict[str, Any]:
    """Revoca todas las sesiones server-side del usuario."""
    user_id = int(ctx["user_id"])
    if user_id:
        n = revoke_all_sessions(user_id)
        log_event(
            event_type="auth.logout_all",
            user_key=_actor_key(ctx),
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
    return _key_repo.get_all_for_user(ctx["user_id"])


@router.post(
    "/me/keys/rotate",
    summary="Rotar API key — genera una nueva con grace period",
    status_code=201,
    responses={
        201: {"description": "Nueva key generada. La key anterior sigue activa N días."},
        400: {"description": "Falta key_id — la sesión no identifica qué key rotar"},
        403: {"description": "Requiere una sesión de navegador reciente"},
        404: {"description": "La key no existe o no pertenece al usuario"},
    },
)
def rotate_my_key(
    ctx: dict[str, Any] = Depends(require_recent_session()),
    key_id: int | None = Query(None, description="ID de la API key a rotar."),
    grace_days: int = Query(7, ge=0, le=30),
) -> dict[str, Any]:
    """Genera una nueva API key con los mismos scopes que la indicada.

    Exige step-up (misma política que ``DELETE /me``): antes bastaba con el
    scope ``api_keys:rotate``, así que una key filtrada podía acuñar otra y
    revocar la original no mataba a la rotada. Con sesión de navegador no hay
    key "actual" implícita, de modo que ``key_id`` es obligatorio y se
    comprueba que pertenezca al usuario autenticado.

    La key anterior permanece activa durante ``grace_days`` (default 7 días)
    para permitir migración gradual. Después de ese período, se desactiva
    automáticamente (requiere que el scheduler ejecute el job de cleanup).

    El token nuevo solo se devuelve en esta respuesta — guárdalo de forma segura.
    """
    from datetime import UTC, datetime, timedelta

    if key_id is None:
        raise HTTPException(
            status_code=400,
            detail="Indicá key_id: la sesión no identifica qué API key rotar.",
        )

    user_id = int(ctx["user_id"])
    # Sin esta comprobación, el step-up solo probaría *quién* pide la rotación,
    # no que la key sea suya: cualquier usuario podría rotar la de otro.
    if _get_user_id_from_key_id(key_id) != user_id:
        raise HTTPException(status_code=404, detail="API key no encontrada.")

    key_info = get_key_name_and_scopes(key_id)
    if not key_info:
        raise HTTPException(status_code=404, detail="API key no encontrada.")

    name, scopes = key_info

    # Marcar la key actual con expires_at = now + grace_days
    grace_expires = (datetime.now(UTC) + timedelta(days=grace_days)).isoformat()
    set_key_expiry(key_id, grace_expires)

    # Crear la nueva key
    new_raw = create_api_key(
        name=f"{name} (rotated)",
        scopes=scopes,
        user_id=user_id,
    )

    log_event(
        event_type="api_key.rotated",
        user_key=_actor_key(ctx),
        resource=f"api_key:{key_id}",
        detail={"grace_days": grace_days, "old_expires_at": grace_expires},
    )
    log.info("api_key_rotated", key_id=key_id, grace_days=grace_days)

    return {
        "new_token": new_raw,
        "message": (
            f"Guarda el token — no es recuperable. "
            f"La key anterior expira en {grace_days} días ({grace_expires[:10]})."
        ),
        "old_key_expires_at": grace_expires,
    }


# ---------------------------------------------------------------------------
# Perfil de scoring personalizado (Feature B)
# ---------------------------------------------------------------------------


class UserProfileBody(BaseModel):
    """Cuerpo para crear/actualizar el perfil de scoring."""

    weights: dict[str, int] | None = None
    afinidad_keywords: list[str] | None = None
    importe_min: float | None = None
    importe_max: float | None = None
    organization_id: int | None = None
    visibility: Literal["private", "organization"] = "private"

    def validate_weights(self) -> None:
        if self.weights is not None:
            total = sum(self.weights.values())
            if total != 100:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=422,
                    detail=f"Los pesos deben sumar 100, suman {total}.",
                )


class UserProfileOut(BaseModel):
    """Perfil devuelto al cliente."""

    user_key: str | None = None
    weights: dict[str, int] | None = None
    afinidad_keywords: list[str] | None = None
    importe_min: float | None = None
    importe_max: float | None = None
    updated_at: str | None = None
    organization_id: int | None = None
    visibility: Literal["private", "organization"] = "private"


@router.get("/me/profile", summary="Obtener el perfil de scoring del usuario")
async def get_profile(
    ctx: dict[str, Any] = Depends(require_organization()),
) -> UserProfileOut:
    """Devuelve el perfil de scoring personalizado del usuario.

    Si no tiene perfil configurado, devuelve un objeto vacio.
    """
    from db.repositories.user_profiles import get_user_profile

    user_key = _user_key(ctx)
    raw = get_user_profile(user_key, ctx["organization_id"])
    if raw is None:
        return UserProfileOut()
    return UserProfileOut(
        weights=raw.get("weights"),
        afinidad_keywords=raw.get("afinidad_keywords"),
        importe_min=raw.get("importe_min"),
        importe_max=raw.get("importe_max"),
        updated_at=raw.get("updated_at"),
        organization_id=raw.get("organization_id"),
        visibility=raw.get("visibility") or "private",
    )


@router.put("/me/profile", summary="Crear o actualizar el perfil de scoring")
async def put_profile(
    body: UserProfileBody,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, str]:
    """Crea o actualiza el perfil de scoring personalizado.

    Los pesos deben sumar 100 cuando se proporcionan.
    Pasar `null` en un campo lo mantiene sin cambios (no sobrescribe).
    """
    from db.repositories.user_profiles import upsert_user_profile

    body.validate_weights()
    ctx = await resolve_organization_ctx(ctx, body.organization_id, write=True)
    user_key = _user_key(ctx)
    upsert_user_profile(
        user_key,
        {
            "weights": body.weights,
            "afinidad_keywords": body.afinidad_keywords,
            "importe_min": body.importe_min,
            "importe_max": body.importe_max,
        },
        ctx["organization_id"],
        body.visibility,
    )
    return {"status": "ok"}


@router.delete("/me/profile", summary="Eliminar el perfil de scoring")
async def delete_profile(
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, str]:
    """Elimina el perfil de scoring. El scoring vuelve a los settings globales."""
    from db.repositories.user_profiles import delete_user_profile

    user_key = _user_key(ctx)
    delete_user_profile(user_key)
    return {"status": "ok"}
