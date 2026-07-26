"""Tests para config/settings.py — validadores Pydantic y derivación de rutas."""

from __future__ import annotations

import warnings

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_settings(**kwargs):
    """Instancia Settings con overrides de env vars."""
    import os
    from unittest.mock import patch

    env = {
        "ENV": "dev",
        "SIGNING_KEY": "",
        "API_HMAC_SECRET": "",
        **kwargs,
    }
    with patch.dict(os.environ, env, clear=False):
        import config.settings as _mod

        return _mod.Settings(**kwargs)


# ---------------------------------------------------------------------------
# Valores por defecto y tipos básicos
# ---------------------------------------------------------------------------


def test_default_env_is_dev():
    from config.settings import Settings

    s = Settings()
    assert s.ENV == "dev"


def test_default_ml_threshold():
    from config.settings import Settings

    s = Settings()
    assert 0.0 < s.ML_CONFIDENCE_THRESHOLD <= 1.0


def test_default_paths_derived(tmp_path):
    """DB_PATH y DOWNLOADS_DIR se derivan de DATA_DIR si no se configuran."""
    from config.settings import Settings

    s = Settings(DATA_DIR=tmp_path)
    assert tmp_path / "licitaciones.db" == s.DB_PATH
    assert tmp_path / "downloads" == s.DOWNLOADS_DIR


def test_explicit_db_path_not_overridden(tmp_path):
    """Si DB_PATH se configura explícitamente, no se sobreescribe."""
    custom = tmp_path / "custom.db"
    from config.settings import Settings

    s = Settings(DATA_DIR=tmp_path, DB_PATH=custom)
    assert custom == s.DB_PATH


# ---------------------------------------------------------------------------
# Validators de umbrales
# ---------------------------------------------------------------------------


def test_ml_confidence_threshold_valid():
    from config.settings import Settings

    s = Settings(ML_CONFIDENCE_THRESHOLD=0.5)
    assert s.ML_CONFIDENCE_THRESHOLD == 0.5


def test_ml_confidence_threshold_zero_valid():
    from config.settings import Settings

    s = Settings(ML_CONFIDENCE_THRESHOLD=0.0)
    assert s.ML_CONFIDENCE_THRESHOLD == 0.0


def test_ml_confidence_threshold_one_valid():
    from config.settings import Settings

    s = Settings(ML_CONFIDENCE_THRESHOLD=1.0)
    assert s.ML_CONFIDENCE_THRESHOLD == 1.0


def test_ml_confidence_threshold_out_of_range_raises():
    from config.settings import Settings

    with pytest.raises(Exception, match=r"0\.0 y 1\.0"):
        Settings(ML_CONFIDENCE_THRESHOLD=1.5)


def test_ml_confidence_threshold_negative_raises():
    from config.settings import Settings

    with pytest.raises(Exception):  # noqa: B017
        Settings(ML_CONFIDENCE_THRESHOLD=-0.1)


def test_otel_sample_ratio_valid():
    from config.settings import Settings

    s = Settings(OTEL_SAMPLE_RATIO=0.05)
    assert pytest.approx(0.05) == s.OTEL_SAMPLE_RATIO


def test_otel_sample_ratio_out_of_range():
    from config.settings import Settings

    with pytest.raises(Exception):  # noqa: B017
        Settings(OTEL_SAMPLE_RATIO=1.5)


def test_request_timeout_positive():
    from config.settings import Settings

    s = Settings(REQUEST_TIMEOUT=60)
    assert s.REQUEST_TIMEOUT == 60


def test_request_timeout_zero_raises():
    from config.settings import Settings

    with pytest.raises(Exception):  # noqa: B017
        Settings(REQUEST_TIMEOUT=0)


def test_smtp_port_valid():
    from config.settings import Settings

    s = Settings(ALERT_SMTP_PORT=587)
    assert s.ALERT_SMTP_PORT == 587


def test_smtp_port_out_of_range_raises():
    from config.settings import Settings

    with pytest.raises(Exception):  # noqa: B017
        Settings(ALERT_SMTP_PORT=99999)


def test_pool_size_min_1():
    from config.settings import Settings

    s = Settings(DB_POOL_SIZE=1)
    assert s.DB_POOL_SIZE == 1


def test_pool_size_zero_raises():
    from config.settings import Settings

    with pytest.raises(Exception):  # noqa: B017
        Settings(DB_POOL_SIZE=0)


# ---------------------------------------------------------------------------
# Cross-field validator: ML_UNCERTAINTY rango
# ---------------------------------------------------------------------------


