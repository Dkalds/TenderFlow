"""Endpoints de seguridad: CSP reports, errores de cliente y GitHub Secret Scanning.

GET  /api/v1/security/csp-report      — recibe CSP violations del navegador
POST /api/v1/security/client-error    — recibe errores JS del navegador (solo log)
POST /api/v1/security/leaked-key      — recibe notificaciones de GitHub Secret Scanning
"""

from __future__ import annotations

import base64
import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from api.auth import AuthContext, require_scope
from api.concurrency import run_db
from api.middleware import _trusted_client_ip
from observability.logging import get_logger
from services.rate_limiting import get_rate_limiter

log = get_logger(__name__)

router = APIRouter(prefix="/security", tags=["security"])
_GITHUB_PARTNER_PUBLIC_KEYS_URL = "https://api.github.com/meta/public_keys/secret_scanning"
_github_keys_cache: tuple[float, dict[str, str]] | None = None


def _github_public_key(identifier: str) -> str:
    """Obtiene una clave ECDSA oficial de GitHub, con caché de una hora."""
    global _github_keys_cache
    now = time.monotonic()
    if _github_keys_cache is None or now >= _github_keys_cache[0]:
        response = httpx.get(_GITHUB_PARTNER_PUBLIC_KEYS_URL, timeout=5.0)
        response.raise_for_status()
        items = response.json().get("public_keys", [])
        keys = {
            str(item["key_identifier"]): str(item["key"])
            for item in items
            if isinstance(item, dict) and item.get("key_identifier") and item.get("key")
        }
        if not keys:
            raise ValueError("GitHub returned no secret-scanning public keys")
        _github_keys_cache = (now + 3600, keys)
    key = _github_keys_cache[1].get(identifier)
    if key is None:
        raise ValueError("Unknown GitHub secret-scanning key identifier")
    return key


def _verify_github_signature(identifier: str | None, signature: str | None, body: bytes) -> None:
    """Exige y verifica la firma ECDSA P-256 de GitHub Secret Scanning."""
    if not identifier or not signature:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Missing GitHub signature"
        )
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        key = serialization.load_pem_public_key(_github_public_key(identifier).encode())
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError("GitHub secret-scanning key must use ECDSA P-256")
        raw_signature = base64.b64decode(signature, validate=True)
        key.verify(raw_signature, body, ec.ECDSA(hashes.SHA256()))
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("leaked_key_invalid_signature", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid GitHub signature"
        ) from exc


# ── CSP report endpoint ───────────────────────────────────────────────────────


@router.post(
    "/csp-report",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Recibir CSP violation report",
    include_in_schema=False,  # No exponer en docs públicos
)
async def csp_report(request: Request) -> None:
    """Recibe reportes de violación de Content-Security-Policy del navegador.

    Almacena en tabla ``csp_violations`` si existe, y loguea en modo estructurado.
    Sin autenticación (el navegador lo envía directamente).
    Rate limiting: 10 reportes/min por IP para mitigar flood/DoS.
    """
    # Rate limiting por IP — los browsers legítimos envían muy pocos reportes.
    # El backend de rate limiting va a BD, así que la comprobación se despacha
    # al threadpool: este endpoint es público y sin auth, justo el que no debe
    # poder parar el event loop a base de reportes.
    client_ip = _trusted_client_ip(request)
    allowed = await run_db(
        lambda: get_rate_limiter().check(f"csp:{client_ip}", max_calls=10, window_seconds=60)
    )
    if not allowed:
        log.warning("csp_report_rate_limited", client_ip=client_ip)
        return  # Responder 204 de todas formas (no revelar al cliente el rate limit)

    try:
        body = await request.json()
    except Exception:
        return  # Ignorar body inválido

    csp_data = body.get("csp-report") or body
    blocked_uri = str(csp_data.get("blocked-uri", ""))[:500]
    violated_directive = str(csp_data.get("violated-directive", ""))[:200]
    document_uri = str(csp_data.get("document-uri", ""))[:500]
    source_file = str(csp_data.get("source-file", ""))[:500]

    log.warning(
        "csp_violation",
        blocked_uri=blocked_uri,
        violated_directive=violated_directive,
        document_uri=document_uri,
        source_file=source_file,
    )

    # Persistir en tabla si existe
    from services.security import store_csp_violation

    await run_db(store_csp_violation, blocked_uri, violated_directive, document_uri, source_file)


# ── Client error endpoint ─────────────────────────────────────────────────────
#
# Canal propio de reporte de errores de cliente. Existe porque no hay Sentry ni
# ningún otro colector en el frontend (`grep -ri sentry web/` = 0 resultados) y
# añadir `@sentry/nextjs` es un cambio de dependencias que requiere OK humano.
# El precedente exacto es `csp-report`, unos cientos de líneas más arriba: POST
# sin autenticación que el navegador envía por su cuenta.
#
# **Solo loguea.** Persistir exigiría una tabla, y una tabla exige migración, que
# está fuera de alcance. La traza queda en el log estructurado (structlog), que
# es donde ya vive `csp_violation`; quien quiera series temporales las saca de
# ahí sin tocar el esquema.

