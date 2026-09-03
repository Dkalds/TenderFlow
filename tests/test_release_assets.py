"""Tests de ``shared/release_assets.py`` — el salto 302 hacia el CDN de assets.

El bug que cubre esta suite estuvo vivo del 2026-07-27 al 2026-09-03: el
endpoint de descarga de assets de GitHub responde siempre 302 y el transporte
pinned rechaza cualquier redirección, así que ``ensure_downloaded`` no bajó el
modelo ni una sola vez y ``ml_scoring``/``ml_tecnologias`` salían ``no_model``
en producción.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
import requests

from shared import release_assets

_CDN = "https://release-assets.githubusercontent.com/repos/1/2?token=abc"


class _FakeResponse:
    """Doble de ``PinnedHttpsResponse`` con la superficie que se usa aquí."""

    def __init__(
        self,
        status_code: int = 200,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body

    def raise_for_status(self) -> None:
        # Misma regla que el transporte real: todo >= 300 es un error.
        if self.status_code >= 300:
            raise requests.HTTPError(f"Pinned HTTPS response status {self.status_code}")

    def iter_content(self, chunk_size: int = 8192) -> Any:
        yield self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _release(assets: list[dict[str, Any]]) -> _FakeResponse:
    return _FakeResponse(body=json.dumps({"tag_name": "v1", "assets": assets}).encode())


def test_download_asset_sigue_el_302_hasta_el_cdn(tmp_path) -> None:
    """El artefacto acaba en disco pese a que la API responde 302."""
    dest = tmp_path / "sap_classifier.pkl"
    respuestas = [
        _FakeResponse(status_code=302, headers={"Location": _CDN}),
        _FakeResponse(body=b"modelo"),
    ]
    with patch.object(release_assets, "pinned_https_request", side_effect=respuestas) as request:
        assert release_assets.download_asset("Dkalds/TenderFlow", 42, dest, token="t") is True

    assert dest.read_bytes() == b"modelo"
    assert request.call_count == 2


def test_el_segundo_salto_va_al_cdn_sin_credenciales(tmp_path) -> None:
    """El ``Location`` es una URL prefirmada: reenviar el token lo filtraría."""
    dest = tmp_path / "m.pkl"
    respuestas = [
        _FakeResponse(status_code=302, headers={"Location": _CDN}),
        _FakeResponse(body=b"x"),
    ]
    with patch.object(release_assets, "pinned_https_request", side_effect=respuestas) as request:
        release_assets.download_asset("Dkalds/TenderFlow", 42, dest, token="secreto")

    primera, segunda = request.call_args_list
    assert primera.kwargs["allowed_hosts"] == frozenset({"api.github.com"})
    assert primera.kwargs["headers"]["Authorization"] == "Bearer secreto"

    assert segunda.args[1] == _CDN
    assert "Authorization" not in segunda.kwargs["headers"]
    assert "release-assets.githubusercontent.com" in segunda.kwargs["allowed_hosts"]
    assert "api.github.com" not in segunda.kwargs["allowed_hosts"]


def test_no_se_encadena_un_segundo_redirect(tmp_path) -> None:
    """Un salto y solo uno: encadenarlos es lo que este módulo evita."""
    dest = tmp_path / "m.pkl"
    respuestas = [
        _FakeResponse(status_code=302, headers={"Location": _CDN}),
        _FakeResponse(status_code=302, headers={"Location": "https://evil.example/x"}),
    ]
    with patch.object(release_assets, "pinned_https_request", side_effect=respuestas):
        assert release_assets.download_asset("Dkalds/TenderFlow", 42, dest) is False

    assert not dest.exists()


def test_redirect_sin_location_falla_sin_dejar_fichero(tmp_path) -> None:
    dest = tmp_path / "m.pkl"
    respuestas = [_FakeResponse(status_code=302)]
    with patch.object(release_assets, "pinned_https_request", side_effect=respuestas):
        assert release_assets.download_asset("Dkalds/TenderFlow", 42, dest) is False

    assert not dest.exists()


def test_descarga_parcial_no_deja_fichero_a_medias(tmp_path) -> None:
    """``is_available()`` es un ``Path.exists()``: un parcial se daría por bueno."""
    dest = tmp_path / "m.pkl"

    class _Rota(_FakeResponse):
        def iter_content(self, chunk_size: int = 8192) -> Any:
            yield b"mitad"
            raise OSError("conexión cortada")

    with patch.object(release_assets, "pinned_https_request", side_effect=[_Rota()]):
        assert release_assets.download_asset("Dkalds/TenderFlow", 42, dest) is False

    assert not dest.exists()


def test_respuesta_200_directa_tambien_vale(tmp_path) -> None:
    """Si algún día GitHub deja de redirigir, el camino corto sigue sirviendo."""
    dest = tmp_path / "m.pkl"
    with patch.object(
        release_assets, "pinned_https_request", side_effect=[_FakeResponse(body=b"m")]
    ):
        assert release_assets.download_asset("Dkalds/TenderFlow", 42, dest) is True

    assert dest.read_bytes() == b"m"


@pytest.mark.parametrize(
    "repo",
    ["Dkalds/TenderFlow?redirect=https://internal.example", "Dkalds/Tender/Flow", "sin-barra"],
)
def test_repositorio_invalido_no_sale_a_la_red(repo: str, tmp_path) -> None:
    """El repo no puede inyectar rutas ni query en la URL de la GitHub API."""
    with patch.object(release_assets, "pinned_https_request") as request:
        assert release_assets.fetch_latest_release(repo) is None
        assert release_assets.download_asset(repo, 42, tmp_path / "m.pkl") is False

    request.assert_not_called()


def test_fetch_latest_release_devuelve_el_json() -> None:
    with patch.object(
        release_assets,
        "pinned_https_request",
        side_effect=[_release([{"name": "sap_classifier.pkl", "id": 7}])],
    ):
        release = release_assets.fetch_latest_release("Dkalds/TenderFlow")

    assert release is not None
    assert release_assets.find_asset_id(release, "sap_classifier.pkl") == 7


def test_find_asset_id_devuelve_none_si_no_esta() -> None:
    assert (
        release_assets.find_asset_id({"assets": [{"name": "otro.pkl", "id": 1}]}, "x.pkl") is None
    )


def test_download_checksum_sidecar_usa_el_nombre_co_ubicado(tmp_path) -> None:
    """``<modelo>.pkl`` ⇒ ``<modelo>.sha256``, que es lo que busca load()."""
    release = {"tag_name": "v1", "assets": [{"name": "tech_classifier.sha256", "id": 9}]}
    target = tmp_path / "tech_classifier.pkl"
    with patch.object(
        release_assets, "pinned_https_request", side_effect=[_FakeResponse(body=b"deadbeef")]
    ):
        assert (
            release_assets.download_checksum_sidecar("Dkalds/TenderFlow", release, target) is True
        )

    assert (tmp_path / "tech_classifier.sha256").read_bytes() == b"deadbeef"
