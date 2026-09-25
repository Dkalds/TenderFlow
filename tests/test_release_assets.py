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
        assert release_assets.fetch_release_by_tag(repo, "ml-models") is None
        assert release_assets.fetch_recent_releases(repo) == []
        assert release_assets.locate_release_asset(repo, "m.pkl") is None
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


# ── Localizar el asset entre Releases (2026-09) ─────────────────────────────
#
# Solo se miraba *latest*, y `release.yml` crea una *latest* nueva —sin assets
# de modelo— con cada tag `v*`: publicar software dejaba al scoring sin
# artefactos. Orden vigente: tag fijo `ml-models` → *latest* → recientes.

_API = "https://api.github.com/repos/Dkalds/TenderFlow/releases"
_URL_TAG = f"{_API}/tags/{release_assets.ML_MODELS_RELEASE_TAG}"
_URL_LATEST = f"{_API}/latest"
_URL_RECIENTES = f"{_API}?per_page=30"


def _json(datos: object) -> _FakeResponse:
    return _FakeResponse(body=json.dumps(datos).encode())


def _rel(
    release_id: int, tag: str, *assets: tuple[str, int], draft: bool = False
) -> dict[str, Any]:
    return {
        "id": release_id,
        "tag_name": tag,
        "draft": draft,
        "assets": [{"name": nombre, "id": asset_id} for nombre, asset_id in assets],
    }


class _GitHubFalso:
    """``pinned_https_request`` que responde por URL; lo no configurado es 404.

    Un valor ``Exception`` se lanza, como haría el transporte ante un fallo
    de red. Registra las URLs y los kwargs de cada petición.
    """

    def __init__(self, rutas: dict[str, object]) -> None:
        self.rutas = rutas
        self.urls: list[str] = []
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, _method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.urls.append(url)
        self.kwargs.append(kwargs)
        respuesta = self.rutas.get(url)
        if isinstance(respuesta, Exception):
            raise respuesta
        if respuesta is None:
            return _FakeResponse(status_code=404)
        return _json(respuesta)


def _localizar(rutas: dict[str, object], nombre: str) -> tuple[Any, _GitHubFalso]:
    github = _GitHubFalso(rutas)
    with patch.object(release_assets, "pinned_https_request", side_effect=github):
        encontrado = release_assets.locate_release_asset("Dkalds/TenderFlow", nombre, token="t")
    return encontrado, github


def test_la_release_de_tag_fijo_gana_y_no_se_pide_nada_mas() -> None:
    """Si está en `ml-models`, ni *latest* ni el listado llegan a pedirse."""
    encontrado, github = _localizar(
        {
            _URL_TAG: _rel(1, "ml-models", ("baja_model-3fa9c1d2e4b5.pkl", 11)),
            _URL_LATEST: _rel(2, "v2.0.0", ("baja_model-3fa9c1d2e4b5.pkl", 22)),
        },
        "baja_model-3fa9c1d2e4b5.pkl",
    )

    assert encontrado is not None
    assert encontrado.asset_id == 11
    assert encontrado.release["tag_name"] == "ml-models"
    assert github.urls == [_URL_TAG]


def test_sin_release_fija_todavia_cae_a_latest() -> None:
    """Hasta la primera publicación en `ml-models`, el tag responde 404."""
    encontrado, github = _localizar(
        {_URL_LATEST: _rel(2, "v0.0.0-model", ("sap_classifier.pkl", 7))},
        "sap_classifier.pkl",
    )

    assert encontrado is not None and encontrado.asset_id == 7
    assert github.urls == [_URL_TAG, _URL_LATEST]


def test_un_asset_viejo_se_encuentra_aunque_su_release_ya_no_sea_latest() -> None:
    """El caso de `release.yml`: una release de software pasa a *latest*.

    Es también la compatibilidad con las filas de nombre fijo: su
    ``baja_model.pkl`` se subió a lo que entonces era *latest* y se sigue
    encontrando entre las recientes.
    """
    software = _rel(3, "v1.5.0")
    encontrado, github = _localizar(
        {
            _URL_LATEST: software,
            _URL_RECIENTES: [software, _rel(2, "v0.0.0-model", ("baja_model.pkl", 5))],
        },
        "baja_model.pkl",
    )

    assert encontrado is not None
    assert encontrado.asset_id == 5
    assert encontrado.release["tag_name"] == "v0.0.0-model"
    assert github.urls == [_URL_TAG, _URL_LATEST, _URL_RECIENTES]


def test_si_no_esta_en_ninguna_devuelve_none() -> None:
    encontrado, github = _localizar(
        {
            _URL_TAG: _rel(1, "ml-models", ("retencion_model-aaaaaaaaaaaa.pkl", 1)),
            _URL_LATEST: _rel(2, "v2.0.0"),
            _URL_RECIENTES: [_rel(2, "v2.0.0"), _rel(1, "ml-models")],
        },
        "baja_model-3fa9c1d2e4b5.pkl",
    )

    assert encontrado is None
    # Todas las lecturas fueron a la API, con su allowlist y su token: el CDN
    # solo aparece en el salto de `download_asset`.
    assert github.urls == [_URL_TAG, _URL_LATEST, _URL_RECIENTES]
    assert all(kw["allowed_hosts"] == frozenset({"api.github.com"}) for kw in github.kwargs)
    assert all(kw["headers"]["Authorization"] == "Bearer t" for kw in github.kwargs)


def test_un_fallo_de_red_en_una_candidata_no_corta_la_busqueda() -> None:
    encontrado, _github = _localizar(
        {
            _URL_TAG: requests.ConnectionError("reset"),
            _URL_LATEST: _rel(2, "v0.0.0-model", ("baja_model.pkl", 5)),
        },
        "baja_model.pkl",
    )

    assert encontrado is not None and encontrado.asset_id == 5


def test_los_borradores_no_cuentan_como_publicados() -> None:
    encontrado, _github = _localizar(
        {
            _URL_RECIENTES: [
                _rel(4, "v9.9.9", ("baja_model.pkl", 99), draft=True),
                _rel(2, "v0.0.0-model", ("baja_model.pkl", 5)),
            ],
        },
        "baja_model.pkl",
    )

    assert encontrado is not None and encontrado.asset_id == 5


@pytest.mark.parametrize("tag", ["../latest", "a/b", "ml-models?per_page=1", "", "..", "%2e%2e"])
def test_un_tag_invalido_no_sale_a_la_red(tag: str) -> None:
    """El tag va en la ruta de la URL: no puede inyectar segmentos ni query."""
    with patch.object(release_assets, "pinned_https_request") as request:
        assert release_assets.fetch_release_by_tag("Dkalds/TenderFlow", tag) is None

    request.assert_not_called()


def test_las_recientes_son_una_pagina_y_se_descarta_lo_que_no_es_release() -> None:
    github = _GitHubFalso({f"{_API}?per_page=100": [{"id": 1}, "basura", 3]})
    with patch.object(release_assets, "pinned_https_request", side_effect=github):
        # GitHub no sirve más de 100 por página: pedir más no puede romper la URL.
        recientes = release_assets.fetch_recent_releases("Dkalds/TenderFlow", limit=500)

    assert recientes == [{"id": 1}]
    assert github.urls == [f"{_API}?per_page=100"]