# Presupuesto de bytes por reporte. 4 KiB da para un mensaje, un stack recortado
# en cliente y poco más; por encima de eso no hay diagnóstico, hay sumidero.
_MAX_CLIENT_ERROR_BYTES = 4096

# Topes de cada campo **en servidor**. El cliente ya trunca, pero el cliente es
# justo la parte que no controlamos: quien postea aquí puede ser cualquiera.
_MAX_MESSAGE = 300
_MAX_STACK = 2000
_MAX_CONTEXT = 80
_MAX_PATH = 200
_MAX_USER_AGENT = 200

# `source` es un campo de log, y un campo de log con texto libre del atacante es
# cardinalidad ilimitada en el agregador. Lista blanca o "desconocido".
_ORIGENES_CLIENTE = frozenset({"onerror", "unhandledrejection", "global-error", "manual"})

# El digest de Next es un hash hexadecimal; cualquier otra cosa se descarta en
# vez de recortarse, porque un digest inválido no sirve para correlacionar nada.
_DIGEST_VALIDO = re.compile(r"[A-Za-z0-9_-]{1,64}")


class ClientErrorReport(BaseModel):
    """Contrato del reporte de error de cliente. **Deliberadamente pobre.**

    No vive en ``shared/dto.py`` porque no es contrato API↔web tipado: el
    endpoint es ``include_in_schema=False`` y el emisor es un ``sendBeacon``
    suelto, igual que el de CSP. Se sigue el precedente local de
    ``AuditChainVerification``.

    ``extra="ignore"`` es la garantía de privacidad, no una comodidad: lo que un
    call-site del frontend adjunte como contexto extra (que puede llevar datos
    de formulario o identificadores de usuario) se descarta aquí aunque llegue.
    El frontend tampoco lo envía — ver ``web/src/lib/report-error.ts`` —, pero
    las dos puertas se cierran por separado.
    """

    model_config = ConfigDict(extra="ignore")

    message: str = ""
    source: str = ""
    context: str = ""
    path: str = ""
    stack: str = ""
    digest: str = ""


async def _leer_body_acotado(request: Request, limite: int) -> bytes | None:
    """Lee el body abortando en cuanto pasa de ``limite`` bytes.

    No vale con mirar ``Content-Length``: una request ``chunked`` no lo trae y
    ``await request.body()`` la acumularía entera en memoria. Se consume el
    stream contando, que es la única forma de acotar de verdad un endpoint que
    acepta POST de cualquiera.

    Returns:
        El body, o ``None`` si excede el límite.
    """
    trozos: list[bytes] = []
    total = 0
    async for trozo in request.stream():
        total += len(trozo)
        if total > limite:
            return None
        trozos.append(trozo)
    return b"".join(trozos)


def _ruta_sin_query(valor: str) -> str:
    """Deja solo el path de la URL: sin query string, sin fragmento, sin origen.

    La query es donde viajan los datos: filtros que pueden llevar el nombre de
    una empresa, tokens de un enlace mágico, o el correo que el repo se niega
    explícitamente a poner en una URL (ver ``api/routes/publico_solicitudes.py``).
    Se corta antes de mirar nada más, y lo que no empiece por ``/`` —una URL
    absoluta, que podría traer credenciales en el userinfo— se tira entero.
    """
    ruta = valor.split("?", 1)[0].split("#", 1)[0]
    return ruta[:_MAX_PATH] if ruta.startswith("/") else ""


