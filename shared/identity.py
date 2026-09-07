"""Identidad: clave opaca heredada y verificación genérica de tokens OIDC.

Dos cosas conviven aquí y conviene no confundirlas:

* :func:`user_key_from_email` — **en retirada** (D18). Ver su docstring.
* La verificación de un ``id_token`` OIDC contra el documento de
  descubrimiento de su emisor, que es lo que permite tener más de un proveedor
  (Google y Microsoft Entra ID) sin duplicar el flujo de login.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import TYPE_CHECKING, Any

from observability.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - solo para el tipado
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

log = get_logger(__name__)


def user_key_from_email(email: str | None, user_id: int) -> str:
    """Deriva una clave opaca de la identidad humana, nunca de una credencial.

    .. deprecated:: 2026-09
        **No la llames desde código nuevo.** Derivar la identidad del correo
        significa que cambiar de dirección pierde favoritos, reglas, vistas,
        descartes, notificaciones y oportunidades, porque la clave cambia con
        ella. La decisión D18 del plan de arquitectura 2026-09 v2 fija el
        camino: fase 1 (S1.4) congela los ficheros que hoy la usan con
        ``scripts/check_user_key_ratchet.py`` —la lista solo puede encoger— y
        fase 2 (T4) migra a ``user_id`` con columna doble y lectura dual.

        Mientras tanto sigue viva porque decenas de tablas están escritas con
        ella; lo que está prohibido es extender su alcance.
    """
    seed = (email or f"user:{user_id}").strip().lower()
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


# ── Verificación genérica de id_token OIDC (S1.2) ──────────────────────────
#
# `shared.auth_core.verify_google_id_token` sigue siendo el camino de Google y
# no se toca: es el flujo que ya funciona en producción y la regla del stream
# es no romperlo. Lo de aquí es su equivalente para cualquier proveedor que
# publique un documento de descubrimiento OpenID, y es lo que sirve a Microsoft
# Entra ID.

#: Vida de las cachés de descubrimiento y JWKS. Una hora es lo mismo que usa el
#: camino de Google y lo que recomienda Microsoft para su JWKS.
_CACHE_TTL_SECONDS = 3600

_discovery_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks_cache: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}


def reset_oidc_caches() -> None:
    """Vacía las cachés. Existe para los tests: en producción caducan solas."""
    _discovery_cache.clear()
    _jwks_cache.clear()


def _json_from_b64url(encoded: str) -> dict[str, Any]:
    decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    data = json.loads(decoded)
    if not isinstance(data, dict):
        raise ValueError("El fragmento JWT debe ser un objeto JSON")
    return data


def _http_get_json(url: str) -> dict[str, Any]:
    import httpx

    response = httpx.get(url, timeout=5.0)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError(f"Respuesta no-objeto desde {url}")
    return data


def fetch_discovery_document(url: str) -> dict[str, Any]:
    """Documento ``.well-known/openid-configuration`` del proveedor, cacheado.

    Se lee del emisor en vez de fijar sus URLs en el código porque son suyas:
    Microsoft cambió el host de su JWKS al pasar de v1 a v2 y quien las tenía
    escritas a mano se enteró en producción.
    """
    now = time.time()
    cached = _discovery_cache.get(url)
    if cached is not None and now < cached[0]:
        return cached[1]
    document = _http_get_json(url)
    _discovery_cache[url] = (now + _CACHE_TTL_SECONDS, document)
    return document


def _jwks_by_kid(jwks_uri: str, *, force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    now = time.time()
    cached = _jwks_cache.get(jwks_uri)
    if cached is not None and now < cached[0] and not force_refresh:
        return cached[1]
    claves = {
        str(item["kid"]): item
        for item in _http_get_json(jwks_uri).get("keys", [])
        if isinstance(item, dict) and item.get("kid") and item.get("n") and item.get("e")
    }
    if not claves:
        raise ValueError(f"El JWKS de {jwks_uri} no traía ninguna clave usable")
    _jwks_cache[jwks_uri] = (now + _CACHE_TTL_SECONDS, claves)
    return claves


def _rsa_public_key(jwk: dict[str, Any]) -> RSAPublicKey:
    """Reconstruye la clave pública RSA a partir de ``n``/``e`` (RFC 7517)."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    def _uint(value: str) -> int:
        return int.from_bytes(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)), "big")

    return rsa.RSAPublicNumbers(e=_uint(jwk["e"]), n=_uint(jwk["n"])).public_key()


