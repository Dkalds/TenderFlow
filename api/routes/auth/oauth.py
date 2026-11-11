"""Login con proveedores OIDC (Google, Microsoft) con PKCE."""

from __future__ import annotations

import os
import urllib.parse
from asyncio import to_thread
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from api.concurrency import run_db
from api.routes.auth.comun import (
    _OAUTH_MAX_AGE,
    _OAUTH_PKCE_COOKIE,
    _OAUTH_TELEMETRY_COOKIE,
    _OAUTH_TELEMETRY_PROVIDER_COOKIE,
    OAUTH_OTRO_PROVEEDOR,
    _activar_invitaciones,
    _is_secure,
    _oauth_access_allowed,
    _set_session_cookie,
)
from config import settings
from db.audit import log_event
from db.users import (
    CuentaDeOtroProveedorError,
    CuentaDesactivadaError,
    admin_granted_by,
    get_or_create_oauth_user,
    is_admin,
    log_access,
    set_admin,
)
from observability.logging import get_logger
from shared.audit_events import AUTH_LOGIN_FAILED
from shared.auth_core import (
    csv_set,
    generate_oauth_state,
    generate_pkce_pair,
    oauth_email_is_admin,
    oauth_email_parts,
    oauth_state_nonce,
    verify_google_id_token,
    verify_oauth_state,
)
from shared.identity import fetch_discovery_document, verify_oidc_id_token

# El nombre de antes de partir el módulo: `logger` sale en cada línea de log.
log = get_logger("api.routes.auth")

router = APIRouter()


class OAuthAuthorizeResult(BaseModel):
    """URL de autorización de Google para que el SPA redirija."""

    authorization_url: str


# ---------------------------------------------------------------------------
# OIDC con PKCE — tabla de proveedores (S1.2, D17)
# ---------------------------------------------------------------------------
#
# Hasta 2026-09 este bloque era el flujo de Google escrito en línea. Ahora los
# proveedores son datos y el flujo es uno solo: PKCE, `state`, `nonce`, la
# allowlist (estática + `access_grants`) y el alta del usuario son idénticos
# para todos, y lo único que cambia por proveedor son sus endpoints, sus
# credenciales y cómo se verifica su `id_token`.
#
# Google conserva su verificador específico (`shared.auth_core.
# verify_google_id_token`) a propósito: es el camino que hoy funciona en
# producción y el riesgo de este stream está justamente en tocarlo. Lo genérico
# —descubrimiento OpenID + JWKS— sirve a Microsoft y a cualquier proveedor que
# venga después.


@dataclass(frozen=True)
class _OAuthEndpoints:
    """Las cuatro URLs que el flujo necesita de un proveedor."""

    authorize_url: str
    token_url: str
    jwks_uri: str
    issuer: str


@dataclass(frozen=True)
class _OAuthProvider:
    """Un proveedor OIDC: credenciales, endpoints y verificación de su token."""

    name: str
    #: Etiqueta para mensajes de error de configuración.
    label: str
    #: ``(client_id, client_secret)``; se lee en cada uso para que un cambio de
    #: entorno no exija reiniciar ni invalidar una constante de módulo.
    credentials: Callable[[], tuple[str, str]]
    #: Endpoints fijos, o ``None`` si salen del documento de descubrimiento.
    static_endpoints: _OAuthEndpoints | None
    #: URL del ``.well-known/openid-configuration``, si aplica.
    discovery_url: Callable[[], str] | None
    scope: str
    #: Claim booleano del ``id_token`` que acredita que quien entra controla el
    #: correo (ADR-037). Sin valor por defecto: un proveedor nuevo tiene que
    #: decirlo. ``None`` solo para Google, cuyo verificador propio ya exige
    #: ``email_verified``.
    claim_correo_verificado: str | None
    #: Claims de los que se toma el correo, por orden. Solo los que el claim
    #: anterior acredita: un correo sin acreditar no puede decidir la allowlist
    #: ni con qué cuenta se entra.
    claims_de_correo: tuple[str, ...] = ("email",)
    #: Parámetros propios del proveedor en la URL de autorización.
    extra_authorize_params: Mapping[str, str] = field(default_factory=dict)
    #: ``True`` cuando el proveedor tiene su propio verificador ya probado.
    usa_verificador_google: bool = False


