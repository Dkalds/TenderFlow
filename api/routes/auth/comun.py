"""Piezas comunes de la autenticación por sesión: cookies, CSRF y dependencias.

Las usan todos los submódulos de ``api.routes.auth`` y, a través de él, el
resto de la API (``UserInfo``, ``SESSION_COOKIE``, ``get_current_session_user``,
``require_csrf``…). No registra rutas.
"""

from __future__ import annotations

import hashlib

from fastapi import Cookie, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel

from api.concurrency import run_db
from config import settings
from db.sessions import create_session, session_max_age_seconds, validate_session_principal
from observability.logging import get_logger
from shared.csrf import csrf_token_valido, generate_csrf_token
from shared.identity import Principal, user_key_from_email

# El nombre de antes de partir el módulo: `logger` sale en cada línea de log.
log = get_logger("api.routes.auth")


#: Nombre de la cookie de sesión. Público porque `api/routes/me.py` lo
#: necesita para marcar cuál de las sesiones listadas es la actual (C2.1), y
#: dos literales "session" en el árbol es exactamente cómo divergen.
SESSION_COOKIE = "session"
_SESSION_COOKIE = SESSION_COOKIE
_CSRF_COOKIE = "csrf_token"
_OAUTH_PKCE_COOKIE = "oauth_pkce"
_OAUTH_TELEMETRY_COOKIE = "oauth_login"
#: Proveedor con el que se entró, para que la analítica pueda distinguirlos.
#: Va aparte de `_OAUTH_TELEMETRY_COOKIE` — ver el comentario en el callback.
_OAUTH_TELEMETRY_PROVIDER_COOKIE = "oauth_login_provider"
#: Vida máxima de la cookie de sesión y del token CSRF que nace con ella. No es
#: un literal: es el techo absoluto de `db/sessions.py` (`SESSION_ABSOLUTE_DAYS`),
#: porque la sesión es deslizante y la cookie tiene que sobrevivir a todas sus
#: renovaciones; quien decide si sigue viva es el servidor.
_SESSION_MAX_AGE = session_max_age_seconds()
_OAUTH_MAX_AGE = 600
_RESET_REQUEST_RESPONSE = "Si existe una cuenta local activa, recibirás un enlace de recuperación."
_REGISTER_RESPONSE = "Revisa tu correo: te hemos enviado un enlace para activar la cuenta."
#: Motivos de los 403 del alta y del login que la web traduce a un mensaje. Son
#: códigos y no frases porque la web decide el texto y los enlaces (solicitar
#: acceso, reenviar el correo).
ACCESS_NOT_GRANTED = "access_not_granted"
EMAIL_NOT_VERIFIED = "email_not_verified"
#: `?error=` del callback OAuth cuando el correo ya es de una cuenta que entra
#: con otro proveedor (ADR-037). La web lo traduce en
#: `web/src/app/login/_lib/fallos-acceso.ts`.
OAUTH_OTRO_PROVEEDOR = "account_other_provider"


async def _oauth_access_allowed(email: str) -> bool:
    """Allowlist estática o grant dinámico; cualquier fallo dinámico deniega.

    La regla vive en ``services.access_grants.acceso_oauth_permitido``, que
    comparte con el login del MCP interno. Además del callback la usa
    ``api/routes/admin_solicitudes.py`` para no escribirle «ya tienes acceso» a
    quien aquí se rechazaría.
    """
    from services.access_grants import acceso_oauth_permitido

    return bool(await run_db(acceso_oauth_permitido, email))


def _activar_invitaciones(user_id: int, email: str | None) -> None:
    """Convierte en membresías activas las invitaciones pendientes de ese correo.

    Se llama desde el alta local y desde el callback OAuth, dentro del mismo
    salto al threadpool que el resto del trabajo de BD. Importación diferida
    para no arrastrar ``services`` al import de este módulo, que es el que
    carga ``api.app`` en el arranque.
    """
    from services.organizations import accept_invitations_for_email

    accept_invitations_for_email(user_id, email)


#: Cuota por IP de la recuperación de contraseña: 5 intentos cada 15 minutos.
#: Pedir el enlace y confirmarlo la aplican cada uno sobre **su** cubo. Mientras
#: compartieron uno, cada solicitud gastaba un intento de confirmar: quien pedía
#: el enlace un par de veces llegaba al formulario con la cuota a medias, y
#: cualquiera detrás de la misma IP podía agotársela a los demás solo pidiendo.
_RESET_IP_MAX_CALLS = 5
_RESET_IP_WINDOW_SECONDS = 900
_RESET_REQUEST_BUCKET = "password-reset"
_RESET_CONFIRM_BUCKET = "password-reset:confirm"
#: El alta cerrada y la verificación usan la misma cuota que el reset, cada una
#: en su cubo: las dos mandan correo a una dirección que escribe un anónimo.
_REGISTER_BUCKET = "register"
_VERIFY_BUCKET = "verify-email"