def _issuer_matches(expected: str, claims: dict[str, Any]) -> bool:
    """Compara ``iss`` admitiendo la plantilla multi-tenant de Microsoft.

    Con el tenant ``common``, el documento de descubrimiento declara el emisor
    como ``https://login.microsoftonline.com/{tenantid}/v2.0``: no es un emisor
    literal sino una plantilla que cada tenant rellena con su propio id. Se
    sustituye por el ``tid`` del token y se compara exacto — aceptar cualquier
    cosa que «se parezca» sería aceptar un emisor arbitrario.
    """
    actual = str(claims.get("iss", ""))
    if "{tenantid}" in expected:
        tid = str(claims.get("tid", ""))
        if not tid:
            return False
        expected = expected.replace("{tenantid}", tid)
    return hmac.compare_digest(expected, actual)


def verify_oidc_id_token(
    raw_token: str,
    *,
    jwks_uri: str,
    issuer: str,
    audience: str,
    expected_nonce: str | None = None,
) -> dict[str, Any] | None:
    """Verifica firma RS256 y claims de un ``id_token`` OIDC cualquiera.

    Devuelve los claims si todo cuadra y ``None`` en cualquier otro caso: un
    token nunca se acepta simplemente decodificado. Se comprueban ``iss``,
    ``aud``, ``exp``, ``sub`` y —si se pide— ``nonce``.

    ``email_verified`` **no** se exige aquí, a diferencia del camino de Google:
    Microsoft Entra ID no emite ese claim, así que exigirlo rechazaría a todo
    el mundo. Quién puede entrar lo decide la allowlist por dominio y
    ``access_grants``, que es donde vive esa política para los dos proveedores.
    """
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        encoded_header, encoded_claims, encoded_signature = raw_token.split(".")
        header = _json_from_b64url(encoded_header)
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str):
            return None

        jwk = _jwks_by_kid(jwks_uri).get(kid)
        if jwk is None:
            # Una rotación puede adelantarse al TTL: un único refresco forzado.
            jwk = _jwks_by_kid(jwks_uri, force_refresh=True).get(kid)
        if jwk is None:
            raise ValueError("El JWKS del proveedor no contiene la clave del token")

        _rsa_public_key(jwk).verify(
            base64.urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4)),
            f"{encoded_header}.{encoded_claims}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        claims = _json_from_b64url(encoded_claims)
    except Exception:
        log.warning("oidc_id_token_signature_invalid", exc_info=True)
        return None

    return claims if _oidc_claims_valid(claims, audience, issuer, expected_nonce) else None


def _oidc_claims_valid(
    claims: dict[str, Any],
    audience: str,
    issuer: str,
    expected_nonce: str | None,
) -> bool:
    if not _issuer_matches(issuer, claims):
        log.warning("oidc_id_token_invalid_iss")
        return False

    aud = claims.get("aud", "")
    aud_values = {str(v) for v in aud} if isinstance(aud, list) else {str(aud)}
    if audience not in aud_values:
        log.warning("oidc_id_token_invalid_aud")
        return False
    if len(aud_values) > 1 and str(claims.get("azp", "")) != audience:
        log.warning("oidc_id_token_invalid_azp")
        return False

    if not str(claims.get("sub", "")):
        log.warning("oidc_id_token_missing_sub")
        return False

    if expected_nonce is not None:
        nonce = claims.get("nonce")
        if not isinstance(nonce, str) or not hmac.compare_digest(nonce, expected_nonce):
            log.warning("oidc_id_token_invalid_nonce")
            return False

    try:
        # 60 s de margen, el mismo que el camino de Google: los relojes de dos
        # máquinas nunca coinciden al segundo.
        if int(str(claims.get("exp", ""))) + 60 < int(time.time()):
            log.warning("oidc_id_token_expired")
            return False
    except (TypeError, ValueError):
        log.warning("oidc_id_token_invalid_exp")
        return False

    return True