def _google_credentials() -> tuple[str, str]:
    return settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET.get_secret_value()


def _microsoft_credentials() -> tuple[str, str]:
    from config.settings import oauth_microsoft_client_id, oauth_microsoft_client_secret

    return oauth_microsoft_client_id(), oauth_microsoft_client_secret()


def _microsoft_discovery_url() -> str:
    from config.settings import oauth_microsoft_tenant

    tenant = urllib.parse.quote(oauth_microsoft_tenant(), safe="")
    return f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration"


#: Tabla de proveedores. Su gemelo en SQL es el ``CHECK`` de
#: ``v105_users_oauth_provider``; ``tests/test_s1_oauth_providers.py`` comprueba
#: que no divergen — un proveedor que la BD no admite guardaría identidades
#: duplicadas de la misma persona.
_PROVIDERS: dict[str, _OAuthProvider] = {
    "google": _OAuthProvider(
        name="google",
        label="Google",
        credentials=_google_credentials,
        static_endpoints=_OAuthEndpoints(
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            # No es una contraseña: es la URL pública del endpoint de token de
            # Google. Tanto ruff (S106) como bandit (B106) miran el nombre del
            # argumento, no el valor. La razón va aquí arriba y no detrás del
            # `nosec` porque bandit lee todo lo que le sigue como ids de test.
            token_url="https://oauth2.googleapis.com/token",  # noqa: S106  # nosec B106
            # Google verifica con su propio camino: estos dos no se usan y se
            # dejan por completitud del registro.
            jwks_uri="https://www.googleapis.com/oauth2/v3/certs",
            issuer="https://accounts.google.com",
        ),
        discovery_url=None,
        scope="openid email profile",
        claim_correo_verificado=None,
        extra_authorize_params={"access_type": "online", "prompt": "select_account"},
        usa_verificador_google=True,
    ),
    "microsoft": _OAuthProvider(
        name="microsoft",
        label="Microsoft",
        credentials=_microsoft_credentials,
        static_endpoints=None,
        discovery_url=_microsoft_discovery_url,
        # `offline_access` queda fuera: no se guarda refresh token, la sesión de
        # TenderFlow es propia y dura 24 h.
        scope="openid email profile",
        # `xms_edov`: el dueño del dominio del correo está verificado en el
        # tenant que emite el token. Es un claim opcional: hay que añadirlo en
        # «Token configuration» de la aplicación de Entra, o no entra nadie
        # (ADR-037). Y el correo sale solo de `email`, que es el claim que
        # `xms_edov` acredita: `preferred_username` y `upn` los escribe el
        # administrador del tenant y no dicen de quién es el buzón.
        claim_correo_verificado="xms_edov",
        claims_de_correo=("email",),
        extra_authorize_params={"prompt": "select_account"},
    ),
}

#: Nombres admitidos, en el orden en que se ofrecen en la pantalla de login.
OAUTH_PROVIDERS: tuple[str, ...] = tuple(_PROVIDERS)


def _provider_or_404(provider: str) -> _OAuthProvider:
    configurado = _PROVIDERS.get(provider)
    if configurado is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proveedor OAuth desconocido: {provider}",
        )
    return configurado


def _provider_credentials(provider: _OAuthProvider) -> tuple[str, str]:
    client_id, client_secret = provider.credentials()
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"{provider.label} OAuth not configured",
        )
    return client_id, client_secret


def _pkce_cookie_path(provider: _OAuthProvider) -> str:
    """El verifier solo viaja al callback de SU proveedor."""
    return f"/api/v1/auth/oauth/{provider.name}"


def _provider_redirect_uri(provider: _OAuthProvider) -> str:
    """Redirect URI del proveedor, derivado del de Google.

    ``OAUTH_REDIRECT_URI`` apunta al callback de Google y es la única variable
    que conoce el host público de la API. Los demás proveedores comparten host
    y solo cambian el segmento del proveedor, así que derivarlo evita una
    variable por proveedor que se olvidaría de actualizar en el próximo cambio
    de dominio (S1.3).
    """
    base = settings.OAUTH_REDIRECT_URI
    if provider.name == "google":
        return base
    return base.replace("/oauth/google/callback", f"/oauth/{provider.name}/callback")


