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
import re
import zipfile
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api.auth import create_api_key
from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth, require_recent_session
from api.tenancy import require_organization, resolve_organization_ctx
from db.audit import log_event
from db.database import now_utc_iso
from db.repositories.api_keys import ApiKeyRepository
from db.sessions import (
    list_active_sessions,
    revoke_all_sessions,
    revoke_session_by_public_id,
    session_public_id,
)
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
    revoke_all_api_keys_for_user,
    set_key_expiry,
)
from shared.cache import invalidate_organization_scoped, invalidate_user_scoped
from shared.dto import SessionsRevoked, StatusMessage, StatusOk
from shared.scoring_weights import validate_scoring_weights

log = get_logger(__name__)

router = APIRouter(tags=["me"])

_key_repo = ApiKeyRepository()


class DeleteMyDataRequest(BaseModel):
    """Explicit confirmation prevents a forged or accidental destructive call."""

    confirmation: Literal["DELETE"]


class RotatedKey(BaseModel):
    """Rotación de API key: el token nuevo solo viaja en esta respuesta."""

    new_token: str
    message: str
    old_key_expires_at: str


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


def _invalidate_profile_scoring(user_key: str, *organization_ids: int | None) -> None:
    """Invalida el ranking propio y el de las organizaciones afectadas."""
    invalidate_user_scoped("analytics", "scoring", user_key)
    for organization_id in {value for value in organization_ids if value is not None}:
        invalidate_organization_scoped("analytics", "scoring", organization_id)


def _actor_key(ctx: dict[str, Any]) -> str:
    """Identificador corto para audit log — misma convención que feedback.py."""
    return str(ctx.get("key_hash") or ctx.get("email") or "session")[:8]


# response_class evita el content application/json {} por defecto: la
# respuesta es un ZIP y su contrato lo declara `responses`.
@router.get(
    "/me/data",
    summary="GDPR — exportar todos mis datos",
    response_class=StreamingResponse,
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
) -> StatusMessage:
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
    return StatusMessage(status="ok", message="Datos anonimizados y credenciales revocadas.")


@router.post(
    "/auth/logout-all",
    summary="Revocar todas las sesiones activas",
    status_code=200,
)
def logout_all(ctx: dict[str, Any] = Depends(require_any_auth)) -> SessionsRevoked:
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
        return SessionsRevoked(status="ok", sessions_revoked=n)
    return SessionsRevoked(status="ok", sessions_revoked=0)


class SessionOut(BaseModel):
    """Una sesión activa del usuario (C2.1).

    **No lleva el token ni el hash completo.** El token abre la sesión; el hash
    no abre nada pero tampoco hay razón para publicarlo. `id` es un prefijo del
    hash: estable, no reversible, y suficiente para revocar.
    """

    id: str
    created_at: str | None = None
    expires_at: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    #: `True` en la sesión desde la que se hace la petición. Sin esta marca, el
    #: usuario no sabe cuál de la lista cerraría su propia sesión.
    actual: bool = False


class SessionsResult(BaseModel):
    items: list[SessionOut] = Field(default_factory=list)


@router.get(
    "/me/sessions",
    summary="Listar mis sesiones activas",
    responses={401: {"description": "No autenticado"}},
)
async def list_my_sessions(
    request: Request,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> SessionsResult:
    """Sesiones abiertas del usuario, con la actual marcada.

    `db/sessions.py::list_active_sessions` existía desde siempre y **nadie la
    llamaba** (hecho 7 del plan complementario): el usuario solo tenía
    `POST /auth/logout-all`, o sea cerrar todas o ninguna.
    """
    user_id = int(ctx.get("user_id") or 0)
    if not user_id:
        return SessionsResult()

    filas = await run_db(list_active_sessions, user_id)
    hash_actual = _hash_de_la_sesion_actual(request)

    return SessionsResult(
        items=[
            SessionOut(
                id=session_public_id(str(fila["token_hash"])),
                created_at=fila.get("created_at"),
                expires_at=fila.get("expires_at"),
                ip=fila.get("ip"),
                user_agent=fila.get("user_agent"),
                actual=bool(hash_actual and fila["token_hash"] == hash_actual),
            )
            for fila in filas
        ]
    )


@router.delete(
    "/me/sessions/{session_id}",
    summary="Revocar UNA sesión propia",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"description": "La sesión no existe o no es tuya"}},
)
async def delete_my_session(
    session_id: str,
    ctx: dict[str, Any] = Depends(require_recent_session()),
) -> None:
    """Cierra una sesión concreta sin tocar las demás.

    Exige sesión reciente (`require_recent_session`), igual que el borrado de
    cuenta: cerrar la sesión de otro dispositivo es la acción que alguien con
    una cookie robada usaría para expulsar al dueño.
    """
    user_id = int(ctx.get("user_id") or 0)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sesión no encontrada.")

    ok = await run_db(revoke_session_by_public_id, user_id, session_id)
    if not ok:
        # 404 y no 403: distinguirlos diría si el id existe, que es justo lo que
        # un enumerador quiere saber.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sesión no encontrada.")

    await run_db(
        log_event,
        event_type="auth.session_revoked",
        user_key=_actor_key(ctx),
        resource=f"user:{user_id}",
        detail={"session_id": session_id},
    )
    log.info("session_revoked", user_id=user_id)