def test_ml_uncertainty_range_valid():
    from config.settings import Settings

    s = Settings(ML_UNCERTAINTY_LO=0.2, ML_UNCERTAINTY_HI=0.8)
    assert s.ML_UNCERTAINTY_LO < s.ML_UNCERTAINTY_HI


def test_ml_uncertainty_range_invalid_raises():
    from config.settings import Settings

    with pytest.raises(Exception, match="ML_UNCERTAINTY_LO"):
        Settings(ML_UNCERTAINTY_LO=0.8, ML_UNCERTAINTY_HI=0.2)


def test_ml_uncertainty_equal_raises():
    from config.settings import Settings

    with pytest.raises(Exception):  # noqa: B017
        Settings(ML_UNCERTAINTY_LO=0.5, ML_UNCERTAINTY_HI=0.5)


# ---------------------------------------------------------------------------
# Producción: validadores de hardening
# ---------------------------------------------------------------------------


def test_prod_requires_signing_key():
    from config.settings import Settings

    with pytest.raises(Exception, match="SIGNING_KEY"):
        Settings(
            ENV="prod",
            SIGNING_KEY="",
            API_HMAC_SECRET="x" * 32,
        )


def test_prod_requires_api_hmac_secret():
    from config.settings import Settings

    with pytest.raises(Exception, match="API_HMAC_SECRET"):
        Settings(
            ENV="prod",
            SIGNING_KEY="x" * 32,
            API_HMAC_SECRET="",
        )


def test_prod_api_hmac_secret_too_short():
    from config.settings import Settings

    with pytest.raises(Exception, match="32 caracteres"):
        Settings(
            ENV="prod",
            SIGNING_KEY="x" * 32,
            API_HMAC_SECRET="short",  # pragma: allowlist secret
        )


def test_prod_valid_config():
    """Configuración mínima válida en prod no lanza excepción."""
    from config.settings import Settings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s = Settings(
            ENV="prod",
            # Explícito para no heredar un DATABASE_URL real de .env local
            # (ver _isolate_database_url en conftest.py: solo cubre el singleton
            # `settings`, no instancias de Settings() construidas directamente).
            DATABASE_URL="",
            GF_SECURITY_ADMIN_PASSWORD="",
            SIGNING_KEY="x" * 32,
            API_HMAC_SECRET="y" * 32,
            REDIS_URL="redis://localhost:6379/0",
            REDIS_PASSWORD="prod-redis-password",
        )
    assert s.ENV == "prod"


# ---------------------------------------------------------------------------
# DATABASE_URL (Postgres/Supabase) — esquema + sslmode
# ---------------------------------------------------------------------------


def test_database_url_invalid_scheme_raises():
    from config.settings import Settings

    with pytest.raises(ValueError, match="esquema no permitido"):
        Settings(DATABASE_URL="mysql://user:pass@host/db")  # pragma: allowlist secret


def test_database_url_without_sslmode_warns_in_dev_with_local_host():
    """Host local (docker-compose de desarrollo): sin red externa que interceptar."""
    from config.settings import Settings

    url = "postgresql://user:pass@localhost:5432/db"  # pragma: allowlist secret
    with pytest.warns(UserWarning, match="sslmode"):
        s = Settings(ENV="dev", DATABASE_URL=url)
    assert s.DATABASE_URL.get_secret_value().startswith("postgresql://")


def test_database_url_without_sslmode_raises_in_dev_with_remote_host():
    """F4 (2026-07-13): cierra el gap de scrape-daily.yml (ENV=dev + Supabase real).

    Un host remoto sin sslmode debe rechazarse aunque ENV=dev — el riesgo MITM
    no depende del nombre del entorno, depende de si hay red externa de por medio.
    """
    from config.settings import Settings

    with pytest.raises(ValueError, match="host remoto"):
        Settings(
            ENV="dev",
            DATABASE_URL="postgresql://user:pass@db.supabase.co:5432/db",  # pragma: allowlist secret
        )


def test_database_url_without_sslmode_raises_in_prod():
    from config.settings import Settings

    with pytest.raises(ValueError, match="sslmode"):
        Settings(
            ENV="prod",
            DATABASE_URL="postgresql://user:pass@host:5432/db",  # pragma: allowlist secret
            SIGNING_KEY="x" * 32,
            API_HMAC_SECRET="y" * 32,
            REDIS_URL="redis://localhost:6379/0",
            REDIS_PASSWORD="prod-redis-password",
            GF_SECURITY_ADMIN_PASSWORD="",
        )


