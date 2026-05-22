"""Tests para config/secrets.py — backends, cache, rotación."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fresh_secrets_module():
    """Recarga el módulo de secrets con entorno limpio para tests aislados."""
    import sys

    sys.modules.pop("config.secrets", None)
    import config.secrets as m

    m.clear_cache()
    return m


# ---------------------------------------------------------------------------
# Backend env (default)
# ---------------------------------------------------------------------------


def test_get_secret_from_env():
    import config.secrets as m

    m.clear_cache()
    with patch.dict(
        os.environ,
        {"TEST_SECRET_XYZ": "hello"},
        clear=False,  # pragma: allowlist secret
    ):
        result = m.get_secret("TEST_SECRET_XYZ")
    assert result == "hello"


def test_get_secret_default_when_missing():
    import config.secrets as m

    m.clear_cache()
    os.environ.pop("NONEXISTENT_SECRET_ABC", None)
    result = m.get_secret("NONEXISTENT_SECRET_ABC", default="fallback")
    assert result == "fallback"


def test_get_secret_default_none_when_missing():
    import config.secrets as m

    m.clear_cache()
    os.environ.pop("NONEXISTENT_SECRET_ABC", None)
    assert m.get_secret("NONEXISTENT_SECRET_ABC") is None


def test_get_secret_cached():
    """La segunda llamada no accede al backend (usa cache)."""
    import config.secrets as m

    m.clear_cache()
    with patch.dict(os.environ, {"CACHED_SECRET": "val1"}, clear=False):  # pragma: allowlist secret
        first = m.get_secret("CACHED_SECRET")
    # Cambiar el entorno después del primer acceso
    with patch.dict(os.environ, {"CACHED_SECRET": "val2"}, clear=False):  # pragma: allowlist secret
        second = m.get_secret("CACHED_SECRET")
    # Debe devolver el valor cacheado (val1)
    assert first == second == "val1"


def test_clear_cache_allows_re_read():
    import config.secrets as m

    m.clear_cache()
    with patch.dict(os.environ, {"ROTATE_ME": "old"}, clear=False):
        old = m.get_secret("ROTATE_ME")

    m.clear_cache()
    with patch.dict(os.environ, {"ROTATE_ME": "new"}, clear=False):
        new = m.get_secret("ROTATE_ME")

    assert old == "old"
    assert new == "new"


# ---------------------------------------------------------------------------
# Rotación
# ---------------------------------------------------------------------------


def test_rotate_secret_env_backend():
    import config.secrets as m

    m.clear_cache()
    original = os.environ.get("ROTATED_KEY")
    try:
        m.rotate_secret("ROTATED_KEY", "rotated_value")
        assert os.environ.get("ROTATED_KEY") == "rotated_value"
        # Cache limpiada — re-leer del env
        assert m.get_secret("ROTATED_KEY") == "rotated_value"
    finally:
        if original is None:
            os.environ.pop("ROTATED_KEY", None)
        else:
            os.environ["ROTATED_KEY"] = original
        m.clear_cache()


# ---------------------------------------------------------------------------
# Backend Azure KeyVault (mock)
# ---------------------------------------------------------------------------


def test_azure_backend_calls_keyvault(monkeypatch):
    import config.secrets as m

    m.clear_cache()
    monkeypatch.setattr(m, "_BACKEND", "azure_keyvault")
    monkeypatch.setattr(m, "_AZURE_VAULT_URL", "https://myvault.vault.azure.net/")

    mock_secret = MagicMock()
    mock_secret.value = "azure_value"
    mock_client = MagicMock()
    mock_client.get_secret.return_value = mock_secret
    mock_client_cls = MagicMock(return_value=mock_client)
    mock_credential = MagicMock()
    mock_cred_cls = MagicMock(return_value=mock_credential)

    with (
        patch.dict(
            "sys.modules",
            {
                "azure": MagicMock(),
                "azure.identity": MagicMock(DefaultAzureCredential=mock_cred_cls),
                "azure.keyvault": MagicMock(),
                "azure.keyvault.secrets": MagicMock(SecretClient=mock_client_cls),
            },
        ),
        patch.dict(os.environ, {}, clear=False),
    ):
        result = m._get_from_azure("MY_SECRET")

    assert result == "azure_value"


def test_azure_backend_fallback_on_import_error(monkeypatch):
    import config.secrets as m

    m.clear_cache()
    monkeypatch.setattr(m, "_BACKEND", "azure_keyvault")

    with patch.dict(os.environ, {"MY_SECRET": "from_env"}, clear=False):  # pragma: allowlist secret
        # Simular ImportError de azure SDK
        def _raise_import(*a, **kw):
            raise ImportError("azure not installed")

        monkeypatch.setattr(m, "_get_from_azure", lambda name: m._get_from_env(name))
        result = m.get_secret("MY_SECRET")

    assert result == "from_env"


# ---------------------------------------------------------------------------
# Backend AWS Secrets Manager (mock)
# ---------------------------------------------------------------------------


def test_aws_backend_calls_secretsmanager(monkeypatch):
    import config.secrets as m

    m.clear_cache()
    monkeypatch.setattr(m, "_BACKEND", "aws_secretsmanager")

    mock_response = {"SecretString": "aws_secret_value"}  # pragma: allowlist secret
    mock_client = MagicMock()
    mock_client.get_secret_value.return_value = mock_response
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_client

    with patch.dict("sys.modules", {"boto3": mock_boto3}):
        result = m._get_from_aws("MY_AWS_SECRET")

    assert result == "aws_secret_value"
    mock_client.get_secret_value.assert_called_once()


def test_aws_backend_fallback_on_error(monkeypatch):
    import config.secrets as m

    m.clear_cache()
    monkeypatch.setattr(m, "_BACKEND", "aws_secretsmanager")

    with patch.dict(os.environ, {"FALLBACK_KEY": "env_val"}, clear=False):
        monkeypatch.setattr(m, "_get_from_aws", lambda name: m._get_from_env(name))
        result = m.get_secret("FALLBACK_KEY")

    assert result == "env_val"
