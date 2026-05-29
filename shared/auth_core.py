"""Lógica de autenticación pura — sin dependencias de Streamlit ni de la capa web.

Este módulo centraliza las operaciones criptográficas compartidas entre el
dashboard y la API REST:

* Verificación de contraseñas (argon2/bcrypt)
* Firma y verificación de tokens OAuth state (HMAC-SHA256)
* Validación de emails OAuth contra allowlists

Al no importar ``streamlit``, puede usarse de forma segura en tests unitarios,
tareas del scheduler, y cualquier módulo sin contexto de Streamlit.

**Nonce store para anti-replay OAuth**:
Por defecto usa un ``cachetools.TTLCache`` en memoria (proceso único, testing).
Si ``REDIS_URL`` está configurado, usa Redis compartido con TTL automático, lo
que evita replay attacks en despliegues multi-proceso/multi-contenedor.
"""

from __future__ import annotations

import base64 as _base64
import hashlib
import hmac
import os
import time
from typing import Any, Protocol

from observability.logging import get_logger

log = get_logger(__name__)

# Tiempo máximo de validez del state OAuth (10 minutos)
_OAUTH_STATE_MAX_AGE_SECONDS = 600


# ---------------------------------------------------------------------------
# Nonce store — abstracción sobre TTLCache (in-process) o Redis (multi-process)
# ---------------------------------------------------------------------------


class _NonceStore(Protocol):
    """Protocolo mínimo del almacén de nonces anti-replay."""

    def contains(self, nonce: str) -> bool:
        """Devuelve True si el nonce ya fue visto (y no expiró)."""
        ...

    def add(self, nonce: str, ttl_seconds: int) -> None:
        """Registra el nonce con tiempo de vida *ttl_seconds*."""
        ...


class _TTLCacheNonceStore:
    """Almacén en memoria usando cachetools.TTLCache (single-process).

    Máximo 10 000 nonces concurrentes — cubre cualquier carga razonable.
    Si cachetools no está instalado, cae a dict con limpieza lazy.
    """

    def __init__(self, ttl: int = _OAUTH_STATE_MAX_AGE_SECONDS) -> None:
        self._ttl = ttl
        try:
            from cachetools import TTLCache

            self._cache: Any = TTLCache(maxsize=10_000, ttl=ttl)
            self._use_ttlcache = True
        except ImportError:
            # Fallback: dict con limpieza lazy (comportamiento previo)
            self._cache = {}
            self._use_ttlcache = False

    def contains(self, nonce: str) -> bool:
        if self._use_ttlcache:
            return nonce in self._cache
        # Limpieza lazy
        now = time.time()
        self._cache = {k: v for k, v in self._cache.items() if v > now}
        return nonce in self._cache

    def add(self, nonce: str, ttl_seconds: int) -> None:
        if self._use_ttlcache:
            self._cache[nonce] = True
        else:
            self._cache[nonce] = time.time() + ttl_seconds


class _RedisNonceStore:
    """Almacén Redis con TTL automático — correcto en despliegues multi-proceso.

    Usa SETNX (set-if-not-exists) + EXPIRE para garantizar atomicidad: si dos
    workers reciben el mismo nonce en paralelo, solo uno podrá registrarlo.

    Incluye un fallback ``_TTLCacheNonceStore`` en memoria: si Redis no está
    disponible, delega al fallback para mantener protección anti-replay
    dentro del mismo proceso (fail-closed, no fail-open).
    """

    def __init__(self, redis_url: str) -> None:
        import redis as _redis

        self._client = _redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
        )
        self._prefix = "oauth_nonce:"
        self._fallback = _TTLCacheNonceStore()

    def contains(self, nonce: str) -> bool:
        try:
            found_in_redis = bool(self._client.exists(f"{self._prefix}{nonce}"))
            if found_in_redis:
                return True
            return self._fallback.contains(nonce)
        except Exception:
            log.warning("redis_nonce_store_read_error", exc_info=True)
            return self._fallback.contains(nonce)

    def add(self, nonce: str, ttl_seconds: int) -> None:
        # Always write to in-memory fallback so it's available if Redis fails later
        self._fallback.add(nonce, ttl_seconds)
        try:
            key = f"{self._prefix}{nonce}"
            # SETNX + EXPIRE atómico: si la key ya existe, set_nx devuelve False
            self._client.set(key, "1", nx=True, ex=ttl_seconds)
        except Exception:
            log.warning("redis_nonce_store_write_error", exc_info=True)


# Singleton del store — se inicializa una vez por proceso en la primera llamada.
_nonce_store: _NonceStore | None = None