async def _password_reset_rate_allowed(
    request: Request,
    email: str | None = None,
    *,
    bucket: str = _RESET_REQUEST_BUCKET,
) -> bool:
    """Cuotas independientes por IP y sujeto; un fallo del limiter deniega.

    ``bucket`` separa los pasos del flujo: cada uno cuenta sus intentos por IP
    aparte, con el mismo tope y la misma ventana. El cubo de sujeto solo existe
    cuando hay correo —al pedir el enlace— y su clave es un hash, no la
    dirección: las claves acaban en ``rate_limits`` o en Redis.
    """
    from api.middleware import _trusted_client_ip
    from services.rate_limiting import get_rate_limiter, ip_de_cuota

    client_ip = _trusted_client_ip(request)
    email_key = hashlib.sha256((email or "").strip().lower().encode()).hexdigest()[:16]

    def _check() -> bool:
        limiter = get_rate_limiter()
        # Una IPv6 cuenta por su /64: con la dirección entera, quien tiene un
        # prefijo estrena cubo en cada petición.
        ip_allowed = limiter.check(
            f"{bucket}:ip:{ip_de_cuota(client_ip)}",
            max_calls=_RESET_IP_MAX_CALLS,
            window_seconds=_RESET_IP_WINDOW_SECONDS,
        )
        if not ip_allowed:
            return False
        if email:
            return limiter.check(f"{bucket}:subject:{email_key}", max_calls=3, window_seconds=3600)
        return True

    try:
        return bool(await run_db(_check))
    except Exception:
        log.exception("password_reset_rate_limiter_unavailable")
        return False


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


def _is_secure() -> bool:
    return settings.ENV in ("prod", "staging")


def _csrf_for_session(session_token: str) -> str:
    """Emite el token double-submit de la sesión, en el formato de ``shared.csrf``.

    Delega en :func:`shared.csrf.generate_csrf_token`: con ``kid`` (sobrevive a
    una rotación de ``SIGNING_KEY``) y con caducidad propia. Antes derivaba
    aquí mismo un HMAC plano sin ninguna de las dos cosas, mientras el módulo
    que sí las tenía no lo usaba nadie.

    **No es determinista**: cada llamada lleva su propio timestamp, así que la
    validación es :func:`shared.csrf.csrf_token_valido` y no una comparación
    con el valor «esperado». Eso es lo que permite la rotación.
    """
    return generate_csrf_token(session_token)


def _set_session_cookie(
    response: Response, user_id: int, request: Request, *, remember: bool = False
) -> str:
    """Crea una sesión opaca revocable y sus cookies de sesión/CSRF.

    ``remember`` («recordar este equipo») alarga la ventana de inactividad de
    la sesión (ver ``db/sessions.py``). El ``max_age`` de las cookies no cambia
    con él: es el techo absoluto en ambos casos, que es lo máximo que la sesión
    puede vivir; caducar la cookie antes dejaría la renovación en servidor sin
    efecto.
    """
    from api.middleware import _trusted_client_ip

    # La misma IP que el rate limiting y el access log. Con ``request.client``
    # /me/sesiones enseñaba el nodo del proxy de Render (RFC 2026-10-24).
    ip_cliente = _trusted_client_ip(request)
    session_token = create_session(
        user_id,
        ip=None if ip_cliente == "unknown" else ip_cliente,
        user_agent=request.headers.get("User-Agent"),
        remember=remember,
    )
    csrf_token = _csrf_for_session(session_token)
    secure = _is_secure()
    response.set_cookie(
        _SESSION_COOKIE,
        session_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=_SESSION_MAX_AGE,
        path="/",
    )
    response.set_cookie(
        _CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=secure,
        samesite="lax",
        max_age=_SESSION_MAX_AGE,
        path="/",
    )
    return csrf_token


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(_SESSION_COOKIE, path="/")
    response.delete_cookie(_CSRF_COOKIE, path="/")


# ---------------------------------------------------------------------------
# Dependency: current session user
# ---------------------------------------------------------------------------