def _hash_de_la_sesion_actual(request: Request) -> str | None:
    """Hash de la cookie de sesión de ESTA petición, si la hay.

    Se calcula aquí y no se pide a `db/sessions` porque la única entrada es la
    cookie, que es de la capa HTTP. Una petición con API key no tiene sesión y
    devuelve `None`: entonces ninguna fila sale marcada como actual, que es
    correcto.
    """
    from api.routes.auth import SESSION_COOKIE

    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    from db.sessions import _hash_token

    return _hash_token(token)


class NotificationPreference(BaseModel):
    """Una preferencia de notificación (C2.7).

    `organization_id` `None` = la preferencia del usuario **en todas partes**.
    Con organización, solo en ese equipo: alguien que quiere el digest diario de
    su consultora y nada de su cooperativa no puede expresarlo con una fila.
    """

    tipo: str
    canal: Literal["email", "in_app", "webhook"]
    frecuencia: Literal["immediate", "daily", "off"]
    organization_id: int | None = None


class NotificationTypeOut(BaseModel):
    """Un tipo de aviso configurable, con su etiqueta legible."""

    tipo: str
    label: str


class NotificationPreferencesResult(BaseModel):
    """Preferencias explícitas, los defectos que aplican y el catálogo de tipos.

    `defaults` no es decorativo: la lista de `items` solo trae lo que el usuario
    fijó, y sin conocer el defecto de cada canal el frontend no puede pintar el
    estado real de un ajuste que nadie ha tocado.

    `tipos` tampoco: sin él, la pantalla tendría que llevar su propia lista de
    avisos, y esa lista se queda atrás en cuanto nace uno nuevo — el usuario
    deja de poder configurarlo y nada falla (ADR-014).
    """

    items: list[NotificationPreference] = Field(default_factory=list)
    defaults: dict[str, str] = Field(default_factory=dict)
    tipos: list[NotificationTypeOut] = Field(default_factory=list)


