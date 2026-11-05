"""Session auth endpoints for the web frontend.

Provides cookie-based session authentication (httpOnly + Secure + SameSite=Lax)
with CSRF protection. Complements the existing X-API-Key auth for machine clients.

El paquete se parte por tema; cada submódulo registra sus rutas en un
``APIRouter`` propio y aquí se incluyen en el orden de siempre:

- ``comun``: cookies, CSRF, dependencias de sesión y ``UserInfo`` (sin rutas).
- ``login``: contraseña local con sus frenos por IP y por cuenta.
- ``registro``: alta local y verificación del correo.
- ``contrasena``: recuperación por correo y cambio desde Ajustes.
- ``dev_login``: entrada sin credenciales, solo con ``ENV=dev``.
- ``sesion``: ``/me`` y ``/logout``.
- ``totp``: segundo factor.
- ``oauth``: proveedores OIDC con PKCE.

Un test que sustituye una pieza la parchea en el submódulo que la usa: aquí
solo se reexporta.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.routes.auth import contrasena, dev_login, login, oauth, registro, sesion, totp
from api.routes.auth.comun import (
    ACCESS_NOT_GRANTED,
    EMAIL_NOT_VERIFIED,
    OAUTH_OTRO_PROVEEDOR,
    SESSION_COOKIE,
    UserInfo,
    get_current_session_user,
    get_session_user_pending_mfa,
    require_csrf,
    require_csrf_pending_mfa,
)
from api.routes.auth.oauth import OAUTH_PROVIDERS
from api.routes.auth.totp import require_recent_session_auth

__all__ = [
    "ACCESS_NOT_GRANTED",
    "EMAIL_NOT_VERIFIED",
    "OAUTH_OTRO_PROVEEDOR",
    "OAUTH_PROVIDERS",
    "SESSION_COOKIE",
    "UserInfo",
    "get_current_session_user",
    "get_session_user_pending_mfa",
    "require_csrf",
    "require_csrf_pending_mfa",
    "require_recent_session_auth",
    "router",
]

router = APIRouter(prefix="/auth", tags=["auth"])
# El orden es el de registro de siempre: `/oauth/google/*` tiene que ir antes que
# `/oauth/{provider}/*`, y el resto conserva su posición en la tabla de rutas.
for _submodulo in (login, registro, contrasena, dev_login, sesion, totp, oauth):
    router.include_router(_submodulo.router)
