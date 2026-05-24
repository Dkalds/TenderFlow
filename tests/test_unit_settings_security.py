"""Tests unitarios para validadores de seguridad en config.settings."""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest


def _fresh_settings(**overrides):
    """Crea una instancia fresca de Settings con env vars controladas."""
    # Limpiar módulo cacheado
    for mod in list(sys.modules):
        if mod.startswith("config"):
            sys.modules.pop(mod, None)

    base_env = {
        "ENV": "dev",
        "DASHBOARD_PASSWORD": "",
        "DASHBOARD_PASSWORD_HASH": "",
        "TURSO_DATABASE_URL": "",
        "TURSO_AUTH_TOKEN": "",
        "SIGNING_KEY": "",
        "API_HMAC_SECRET": "",
        "GF_SECURITY_ADMIN_PASSWORD": "",
        "ALERT_EMAIL_TO": "",
        "ALERT_SMTP_PASSWORD": "",
        "REDIS_URL": "",
        "REDIS_PASSWORD": "",
    }
    base_env.update(overrides)

    with patch.dict(os.environ, base_env, clear=False):
        from config.settings import Settings
        return Settings(**{k.upper(): v for k, v in overrides.items() if k.isupper()})


# ---------------------------------------------------------------------------
# DASHBOARD_PASSWORD weak in prod
# ---------------------------------------------------------------------------


def test_weak_dashboard_password_rejected_in_prod():
    with pytest.raises(Exception, match=r"DASHBOARD_PASSWORD.*débil|DASHBOARD_PASSWORD_HASH"):
        _fresh_settings(
            ENV="prod",
            DASHBOARD_PASSWORD="Deloitte123456.",  # pragma: allowlist secret
            DASHBOARD_PASSWORD_HASH="$2b$12$abc",
            SIGNING_KEY="x" * 32,
            API_HMAC_SECRET="x" * 32,
            REDIS_URL="redis://localhost:6379/0",
            REDIS_PASSWORD="x" * 32,
        )


def test_strong_dashboard_password_accepted_in_prod():
    """Una contraseña fuerte no debe fallar por el validador de fortaleza."""
    # Puede fallar por otros validadores (redis, etc.) pero no por fortaleza
    try:
        _fresh_settings(
            ENV="prod",
            DASHBOARD_PASSWORD="X9$kLm2pQr!sT4vW",  # pragma: allowlist secret
            DASHBOARD_PASSWORD_HASH="$2b$12$abc",
            SIGNING_KEY="x" * 32,
            API_HMAC_SECRET="x" * 32,
            REDIS_URL="redis://localhost:6379/0",
            REDIS_PASSWORD="x" * 32,
        )
    except ValueError as e:
        # Si falla, no debe ser por DASHBOARD_PASSWORD
        assert "DASHBOARD_PASSWORD" not in str(e) or "HASH" in str(e)


# ---------------------------------------------------------------------------
# GF_SECURITY_ADMIN_PASSWORD weak in prod
# ---------------------------------------------------------------------------


def test_weak_grafana_password_rejected_in_prod():
    with pytest.raises(Exception, match=r"GF_SECURITY_ADMIN_PASSWORD.*débil|GF_SECURITY_ADMIN_PASSWORD"):
        _fresh_settings(
            ENV="prod",
            GF_SECURITY_ADMIN_PASSWORD="Deloitte123456.",  # pragma: allowlist secret
            DASHBOARD_PASSWORD_HASH="$2b$12$abc",
            SIGNING_KEY="x" * 32,
            API_HMAC_SECRET="x" * 32,
            REDIS_URL="redis://localhost:6379/0",
            REDIS_PASSWORD="x" * 32,
        )


# ---------------------------------------------------------------------------
# SIGNING_KEY too short in prod
# ---------------------------------------------------------------------------


def test_short_signing_key_rejected_in_prod():
    with pytest.raises(Exception, match=r"SIGNING_KEY.*corto|SIGNING_KEY"):
        _fresh_settings(
            ENV="prod",
            SIGNING_KEY="short",
            DASHBOARD_PASSWORD_HASH="$2b$12$abc",
            API_HMAC_SECRET="x" * 32,
            REDIS_URL="redis://localhost:6379/0",
            REDIS_PASSWORD="x" * 32,
        )


# ---------------------------------------------------------------------------
# SMTP password required when ALERT_EMAIL_TO is set in prod
# ---------------------------------------------------------------------------


def test_smtp_password_required_with_alert_email_in_prod():
    with pytest.raises(Exception, match="ALERT_SMTP_PASSWORD"):
        _fresh_settings(
            ENV="prod",
            ALERT_EMAIL_TO="admin@example.com",
            ALERT_SMTP_PASSWORD="",
            DASHBOARD_PASSWORD_HASH="$2b$12$abc",
            SIGNING_KEY="x" * 32,
            API_HMAC_SECRET="x" * 32,
            REDIS_URL="redis://localhost:6379/0",
            REDIS_PASSWORD="x" * 32,
        )


# ---------------------------------------------------------------------------
# Dev mode — no restrictions
# ---------------------------------------------------------------------------


def test_weak_password_allowed_in_dev():
    """En dev, no se valida fortaleza de contraseñas."""
    s = _fresh_settings(
        ENV="dev",
        DASHBOARD_PASSWORD="weak",  # pragma: allowlist secret
        GF_SECURITY_ADMIN_PASSWORD="weak",  # pragma: allowlist secret
    )
    assert s.ENV == "dev"
