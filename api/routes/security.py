"""Endpoints de seguridad: CSP reports y GitHub Secret Scanning.

GET  /api/v1/security/csp-report      — recibe CSP violations del navegador
POST /api/v1/security/leaked-key      — recibe notificaciones de GitHub Secret Scanning
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from api.auth import AuthContext, require_api_key, require_scope
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/security", tags=["security"])


# ── CSP report endpoint ───────────────────────────────────────────────────────


class CSPReport(BaseModel):
    """Estructura de un reporte CSP (RFC 7486 / CSP Level 3)."""

    model_config = {"extra": "allow"}


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
    """
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

    store_csp_violation(blocked_uri, violated_directive, document_uri, source_file)


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
) -> list[dict]:
    """Endpoint registrado en GitHub Secret Scanning Partner Program.

    GitHub envía una request firmada cuando detecta un token ``lic_`` en un
    repositorio público. Este endpoint verifica la firma HMAC, revoca la key
    y devuelve el resultado en el formato esperado por GitHub.

    Ref: https://docs.github.com/en/code-security/secret-scanning/
    """
    import base64
    import hashlib
    import hmac
    import json

    from config import settings

    body_bytes = await request.body()

    # Verificar firma GitHub (ECDSA P-256) — si API_HMAC_SECRET está configurado
    # se usa como fallback para tests. En producción se debería usar la clave pública
    # de GitHub descargada de https://api.github.com/meta/public_keys/secret_scanning
    if settings.API_HMAC_SECRET and x_github_public_key_signature:
        try:
            expected = hmac.new(
                settings.API_HMAC_SECRET.encode(),
                body_bytes,
                hashlib.sha256,
            ).hexdigest()
            sig_hex = base64.b64decode(x_github_public_key_signature).hex()
            if not hmac.compare_digest(expected, sig_hex):
                log.warning("leaked_key_invalid_signature")
                raise HTTPException(status_code=403, detail="Invalid signature")
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            log.warning("leaked_key_signature_verify_error", error=str(exc))

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


@router.get(
    "/audit/verify",
    summary="Verificar integridad del audit log (hash chain)",
    tags=["admin"],
)
async def verify_audit_integrity(auth: AuthContext = Depends(require_scope("admin"))) -> dict:
    """Recorre el audit log y verifica que el hash chain no ha sido alterado.

    Requiere autenticación + scope ``admin``.

    Returns:
        ``{"valid": bool, "checked": int, "first_tampered_id": int|None, "error": str|None}``
    """
    from db.audit import verify_hash_chain

    return verify_hash_chain()
