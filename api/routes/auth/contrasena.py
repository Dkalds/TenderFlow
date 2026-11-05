"""Recuperación de contraseña por correo y cambio desde Ajustes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from api.concurrency import run_db, run_kdf
from api.routes.auth.comun import (
    _RESET_CONFIRM_BUCKET,
    _RESET_IP_WINDOW_SECONDS,
    _RESET_REQUEST_RESPONSE,
    _password_reset_rate_allowed,
    require_csrf,
)
from config.password_policy import check_account_password
from db.audit import log_event
from db.users import get_user_by_id
from observability.logging import get_logger
from shared.audit_events import AUTH_PASSWORD_CHANGED, AUTH_PASSWORD_RESET_COMPLETED
from shared.auth_core import hash_password, verify_password
from shared.dto import DetailMessage, StatusOk

# El nombre de antes de partir el módulo: `logger` sale en cada línea de log.
log = get_logger("api.routes.auth")

router = APIRouter()


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=32, max_length=200)
    password: str = Field(min_length=10, max_length=512)


class PasswordChangeRequest(BaseModel):
    """Cambio de contraseña desde Ajustes: la actual y la nueva."""

    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=10, max_length=512)


# ---------------------------------------------------------------------------
# Password recovery for local accounts
# ---------------------------------------------------------------------------


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DetailMessage,
)
async def request_password_reset(
    body: PasswordResetRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> DetailMessage:
    """Emite una respuesta indistinguible exista o no la cuenta."""
    email = str(body.email).strip().lower()
    if not await _password_reset_rate_allowed(request, email):
        return DetailMessage(detail=_RESET_REQUEST_RESPONSE)

    from services.password_reset import process_password_reset_request

    # Hasta aquí —validar y contar las cuotas— el camino pesa lo mismo exista o
    # no la cuenta. Lo que sí depende de ella (emitir el token, el rastro de
    # auditoría, el correo) se hace con la respuesta ya enviada, para que
    # tampoco el tiempo de respuesta distinga una cuenta de otra.
    background_tasks.add_task(process_password_reset_request, email)
    return DetailMessage(detail=_RESET_REQUEST_RESPONSE)


@router.post("/password-reset/confirm", response_model=StatusOk)
async def confirm_password_reset(
    body: PasswordResetConfirm,
    request: Request,
    background_tasks: BackgroundTasks,
) -> StatusOk:
    """Consume un token una sola vez, cambia la contraseña y revoca sesiones y claves.

    Al titular le llega después un aviso de que su contraseña ha cambiado.
    """
    if not await _password_reset_rate_allowed(request, bucket=_RESET_CONFIRM_BUCKET):
        # `Retry-After` con la ventana entera, igual que el 429 del
        # `RateLimitMiddleware`: el limitador responde sí o no, no cuánto
        # falta, y decir de más es el lado seguro.
        raise HTTPException(
            status_code=429,
            detail="Demasiados intentos. Inténtalo más tarde.",
            headers={"Retry-After": str(_RESET_IP_WINDOW_SECONDS)},
        )

    # La misma política que el alta, por la misma función. Va antes de tocar el
    # token: una contraseña rechazada no gasta el enlace.
    password_check = check_account_password(body.password)
    if not password_check.is_strong:
        raise HTTPException(status_code=400, detail=password_check.summary)

    from db.password_reset import consume_reset_token, reset_token_vigente
    from services.password_reset import token_hash

    def _consume() -> int | None:
        digest = token_hash(body.token)
        # Se mira el enlace antes de hashear: un token inventado no debe costar
        # un argon2 de 64 MiB. `consume_reset_token` lo vuelve a comprobar.
        if not reset_token_vigente(digest):
            return None
        return consume_reset_token(digest, hash_password(body.password))

    user_id = await run_kdf(_consume)
    if user_id is None:
        raise HTTPException(status_code=400, detail="El enlace no es válido o ha caducado.")
    await run_db(
        log_event,
        event_type=AUTH_PASSWORD_RESET_COMPLETED,
        user_id=user_id,
        resource=f"user:{user_id}",
    )
    log.info("password_reset_completed", user_id=user_id)
    _avisar_contrasena_cambiada(background_tasks, user_id)
    return StatusOk(status="ok")


def _avisar_contrasena_cambiada(background_tasks: BackgroundTasks, user_id: int) -> None:
    """Encola el correo «tu contraseña ha cambiado» para después de responder.

    Lo mandan el reset y el cambio desde Ajustes. En segundo plano y sin poder
    fallar la petición: la contraseña ya cambió, y un correo que no sale no
    puede convertir eso en un error (``notify_password_changed`` no lanza).
    """
    from services.password_reset import notify_password_changed

    background_tasks.add_task(notify_password_changed, user_id)


#: Bloqueo del cambio de contraseña: 5 contraseñas actuales erróneas por cuenta
#: cada 15 minutos. Por cuenta y no por IP: lo que se protege es la contraseña
#: de una sesión que alguien pudo dejarse abierta, y quien la tiene delante
#: tiene también su IP. Solo cuentan los fallos.
_CAMBIO_BUCKET_FALLOS = "password_change_fail"
_CAMBIO_MAX_FALLOS = 5
_CAMBIO_VENTANA_SEGUNDOS = 900.0
_CAMBIO_ACTUAL_ERRONEA = "La contraseña actual no es correcta."
#: El reset público solo sirve a cuentas con contraseña; quien entra solo con
#: un proveedor crea la primera repitiendo el alta con su correo, que le manda
#: «ya tienes cuenta» con un enlace para elegirla (`services/email_verification.py`).
_CAMBIO_SIN_CONTRASENA = (
    "Tu cuenta no tiene contraseña: entras con Google o Microsoft. Para crear una, "
    "usa «Crear cuenta» en la pantalla de acceso con este mismo correo y te llegará "
    "un enlace para elegirla."
)


@router.post(
    "/password/change",
    response_model=StatusOk,
    responses={
        400: {
            "description": "La contraseña actual no es correcta, o la nueva no cumple la política."
        },
        409: {"description": "La cuenta no tiene contraseña (entra solo con un proveedor)."},
        429: {"description": "Demasiadas contraseñas actuales erróneas seguidas."},
    },
)
async def change_password(
    body: PasswordChangeRequest,
    background_tasks: BackgroundTasks,
    user: dict[str, Any] = Depends(require_csrf),
) -> StatusOk:
    """Cambia la contraseña conociendo la actual.

    Exige sesión con CSRF (y el segundo factor ya verificado, si la cuenta lo
    tiene). La nueva pasa por la misma política que el alta y el reset. Al
    cambiarla se cierran **las demás** sesiones —la que hace el cambio sigue
    abierta— y se desactivan las claves de API de la cuenta, y llega un aviso
    al correo del titular.
    """
    # Antes que nada, como el reset: una contraseña rechazada no cuenta como
    # intento ni le cuesta nada a nadie.
    password_check = check_account_password(body.new_password)
    if not password_check.is_strong:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=password_check.summary)

    from db.password_reset import change_password as cambiar_contrasena
    from db.rate_limits import clear_login_attempts, is_login_locked_out, record_failed_login

    user_id = int(user["user_id"])
    clave_bloqueo = f"user:{user_id}"

    def _cambiar() -> int:
        """KDF y BD en el threadpool, como el login: argon2 es caro por diseño."""
        # El intento se apunta antes de mirar el tope y de verificar: con
        # «mirar, verificar, apuntar el fallo», N peticiones en paralelo pasaban
        # todas el control antes de que se apuntara ninguna y el tope no
        # limitaba nada. Apuntado primero, la k-ésima ve al menos k filas; el
        # +1 deja pasar los mismos _CAMBIO_MAX_FALLOS intentos que antes. Un
        # cambio correcto limpia el contador.
        record_failed_login(
            clave_bloqueo,
            bucket=_CAMBIO_BUCKET_FALLOS,
            window_seconds=_CAMBIO_VENTANA_SEGUNDOS,
        )
        bloqueado, retry_after = is_login_locked_out(
            clave_bloqueo,
            max_attempts=_CAMBIO_MAX_FALLOS + 1,
            bucket=_CAMBIO_BUCKET_FALLOS,
            window_seconds=_CAMBIO_VENTANA_SEGUNDOS,
        )
        if bloqueado:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiados intentos. Inténtalo más tarde.",
                headers={"Retry-After": str(max(1, int(retry_after)))},
            )
        cuenta = get_user_by_id(user_id)
        actual = str((cuenta or {}).get("password_hash") or "")
        if not actual:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_CAMBIO_SIN_CONTRASENA)
        if not verify_password(body.current_password, actual):
            log.warning("password_change_failed", user_id=user_id, reason="bad_current_password")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=_CAMBIO_ACTUAL_ERRONEA
            )
        claves = cambiar_contrasena(
            user_id,
            hash_password(body.new_password),
            sesion_actual=str(user["session_token"]),
        )
        if claves is None:
            # La cuenta se desactivó entre la sesión y el cambio.
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
        clear_login_attempts(clave_bloqueo, bucket=_CAMBIO_BUCKET_FALLOS)
        return claves

    claves_revocadas = await run_db(_cambiar)
    await run_db(
        log_event,
        event_type=AUTH_PASSWORD_CHANGED,
        user_id=user_id,
        resource=f"user:{user_id}",
        detail={"api_keys_revoked": claves_revocadas},
    )
    log.info("password_changed", user_id=user_id, api_keys_revoked=claves_revocadas)
    _avisar_contrasena_cambiada(background_tasks, user_id)
    return StatusOk(status="ok")