async def _provider_endpoints(provider: _OAuthProvider) -> _OAuthEndpoints:
    """Endpoints fijos o leídos del documento de descubrimiento del proveedor."""
    if provider.static_endpoints is not None:
        return provider.static_endpoints
    if provider.discovery_url is None:  # pragma: no cover - configuración imposible
        raise RuntimeError(f"El proveedor {provider.name} no declara endpoints")
    document = await to_thread(fetch_discovery_document, provider.discovery_url())
    try:
        return _OAuthEndpoints(
            authorize_url=str(document["authorization_endpoint"]),
            token_url=str(document["token_endpoint"]),
            jwks_uri=str(document["jwks_uri"]),
            issuer=str(document["issuer"]),
        )
    except KeyError as exc:
        raise RuntimeError(
            f"El documento de descubrimiento de {provider.name} no trae {exc}"
        ) from exc


def _verify_provider_id_token(
    provider: _OAuthProvider,
    raw_token: str,
    *,
    endpoints: _OAuthEndpoints,
    audience: str,
    expected_nonce: str,
) -> dict[str, Any] | None:
    """Verifica el ``id_token`` con el camino que corresponde al proveedor."""
    if provider.usa_verificador_google:
        # Búsqueda del nombre en el módulo (no una referencia capturada) para
        # que los tests que ya existían puedan seguir sustituyéndolo.
        return verify_google_id_token(raw_token, audience=audience, expected_nonce=expected_nonce)
    return verify_oidc_id_token(
        raw_token,
        jwks_uri=endpoints.jwks_uri,
        issuer=endpoints.issuer,
        audience=audience,
        expected_nonce=expected_nonce,
        email_verified_claim=provider.claim_correo_verificado,
    )


def _email_from_claims(
    claims: Mapping[str, Any],
    claves: tuple[str, ...] = ("email", "preferred_username", "upn"),
) -> str:
    """Correo del token, de los claims ``claves`` y en ese orden.

    El callback pasa los de su proveedor (``claims_de_correo``): para los dos
    de hoy, solo ``email``. Hasta 2026-10 Microsoft caía a
    ``preferred_username`` y ``upn`` cuando el tenant no poblaba ``email``,
    pero esos dos los escribe el administrador del tenant y ningún claim
    acredita que el buzón sea de quien entra (ADR-037). El orden por defecto
    sigue describiendo las formas que puede traer un token.

    El primer claim que trae un ``@`` es el que identifica a la cuenta, y tiene
    que tener forma de dirección (``oauth_email_parts``: un solo ``@`` con algo
    a cada lado). Si no la tiene se devuelve vacío —el callback lo deniega— en
    vez de seguir con el siguiente claim: lo que decide la allowlist es esta
    cadena, y de ``x@evil.com@empresa.com`` no se puede decir de qué dominio es.
    """
    for clave in claves:
        valor = str(claims.get(clave, "") or "").strip()
        if "@" in valor:
            partes = oauth_email_parts(valor)
            return partes[0] if partes is not None else ""
    return ""


async def _authorize_url(provider: _OAuthProvider, response: Response) -> OAuthAuthorizeResult:
    """URL de autorización con PKCE, idéntica para todos los proveedores."""
    client_id, _ = _provider_credentials(provider)
    endpoints = await _provider_endpoints(provider)

    state = generate_oauth_state()
    oidc_nonce = oauth_state_nonce(state)
    if oidc_nonce is None:
        raise RuntimeError("Generated OAuth state did not contain a valid nonce")
    verifier, challenge = generate_pkce_pair()

    response.set_cookie(
        _OAUTH_PKCE_COOKIE,
        verifier,
        httponly=True,
        secure=_is_secure(),
        samesite="lax",
        max_age=_OAUTH_MAX_AGE,
        path=_pkce_cookie_path(provider),
    )

    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": _provider_redirect_uri(provider),
            "response_type": "code",
            "scope": provider.scope,
            "state": state,
            "nonce": oidc_nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            **provider.extra_authorize_params,
        }
    )
    log.info("oauth_authorize_redirect", provider=provider.name)
    return OAuthAuthorizeResult(authorization_url=f"{endpoints.authorize_url}?{params}")