@router.get(
    "/me/notification-preferences",
    summary="Mis preferencias de notificación",
)
async def get_notification_preferences(
    organization_id: int | None = Query(None, description="Acota a una organización"),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> NotificationPreferencesResult:
    """Qué avisos quiere recibir el usuario, y por dónde.

    Ninguna tabla las modelaba (hecho 13 del plan complementario) y el
    despachador de eventos de v2 S4.6 las necesita.
    """
    from db.repositories import notification_preferences as prefs

    user_id = int(ctx.get("user_id") or 0)
    if not user_id:
        return NotificationPreferencesResult(
            defaults=dict(prefs.DEFECTOS),
            tipos=[NotificationTypeOut(tipo=t, label=e) for t, e in prefs.TIPOS],
        )

    filas = await run_db(prefs.listar, user_id, organization_id=organization_id)
    return NotificationPreferencesResult(
        items=[
            NotificationPreference(
                tipo=str(f["tipo"]),
                canal=str(f["canal"]),  # type: ignore[arg-type]
                frecuencia=str(f["frecuencia"]),  # type: ignore[arg-type]
                organization_id=f.get("organization_id"),
            )
            for f in filas
        ],
        defaults=dict(prefs.DEFECTOS),
        tipos=[NotificationTypeOut(tipo=t, label=e) for t, e in prefs.TIPOS],
    )


@router.put(
    "/me/notification-preferences",
    summary="Fijar mis preferencias de notificación",
)
async def put_notification_preferences(
    body: list[NotificationPreference],
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> StatusOk:
    """Guarda las preferencias enviadas. Idempotente por `(org, tipo, canal)`.

    Un `PUT` que solo **añade o pisa** lo enviado, sin borrar lo que no viene:
    el frontend manda lo que el usuario tocó, y una semántica de reemplazo total
    haría que abrir Ajustes en una pantalla estrecha —donde no caben todos los
    tipos— borrase los ajustes que no se llegaron a renderizar.
    """
    from db.repositories import notification_preferences as prefs

    user_id = int(ctx.get("user_id") or 0)
    if not user_id:
        raise HTTPException(status_code=401, detail="No autenticado.")

    def _guardar() -> None:
        for pref in body:
            prefs.guardar(
                user_id,
                tipo=pref.tipo,
                canal=pref.canal,
                frecuencia=pref.frecuencia,
                organization_id=pref.organization_id,
            )

    try:
        await run_db(_guardar)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    log.info("notification_preferences_updated", user_id=user_id, n=len(body))
    return StatusOk(status="ok")


class MyApiKeyOut(BaseModel):
    """Una API key del usuario, sin secreto.

    La ruta devolvía `list[dict[str, Any]]`, así que el esquema generado la
    describía como una lista de objetos opacos y el frontend tenía que suponer
    su forma. Tipada, un campo que el backend deja de enviar deja de compilar
    en la UI en vez de aparecer vacío en pantalla.

    Los campos son la proyección exacta de
    ``ApiKeyRepository.get_all_for_user``: ``id`` es lo único con lo que el
    dueño puede señalar qué key rotar en ``POST /me/keys/rotate``, y por eso
    ese repositorio lo devuelve.

    ``is_active`` llega como ``0``/``1`` de la columna —herencia de SQLite— y
    aquí se declara ``bool`` porque eso es la representación en disco, no el
    contrato; Pydantic hace la coerción. Mismo criterio que ``WebhookOut`` en
    ``api/routes/webhooks.py``.
    """

    id: int
    name: str | None = None
    tier: str = Field(default="standard", description="Tier de rate limit aplicado (C2.3)")
    is_active: bool = True
    created_at: str | None = None
    expires_at: str | None = None


class MyApiKeysResult(BaseModel):
    items: list[MyApiKeyOut] = Field(default_factory=list)


@router.get(
    "/me/keys",
    summary="Listar mis API keys (sin el secret — solo metadatos y tier)",
    responses={401: {"description": "API key inválida"}},
)
def list_my_keys(ctx: dict[str, Any] = Depends(require_any_auth)) -> MyApiKeysResult:
    """Devuelve las API keys vinculadas al usuario autenticado.

    Para API key auth: usa ``key_id``. For session auth: usa ``user_id``.
    Nunca incluye el hash ni el token: el secreto se enseña una sola vez, al
    crearla.
    """
    return MyApiKeysResult(
        items=[
            MyApiKeyOut(
                id=int(fila["id"]),
                name=(str(fila["name"]) if fila.get("name") else None),
                tier=str(fila.get("tier") or "standard"),
                is_active=bool(fila.get("is_active", True)),
                created_at=(str(fila["created_at"]) if fila.get("created_at") else None),
                expires_at=(str(fila["expires_at"]) if fila.get("expires_at") else None),
            )
            for fila in _key_repo.get_all_for_user(ctx["user_id"])
        ]
    )


class CreateKeyBody(BaseModel):
    """Petición de creación de API key (C2.3, D25)."""

    name: str = Field(min_length=1, max_length=100)
    #: Scopes separados por coma. Se **acotan a los del rol** del usuario: pedir
    #: `admin` desde una cuenta que no lo es devuelve 403, no una clave capada
    #: en silencio.
    scopes: str | None = None
    #: TTL en días. El tope es `API_KEY_MAX_TTL_DAYS`; sin valor, el default.
    expires_days: int | None = Field(default=None, ge=1)


class CreatedKey(BaseModel):
    """Clave recién creada. **El secreto viaja una sola vez.**"""

    id: int | None = None
    name: str
    #: El token en bruto. No se puede recuperar: la BD guarda su hash.
    api_key: str
    expires_at: str | None = None
    organization_id: int | None = None


#: Scopes que solo puede pedir un administrador de la plataforma.
#:
#: Una clave se crea desde el producto (C2.3) y por tanto la pide el usuario:
#: sin esta lista, cualquiera acuñaría una credencial `admin` desde su propia
#: cuenta, que es una escalada de privilegios servida por el propio formulario.
_SCOPES_RESERVADOS = frozenset({"admin", "*"})


def _validar_scopes(pedidos: str | None, ctx: dict[str, Any]) -> str | None:
    """Rechaza los scopes que el rol del usuario no puede conceder."""
    if not pedidos:
        return None
    solicitados = {s.strip() for s in pedidos.split(",") if s.strip()}
    reservados = solicitados & _SCOPES_RESERVADOS
    if reservados and not ctx.get("is_admin"):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Scopes reservados a administración: {', '.join(sorted(reservados))}. "
                "Una clave no puede conceder más permiso del que tiene quien la crea."
            ),
        )
    return ",".join(sorted(solicitados)) or None


