"""Validadores de ``config.settings`` que endurecen CORS y Redis en prod/staging.

Se construye ``Settings`` con ``model_construct`` (sin pasar por la validación
completa de prod, que exige media docena de secretos) y se invoca solo el
validador que se prueba.
"""

from __future__ import annotations

import warnings

import pytest

from config.settings import Settings, _origen_cors_seguro, _redis_publico_sin_tls


def _api(**campos: object) -> Settings:
    return Settings.model_construct(ENV="prod", APP_PROFILE="api", **campos)


@pytest.mark.parametrize(
    "origen",
    ["https://app.example.com", "https://app.example.com:8443", "http://localhost:3000"],
)
def test_origen_cors_admitido(origen: str) -> None:
    assert _origen_cors_seguro(origen)


@pytest.mark.parametrize(
    "origen",
    ["*", "http://app.example.com", "app.example.com", "ftp://app.example.com", "https://"],
)
def test_origen_cors_rechazado(origen: str) -> None:
    assert not _origen_cors_seguro(origen)


@pytest.mark.parametrize("entorno", ["prod", "staging"])
@pytest.mark.parametrize(
    "valor", ["*", "https://app.example.com, *", "http://app.example.com", "https://a.example,x"]
)
def test_cors_con_comodin_o_sin_https_aborta_en_prod_y_staging(entorno: str, valor: str) -> None:
    ajustes = Settings.model_construct(ENV=entorno, APP_PROFILE="api", CORS_ALLOWED_ORIGINS=valor)
    with pytest.raises(ValueError, match="CORS_ALLOWED_ORIGINS"):
        ajustes._validate_prod_cors_origins()


def test_cors_https_y_loopback_pasan_en_prod() -> None:
    ajustes = _api(CORS_ALLOWED_ORIGINS="https://app.example.com, http://localhost:3000,")
    assert ajustes._validate_prod_cors_origins() is ajustes


def test_cors_vacio_en_prod_solo_avisa() -> None:
    with pytest.warns(UserWarning, match="CORS_ALLOWED_ORIGINS está vacío"):
        _api(CORS_ALLOWED_ORIGINS="")._validate_prod_cors_origins()


@pytest.mark.parametrize(
    ("perfil", "entorno"), [("worker", "prod"), ("scraper", "prod"), ("api", "dev")]
)
def test_cors_solo_se_valida_si_el_proceso_sirve_http_con_datos_de_prod(
    perfil: str, entorno: str
) -> None:
    ajustes = Settings.model_construct(ENV=entorno, APP_PROFILE=perfil, CORS_ALLOWED_ORIGINS="*")
    assert ajustes._validate_prod_cors_origins() is ajustes


@pytest.mark.parametrize(
    ("url", "esperado"),
    [
        ("redis://cache.example.com:6379/0", True),
        ("redis://:pw@8.8.8.8:6379", True),
        ("rediss://cache.example.com:6380", False),
        ("redis://localhost:6379", False),
        ("redis://127.0.0.1:6379", False),
        ("redis://10.0.0.5:6379", False),
        ("redis://red-abc123:6379", False),  # red privada de la plataforma
        ("", False),
    ],
)
def test_redis_publico_sin_tls(url: str, esperado: bool) -> None:
    assert _redis_publico_sin_tls(url) is esperado


def test_redis_sin_tls_a_host_publico_avisa_en_prod() -> None:
    from pydantic import SecretStr

    ajustes = _api(REDIS_URL="redis://cache.example.com:6379", REDIS_PASSWORD=SecretStr("p" * 32))
    with pytest.warns(UserWarning, match="rediss://"):
        ajustes._validate_prod_redis()


def test_redis_con_tls_no_avisa() -> None:
    from pydantic import SecretStr

    ajustes = _api(REDIS_URL="rediss://cache.example.com:6380", REDIS_PASSWORD=SecretStr("p" * 32))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ajustes._validate_prod_redis()