def _get_nonce_store() -> _NonceStore:
    """Devuelve el almacén de nonces adecuado según la configuración."""
    global _nonce_store
    if _nonce_store is not None:
        return _nonce_store

    try:
        from config import settings as _settings

        redis_url = getattr(_settings, "REDIS_URL", "")
        if redis_url:
            try:
                store: _NonceStore = _RedisNonceStore(redis_url)
                log.info("oauth_nonce_store", backend="redis")
                _nonce_store = store
                return _nonce_store
            except Exception:
                log.warning(
                    "oauth_nonce_store_redis_fallback",
                    hint="Redis no disponible; usando TTLCache en memoria.",
                    exc_info=True,
                )
    except Exception:
        pass

    _nonce_store = _TTLCacheNonceStore()
    log.debug("oauth_nonce_store", backend="ttlcache")
    return _nonce_store


def _reset_nonce_store() -> None:
    """Resetea el singleton del nonce store. Uso exclusivo en tests."""
    global _nonce_store
    _nonce_store = None


# ---------------------------------------------------------------------------
# Verificación de contraseñas
# ---------------------------------------------------------------------------


def verify_password(candidate: str, pw_hash: str) -> bool:
    """Verifica *candidate* contra *pw_hash*.

    Soporta:
    * **argon2** (``$argon2id$``, ``$argon2i$``, ``$argon2d$``).
    * **bcrypt** (``$2b$``, ``$2y$``, ``$2a$``).

    Returns False y emite warning si el formato no es reconocido o la
    librería correspondiente no está instalada.
    """
    if not pw_hash:
        log.warning(
            "no_password_hash_configured",
            hint="Configura DASHBOARD_PASSWORD_HASH. "
            "Genera el hash con: python scripts/hash_password.py",
        )
        return False

    if pw_hash.startswith("$argon2"):
        try:
            from argon2 import PasswordHasher
            from argon2.exceptions import VerifyMismatchError

            ph = PasswordHasher()
            try:
                return ph.verify(pw_hash, candidate)
            except VerifyMismatchError:
                return False
        except ImportError:
            log.warning("argon2_not_installed", hint="pip install argon2-cffi")
            return False
        except Exception:
            log.warning("argon2_verify_failed", exc_info=True)
            return False

    # bcrypt (prefijo: $2b$, $2y$, $2a$)
    try:
        import bcrypt

        return bool(bcrypt.checkpw(candidate.encode("utf-8"), pw_hash.encode("utf-8")))
    except Exception:
        log.warning("bcrypt_verify_failed", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# OAuth state: HMAC-signed token
# ---------------------------------------------------------------------------


def get_signing_key() -> bytes:
    """Devuelve la clave para firmar/verificar el state OAuth.

    Usa ``SIGNING_KEY`` si está configurada (recomendado en producción).
    Fallback: deriva una clave de ``GOOGLE_CLIENT_SECRET``.
    """
    from config import settings

    if settings.SIGNING_KEY.get_secret_value():
        return settings.SIGNING_KEY.get_secret_value().encode()
    return hashlib.sha256(
        b"oauth_state_signing_v1:" + settings.GOOGLE_CLIENT_SECRET.get_secret_value().encode()
    ).digest()


def generate_oauth_state() -> str:
    """Genera un state OAuth firmado con HMAC.

    Formato: ``{nonce}:{timestamp}:{signature}``
    """
    nonce = os.urandom(16).hex()
    timestamp = str(int(time.time()))
    payload = f"{nonce}:{timestamp}"
    signature = hmac.new(
        get_signing_key(),
        payload.encode(),
        hashlib.sha256,
        # Truncated to 128 bits (32 hex chars). SHA-256 full output is 256 bits (64 hex)
        # but 128 bits is more than sufficient for HMAC signatures on short-lived OAuth
        # state tokens (max_age ≤ 600s). Shorter signatures also reduce the URL size in
        # OAuth redirect flows. If interoperability with external systems is needed in
        # the future, consider switching to the full 64-char digest.
    ).hexdigest()[:32]
    return f"{payload}:{signature}"


def verify_oauth_state(
    state: str,
    max_age: int = _OAUTH_STATE_MAX_AGE_SECONDS,
) -> bool:
    """Verifica la firma y frescura de un state OAuth.

    Returns True si el formato es válido, la firma HMAC coincide, el
    timestamp no supera *max_age* segundos de antigüedad y el nonce no
    ha sido visto antes (anti-replay).

    El almacén de nonces es compartido entre procesos cuando REDIS_URL
    está configurado, evitando ataques de replay en despliegues multi-proceso.
    """
    if not state:
        return False
    parts = state.split(":")
    if len(parts) != 3:
        return False
    nonce, timestamp_str, signature = parts
    try:
        ts = int(timestamp_str)
    except ValueError:
        return False
    if abs(time.time() - ts) > max_age:
        return False

    store = _get_nonce_store()
    if store.contains(nonce):
        log.warning("oauth_nonce_replay_detected", nonce=nonce[:8] + "...")
        return False

    payload = f"{nonce}:{timestamp_str}"
    expected = hmac.new(
        get_signing_key(),
        payload.encode(),
        hashlib.sha256,
        # Truncated to 128 bits — see generate_oauth_state() for rationale.
    ).hexdigest()[:32]
    valid = hmac.compare_digest(signature, expected)
    if valid:
        store.add(nonce, max_age)
    return valid


# ---------------------------------------------------------------------------
# Email allowlist helpers
# ---------------------------------------------------------------------------


def csv_set(value: str) -> set[str]:
    """Convierte una cadena CSV a un conjunto de valores en minúsculas."""
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def oauth_email_allowed(email: str) -> bool:
    """Valida el email OAuth contra allowlists opcionales (settings)."""
    from config import settings

    normalized = email.strip().lower()
    allowed_emails = csv_set(settings.OAUTH_ALLOWED_EMAILS)
    allowed_domains = csv_set(settings.OAUTH_ALLOWED_DOMAINS)
    if not allowed_emails and not allowed_domains:
        return True
    domain = normalized.rsplit("@", 1)[-1] if "@" in normalized else ""
    return normalized in allowed_emails or domain in allowed_domains


def oauth_email_is_admin(email: str) -> bool:
    """True si el email está en la lista de admins OAuth."""
    from config import settings

    return email.strip().lower() in csv_set(settings.OAUTH_ADMIN_EMAILS)


# ---------------------------------------------------------------------------
# PKCE (Proof Key for Code Exchange — RFC 7636)
# ---------------------------------------------------------------------------


def generate_pkce_pair() -> tuple[str, str]:
    """Genera un par (code_verifier, code_challenge) para PKCE S256.

    Returns:
        (code_verifier, code_challenge)
        * ``code_verifier`` — 32 bytes aleatorios codificados en base64url.
          Debe guardarse en sesión hasta el callback.
        * ``code_challenge`` — SHA-256 del verifier codificado en base64url.
          Se incluye en la URL de autorización de Google como
          ``code_challenge`` + ``code_challenge_method=S256``.

    Uso:
        verifier, challenge = generate_pkce_pair()
        # Guarda verifier en st.session_state['pkce_verifier']
        # Añade a la URL: &code_challenge=<challenge>&code_challenge_method=S256
    """
    verifier_bytes = os.urandom(32)
    code_verifier = _base64.urlsafe_b64encode(verifier_bytes).rstrip(b"=").decode()
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = _base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


def verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """Verifica que *code_verifier* corresponde a *code_challenge* (S256).

    Returns True si SHA-256(base64url(code_verifier)) == code_challenge.
    Uso en el servidor al recibir el token de intercambio.
    """
    if not code_verifier or not code_challenge:
        return False
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = _base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return hmac.compare_digest(expected, code_challenge)


# ---------------------------------------------------------------------------
# Validación de tokens de identidad Google (id_token)
# ---------------------------------------------------------------------------

# Campos obligatorios de un id_token de Google según la especificación OpenID.
_GOOGLE_ISS_VALUES = frozenset({"accounts.google.com", "https://accounts.google.com"})


def validate_google_id_token(
    id_token_claims: dict[str, object],
    *,
    audience: str,
    require_email_verified: bool = True,
) -> bool:
    """Valida los claims de un id_token de Google ya decodificado.

    Sólo valida los claims (no la firma JWT — eso lo hace la librería
    oauth o la llamada a tokeninfo). Comprueba:

    * ``iss`` pertenece a los valores permitidos de Google.
    * ``aud`` coincide con el ``client_id`` de la aplicación (``audience``).
    * ``exp`` no ha expirado (con 60 s de margen).
    * ``email_verified`` es ``True`` si ``require_email_verified=True``.

    Args:
        id_token_claims: Dict de claims extraído del id_token.
        audience: ``client_id`` de Google OAuth de la aplicación.
        require_email_verified: Si True, rechaza cuentas con email no verificado.

    Returns:
        True si los claims son válidos; False en caso contrario.
    """
    if not id_token_claims:
        log.warning("google_id_token_empty_claims")
        return False

    iss = str(id_token_claims.get("iss", ""))
    if iss not in _GOOGLE_ISS_VALUES:
        log.warning("google_id_token_invalid_iss", iss=iss)
        return False

    aud = id_token_claims.get("aud", "")
    # aud puede ser string o lista de strings (multi-audience)
    aud_values = set(aud) if isinstance(aud, list) else {str(aud)}
    if audience not in aud_values:
        log.warning("google_id_token_invalid_aud", aud=aud)
        return False

    exp = id_token_claims.get("exp")
    if exp is None:
        log.warning("google_id_token_missing_exp")
        return False
    try:
        if int(str(exp)) + 60 < int(time.time()):
            log.warning("google_id_token_expired", exp=exp)
            return False
    except (TypeError, ValueError):
        log.warning("google_id_token_invalid_exp", exp=exp)
        return False

    if require_email_verified:
        email_verified = id_token_claims.get("email_verified")
        if not email_verified:
            log.warning(
                "google_id_token_email_not_verified",
                email=id_token_claims.get("email", "unknown"),
            )
            return False

    return True