@router.post(
    "/me/keys",
    summary="Crear una API key personal",
    status_code=201,
    responses={
        201: {"description": "Clave creada. El secreto solo se muestra aquí."},
        403: {"description": "Sesión no reciente, o scopes por encima del rol"},
        422: {"description": "TTL fuera del rango permitido"},
    },
)
async def create_my_key(
    body: CreateKeyBody,
    ctx: dict[str, Any] = Depends(require_recent_session()),
) -> CreatedKey:
    """Acuña una API key personal (C2.3, D25).

    Hasta 2026-09 `create_api_key` existía y **solo la usaba un script**:
    `/me/keys` listaba y rotaba, pero no creaba. Para tener una clave había que
    pedírsela al mantenedor.

    Exige sesión reciente, igual que la rotación y el borrado de cuenta: acuñar
    una credencial es la primera cosa que haría alguien con una cookie robada,
    porque sobrevive al cierre de sesión.
    """
    user_id = int(ctx.get("user_id") or 0)
    if not user_id:
        raise HTTPException(status_code=401, detail="No autenticado.")

    scopes = _validar_scopes(body.scopes, ctx)

    def _crear() -> tuple[str, dict[str, Any] | None]:
        raw = create_api_key(
            body.name,
            scopes=scopes,
            user_id=user_id,
            expires_days=body.expires_days,
        )
        # `get_by_hash` y no un `get_by_raw`: el repositorio nunca recibe el
        # token en bruto, que es la razón por la que existe `_hash`.
        from api.auth import hash_api_key

        fila = ApiKeyRepository().get_by_hash(hash_api_key(raw))
        return raw, fila

    try:
        raw, fila = await run_db(_crear)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await run_db(
        log_event,
        event_type="api_key.created",
        user_key=_actor_key(ctx),
        resource=f"user:{user_id}",
        detail={"name": body.name, "scopes": scopes},
    )
    log.info("api_key_created", user_id=user_id, scoped=bool(scopes))
    return CreatedKey(
        id=(fila or {}).get("id"),
        name=body.name,
        api_key=raw,
        expires_at=(fila or {}).get("expires_at"),
    )


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
) -> RotatedKey:
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
    # `get_rotatable` exige que la key exista, siga activa y no haya caducado.
    # Consultar solo por id resucitaba credenciales revocadas: el step-up prueba
    # *quién* pide la rotación, no que la key siga siendo legítima ni que sea
    # suya. Ambas cosas se comprueban aquí.
    rotatable = _key_repo.get_rotatable(key_id)
    if rotatable is None or rotatable["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="API key no encontrada.")

    name, scopes = rotatable["name"], rotatable["scopes"]

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

    return RotatedKey(
        new_token=new_raw,
        message=(
            f"Guarda el token — no es recuperable. "
            f"La key anterior expira en {grace_days} días ({grace_expires[:10]})."
        ),
        old_key_expires_at=grace_expires,
    )


# ---------------------------------------------------------------------------
# Perfil de scoring personalizado (Feature B)
# ---------------------------------------------------------------------------


_CPV_RE = re.compile(r"^\d{4,8}$")
_MAX_CPVS = 50


class UserProfileBody(BaseModel):
    """Cuerpo para crear/actualizar el perfil de scoring."""

    weights: dict[str, int] | None = None
    afinidad_keywords: list[str] | None = None
    # La columna `cpvs_json` existía y el scoring la leía, pero ningún cuerpo la
    # declaraba: era inescribible por API, y encima cada PUT la machacaba con
    # NULL. La similitud por CPV de la afinidad (1.0 exacto / 0.8 por división)
    # nunca llegó a activarse en producción.
    cpvs: list[str] | None = None
    importe_min: float | None = None
    importe_max: float | None = None
    organization_id: int | None = None
    visibility: Literal["private", "organization"] = "private"

    @field_validator("cpvs")
    @classmethod
    def _clean_cpvs(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        limpios: list[str] = []
        for raw in value:
            cpv = str(raw).strip()
            if not cpv:
                continue
            if not _CPV_RE.match(cpv):
                raise ValueError(
                    f"CPV invalido: {cpv!r}. Se esperan 4-8 digitos (division, grupo o codigo)."
                )
            if cpv not in limpios:
                limpios.append(cpv)
        if len(limpios) > _MAX_CPVS:
            raise ValueError(f"Maximo {_MAX_CPVS} CPVs por perfil, llegaron {len(limpios)}.")
        return limpios

    def validate_weights(self) -> None:
        """Aplica la misma regla que los pesos globales de settings.

        Antes solo comprobaba la suma, así que `{"foo": 100}` pasaba: las cinco
        dimensiones reales se quedaban a 0 —`w.get(dim, 0)`— y el usuario veía
        el corpus entero en banda Descarte sin ningún error que lo explicara.
        """
        if self.weights is None:
            return
        try:
            validate_scoring_weights(self.weights)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


class UserProfileOut(BaseModel):
    """Perfil devuelto al cliente."""

    user_key: str | None = None
    weights: dict[str, int] | None = None
    afinidad_keywords: list[str] | None = None
    cpvs: list[str] | None = None
    importe_min: float | None = None
    importe_max: float | None = None
    updated_at: str | None = None
    organization_id: int | None = None
    visibility: Literal["private", "organization"] = "private"
    inherited: bool = False


@router.get("/me/profile", summary="Obtener el perfil de scoring del usuario")
async def get_profile(
    ctx: dict[str, Any] = Depends(require_organization()),
) -> UserProfileOut:
    """Devuelve el perfil de scoring personalizado del usuario.

    Si no tiene perfil configurado, devuelve un objeto vacio.
    """
    from db.repositories.user_profiles import get_user_profile

    user_key = _user_key(ctx)
    raw = await run_db(get_user_profile, user_key, ctx["organization_id"])
    if raw is None:
        return UserProfileOut()
    return UserProfileOut(
        user_key=raw.get("user_key"),
        weights=raw.get("weights"),
        afinidad_keywords=raw.get("afinidad_keywords"),
        cpvs=raw.get("cpvs"),
        importe_min=raw.get("importe_min"),
        importe_max=raw.get("importe_max"),
        updated_at=raw.get("updated_at"),
        organization_id=raw.get("organization_id"),
        visibility=raw.get("visibility") or "private",
        inherited=raw.get("user_key") != user_key,
    )


@router.put("/me/profile", summary="Crear o actualizar el perfil de scoring")
async def put_profile(
    body: UserProfileBody,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> StatusOk:
    """Crea o actualiza el perfil de scoring personalizado.

    Los pesos, cuando se proporcionan, deben ser dimensiones conocidas, no
    negativas y sumar 100.

    **Reemplaza el perfil completo**: el upsert escribe todas las columnas, así
    que un campo omitido (o `null`) se guarda como `null`, no conserva el valor
    anterior. Enviá siempre el estado íntegro.
    """
    from db.repositories.user_profiles import (
        get_own_user_profile,
        upsert_user_profile,
    )

    body.validate_weights()
    ctx = await resolve_organization_ctx(ctx, body.organization_id, write=True)
    user_key = _user_key(ctx)
    # Sin ámbito a propósito: hace falta la organización que tenía ANTES
    # para invalidar su caché, y esa es justo la que no se conoce aquí.
    previous = await run_db(get_own_user_profile, user_key)
    await run_db(
        upsert_user_profile,
        user_key,
        {
            "weights": body.weights,
            "afinidad_keywords": body.afinidad_keywords,
            "cpvs": body.cpvs,
            "importe_min": body.importe_min,
            "importe_max": body.importe_max,
        },
        ctx["organization_id"],
        body.visibility,
    )
    _invalidate_profile_scoring(
        user_key,
        previous.get("organization_id") if previous else None,
        int(ctx["organization_id"]),
    )
    return StatusOk(status="ok")


@router.delete("/me/profile", summary="Eliminar el perfil de scoring")
async def delete_profile(
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> StatusOk:
    """Elimina el perfil de scoring. El scoring vuelve a los settings globales."""
    from db.repositories.user_profiles import delete_user_profile, get_own_user_profile

    user_key = _user_key(ctx)
    # Sin ámbito a propósito: hace falta la organización que tenía ANTES
    # para invalidar su caché, y esa es justo la que no se conoce aquí.
    previous = await run_db(get_own_user_profile, user_key)
    await run_db(delete_user_profile, user_key)
    _invalidate_profile_scoring(
        user_key,
        previous.get("organization_id") if previous else None,
    )
    return StatusOk(status="ok")