def _session_principal(session: str | None) -> Principal:
    """Resuelve el principal de la cookie de sesión, sin gate de MFA.

    Síncrona a propósito: va a BD (``validate_session_principal``: una lectura
    por el pool de lectura, más el ``UPDATE`` de renovación como mucho una vez
    por minuto) y es la dependencia de casi toda la API autenticada por cookie.
    Sus dos llamadores async la despachan con un único ``run_db`` para que ese
    trabajo no corra sobre el event loop.

    Raises 401 if the session is missing, invalid, or expired.

    Función **síncrona**: las dependencias que la usan la despachan al
    threadpool con ``run_db``. Llamarla directamente desde un ``async def``
    bloquea el event loop durante todo el viaje a la BD, y esta es la
    dependencia base de todo el SPA.
    """
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No session")
    principal = validate_session_principal(session)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    user_id = principal.get("id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session payload"
        )
    email = principal.get("email")
    return {
        "user_id": user_id,
        "email": email,
        "display_name": principal.get("display_name"),
        "is_admin": bool(principal.get("is_admin")),
        "csrf": _csrf_for_session(session),
        "session_token": session,
        "authenticated_at": principal.get("authenticated_at"),
        "mfa_verified_at": principal.get("mfa_verified_at"),
        "mfa_required": bool(principal.get("mfa_required")),
        "user_key": user_key_from_email(email, int(user_id)),
    }


def _reject_pending_mfa(user: Principal) -> None:
    """Corta una sesión cuyo segundo factor todavía no se verificó."""
    if user.get("mfa_required") and not user.get("mfa_verified_at"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA verification required for this session.",
        )


async def get_current_session_user(
    session: str | None = Cookie(default=None, alias=_SESSION_COOKIE),
) -> Principal:
    """Dependency that reads the session cookie and returns user info.

    El gate de MFA vive aquí y no en cada ruta: cuando solo lo aplicaba
    ``dual_auth.require_any_auth``, los 35 endpoints de ``analytics`` y
    ``GET /exports/download`` colgaban directamente de esta dependencia y una
    contraseña robada bastaba para leer todo el BI. Al gatear la dependencia
    base, una ruta nueva nace protegida; lo que debe funcionar *antes* de
    completar MFA usa explícitamente :func:`get_session_user_pending_mfa`.
    """
    user = await run_db(_session_principal, session)
    _reject_pending_mfa(user)
    return user


async def get_session_user_pending_mfa(
    session: str | None = Cookie(default=None, alias=_SESSION_COOKIE),
) -> Principal:
    """Variante sin gate, solo para el propio flujo de segundo factor.

    La usan ``POST /auth/totp/verify`` (donde se verifica el factor),
    ``POST /auth/logout`` y ``GET /auth/me`` (el SPA lo consulta para saber que
    debe pedir el TOTP). Sin estas excepciones, un usuario con MFA quedaría
    encerrado fuera de su propia cuenta.

    No se expone ``allow_pending_mfa`` como parámetro de la dependencia a
    propósito: FastAPI lo interpretaría como query param y el bypass sería
    invocable desde la URL.
    """
    return await run_db(_session_principal, session)


# ---------------------------------------------------------------------------
# CSRF validation dependency for mutations
# ---------------------------------------------------------------------------


def _reject_bad_csrf(user: Principal, x_csrf_token: str | None) -> None:
    """Valida el double-submit token contra la sesión que lo emitió.

    ``max_age`` es la vida de la sesión y no el default de una hora de
    ``shared.csrf``: la cookie CSRF se emite una sola vez, en el login, así que
    caducarla antes que la sesión dejaría al usuario con una sesión viva y
    todas sus mutaciones en 403 — un logout disfrazado de error.
    """
    if not csrf_token_valido(
        x_csrf_token,
        str(user.get("session_token") or ""),
        max_age=_SESSION_MAX_AGE,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token mismatch")


async def require_csrf(
    user: Principal = Depends(get_current_session_user),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> Principal:
    """Validates that X-CSRF-Token header matches the value stored in the session."""
    _reject_bad_csrf(user, x_csrf_token)
    return user


async def require_csrf_pending_mfa(
    user: Principal = Depends(get_session_user_pending_mfa),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> Principal:
    """Igual que :func:`require_csrf` pero admite sesiones pendientes de MFA.

    ``/auth/logout`` y ``/auth/totp/verify`` son mutaciones y siguen exigiendo
    CSRF; lo que no pueden exigir es un segundo factor que aún no se verificó.
    """
    _reject_bad_csrf(user, x_csrf_token)
    return user


class UserInfo(BaseModel):
    """Public user info returned by auth endpoints."""

    user_id: int
    email: str | None = None
    display_name: str | None = None
    is_admin: bool = False
    mfa_required: bool = False
