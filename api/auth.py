"""Autenticación y autorización por API-Key para la API REST.

La clave se pasa en la cabecera ``X-API-Key``.  Se almacena en la tabla
``api_keys`` como hash HMAC-SHA256 (con server secret) o SHA-256 plain.

Uso básico::

    from api.auth import require_api_key, require_scope

    @router.get("/endpoint")
    async def my_endpoint(ctx: AuthContext = Depends(require_api_key)):
        ...

    @router.post("/admin")
    async def admin_ep(ctx: AuthContext = Depends(require_scope("admin:write"))):
        ...
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

from fastapi import BackgroundTasks, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from db.database import now_utc_iso
from observability.logging import get_logger
from services import auth as auth_service

log = get_logger(__name__)

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    """Contexto de autenticación de una request autenticada.

    Attributes:
        key_hash: Hash de la API key (para auditoría — nunca el token en bruto).
        key_id: ID en la tabla api_keys.
        scopes: Conjunto de scopes autorizados (``{'*'}`` = todos).
    """

    key_hash: str
    key_id: int
    scopes: frozenset[str]

    def has_scope(self, scope: str) -> bool:
        """True si el contexto tiene el scope o es wildcard."""
        return "*" in self.scopes or scope in self.scopes


# ── Hashing ──────────────────────────────────────────────────────────────────


def hash_api_key(raw: str) -> str:
    """HMAC-SHA256 (con server secret si configurado) o SHA-256 plain."""
    from config import settings

    secret = settings.API_HMAC_SECRET
    if secret:
        return hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return hashlib.sha256(raw.encode()).hexdigest()


# Alias privado para compat con dashboard/pages/admin.py
_hash_key = hash_api_key


# ── Dependencias ─────────────────────────────────────────────────────────────

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="API key ausente o inválida.",
    headers={"WWW-Authenticate": "ApiKey"},
)

_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Acceso denegado. Scope insuficiente.",
)


async def require_api_key(
    api_key_raw: str | None = Security(_API_KEY_HEADER),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> AuthContext:
    """Dependencia FastAPI que valida la API Key.

    - Comparación de hash en tiempo constante (``hmac.compare_digest``).
    - Loguea warning si la tabla no tiene columna ``expires_at`` (DB legacy).
    - Actualiza ``last_used`` en background (no penaliza latencia).

    Returns:
        :class:`AuthContext` con key_hash, key_id y scopes.

    Raises:
        HTTPException 401 si la key es inválida, inactiva o expirada.
    """
    if not api_key_raw:
        raise _UNAUTHORIZED

    key_hash = hash_api_key(api_key_raw)

    try:
        record = auth_service.lookup_active_key(key_hash)
    except Exception as exc:
        log.warning("api_key_db_error", error=str(exc))
        raise _UNAUTHORIZED from exc

    if record is None:
        # Comparación dummy para mantener tiempo constante ante timing attacks
        hmac.compare_digest(key_hash, "0" * len(key_hash))
        raise _UNAUTHORIZED

    key_id = record.key_id
    expires_at = record.expires_at
    scopes_str = record.scopes

    # Comparar en tiempo constante (defensa extra sobre el índice DB)
    stored_hash = auth_service.get_stored_hash(key_id)
    if stored_hash and not hmac.compare_digest(stored_hash, key_hash):
        raise _UNAUTHORIZED

    # Validar expiración
    if expires_at and now_utc_iso() > expires_at:
        log.info("api_key_expired", key_id=key_id)
        raise _UNAUTHORIZED

    # Actualizar last_used en background
    background_tasks.add_task(_update_last_used, key_id)

    scopes = frozenset(s.strip() for s in scopes_str.split(",") if s.strip())
    return AuthContext(key_hash=key_hash, key_id=key_id, scopes=scopes)


def _update_last_used(key_id: int) -> None:
    """Actualiza last_used de forma best-effort (llamado en background)."""
    auth_service.update_last_used(key_id)


def require_scope(scope: str):
    """Factory de dependencias que require un scope específico.

    Uso::

        @router.delete("/webhooks/{id}")
        async def delete_webhook(ctx: AuthContext = Depends(require_scope("webhooks:write"))):
            ...
    """

    async def _dependency(ctx: AuthContext = Depends(require_api_key)) -> AuthContext:
        if not ctx.has_scope(scope):
            log.warning(
                "scope_denied",
                required=scope,
                available=list(ctx.scopes),
                key_id=ctx.key_id,
            )
            raise _FORBIDDEN
        return ctx

    _dependency.__name__ = f"require_scope_{scope.replace(':', '_')}"
    return _dependency


# ── Helpers de administración (no expuestos vía HTTP) ─────────────────────────


def create_api_key(
    name: str,
    scopes: str = "*",
    user_id: int | None = None,
    expires_days: int | None = None,
) -> str:
    """Genera una nueva API Key segura, la persiste y devuelve el token en bruto.

    El token devuelto no es recuperable — el llamante debe guardarlo.

    Args:
        name: Nombre descriptivo de la key (p.ej. nombre del integrador).
        scopes: Scopes autorizados, separados por coma. ``"*"`` = todos.
        user_id: FK opcional a la tabla de usuarios/admin (para GDPR export).
        expires_days: Si se especifica, la key expira en N días. None = sin expiración.
    """
    raw = secrets.token_urlsafe(32)
    key_hash = hash_api_key(raw)
    prefix = raw[:8]  # Primeros 8 chars — suficiente para identificar sin exponer
    expires_at: str | None = None
    if expires_days is not None:
        from datetime import UTC, datetime, timedelta

        expires_at = (datetime.now(UTC) + timedelta(days=expires_days)).isoformat()

    auth_service.insert_api_key(
        key_hash=key_hash,
        name=name,
        scopes=scopes,
        prefix=prefix,
        user_id=user_id,
        expires_at=expires_at,
    )
    log.info("api_key_created", name=name, has_user_id=user_id is not None, prefix=prefix)
    return raw


def revoke_api_key(key_hash: str) -> bool:
    """Desactiva una API Key por su hash. Devuelve True si se encontró."""
    return auth_service.deactivate_key(key_hash)