@router.get("/oauth/google/authorize")
async def google_authorize(response: Response) -> OAuthAuthorizeResult:
    """Redirect URL for Google OAuth with PKCE.

    Returns JSON with ``authorization_url`` so the SPA can redirect the user.
    The verifier remains in a short-lived HttpOnly cookie scoped to the OAuth
    callback; the signed state contains no credential material.
    """
    return await _authorize_url(_PROVIDERS["google"], response)


@router.get("/oauth/{provider}/authorize")
async def oauth_authorize(provider: str, response: Response) -> OAuthAuthorizeResult:
    """URL de autorización del proveedor OIDC indicado (``google``, ``microsoft``).

    Devuelve JSON con ``authorization_url`` para que el SPA redirija. El
    verifier PKCE queda en una cookie HttpOnly de vida corta, limitada al
    callback de ese proveedor; el ``state`` firmado no lleva material sensible.
    """
    return await _authorize_url(_provider_or_404(provider), response)


def _sync_oauth_admin(user_id: int, email: str) -> None:
    """Refleja ``OAUTH_ADMIN_EMAILS`` sobre ``is_admin`` en ambos sentidos.

    Antes solo promovía: sacar a alguien de la lista no le quitaba admin nunca,
    así que revocar un administrador exigía acordarse de tocar la BD a mano.

    La sincronización se salta cuando la lista está vacía, porque ese caso no
    significa "nadie es admin" sino "OAuth no gobierna el flag": la otra fuente
    legítima es el panel (``admin_users.admin_set_admin``), y degradar ahí
    desadministraría a todos sus promovidos en el próximo login.

    **Precedencia, con la lista configurada:** OAuth solo gobierna *sus
    propias* concesiones. Antes mandaba sobre el panel —a quien se promovía con
    ``admin_users.admin_set_admin`` y además entraba con Google se le retiraba
    el flag en su siguiente login—, porque ``users.is_admin`` era un booleano
    sin procedencia y no se podía distinguir el origen. Con
    ``users.admin_granted_by`` (v75) sí se puede: esta función degrada
    únicamente lo que concedió ella (``'oauth'``), y deja intactas tanto las
    concesiones del panel como las de procedencia desconocida (``NULL``:
    anteriores a la migración, nadie puede afirmar quién las hizo).
    """
    if not csv_set(settings.OAUTH_ADMIN_EMAILS):
        return
    should_be_admin = oauth_email_is_admin(email)
    if should_be_admin:
        set_admin(user_id, True, granted_by="oauth")
        return
    if not is_admin(user_id):
        return
    origen = admin_granted_by(user_id)
    if origen != "oauth":
        # Concesión del panel (o previa a v75): OAuth no la otorgó, así que no
        # la retira. Se deja constancia porque es un desacuerdo entre las dos
        # fuentes y conviene poder verlo.
        log.info(
            "oauth_admin_preserved",
            user_id=user_id,
            granted_by=origen or "desconocido",
            hint=(
                "El email no está en OAUTH_ADMIN_EMAILS pero la concesión no vino "
                "de OAuth: se conserva. Para revocarla, usá el panel de administración."
            ),
        )
        return
    log.warning(
        "oauth_admin_revoked",
        user_id=user_id,
        hint=(
            "La cuenta tenía is_admin concedido por OAuth y su email ya no está "
            "en OAUTH_ADMIN_EMAILS."
        ),
    )
    set_admin(user_id, False)


def _oauth_error_redirect(frontend_url: str, error: str, provider: str = "google") -> Response:
    """Redirige a /login con un slug de error en vez de servir JSON crudo.

    El proveedor entrega este callback mediante una navegación de nivel
    superior del navegador (no una llamada fetch del SPA), así que cualquier
    HTTPException lanzada aquí se le muestra al usuario tal cual — un blob JSON
    en blanco en vez de la pantalla de login. Redirigimos siempre a
    /login?error=<slug> para que el usuario vea un mensaje entendible y pueda
    reintentar.
    """
    redirect = RedirectResponse(url=f"{frontend_url}/login?error={error}", status_code=302)
    redirect.delete_cookie(_OAUTH_PKCE_COOKIE, path=f"/api/v1/auth/oauth/{provider}")
    return redirect