def test_database_url_with_sslmode_ok_in_prod():
    """No lanza excepción (aunque otros validators de prod puedan avisar)."""
    from config.settings import Settings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s = Settings(
            ENV="prod",
            DATABASE_URL="postgresql://user:pass@host:5432/db?sslmode=require",  # pragma: allowlist secret
            SIGNING_KEY="x" * 32,
            API_HMAC_SECRET="y" * 32,
            REDIS_URL="redis://localhost:6379/0",
            REDIS_PASSWORD="prod-redis-password",
            GF_SECURITY_ADMIN_PASSWORD="",
        )
    assert "sslmode=require" in s.DATABASE_URL.get_secret_value()


def _prod_db_settings(url: str):
    """Construye Settings prod con los secrets mínimos, variando DATABASE_URL."""
    from config.settings import Settings

    return Settings(
        ENV="prod",
        DATABASE_URL=url,
        SIGNING_KEY="x" * 32,
        API_HMAC_SECRET="y" * 32,
        REDIS_URL="redis://localhost:6379/0",
        REDIS_PASSWORD="prod-redis-password",
        GF_SECURITY_ADMIN_PASSWORD="",
    )


@pytest.mark.parametrize("mode", ["disable", "allow", "prefer"])
def test_database_url_insecure_sslmode_raises_in_prod(mode):
    """sslmode=disable/allow/prefer NO garantizan TLS → rechazados en prod.

    Regresión: el chequeo por substring anterior ('sslmode=' in url) los dejaba
    pasar, deshabilitando TLS en silencio.
    """
    from config.settings import Settings

    with pytest.raises(ValueError, match="no garantiza TLS"):
        _prod_db_settings(
            f"postgresql://user:pass@host:5432/db?sslmode={mode}"  # pragma: allowlist secret
        )

    # y en dev con host LOCAL solo avisa (no lanza) — sin red externa que interceptar
    dev_url = f"postgresql://user:pass@localhost:5432/d?sslmode={mode}"  # pragma: allowlist secret
    with pytest.warns(UserWarning, match="sin TLS"):
        Settings(ENV="dev", DATABASE_URL=dev_url)


@pytest.mark.parametrize("mode", ["disable", "allow", "prefer"])
def test_database_url_insecure_sslmode_raises_in_dev_with_remote_host(mode):
    """F4 (2026-07-13): host remoto + sslmode inseguro rechazado aunque ENV=dev."""
    from config.settings import Settings

    dev_url = (
        f"postgresql://user:pass@db.supabase.co:5432/d?sslmode={mode}"  # pragma: allowlist secret
    )
    with pytest.raises(ValueError, match="host remoto"):
        Settings(ENV="dev", DATABASE_URL=dev_url)


def test_database_url_require_warns_recommend_verify_full_in_prod():
    """sslmode=require se permite pero avisa que se recomienda verify-full."""
    url = "postgresql://user:pass@host:5432/db?sslmode=require"  # pragma: allowlist secret
    with pytest.warns(UserWarning, match="verify-full"):
        _prod_db_settings(url)


