"""``POST /auth/login``: contraseña local, con sus frenos por IP y por cuenta."""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from api.concurrency import run_db, run_kdf
from api.routes.auth.comun import (
    ACCESS_NOT_GRANTED,
    EMAIL_NOT_VERIFIED,
    UserInfo,
    _set_session_cookie,
)
from db.audit import log_event
from db.users import get_user_by_email, is_admin, log_access
from observability.logging import get_logger
from shared.audit_events import AUTH_LOGIN_FAILED, AUTH_LOGIN_SUCCESS
from shared.auth_core import verify_password, verify_password_against_dummy

# El nombre de antes de partir el módulo: `logger` sale en cada línea de log.
log = get_logger("api.routes.auth")

router = APIRouter()


def _login_client_key(request: Request, email: str) -> str:
    """Clave opaca por IP y cuenta para el lockout, sin persistir PII directa.

    La IP es la de cuota (:func:`services.rate_limiting.ip_de_cuota`): una IPv6
    por su /64, o el lockout se evita cambiando de dirección dentro del prefijo.
    """
    from api.middleware import _trusted_client_ip
    from services.rate_limiting import ip_de_cuota

    material = f"{ip_de_cuota(_trusted_client_ip(request))}:{email.strip().lower()}"
    return hashlib.sha256(material.encode()).hexdigest()[:32]


#: Intentos fallidos por (IP, correo) en cinco minutos antes del bloqueo.
_LOGIN_MAX_FALLOS = 5

#: Tareas de auditoría de fallos de login en vuelo. El loop solo guarda
#: referencias débiles a las tareas: sin esto el GC podría recogerlas a medias.
_auditorias_en_vuelo: set[asyncio.Task[None]] = set()


def _auditar_fallo_despues(user_id: int) -> None:
    """Escribe ``auth.login_failed`` (contraseña mala) sin hacer esperar la respuesta.

    La auditoría serializa cada escritura tras un lock global. Hecha en línea,
    el fallo de una cuenta que existe tardaba más que el de una que no (que ya
    no audita), y esa diferencia de tiempo decía qué correos tienen cuenta. Un
    fallo al escribir queda en el log; la respuesta ya salió.
    """

    async def _escribir() -> None:
        try:
            await run_db(
                log_event,
                event_type=AUTH_LOGIN_FAILED,
                user_id=user_id,
                outcome="failure",
                resource=f"user:{user_id}",
                detail={"reason": "bad_password"},
            )
        except Exception:
            log.warning("login_failed_audit_error", user_id=user_id, exc_info=True)

    tarea = asyncio.get_running_loop().create_task(_escribir())
    _auditorias_en_vuelo.add(tarea)
    tarea.add_done_callback(_auditorias_en_vuelo.discard)


#: Contador de fallos **por cuenta**, sin IP. El lockout por (IP, correo) no
#: frena a quien rota de IP: cada una estrena sus cinco intentos. Este cuenta
#: los de todas y, pasado el umbral, no bloquea —bloquear le regalaría a
#: cualquiera la posibilidad de dejar fuera a un titular— sino que exige una
#: pausa entre intentos que se duplica con cada fallo más (15, 30, 60 s…) hasta
#: un máximo de dos minutos: 30 intentos por hora y cuenta como mucho, frente
#: a los que dé el KDF.
_LOGIN_CUENTA_BUCKET = "login_fail_cuenta"
_LOGIN_CUENTA_VENTANA_S = 3600.0
_LOGIN_CUENTA_UMBRAL = 20
_LOGIN_CUENTA_PAUSA_BASE_S = 15.0
_LOGIN_CUENTA_PAUSA_MAX_S = 120.0