async def _oauth_callback_impl(
    provider: _OAuthProvider,
    *,
    code: str,
    state: str,
    request: Request,
    pkce_verifier: str | None,
) -> Response:
    """Canje del código, verificación del ``id_token`` y alta de la sesión.

    Es el cuerpo compartido de los callbacks: lo único que varía por proveedor
    son sus endpoints, sus credenciales y cómo se verifica su ``id_token``.
    """
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")

    if not verify_oauth_state(state):
        log.warning("oauth_callback_invalid_state", reason="nonce_or_timestamp")
        return _oauth_error_redirect(frontend_url, "invalid_state", provider.name)
    oidc_nonce = oauth_state_nonce(state)
    if oidc_nonce is None:
        return _oauth_error_redirect(frontend_url, "invalid_state", provider.name)

    if not pkce_verifier:
        log.warning("oauth_callback_missing_pkce_verifier")
        return _oauth_error_redirect(frontend_url, "invalid_state", provider.name)

    # Sin `_provider_credentials`: esa función lanza 501 y este callback NUNCA
    # puede lanzar —el navegador llega por navegación de nivel superior y vería
    # el JSON crudo—. Con el proveedor sin configurar, el canje del código falla
    # y se sale por el redirect de error, que es lo que hacía antes de S1.2.
    client_id, client_secret = provider.credentials()
    try:
        endpoints = await _provider_endpoints(provider)
    except Exception:
        log.exception("oauth_discovery_unavailable", provider=provider.name)
        return _oauth_error_redirect(frontend_url, "oauth_failed", provider.name)

    # Exchange code for tokens
    try:
        async with httpx.AsyncClient(timeout=10.0) as oauth_client:
            token_resp = await oauth_client.post(
                endpoints.token_url,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": _provider_redirect_uri(provider),
                    "grant_type": "authorization_code",
                    "code_verifier": pkce_verifier,
                },
            )
    except httpx.HTTPError as exc:
        log.warning("oauth_token_exchange_network_error", error_type=type(exc).__name__)
        return _oauth_error_redirect(frontend_url, "oauth_failed", provider.name)
    if token_resp.status_code != 200:
        log.warning("oauth_token_exchange_failed", status=token_resp.status_code)
        return _oauth_error_redirect(frontend_url, "oauth_failed", provider.name)

    tokens = token_resp.json()
    id_token_raw: str | None = tokens.get("id_token")
    if not id_token_raw:
        log.warning("oauth_token_exchange_missing_id_token")
        return _oauth_error_redirect(frontend_url, "oauth_failed", provider.name)

    claims = await to_thread(
        _verify_provider_id_token,
        provider,
        id_token_raw,
        endpoints=endpoints,
        audience=client_id,
        expected_nonce=oidc_nonce,
    )
    if claims is None:
        return _oauth_error_redirect(frontend_url, "oauth_failed", provider.name)

    email: str = _email_from_claims(claims, provider.claims_de_correo)
    if not email or not await _oauth_access_allowed(email):
        log.warning("oauth_email_not_allowed", provider=provider.name)
        return _oauth_error_redirect(frontend_url, "email_not_allowed", provider.name)

    from db.totp import is_totp_required

    def _provision_user() -> tuple[int, bool]:
        """Alta/actualización del usuario OAuth y su gate de MFA, en threadpool."""
        new_id = get_or_create_oauth_user(
            email=email,
            oauth_provider=provider.name,
            oauth_sub=str(claims.get("sub", "")),
            display_name=str(claims.get("name", "")),
        )
        _sync_oauth_admin(new_id, email)
        # Entrar por OAuth con el correo invitado demuestra que se controla ese
        # buzón: es el momento en que la membresía `invited` pasa a `active`.
        _activar_invitaciones(new_id, email)
        log_access(auth_method=f"{provider.name}_oauth", user_id=new_id)
        return new_id, is_totp_required(new_id)

    try:
        user_id, mfa_required = await run_db(_provision_user)
    except CuentaDeOtroProveedorError as conflicto:
        # El correo ya es de una cuenta que entra con otro proveedor: no se le
        # da a esta identidad (ADR-037). Queda en el rastro de la cuenta
        # afectada —un intento así puede ser una suplantación— sin el correo.
        log.warning(
            "oauth_provider_conflict",
            provider=provider.name,
            existing_provider=conflicto.proveedor_existente,
            user_id=conflicto.user_id,
        )
        await run_db(
            log_event,
            event_type=AUTH_LOGIN_FAILED,
            user_id=conflicto.user_id,
            outcome="failure",
            resource=f"user:{conflicto.user_id}",
            detail={
                "reason": OAUTH_OTRO_PROVEEDOR,
                "provider": provider.name,
                "existing_provider": conflicto.proveedor_existente,
            },
        )
        return _oauth_error_redirect(frontend_url, OAUTH_OTRO_PROVEEDOR, provider.name)
    except CuentaDesactivadaError as inactiva:
        log.warning(
            "oauth_deactivated_user_rejected",
            provider=provider.name,
            user_id=inactiva.user_id,
        )
        return _oauth_error_redirect(frontend_url, "account_deactivated", provider.name)
    log.info("oauth_login_success", user_id=user_id, provider=provider.name)

    # Con MFA confirmado la sesión nace pendiente: mandarla al dashboard la
    # dejaría en una pantalla que responde 403 en todo. El SPA lee `?mfa=required`
    # y muestra la verificación del segundo factor sobre la sesión ya creada.
    destino = "/login?mfa=required" if mfa_required else "/resumen"
    redirect = RedirectResponse(url=f"{frontend_url}{destino}", status_code=302)
    redirect.delete_cookie(_OAUTH_PKCE_COOKIE, path=_pkce_cookie_path(provider))
    if not mfa_required:
        secure = settings.ENV in ("prod", "staging")
        redirect.set_cookie(
            _OAUTH_TELEMETRY_COOKIE,
            "1",
            max_age=120,
            httponly=False,
            secure=secure,
            samesite="lax",
            path="/",
        )
        # Cookie aparte y no un valor distinto en la anterior: el componente que
        # la lee (`web/src/components/oauth-login-telemetry.tsx`) compara contra
        # `oauth_login=1` exacto, así que cambiarle el valor apagaría el evento
        # que ya funciona. Solo lleva el nombre del proveedor — ni correo, ni id,
        # ni nada que identifique a la persona.
        redirect.set_cookie(
            _OAUTH_TELEMETRY_PROVIDER_COOKIE,
            provider.name,
            max_age=120,
            httponly=False,
            secure=secure,
            samesite="lax",
            path="/",
        )
    await run_db(_set_session_cookie, redirect, user_id, request)
    return redirect


