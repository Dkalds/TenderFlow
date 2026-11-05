"""Alta local (``POST /auth/register``) y verificación del correo."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from api.concurrency import run_db
from api.routes.auth.comun import (
    _REGISTER_BUCKET,
    _REGISTER_RESPONSE,
    _RESET_IP_WINDOW_SECONDS,
    _VERIFY_BUCKET,
    ACCESS_NOT_GRANTED,
    UserInfo,
    _activar_invitaciones,
    _oauth_access_allowed,
    _password_reset_rate_allowed,
    _set_session_cookie,
)
from config import settings
from config.password_policy import check_account_password
from db.audit import log_event
from db.users import create_user, get_user_by_email, get_user_by_id, is_admin, log_access
from observability.logging import get_logger
from shared.audit_events import AUTH_EMAIL_VERIFIED
from shared.auth_core import hash_password
from shared.dto import DetailMessage

# El nombre de antes de partir el módulo: `logger` sale en cada línea de log.
log = get_logger("api.routes.auth")

router = APIRouter()


class RegisterRequest(BaseModel):
    """Datos para el alta self-service con email + password."""

    email: EmailStr
    password: str = Field(max_length=512)
    display_name: str | None = None


class EmailVerificationConfirm(BaseModel):
    """Token del enlace de activación que llega al correo tras el alta."""

    token: str = Field(min_length=32, max_length=200)


def _registro_abierto() -> bool:
    """``True`` en el modo abierto del alta: dev o ``ALLOW_SELF_REGISTRATION``.

    Función y no condición en línea para que los tests del modo cerrado —el
    de producción— lo fuercen sin cambiar ``ENV``, que decide muchas otras
    cosas en el resto de la app.
    """
    return bool(settings.ALLOW_SELF_REGISTRATION) or settings.ENV == "dev"


@router.post(
    "/register",
    response_model=UserInfo,
    status_code=status.HTTP_201_CREATED,
    # El 201 (modo abierto) conserva su contrato; el 202 del modo cerrado es
    # una respuesta más, no un cambio de la existente.
    responses={
        202: {
            "model": DetailMessage,
            "description": "Alta cerrada: el enlace de activación va al correo.",
        },
        403: {"description": "El correo no tiene el acceso concedido (`access_not_granted`)."},
    },
)
async def register(
    body: RegisterRequest,
    response: Response,
    request: Request,
    background_tasks: BackgroundTasks,
) -> UserInfo | JSONResponse:
    """Alta con correo y contraseña.

    Política de contraseña equilibrada: mínimo 10 caracteres con mayúsculas,
    minúsculas y al menos un dígito (sin exigir carácter especial).

    **Modo cerrado** (producción): solo para correos con el acceso concedido
    —lista estática o ``access_grants``, la misma regla que el login OAuth—.
    Responde 202 sin crear sesión, exista o no la cuenta, y el enlace de
    activación llega al correo (RFC 2026-10-21-alta-con-contrasena-tras-concesion).
    Un correo sin concesión recibe 403 ``access_not_granted``.

    **Modo abierto** (``ENV=dev`` o ``ALLOW_SELF_REGISTRATION``): crea la cuenta
    verificada, abre sesión y responde 201 con el usuario, como siempre.
    """
    check = check_account_password(body.password)
    if not check.is_strong:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=check.summary)

    display_name = (body.display_name or "").strip() or None

    if not _registro_abierto():
        return await _register_closed(body, display_name, request, background_tasks)

    def _create_account() -> int:
        """BD + ``hash_password`` (argon2) fuera del event loop."""
        if get_user_by_email(body.email, include_deactivated=True):
            log.warning("signup_rejected", reason="email_exists")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
            )
        new_id = create_user(
            email=body.email,
            password_hash=hash_password(body.password),
            display_name=display_name,
        )
        # Sin `_activar_invitaciones`: este modo no verifica el buzón, y aceptar
        # aquí las invitaciones pendientes de esa dirección (administrador
        # incluido) se las daba a quien se registrara primero con ella. El modo
        # cerrado las activa al verificar el correo; en este quedan por su token.
        _set_session_cookie(response, new_id, request)  # auto-login
        log_access(auth_method="password_signup", user_id=new_id)
        return new_id

    user_id = await run_db(_create_account)
    log.info("signup_success", user_id=user_id)

    return UserInfo(
        user_id=user_id,
        email=body.email,
        display_name=display_name,
        is_admin=False,
    )


async def _register_closed(
    body: RegisterRequest,
    display_name: str | None,
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """El alta de producción: concesión, cuota y todo lo demás en segundo plano."""
    email = str(body.email).strip().lower()
    # La cuota va antes de mirar la concesión: el 403 dice si un correo la
    # tiene, y sin tope serviría para sondear la lista.
    if not await _password_reset_rate_allowed(request, email, bucket=_REGISTER_BUCKET):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Inténtalo más tarde.",
            headers={"Retry-After": str(_RESET_IP_WINDOW_SECONDS)},
        )
    if not await _oauth_access_allowed(email):
        log.info("signup_rejected", reason=ACCESS_NOT_GRANTED)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ACCESS_NOT_GRANTED)

    from services.email_verification import process_registration

    # Como el reset: lo que depende de si la cuenta existe (crearla, reemplazar
    # una sin verificar, el correo que toca) va con la respuesta ya enviada, para
    # que ni el cuerpo ni la latencia lo distingan.
    background_tasks.add_task(process_registration, email, body.password, display_name)
    # Respuesta directa y no el modelo: `response_model` es el `UserInfo` del 201,
    # y FastAPI no valida contra él lo que ya es una `Response`. Las tareas en
    # segundo plano se le cuelgan igual (`background_tasks` inyectado).
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=DetailMessage(detail=_REGISTER_RESPONSE).model_dump(),
    )


@router.post(
    "/verify-email",
    response_model=UserInfo,
    responses={403: {"description": "El acceso se revocó antes de verificar."}},
)
async def verify_email(
    body: EmailVerificationConfirm,
    response: Response,
    request: Request,
) -> UserInfo:
    """Activa la cuenta del alta cerrada con el enlace del correo y abre sesión.

    Comprueba otra vez la concesión: si se revocó entre el alta y el clic,
    responde 403 ``access_not_granted`` sin gastar el enlace ni abrir sesión.
    Token inválido, caducado o ya usado → 400 genérico.
    """
    if not await _password_reset_rate_allowed(request, bucket=_VERIFY_BUCKET):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Inténtalo más tarde.",
            headers={"Retry-After": str(_RESET_IP_WINDOW_SECONDS)},
        )

    from db.email_verification import consume_verification_token, pending_token_email
    from services.access_grants import acceso_oauth_permitido
    from services.password_reset import token_hash

    def _verify() -> UserInfo:
        digest = token_hash(body.token)
        email = pending_token_email(digest)
        if email is None:
            raise HTTPException(status_code=400, detail="El enlace no es válido o ha caducado.")
        if not acceso_oauth_permitido(email):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ACCESS_NOT_GRANTED)
        user_id = consume_verification_token(digest)
        if user_id is None:
            raise HTTPException(status_code=400, detail="El enlace no es válido o ha caducado.")
        # Es aquí, y no en el alta, donde se demuestra el buzón: las
        # invitaciones pendientes de este correo pasan a membresías activas.
        _activar_invitaciones(user_id, email)
        _set_session_cookie(response, user_id, request)
        log_access(auth_method="password_signup", user_id=user_id)
        log_event(
            event_type=AUTH_EMAIL_VERIFIED,
            user_id=user_id,
            resource=f"user:{user_id}",
        )
        user = get_user_by_id(user_id)
        return UserInfo(
            user_id=user_id,
            email=email,
            display_name=(user or {}).get("display_name"),
            is_admin=is_admin(user_id),
        )

    info = await run_db(_verify)
    log.info("email_verified", user_id=info.user_id)
    return info
