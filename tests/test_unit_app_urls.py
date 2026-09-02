"""El origen del frontend se deduce de lo ya configurado, nunca se inventa."""

from __future__ import annotations

import pytest

from services import app_urls


@pytest.fixture()
def sin_origenes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_urls.settings, "CORS_ALLOWED_ORIGINS", "", raising=False)
    monkeypatch.setattr(app_urls.settings, "OAUTH_REDIRECT_URI", "", raising=False)


def test_prefiere_el_primer_origen_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        app_urls.settings,
        "CORS_ALLOWED_ORIGINS",
        " https://app.example/ , https://otro.example",
        raising=False,
    )
    assert app_urls.frontend_base_url() == "https://app.example"
    assert app_urls.url_absoluta("mi-watchlist") == "https://app.example/mi-watchlist"
    assert (
        app_urls.url_de_detalle("PA-S 2026/1") == "https://app.example/detalle?lic=PA-S%202026%2F1"
    )
    assert app_urls.url_de_oportunidad(42) == "https://app.example/oportunidades/42"


def test_cae_al_origen_del_callback_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_urls.settings, "CORS_ALLOWED_ORIGINS", "", raising=False)
    monkeypatch.setattr(
        app_urls.settings,
        "OAUTH_REDIRECT_URI",
        "https://api.example/api/v1/auth/oauth/google/callback",
        raising=False,
    )
    assert app_urls.frontend_base_url() == "https://api.example"


def test_sin_configuracion_no_hay_enlace(sin_origenes: None) -> None:
    assert app_urls.frontend_base_url() is None
    assert app_urls.url_absoluta("/login") is None
    assert app_urls.url_de_oportunidad(1) is None