# status_code=302: el callback SIEMPRE redirige (éxito → /resumen, error →
# /login?error=<slug>) — nunca sirve JSON. Sin esto, OpenAPI documentaba un
# 200 application/json {} que no existe (operación opaca en el ratchet).
@router.get("/oauth/google/callback", response_model=None, status_code=302)
async def google_callback(
    code: str,
    state: str,
    response: Response,
    request: Request,
    pkce_verifier: str | None = Cookie(default=None, alias=_OAUTH_PKCE_COOKIE),
) -> Response:
    """Handle Google OAuth callback: exchange code, validate, set session."""
    return await _oauth_callback_impl(
        _PROVIDERS["google"],
        code=code,
        state=state,
        request=request,
        pkce_verifier=pkce_verifier,
    )


@router.get("/oauth/{provider}/callback", response_model=None, status_code=302)
async def oauth_callback(
    provider: str,
    code: str,
    state: str,
    response: Response,
    request: Request,
    pkce_verifier: str | None = Cookie(default=None, alias=_OAUTH_PKCE_COOKIE),
) -> Response:
    """Callback OIDC: canjea el código, valida el token y abre la sesión.

    Siempre redirige (éxito → /resumen, error → /login?error=<slug>): el
    navegador llega aquí por navegación de nivel superior, no por fetch.
    """
    return await _oauth_callback_impl(
        _provider_or_404(provider),
        code=code,
        state=state,
        request=request,
        pkce_verifier=pkce_verifier,
    )
