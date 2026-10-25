"""Tests para api/auth.py — hashing, creación, revocación y scope checks."""

from __future__ import annotations

import hashlib

import pytest

# ── hash_api_key ─────────────────────────────────────────────────────────────


def test_hash_api_key_plain_sha256(monkeypatch):
    """Sin API_HMAC_SECRET usa SHA-256 plain."""
    from pydantic import SecretStr

    import config as _cfg

    monkeypatch.setattr(_cfg.settings, "API_HMAC_SECRET", SecretStr(""))

    from api.auth import hash_api_key

    raw = "test-key-12345"
    expected = hashlib.sha256(raw.encode()).hexdigest()
    assert hash_api_key(raw) == expected


def test_hash_api_key_hmac_with_secret(monkeypatch):
    """Con API_HMAC_SECRET usa HMAC-SHA256."""
    import hmac as _hmac

    from pydantic import SecretStr

    import config as _cfg

    monkeypatch.setattr(_cfg.settings, "API_HMAC_SECRET", SecretStr("supersecret"))

    from api.auth import hash_api_key

    raw = "test-key-12345"
    expected = _hmac.new(b"supersecret", raw.encode(), hashlib.sha256).hexdigest()
    assert hash_api_key(raw) == expected


def test_hash_api_key_deterministic(monkeypatch):
    """El mismo input siempre produce el mismo hash."""
    monkeypatch.setenv("API_HMAC_SECRET", "")

    from api.auth import hash_api_key

    raw = "my-api-key"
    assert hash_api_key(raw) == hash_api_key(raw)


def test_hash_api_key_different_inputs_differ(monkeypatch):
    """Inputs distintos → hashes distintos."""
    monkeypatch.setenv("API_HMAC_SECRET", "")

    from api.auth import hash_api_key

    assert hash_api_key("key-A") != hash_api_key("key-B")


# ── AuthContext.has_scope ─────────────────────────────────────────────────────


def test_auth_context_wildcard_grants_any_scope():
    from api.auth import AuthContext

    ctx = AuthContext(key_hash="abc", key_id=1, scopes=frozenset({"*"}))
    assert ctx.has_scope("admin")
    assert ctx.has_scope("webhooks:write")
    assert ctx.has_scope("nonexistent")


def test_auth_context_specific_scope_granted():
    from api.auth import AuthContext

    ctx = AuthContext(key_hash="abc", key_id=1, scopes=frozenset({"read", "webhooks:read"}))
    assert ctx.has_scope("read")
    assert ctx.has_scope("webhooks:read")


def test_auth_context_specific_scope_denied():
    from api.auth import AuthContext

    ctx = AuthContext(key_hash="abc", key_id=1, scopes=frozenset({"read"}))
    assert not ctx.has_scope("admin")
    assert not ctx.has_scope("webhooks:write")


# ── create_api_key + revoke_api_key ──────────────────────────────────────────


def test_create_api_key_returns_token(api_db):
    """create_api_key devuelve un token en bruto no vacío."""
    from tests.claves import clave_de_prueba

    token = clave_de_prueba("test-integration")
    assert isinstance(token, str)
    assert len(token) > 10


def test_revoke_api_key_deactivates(api_db):
    """Revocar una key existente devuelve True."""
    from api.auth import hash_api_key, revoke_api_key
    from tests.claves import clave_de_prueba

    token = clave_de_prueba("revoke-test")
    key_hash = hash_api_key(token)
    assert revoke_api_key(key_hash) is True


def test_revoke_api_key_nonexistent_returns_false(api_db):
    """Revocar una key que no existe devuelve False."""
    from api.auth import revoke_api_key

    assert revoke_api_key("0" * 64) is False


def test_create_api_key_with_expiry(api_db):
    """create_api_key acepta expires_days sin error."""
    from tests.claves import clave_de_prueba

    token = clave_de_prueba("expiry-test", expires_days=30)
    assert isinstance(token, str)
    assert len(token) > 10


# ── Ninguna clave nace sin dueño ni sin caducidad ────────────────────────────
#
# Antes la exigencia de dueño era solo de prod/staging, y la caducidad podía
# faltar en el INSERT: en producción se acumularon 89 claves activas sin
# usuario ni `expires_at`. Estos tests no abren Postgres: la comprobación va
# antes de escribir, y el INSERT se sustituye para ver qué llegaría a la tabla.


@pytest.mark.parametrize("env", ["dev", "staging", "prod"])
@pytest.mark.parametrize("dueno", [0, -1])
def test_create_api_key_sin_dueno_falla_en_cualquier_entorno(monkeypatch, env, dueno):
    import config as _cfg
    from api import auth as auth_mod

    insertadas: list[dict[str, object]] = []
    monkeypatch.setattr(_cfg.settings, "ENV", env)
    monkeypatch.setattr(auth_mod.auth_service, "insert_api_key", lambda **kw: insertadas.append(kw))

    with pytest.raises(ValueError, match="dueño"):
        auth_mod.create_api_key("sin-dueno", user_id=dueno)
    assert insertadas == []


def test_create_api_key_sin_user_id_es_type_error():
    """`user_id` es obligatorio y solo por nombre: olvidarlo es un TypeError."""
    from api.auth import create_api_key

    with pytest.raises(TypeError):
        create_api_key("sin-dueno")  # type: ignore[call-arg]  # es justo lo que se prueba


def test_create_api_key_sin_ttl_usa_la_caducidad_por_defecto(monkeypatch):
    """Sin `expires_days`, la clave caduca a los `API_KEY_DEFAULT_TTL_DAYS`."""
    from datetime import UTC, datetime, timedelta

    import config as _cfg
    from api import auth as auth_mod

    insertadas: list[dict[str, object]] = []
    monkeypatch.setattr(auth_mod.auth_service, "insert_api_key", lambda **kw: insertadas.append(kw))

    antes = datetime.now(UTC)
    auth_mod.create_api_key("con-dueno", user_id=7)

    (fila,) = insertadas
    assert fila["user_id"] == 7
    caduca = datetime.fromisoformat(str(fila["expires_at"]))
    esperado = antes + timedelta(days=_cfg.settings.API_KEY_DEFAULT_TTL_DAYS)
    assert abs((caduca - esperado).total_seconds()) < 60


def test_create_api_key_rechaza_caducidad_por_encima_del_tope(monkeypatch):
    import config as _cfg
    from api import auth as auth_mod

    monkeypatch.setattr(auth_mod.auth_service, "insert_api_key", lambda **kw: None)
    with pytest.raises(ValueError):
        auth_mod.create_api_key(
            "perpetua", user_id=7, expires_days=_cfg.settings.API_KEY_MAX_TTL_DAYS + 1
        )


@pytest.mark.parametrize(
    ("user_id", "expires_at", "falta"),
    [(0, "2099-01-01T00:00:00+00:00", "dueño"), (7, "", "caducidad")],
)
def test_repositorio_rechaza_insertar_sin_dueno_o_sin_caducidad(user_id, expires_at, falta):
    """El único INSERT de producción también lo comprueba, antes de conectar."""
    from db.repositories.api_keys import ApiKeyRepository

    with pytest.raises(ValueError, match=falta):
        ApiKeyRepository().insert(
            key_hash="h" * 64,
            name="x",
            scopes="*",
            prefix="abcdefgh",
            user_id=user_id,
            expires_at=expires_at,
        )
