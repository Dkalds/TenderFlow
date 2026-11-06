"""Segundo factor TOTP: alta, confirmación, verificación, códigos y baja."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator

from api.concurrency import run_db
from api.routes.auth.comun import require_csrf, require_csrf_pending_mfa
from config import settings
from db.audit import log_event
from shared.audit_events import (
    AUTH_TOTP_DISABLED,
    AUTH_TOTP_ENABLED,
    AUTH_TOTP_RECOVERY_REGENERATED,
)
from shared.dto import StatusOk
from shared.identity import Principal

router = APIRouter()


class TotpSetupResult(BaseModel):
    """Alta de TOTP: el secreto viaja solo aquí, como URI otpauth."""

    otpauth_uri: str


class TotpConfirmResult(BaseModel):
    """Confirmación de TOTP: los recovery codes se entregan una sola vez."""

    status: str
    recovery_codes: list[str]


# ---------------------------------------------------------------------------
# TOTP MFA
# ---------------------------------------------------------------------------


class TotpCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=16)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"(?:[0-9]{6}|[0-9a-fA-F]{16})", normalized):
            raise ValueError("MFA code must be a six-digit TOTP or a recovery code")
        return normalized.lower()


def _reject_if_mfa_locked(user_id: int, *, margen: int = 0) -> None:
    from db.rate_limits import is_mfa_locked_out

    locked, retry_after = is_mfa_locked_out(
        user_id,
        max_attempts=settings.MFA_MAX_FAILURES + margen,
        window_seconds=float(settings.MFA_FAILURE_WINDOW_SECONDS),
    )
    if locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed MFA attempts. Try again later.",
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )


def _apuntar_intento_mfa(user_id: int) -> None:
    """Apunta el intento ANTES de verificar el código, como el login.

    Con «mirar el bloqueo, verificar, apuntar el fallo», N peticiones en
    paralelo pasaban todas el control antes de que se apuntara ninguna. Apuntado
    primero, la k-ésima ve al menos k filas, y el +1 deja pasar los mismos
    ``MFA_MAX_FAILURES`` intentos. Un acierto lo borra (``clear_mfa_attempts``).
    """
    from db.rate_limits import record_failed_mfa

    record_failed_mfa(user_id, window_seconds=float(settings.MFA_FAILURE_WINDOW_SECONDS))
    _reject_if_mfa_locked(user_id, margen=1)


async def require_recent_session_auth(
    user: Principal = Depends(require_csrf),
) -> Principal:
    """Require a recently-created browser session before changing MFA state."""
    from api.routes.dual_auth import require_recent_session

    # Reuse the canonical step-up policy.  Calling its inner dependency through
    # FastAPI would repeat CSRF validation, so provide the already validated
    # cookie principal directly to the same checks here.
    dependency = require_recent_session()
    user["auth_method"] = "session"
    return await dependency(user)


@router.post("/totp/setup")
async def setup_totp(
    response: Response,
    user: Principal = Depends(require_recent_session_auth),
) -> TotpSetupResult:
    """Inicia el alta de TOTP; el secreto solo se revela en esta respuesta.

    Un alta sin confirmar se puede empezar de nuevo: quien cerró la pestaña con
    el código a medias recibe un secreto nuevo. Solo un segundo factor ya
    confirmado responde 409.
    """
    from db.totp import generate_totp_secret, get_totp_secret, get_totp_uri, save_totp_secret

    user_id = int(user["user_id"])

    def _setup() -> str:
        # Hasta 2026-10 cualquier fila, confirmada o no, daba 409: un alta
        # abandonada dejaba la cuenta sin forma de activar el segundo factor
        # salvo llamando a mano a `DELETE /auth/totp`. Pisar un secreto sin
        # confirmar no abre nada —ese secreto todavía no protege la cuenta—, y
        # `save_totp_secret` lo sustituye en la misma fila.
        actual = get_totp_secret(user_id)
        if actual is not None and actual["confirmed"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="TOTP already configured"
            )
        secret = generate_totp_secret()
        save_totp_secret(user_id, secret, confirmed=False)
        return get_totp_uri(secret, str(user.get("email") or user_id))

    otpauth_uri = await run_db(_setup)
    response.headers["Cache-Control"] = "no-store"
    return TotpSetupResult(otpauth_uri=otpauth_uri)


@router.post("/totp/confirm")
async def confirm_totp(
    body: TotpCodeRequest,
    response: Response,
    user: Principal = Depends(require_recent_session_auth),
) -> TotpConfirmResult:
    """Confirma el primer código TOTP y entrega recovery codes una sola vez."""
    from db.rate_limits import clear_mfa_attempts
    from db.sessions import mark_session_mfa_verified
    from db.totp import confirm_totp as confirm_totp_secret
    from db.totp import generate_recovery_codes, get_totp_secret, verify_totp

    user_id = int(user["user_id"])

    def _confirm() -> list[str]:
        _reject_if_mfa_locked(user_id)
        _apuntar_intento_mfa(user_id)
        record = get_totp_secret(user_id)
        if (
            record is None
            or record["confirmed"]
            or not body.code.isdecimal()
            or not verify_totp(record["secret"], body.code)
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")
        confirm_totp_secret(user_id)
        mark_session_mfa_verified(str(user["session_token"]))
        clear_mfa_attempts(user_id)
        return generate_recovery_codes(user_id)

    recovery_codes = await run_db(_confirm)
    await run_db(
        log_event,
        event_type=AUTH_TOTP_ENABLED,
        user_id=user_id,
        resource=f"user:{user_id}",
    )
    response.headers["Cache-Control"] = "no-store"
    return TotpConfirmResult(status="ok", recovery_codes=recovery_codes)


@router.post("/totp/verify")
async def verify_totp_login(
    body: TotpCodeRequest,
    user: Principal = Depends(require_csrf_pending_mfa),
) -> StatusOk:
    """Eleva una sesión pendiente tras verificar TOTP o un recovery code.

    Es la única ruta que *tiene* que aceptar una sesión sin MFA verificado:
    gatearla dejaría a todo usuario con TOTP sin forma de completar el login.
    """
    from db.rate_limits import clear_mfa_attempts
    from db.sessions import mark_session_mfa_verified
    from db.totp import get_totp_secret, use_recovery_code, verify_totp

    user_id = int(user["user_id"])

    def _verify() -> None:
        _reject_if_mfa_locked(user_id)
        _apuntar_intento_mfa(user_id)
        record = get_totp_secret(user_id)
        valid = bool(
            body.code.isdecimal()
            and record
            and record["confirmed"]
            and verify_totp(record["secret"], body.code)
        )
        if not valid and len(body.code) == 16:
            valid = use_recovery_code(user_id, body.code)
        if not valid:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA code")
        mark_session_mfa_verified(str(user["session_token"]))
        clear_mfa_attempts(user_id)

    await run_db(_verify)
    return StatusOk(status="ok")


@router.post(
    "/totp/recovery-codes",
    responses={
        400: {"description": "El código no es válido"},
        403: {"description": "La sesión no es reciente: hay que volver a entrar"},
        409: {"description": "La cuenta no tiene el segundo factor activo"},
        429: {"description": "Demasiados códigos fallidos seguidos"},
    },
)
async def regenerate_recovery_codes(
    body: TotpCodeRequest,
    response: Response,
    user: Principal = Depends(require_recent_session_auth),
) -> TotpConfirmResult:
    """Códigos de recuperación nuevos sin desactivar el segundo factor.

    Hasta ahora la única forma de tener otros era quitar el segundo factor y
    volver a darlo de alta. Pide un código vigente del autenticador, no uno de
    recuperación: quien regenera tiene el móvil, y un código de recuperación
    robado no debe servir para fabricar diez más. Los anteriores dejan de
    valer (``generate_recovery_codes`` los borra) y los nuevos se entregan
    una sola vez, como al confirmar el alta.
    """
    if user.get("mfa_required") and not user.get("mfa_verified_at"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Verify MFA before regenerating codes"
        )
    from db.rate_limits import clear_mfa_attempts
    from db.totp import generate_recovery_codes, get_totp_secret, verify_totp

    user_id = int(user["user_id"])

    def _regenerar() -> list[str]:
        # Mismo límite de intentos que el login y que desactivar.
        _reject_if_mfa_locked(user_id)
        record = get_totp_secret(user_id)
        if record is None or not record["confirmed"]:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="TOTP not configured")
        _apuntar_intento_mfa(user_id)
        if not (body.code.isdecimal() and verify_totp(record["secret"], body.code)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")
        clear_mfa_attempts(user_id)
        return generate_recovery_codes(user_id)

    recovery_codes = await run_db(_regenerar)
    await run_db(
        log_event,
        event_type=AUTH_TOTP_RECOVERY_REGENERATED,
        user_id=user_id,
        resource=f"user:{user_id}",
    )
    response.headers["Cache-Control"] = "no-store"
    return TotpConfirmResult(status="ok", recovery_codes=recovery_codes)


@router.delete(
    "/totp",
    responses={
        400: {"description": "El código no es válido"},
        403: {"description": "La sesión no es reciente: hay que volver a entrar"},
        409: {"description": "La cuenta no tiene el segundo factor activo"},
        429: {"description": "Demasiados códigos fallidos seguidos"},
    },
)
async def remove_totp(
    body: TotpCodeRequest,
    user: Principal = Depends(require_recent_session_auth),
) -> StatusOk:
    """Desactiva el segundo factor con un código vigente o uno de recuperación.

    El código se pide aunque la sesión ya sea reciente y haya pasado el segundo
    factor: sin él, quien se sentara delante de un navegador abierto podía
    quitarlo sin tener el móvil, que es justo lo que el segundo factor protege.
    Uno de recuperación también vale —quien perdió el móvil es quien más
    necesita quitarlo— y queda gastado.
    """
    if user.get("mfa_required") and not user.get("mfa_verified_at"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Verify MFA before disabling it"
        )
    from db.rate_limits import clear_mfa_attempts
    from db.totp import delete_totp, get_totp_secret, use_recovery_code, verify_totp

    user_id = int(user["user_id"])

    def _remove() -> None:
        # Mismo límite de intentos que el login: si no, esta ruta serviría
        # para adivinar códigos sin la ventana de bloqueo.
        _reject_if_mfa_locked(user_id)
        record = get_totp_secret(user_id)
        if record is None or not record["confirmed"]:
            # Nada que quitar: no es un código fallido y no cuenta como intento.
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="TOTP not configured")
        _apuntar_intento_mfa(user_id)
        valid = body.code.isdecimal() and verify_totp(record["secret"], body.code)
        if not valid and len(body.code) == 16:
            valid = use_recovery_code(user_id, body.code)
        if not valid:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid MFA code")
        delete_totp(user_id)
        clear_mfa_attempts(user_id)

    await run_db(_remove)
    await run_db(
        log_event,
        event_type=AUTH_TOTP_DISABLED,
        user_id=user_id,
        resource=f"user:{user_id}",
    )
    return StatusOk(status="ok")
