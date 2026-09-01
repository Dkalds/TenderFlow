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
            GOOGLE_CLIENT_ID="",
            GF_SECURITY_ADMIN_PASSWORD="",
            SIGNING_KEY="x" * 32,
            API_HMAC_SECRET="y" * 32,
            AUDIT_HMAC_KEY="z" * 32,
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
            GOOGLE_CLIENT_ID="",
            SIGNING_KEY="x" * 32,
            API_HMAC_SECRET="y" * 32,
            AUDIT_HMAC_KEY="z" * 32,
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
            GOOGLE_CLIENT_ID="",
            SIGNING_KEY="x" * 32,
            API_HMAC_SECRET="y" * 32,
            AUDIT_HMAC_KEY="z" * 32,
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
        GOOGLE_CLIENT_ID="",
        SIGNING_KEY="x" * 32,
        API_HMAC_SECRET="y" * 32,
        AUDIT_HMAC_KEY="z" * 32,
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
# APP_PROFILE — separación entorno de datos vs componentes arrancados
# ---------------------------------------------------------------------------

# Secretos que solo exige el perfil `api`. El cron de scrape toca datos de
# producción pero no sirve HTTP, así que no debe necesitar ninguno de estos.
_API_SECRETS = {
    "SIGNING_KEY": "k" * 32,
    "API_HMAC_SECRET": "h" * 32,
    "REDIS_URL": "redis://localhost:6379/0",
    "REDIS_PASSWORD": "p" * 32,
    "AUDIT_HMAC_KEY": "z" * 32,
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
        s = Settings(ENV=env, APP_PROFILE=profile, DATABASE_URL="", AUDIT_HMAC_KEY="z" * 32)

    resultado = {"env": s.ENV, "perfil": s.APP_PROFILE}
    assert resultado == {"env": env, "perfil": profile}


@pytest.mark.parametrize("profile", ["scraper", "worker"])
def test_non_api_profiles_do_not_require_audit_hmac_key(profile):
    """Regresión: db/audit.py solo lo usa el proceso api (login, exports,
    acciones admin) — scraper/scheduler nunca llaman a log_action/log_event.

    Antes de este fix, _validate_prod_audit_hmac_secret exigía AUDIT_HMAC_KEY
    sin mirar APP_PROFILE, así que el cron diario de scraping (ENV=prod,
    APP_PROFILE=scraper) fallaba al construir Settings() antes de ejecutar
    ni una línea de scraping — visto en producción como el job
    "Run daily scraper" fallando en <1s con "AUDIT_HMAC_KEY ... obligatorio".
    """
    from config.settings import Settings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s = Settings(ENV="prod", APP_PROFILE=profile, DATABASE_URL="", AUDIT_HMAC_KEY="")

    assert s.AUDIT_HMAC_KEY.get_secret_value() == ""


@pytest.mark.parametrize(
    ("missing", "match"),
    [
        ("SIGNING_KEY", "SIGNING_KEY es obligatorio"),
        ("API_HMAC_SECRET", "API_HMAC_SECRET es obligatorio"),
        ("REDIS_URL", "REDIS_URL es obligatorio"),
        ("AUDIT_HMAC_KEY", "AUDIT_HMAC_KEY"),
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


# ---------------------------------------------------------------------------
# OAuth fail-closed en producción (allowlists vacíos con Google OAuth activo)
# ---------------------------------------------------------------------------


def test_prod_oauth_without_static_allowlists_uses_dynamic_fail_closed_path():
    """La tabla dinámica permite arrancar sin convertir vacío en acceso abierto."""
    from config.settings import Settings

    configured = Settings(
        ENV="prod",
        APP_PROFILE="api",
        DATABASE_URL="",
        GOOGLE_CLIENT_ID="client-id.apps.googleusercontent.com",
        OAUTH_ALLOWED_DOMAINS="",
        OAUTH_ALLOWED_EMAILS="",
        **_API_SECRETS,
    )
    assert configured.GOOGLE_CLIENT_ID


@pytest.mark.parametrize(
    "kwargs",
    [
        {"OAUTH_ALLOWED_DOMAINS": "example.com"},
        {"OAUTH_ALLOWED_EMAILS": "ana@example.com"},
        {"OAUTH_ALLOWED_DOMAINS": "*"},
    ],
)
def test_prod_oauth_with_allowlist_boots(kwargs):
    """Cualquiera de los dos allowlists (o el comodín explícito) desbloquea el arranque."""
    from config.settings import Settings

    s = Settings(
        ENV="prod",
        APP_PROFILE="api",
        DATABASE_URL="",
        GOOGLE_CLIENT_ID="client-id.apps.googleusercontent.com",
        **kwargs,
        **_API_SECRETS,
    )
    assert s.GOOGLE_CLIENT_ID


def test_prod_oauth_scraper_profile_not_affected():
    """El perfil scraper no expone login: el validator solo aplica al perfil api."""
    from config.settings import Settings

    s = Settings(
        ENV="prod",
        APP_PROFILE="scraper",
        DATABASE_URL="",
        GOOGLE_CLIENT_ID="client-id.apps.googleusercontent.com",
        **_API_SECRETS,
    )
    assert s.APP_PROFILE == "scraper"


def test_oauth_wildcard_domain_allows_any_email(monkeypatch):
    """OAUTH_ALLOWED_DOMAINS=* permite cualquier cuenta de forma deliberada."""
    from config import settings
    from shared.auth_core import oauth_email_allowed

    monkeypatch.setattr(settings, "OAUTH_ALLOWED_DOMAINS", "*", raising=False)
    monkeypatch.setattr(settings, "OAUTH_ALLOWED_EMAILS", "", raising=False)
    assert oauth_email_allowed("cualquiera@dominio-ajeno.example") is True


# ── API_THREADPOOL_TOKENS ────────────────────────────────────────────────────
# Al final del fichero a propósito: `.secrets.baseline` referencia por número de
# línea un literal de este módulo, así que insertar tests más arriba lo desplaza
# y obliga a regenerar un fichero que AGENTS.md §6 pone bajo gate humano.
def test_api_threadpool_tokens_default_is_24():
    """El default es el techo ampliado en #159, no el 4 que estuvo hardcodeado.

    Los 4 hilos originales acotaban la analítica pandas, pero castigaban por
    igual a las lecturas IO-bound. Ahora lo CPU-bound tiene su propio bulkhead
    (``API_CPU_BOUND_TOKENS``) y el pool general puede respirar.
    """
    from config.settings import Settings

    assert Settings().API_THREADPOOL_TOKENS == 24


def test_api_threadpool_tokens_override():
    from config.settings import Settings

    assert Settings(API_THREADPOOL_TOKENS=16).API_THREADPOOL_TOKENS == 16


def test_api_threadpool_tokens_zero_raises():
    from config.settings import Settings

    with pytest.raises(Exception, match="API_THREADPOOL_TOKENS"):
        Settings(API_THREADPOOL_TOKENS=0)