@router.post(
    "/client-error",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Recibir error de cliente (JS) del navegador",
    include_in_schema=False,  # No exponer en docs públicos
)
async def client_error(request: Request) -> None:
    """Recibe un error de JavaScript ocurrido en el navegador y lo loguea.

    Sin autenticación: un fallo del layout raíz ocurre por encima de la sesión,
    así que exigir credenciales dejaría fuera justo los errores más graves.

    **Qué viaja**: mensaje del error, origen (``onerror``,
    ``unhandledrejection``, ``global-error``, ``manual``), etiqueta de contexto
    del call-site, ``pathname`` sin query, stack y ``digest`` de Next. **Qué no
    viaja**: correo, identificador de usuario, contenido de formularios, query
    string, cookies, la IP del cliente, ni el ``extra`` que los call-sites pasan
    a ``reportError``.

    La IP se lee —hace falta para la clave del rate limiter— pero **no se
    registra**. Es dato personal bajo RGPD, y junto a ``path`` y ``user_agent``
    en la misma línea de log construiría un rastro de navegación por IP en un
    endpoint sin autenticación. Es el mismo criterio que ``csp_violation``, doce
    líneas más arriba, que tampoco la escribe; la única línea del fichero que
    registra una IP es el corte por rate limit de ``csp-report``, que no lleva
    contenido del reporte. Si algún día hace falta para investigar abuso, lo que
    corresponde es un hash truncado con sal de proceso, no la IP en claro.

    Riesgo residual asumido: un stack puede contener la URL del script y, en un
    error lanzado desde un script inline, la de la propia página. Por eso el
    stack se trunca y la ruta se sanea aparte; no se intenta reescribir el stack
    porque un stack reescrito deja de servir para depurar, que es todo el punto.

    Rate limiting: 20 reportes/min por IP, además del límite global del
    middleware (bucket ``api:{ip}``, 120/min). Un cliente en bucle de error
    consume su cuota y deja de escribir en el log; el resto sigue reportando.
    """
    client_ip = _trusted_client_ip(request)
    allowed = await run_db(
        lambda: get_rate_limiter().check(f"clierr:{client_ip}", max_calls=20, window_seconds=60)
    )
    if not allowed:
        # 204 igualmente: revelar el rate limit al emisor no aporta nada y
        # convertiría el propio descarte en ruido que el navegador reintentaría.
        return

    body = await _leer_body_acotado(request, _MAX_CLIENT_ERROR_BYTES)
    if body is None:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Client error report too large",
        )

    try:
        reporte = ClientErrorReport.model_validate_json(body)
    except Exception:
        return  # Body inválido: se ignora en silencio, como en csp-report

    message = reporte.message.strip()[:_MAX_MESSAGE]
    if not message:
        return  # Un reporte sin mensaje no es diagnosticable; no ensucia el log

    digest = reporte.digest if _DIGEST_VALIDO.fullmatch(reporte.digest) else ""
    source = reporte.source if reporte.source in _ORIGENES_CLIENTE else "desconocido"

    log.warning(
        "client_error",
        source=source,
        context=reporte.context.strip()[:_MAX_CONTEXT],
        message=message,
        path=_ruta_sin_query(reporte.path),
        digest=digest,
        stack=reporte.stack[:_MAX_STACK],
        user_agent=request.headers.get("user-agent", "")[:_MAX_USER_AGENT],
    )


# ── GitHub Secret Scanning partner endpoint ───────────────────────────────────


@router.post(
    "/leaked-key",
    status_code=status.HTTP_200_OK,
    summary="GitHub Secret Scanning — revocar key filtrada",
    include_in_schema=False,  # Solo para GitHub, no público
)
async def leaked_key_notification(
    request: Request,
    x_github_public_key_identifier: str | None = Header(None),
    x_github_public_key_signature: str | None = Header(None),
) -> list[dict[str, Any]]:
    """Endpoint registrado en GitHub Secret Scanning Partner Program.

    GitHub envía una request firmada cuando detecta un token ``lic_`` en un
    repositorio público. Este endpoint verifica la firma HMAC, revoca la key
    y devuelve el resultado en el formato esperado por GitHub.

    Ref: https://docs.github.com/en/code-security/secret-scanning/
    """
    import json

    body_bytes = await request.body()

    # Verificar firma GitHub (ECDSA P-256) — si API_HMAC_SECRET está configurado
    # se usa como fallback para tests. En producción se debería usar la clave pública
    # de GitHub descargada de https://api.github.com/meta/public_keys/secret_scanning
    _verify_github_signature(
        x_github_public_key_identifier,
        x_github_public_key_signature,
        body_bytes,
    )

    try:
        tokens = json.loads(body_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None

    results = []
    for item in tokens:
        token = str(item.get("token", ""))
        token_type = str(item.get("type", ""))
        url = str(item.get("url", ""))

        if not token:
            continue

        from api.auth import hash_api_key, revoke_api_key

        key_hash = hash_api_key(token)
        revoked = revoke_api_key(key_hash)

        log.warning(
            "leaked_key_notification",
            token_type=token_type,
            url=url[:200],
            revoked=revoked,
            key_prefix=token[:8],
        )

        results.append(
            {
                "token_raw": token,
                "token_type": token_type,
                "label": "true_positive" if revoked else "false_positive",
            }
        )

    return results


# ── Audit log integrity endpoint ──────────────────────────────────────────────


class AuditChainVerification(BaseModel):
    """Resultado de recalcular el hash chain del audit log.

    ``valid`` es None cuando la cadena no está disponible (migración
    pendiente) — distinto de False, que significa manipulación detectada.
    """

    valid: bool | None
    checked: int
    first_tampered_id: int | None
    error: str | None


@router.get(
    "/audit/verify",
    summary="Verificar integridad del audit log (hash chain)",
    tags=["admin"],
)
async def verify_audit_integrity(
    auth: AuthContext = Depends(require_scope("admin")),
) -> AuditChainVerification:
    """Recorre el audit log y verifica que el hash chain no ha sido alterado.

    Requiere autenticación + scope ``admin``.

    Returns:
        ``{"valid": bool, "checked": int, "first_tampered_id": int|None, "error": str|None}``
    """
    from db.audit import verify_hash_chain

    # Recorre audit_log entero recalculando el HMAC fila a fila: O(n) en CPU y
    # en memoria sobre una tabla que solo crece. Nunca sobre el event loop.
    return AuditChainVerification.model_validate(await run_db(verify_hash_chain))
