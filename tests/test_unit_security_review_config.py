"""Tests del hardening de configuración del security review (stream B).

Cubren tres arreglos que solo se sostienen desde ``config/settings.py``:

- ``FORWARDED_ALLOW_IPS`` como campo real (antes era config muerta: ``model_config``
  usa ``extra="ignore"``, así que la variable de entorno se descartaba en silencio
  y el ``getattr`` de ``api/middleware.py`` caía siempre al default).
- El rechazo del comodín ``*`` en prod/staging cuando el proceso sirve HTTP.
- Los defaults del presupuesto LLM (``enforce`` y el tope por usuario).

Los tests de middleware existentes no detectaban el campo muerto porque mockean
``settings`` con un ``Mock``, y a un ``Mock`` cualquier atributo le existe. Aquí
se construye ``Settings`` de verdad, sin BD ni red.
"""

from __future__ import annotations

import warnings

import pytest

# Secretos mínimos para que los validators de prod anteriores al de
# FORWARDED_ALLOW_IPS no aborten antes de llegar a él.
_PROD_SECRETS = {
    "SIGNING_KEY": "k" * 32,
    "API_HMAC_SECRET": "h" * 32,
    "AUDIT_HMAC_KEY": "z" * 32,
    "REDIS_URL": "redis://localhost:6379/0",
    "REDIS_PASSWORD": "p" * 32,
}


def _prod_settings(**overrides):
    """Settings de prod/staging con perfil api y los secretos HTTP puestos.

    ``DATABASE_URL`` y ``GF_SECURITY_ADMIN_PASSWORD`` van explícitos para no
    heredar valores reales de un ``.env`` local (ver ``test_config_settings.py``).
    """
    from config.settings import Settings

    kwargs = {
        "ENV": "prod",
        "APP_PROFILE": "api",
        "DATABASE_URL": "",
        "GOOGLE_CLIENT_ID": "",
        "GF_SECURITY_ADMIN_PASSWORD": "",
        **_PROD_SECRETS,
        **overrides,
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return Settings(**kwargs)


# ---------------------------------------------------------------------------
# FORWARDED_ALLOW_IPS como campo declarado
# ---------------------------------------------------------------------------


def test_forwarded_allow_ips_es_campo_declarado():
    """Regresión: si alguien vuelve a quitar el campo, la defensa deja de ser
    configurable sin que nada falle (extra="ignore" descarta el env var)."""
    from config.settings import Settings

    assert "FORWARDED_ALLOW_IPS" in Settings.model_fields


def test_forwarded_allow_ips_default_es_loopback():
    from config.settings import Settings

    assert Settings.model_fields["FORWARDED_ALLOW_IPS"].default == "127.0.0.1"


def test_forwarded_allow_ips_llega_desde_el_entorno(monkeypatch):
    """El valor del entorno debe verse en la instancia, no quedarse en el aire."""
    from config.settings import Settings

    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.0/8,192.168.1.7")
    s = Settings(ENV="dev", DATABASE_URL="")
    assert s.FORWARDED_ALLOW_IPS == "10.0.0.0/8,192.168.1.7"


# ---------------------------------------------------------------------------
# Validator: comodín y vacío prohibidos en prod/staging con perfil api
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["prod", "staging"])
@pytest.mark.parametrize("valor", ["*", " * ", "10.0.0.1,*"])
def test_forwarded_allow_ips_comodin_rechazado_sirviendo_http(env, valor):
    """Con "*" el cliente elige su propia IP vía X-Forwarded-For."""
    with pytest.raises(Exception, match="FORWARDED_ALLOW_IPS"):
        _prod_settings(ENV=env, FORWARDED_ALLOW_IPS=valor)


@pytest.mark.parametrize("valor", ["0.0.0.0/0", "::/0", "10.0.0.1, 0.0.0.0/0"])
def test_forwarded_allow_ips_rango_universal_rechazado(valor):
    """Un CIDR que abarca todo el espacio equivale al comodín.

    uvicorn 0.46 (``_TrustedHosts``) y ``api.middleware._trusted_client_ip``
    resuelven rangos, así que ``0.0.0.0/0`` hace que cualquier peer sea un
    proxy de confianza: mismo agujero que ``*``, escrito distinto.
    """
    with pytest.raises(Exception, match="FORWARDED_ALLOW_IPS"):
        _prod_settings(FORWARDED_ALLOW_IPS=valor)


@pytest.mark.parametrize("valor", ["", "   ", ","])
def test_forwarded_allow_ips_vacio_rechazado_sirviendo_http(valor):
    """Vacío es el mismo agujero por la vía contraria: campo sin configurar
    en un despliegue que sí está detrás de un proxy."""
    with pytest.raises(Exception, match="FORWARDED_ALLOW_IPS"):
        _prod_settings(FORWARDED_ALLOW_IPS=valor)


def test_forwarded_allow_ips_rango_concreto_aceptado_en_prod():
    s = _prod_settings(FORWARDED_ALLOW_IPS="10.0.0.0/8")
    assert s.FORWARDED_ALLOW_IPS == "10.0.0.0/8"


@pytest.mark.parametrize("perfil", ["worker", "scraper"])
def test_forwarded_allow_ips_no_aplica_a_perfiles_sin_http(perfil):
    """El scraper y los workers no exponen la API: no hay cabecera que confiar."""
    s = _prod_settings(APP_PROFILE=perfil, FORWARDED_ALLOW_IPS="*")
    assert s.FORWARDED_ALLOW_IPS == "*"


def test_forwarded_allow_ips_comodin_permitido_en_dev():
    """En dev el proxy suele ser el propio docker-compose y no hay datos reales."""
    from config.settings import Settings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        s = Settings(ENV="dev", APP_PROFILE="api", DATABASE_URL="", FORWARDED_ALLOW_IPS="*")
    assert s.FORWARDED_ALLOW_IPS == "*"


# ---------------------------------------------------------------------------
# Presupuesto LLM
# ---------------------------------------------------------------------------

# Se comprueba el default declarado en el modelo, no el de una instancia: un
# env var o un .env local sobrescribirían la instancia y el test dejaría de
# medir lo que dice medir.


def test_llm_budget_mode_default_es_enforce():
    """En monitor los topes no cortan nada: son un indicador, no un límite."""
    from config.settings import Settings

    assert Settings.model_fields["LLM_BUDGET_MODE"].default == "enforce"


def test_llm_budget_usd_daily_per_user_declarado():
    """Contrato con llm/budget.py: segunda dimensión del presupuesto."""
    from config.settings import Settings

    campo = Settings.model_fields["LLM_BUDGET_USD_DAILY_PER_USER"]
    assert (campo.annotation, campo.default) == (float, 1.0)