def _login_account_key(email: str) -> str:
    """Clave opaca de la cuenta (solo el correo) para el contador de fallos."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]


def _pausa_por_cuenta(fallos: int, desde_el_ultimo: float) -> float:
    """Segundos que faltan para que la cuenta admita otro intento; 0 si puede ya.

    ``fallos`` son los de la última hora y ``desde_el_ultimo`` los segundos que
    han pasado desde el más reciente. Bajo el umbral no hay pausa.
    """
    if fallos < _LOGIN_CUENTA_UMBRAL:
        return 0.0
    exceso = min(fallos - _LOGIN_CUENTA_UMBRAL, 10)
    pausa = min(_LOGIN_CUENTA_PAUSA_MAX_S, _LOGIN_CUENTA_PAUSA_BASE_S * (1 << exceso))
    return max(0.0, pausa - desde_el_ultimo)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Credentials for email/password login."""

    email: EmailStr
    #: Tope generoso (el cambio y el reset aceptan 512): sin él, un cuerpo de
    #: 1 MiB entero iba a argon2.
    password: str = Field(max_length=512)
    #: «Recordar este equipo»: la sesión no caduca por inactividad hasta
    #: ``SESSION_REMEMBER_DAYS`` (con el mismo techo absoluto). Opcional y
    #: falso por defecto: los clientes que no lo envían conservan el
    #: comportamiento anterior.
    remember: bool = False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _motivo_login_denegado(user: Mapping[str, Any]) -> str | None:
    """Por qué una contraseña correcta no basta para entrar, o ``None``.

    - ``email_not_verified``: alta cerrada cuyo enlace nadie ha pulsado.
    - ``access_not_granted``: el correo ya no pasa la misma regla que el login
      OAuth (lista estática o ``access_grants``), p. ej. porque se revocó la
      concesión. Los administradores quedan exentos: el panel desde el que se
      conceden los accesos no puede quedarse sin nadie que entre.

    Síncrona: consulta ``access_grants``, se llama desde el hilo del login.
    """
    from services.access_grants import acceso_oauth_permitido

    if user.get("email_verified_at") is None:
        return EMAIL_NOT_VERIFIED
    user_id = int(user["id"])
    if not is_admin(user_id) and not acceso_oauth_permitido(str(user.get("email") or "")):
        return ACCESS_NOT_GRANTED
    return None


