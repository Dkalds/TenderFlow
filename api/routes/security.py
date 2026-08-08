"""Endpoints de seguridad: CSP reports y GitHub Secret Scanning.

GET  /api/v1/security/csp-report      — recibe CSP violations del navegador
POST /api/v1/security/leaked-key      — recibe notificaciones de GitHub Secret Scanning
"""

from __future__ import annotations

import base64
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

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