def test_database_url_verify_full_ok_in_prod():
    """verify-full es el modo recomendado: no lanza ni exige nada más."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s = _prod_db_settings(
            "postgresql://user:pass@host:5432/db?sslmode=verify-full"  # pragma: allowlist secret
        )
    assert "verify-full" in s.DATABASE_URL.get_secret_value()


# ---------------------------------------------------------------------------
# Turso URL scheme validator
# ---------------------------------------------------------------------------


def test_turso_valid_libsql_scheme():
    from config.settings import Settings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s = Settings(TURSO_DATABASE_URL="libsql://mydb.turso.io", TURSO_AUTH_TOKEN="tok")
    assert s.TURSO_DATABASE_URL == "libsql://mydb.turso.io"


def test_turso_valid_https_scheme():
    from config.settings import Settings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s = Settings(TURSO_DATABASE_URL="https://mydb.turso.io", TURSO_AUTH_TOKEN="tok")
    assert s.TURSO_DATABASE_URL.startswith("https://")


def test_turso_invalid_scheme_raises():
    from config.settings import Settings

    with pytest.raises(Exception, match="esquema no permitido"):
        Settings(TURSO_DATABASE_URL="sqlite:///bad.db", TURSO_AUTH_TOKEN="tok")


def test_turso_empty_url_ok():
    from config.settings import Settings

    s = Settings(TURSO_DATABASE_URL="", TURSO_AUTH_TOKEN="")
    assert s.TURSO_DATABASE_URL == ""


def test_turso_incomplete_pair_warns():
    """URL sin token o token sin URL emite warning y resetea ambos."""
    from config.settings import Settings

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        s = Settings(TURSO_DATABASE_URL="libsql://x.turso.io", TURSO_AUTH_TOKEN="")
    assert s.TURSO_DATABASE_URL == ""
    assert s.TURSO_AUTH_TOKEN.get_secret_value() == ""
    assert any("Turso" in str(warning.message) for warning in w)


# ---------------------------------------------------------------------------
# APP_PROFILE — separación entorno de datos vs componentes arrancados
# ---------------------------------------------------------------------------

# Secretos que solo exige el perfil `api`. El cron de scrape toca datos de
# producción pero no sirve HTTP, así que no debe necesitar ninguno de estos.
_API_SECRETS = {
    "SIGNING_KEY": "k" * 32,
    "API_HMAC_SECRET": "h" * 32,
    "REDIS_URL": "redis://localhost:6379/0",
    "REDIS_PASSWORD": "p" * 32,
}


def test_app_profile_defaults_to_api():
    """El default es el perfil más exigente: no relaja nada por omisión."""
    from config.settings import Settings

    assert Settings().APP_PROFILE == "api"


@pytest.mark.parametrize("profile", ["scraper", "worker"])
@pytest.mark.parametrize("env", ["prod", "staging"])
def test_non_api_profiles_skip_http_secrets(env, profile):
    """ENV=prod sin secretos HTTP es válido para scraper/worker.

    Es el caso del cron de GitHub Actions: escribe en la BD de producción
    (por eso ENV=prod, que mantiene activos los validators de BD) pero no
    expone la API.
    """
    from config.settings import Settings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s = Settings(ENV=env, APP_PROFILE=profile, DATABASE_URL="")

    resultado = {"env": s.ENV, "perfil": s.APP_PROFILE}
    assert resultado == {"env": env, "perfil": profile}


@pytest.mark.parametrize(
    ("missing", "match"),
    [
        ("SIGNING_KEY", "SIGNING_KEY es obligatorio"),
        ("API_HMAC_SECRET", "API_HMAC_SECRET es obligatorio"),
        ("REDIS_URL", "REDIS_URL es obligatorio"),
    ],
)
def test_api_profile_still_requires_http_secrets(missing, match):
    """El perfil api en prod sigue exigiendo todos los secretos HTTP."""
    from config.settings import Settings

    kwargs = dict(_API_SECRETS)
    kwargs[missing] = ""

    with pytest.raises(Exception, match=match):
        Settings(ENV="prod", APP_PROFILE="api", DATABASE_URL="", **kwargs)


def test_api_profile_prod_ok_with_all_secrets():
    from config.settings import Settings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s = Settings(ENV="prod", APP_PROFILE="api", DATABASE_URL="", **_API_SECRETS)

    assert s.APP_PROFILE == "api"


@pytest.mark.parametrize("profile", ["api", "worker", "scraper"])
def test_database_ssl_validator_applies_to_every_profile(profile):
    """El validator de TLS no depende del perfil.

    Es el invariante que hacía falta: el cron corría con ENV=dev y por eso
    escapaba de este chequeo apuntando a Supabase. Con APP_PROFILE separado,
    ningún perfil puede saltárselo.
    """
    from config.settings import Settings

    with pytest.raises(Exception, match="sslmode"):
        Settings(
            ENV="prod",
            APP_PROFILE=profile,
            DATABASE_URL="postgresql://u:p@db.supabase.co:5432/postgres",  # pragma: allowlist secret
            **_API_SECRETS,
        )


@pytest.mark.parametrize("profile", ["api", "worker", "scraper"])
def test_smtp_password_required_for_every_profile(profile):
    """Las alertas las envían todos los perfiles, no solo la API."""
    from config.settings import Settings

    with pytest.raises(Exception, match="ALERT_SMTP_PASSWORD"):
        Settings(
            ENV="prod",
            APP_PROFILE=profile,
            DATABASE_URL="",
            ALERT_EMAIL_TO="ops@example.com",
            ALERT_SMTP_PASSWORD="",
            **_API_SECRETS,
        )


def test_invalid_app_profile_rejected():
    """``dashboard`` fue un perfil real (Streamlit, ADR-002) y ya no existe."""
    from pydantic import ValidationError

    from config.settings import Settings

    with pytest.raises(ValidationError, match="APP_PROFILE"):
        Settings(APP_PROFILE="dashboard")


# ---------------------------------------------------------------------------
# ensure_data_dirs
# ---------------------------------------------------------------------------


def test_ensure_data_dirs_creates_directories(tmp_path):
    import sys

    # Ensure module is loaded
    import config.settings  # noqa: F401
    from config.settings import Settings, ensure_data_dirs

    mod = sys.modules["config.settings"]
    s = Settings(DATA_DIR=tmp_path / "data_new")
    original = mod.__dict__["_settings"]
    mod.__dict__["_settings"] = s
    try:
        ensure_data_dirs()
        assert (tmp_path / "data_new").exists()
    finally:
        mod.__dict__["_settings"] = original