@router.post(
    "/login",
    response_model=UserInfo,
    responses={
        403: {
            "description": (
                "Contraseña correcta pero sin entrada: `email_not_verified` o `access_not_granted`."
            )
        }
    },
)
async def login(body: LoginRequest, response: Response, request: Request) -> UserInfo:
    """Authenticate with email + password, set session cookie."""
    # Nota de implementación (deliberadamente FUERA del docstring: FastAPI lo
    # publica como descripción del endpoint en el OpenAPI, y de ahí baja al
    # cliente TypeScript generado — un detalle de threadpool no es contrato
    # público). Todo el trabajo (seis viajes a BD y el `verify_password` de
    # argon2, caro por diseño) va en un solo salto al threadpool: ejecutado
    # sobre el event loop, cada login serializaba la API entera mientras
    # duraba el KDF.
    from db.rate_limits import (
        clear_login_attempts,
        fallos_recientes,
        is_login_locked_out,
        record_failed_login,
    )
    from db.totp import is_totp_required

    client_key = _login_client_key(request, str(body.email))
    cuenta_key = _login_account_key(str(body.email))
    #: Cuentas con una contraseña mala cuyo fallo se audita tras responder.
    auditar_despues: list[int] = []

    def _demasiados_intentos(espera: float) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(max(1, math.ceil(espera)))},
        )

    def _authenticate() -> UserInfo:
        locked, retry_after = is_login_locked_out(client_key)
        if locked:
            raise _demasiados_intentos(retry_after)
        # Contador por cuenta, de todas las IP: pasado el umbral exige una pausa
        # creciente entre intentos. Cuenta también los correos sin cuenta, para
        # que la pausa no diga cuáles existen.
        fallos, desde_el_ultimo = fallos_recientes(
            cuenta_key, bucket=_LOGIN_CUENTA_BUCKET, window_seconds=_LOGIN_CUENTA_VENTANA_S
        )
        pausa = _pausa_por_cuenta(fallos, desde_el_ultimo)
        if pausa > 0:
            log.warning("login_cuenta_en_pausa", fallos=fallos)
            raise _demasiados_intentos(pausa)
        # El intento se apunta ANTES de verificar la contraseña, como en el
        # cambio de contraseña: con «mirar, argon2, apuntar el fallo», N
        # peticiones en paralelo pasaban todas el control antes de que se
        # apuntara ninguna (argon2 dura ~100 ms) y el tope no limitaba nada.
        # Apuntado primero, la k-ésima ve al menos k filas, y el +1 deja pasar
        # los mismos `_LOGIN_MAX_FALLOS` intentos. Un acceso correcto lo borra.
        record_failed_login(client_key)
        locked, retry_after = is_login_locked_out(client_key, max_attempts=_LOGIN_MAX_FALLOS + 1)
        if locked:
            raise _demasiados_intentos(retry_after)
        # Primero tal cual —las cuentas de siempre se guardaron con la
        # capitalización que se tecleó— y después en minúsculas, que es como
        # guarda el correo el alta cerrada: quien se dio de alta como
        # «Ana@Empresa.es» tiene que poder entrar escribiéndolo igual. Las dos
        # son búsquedas exactas; no se compara sin mayúsculas porque ahí pueden
        # coincidir dos cuentas heredadas.
        user = get_user_by_email(body.email) or get_user_by_email(str(body.email).strip().lower())
        # Sin hash con el que comparar (no hay cuenta, o es solo-OAuth) se
        # verifica igual contra uno ficticio del mismo KDF y coste: respondiendo
        # sin pasar por argon2, el tiempo decía qué correos tienen contraseña.
        pw_hash: str = (user or {}).get("password_hash", "") or ""
        if not pw_hash:
            verify_password_against_dummy(body.password)
        if not user:
            record_failed_login(
                cuenta_key, bucket=_LOGIN_CUENTA_BUCKET, window_seconds=_LOGIN_CUENTA_VENTANA_S
            )
            # Sin `log_event`: un intento contra una cuenta que no existe no
            # tiene actor ni correo que registrar (ADR-030 §D), y la auditoría
            # serializa cada escritura tras un lock global: dejar que cualquiera
            # la alimente sin autenticarse saturaba el pool de escritura. Queda
            # el log estructurado.
            log.warning("login_failed", reason="user_not_found")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )

        if not pw_hash or not verify_password(body.password, pw_hash):
            record_failed_login(
                cuenta_key, bucket=_LOGIN_CUENTA_BUCKET, window_seconds=_LOGIN_CUENTA_VENTANA_S
            )
            # La auditoría se escribe con la respuesta ya en camino (ver
            # `_auditar_fallo_despues`): en línea, este camino tardaba lo que una
            # escritura de auditoría más que el de «no existe la cuenta», y esa
            # diferencia de tiempo delataba qué correos tienen cuenta.
            auditar_despues.append(int(user["id"]))
            log.warning("login_failed", user_id=user["id"], reason="bad_password")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )

        # Las dos comprobaciones van DESPUÉS de la contraseña: antes le dirían
        # a cualquiera que ese correo tiene cuenta (RFC
        # 2026-10-21-alta-con-contrasena-tras-concesion §3).
        motivo_denegado = _motivo_login_denegado(user)
        if motivo_denegado is not None:
            # La contraseña era la buena: no es un fallo de fuerza bruta.
            clear_login_attempts(client_key)
            clear_login_attempts(cuenta_key, bucket=_LOGIN_CUENTA_BUCKET)
            log_event(
                event_type=AUTH_LOGIN_FAILED,
                user_id=int(user["id"]),
                outcome="failure",
                resource=f"user:{user['id']}",
                detail={"reason": motivo_denegado},
            )
            log.warning("login_failed", user_id=user["id"], reason=motivo_denegado)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=motivo_denegado)

        clear_login_attempts(client_key)
        clear_login_attempts(cuenta_key, bucket=_LOGIN_CUENTA_BUCKET)
        _set_session_cookie(response, user["id"], request, remember=body.remember)

        log_access(auth_method="password", user_id=user["id"])
        log_event(
            event_type=AUTH_LOGIN_SUCCESS,
            user_id=int(user["id"]),
            resource=f"user:{user['id']}",
            detail={"auth_method": "password"},
        )
        log.info("login_success", user_id=user["id"])

        return UserInfo(
            user_id=user["id"],
            email=user.get("email"),
            display_name=user.get("display_name"),
            is_admin=is_admin(user["id"]),
            mfa_required=is_totp_required(user["id"]),
        )

    # `run_kdf` y no `run_db`: bulkhead propio de tres hilos para el argon2.
    try:
        return await run_kdf(_authenticate)
    finally:
        for user_id in auditar_despues:
            _auditar_fallo_despues(user_id)
