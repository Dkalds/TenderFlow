"""Cotas de coste de la superficie anónima ``/publico`` (auditoría 2026-11, ruta 19).

Sin base de datos: el repositorio se sustituye por un doble que cuenta las
consultas, porque lo que se fija aquí es **cuándo se paga una consulta**, no lo
que devuelve (eso lo cubren ``test_routes_publico.py`` y
``test_publico_repository.py``, que sí usan Postgres).

- Los hubs se leen una vez por ventana, no en cada visita.
- Un slug de comunidad u órgano que el corpus no tiene devuelve la página vacía
  sin tocar ``listar`` ni ``contar`` (el slug se calcula en SQL sin índice).
- Un tramo de sitemap conserva su tope de 50.000 entradas (el contrato público).
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import publico

_HUB_CCAA = {"slug": "comunidad-de-madrid", "nombre": "Comunidad de Madrid", "total": 3}
_HUB_ORGANO = {"slug": "ayuntamiento-de-segovia", "nombre": "Ayuntamiento de Segovia", "total": 5}


class _RepoFalso:
    """Registra qué consultas se hicieron y con qué argumentos."""

    def __init__(self) -> None:
        self.llamadas: list[tuple[str, dict[str, Any]]] = []
        self.falla_hubs_organo = False

    def _anota(self, nombre: str, **kwargs: Any) -> None:
        self.llamadas.append((nombre, kwargs))

    def nombres(self) -> list[str]:
        return [nombre for nombre, _ in self.llamadas]

    def hubs_ccaa(self) -> list[dict[str, Any]]:
        self._anota("hubs_ccaa")
        return [_HUB_CCAA]

    def hubs_cpv(self) -> list[dict[str, Any]]:
        self._anota("hubs_cpv")
        return []

    def hubs_organo(self) -> list[dict[str, Any]]:
        self._anota("hubs_organo")
        if self.falla_hubs_organo:
            raise RuntimeError("base caída")
        return [_HUB_ORGANO]

    def slugs_ccaa(self) -> list[str]:
        self._anota("slugs_ccaa")
        # `ceuta` existe en el corpus pero no llega al umbral de los hubs.
        return ["comunidad-de-madrid", "ceuta"]

    def listar(self, **kwargs: Any) -> list[Any]:
        self._anota("listar", **kwargs)
        return []

    def contar(self, **kwargs: Any) -> int:
        self._anota("contar", **kwargs)
        return 0

    def pagina_de_sitemap(self, **kwargs: Any) -> list[Any]:
        self._anota("pagina_de_sitemap", **kwargs)
        return []


@pytest.fixture()
def repo(monkeypatch: pytest.MonkeyPatch) -> _RepoFalso:
    falso = _RepoFalso()
    monkeypatch.setattr(publico, "_repo", falso)
    # La caché de hubs consulta la señal de ingesta, que mira la base: aquí no hay.
    monkeypatch.setattr("services._data_cache.get_signal_timestamp", lambda: 0.0)
    publico.limpiar_cache_hubs()
    yield falso
    publico.limpiar_cache_hubs()


@pytest.fixture()
def cliente(repo: _RepoFalso) -> TestClient:
    app = FastAPI()
    app.include_router(publico.router, prefix="/api/v1")
    return TestClient(app)


def _listar(cliente: TestClient, query: str = "") -> Any:
    return cliente.get(f"/api/v1/publico/licitaciones?{query}")


def test_los_hubs_se_leen_una_vez_para_varias_visitas(
    cliente: TestClient, repo: _RepoFalso
) -> None:
    primera = cliente.get("/api/v1/publico/hubs").json()
    for _ in range(3):
        assert cliente.get("/api/v1/publico/hubs").json() == primera

    assert primera["ccaa"] == [_HUB_CCAA]
    assert primera["organo"] == [_HUB_ORGANO]
    assert repo.nombres().count("hubs_organo") == 1
    assert repo.nombres().count("hubs_ccaa") == 1


def test_un_organo_inventado_devuelve_pagina_vacia_sin_consultar(
    cliente: TestClient, repo: _RepoFalso
) -> None:
    respuesta = _listar(cliente, "organo=no-existe-este-organo&limit=7&offset=14")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert (cuerpo["total"], cuerpo["limit"], cuerpo["offset"], cuerpo["items"]) == (0, 7, 14, [])
    assert respuesta.headers["Cache-Control"], "tiene que seguir declarando caché"
    assert "listar" not in repo.nombres()
    assert "contar" not in repo.nombres()


def test_una_comunidad_inventada_devuelve_pagina_vacia_sin_consultar(
    cliente: TestClient, repo: _RepoFalso
) -> None:
    respuesta = _listar(cliente, "ccaa=comunidad-que-no-existe")

    assert respuesta.status_code == 200
    assert respuesta.json()["total"] == 0
    assert "listar" not in repo.nombres()
    assert "contar" not in repo.nombres()


def test_un_organo_con_hub_si_se_consulta(cliente: TestClient, repo: _RepoFalso) -> None:
    respuesta = _listar(cliente, "organo=ayuntamiento-de-segovia")

    assert respuesta.status_code == 200
    llamadas = dict(repo.llamadas)
    assert llamadas["listar"]["organo_slug"] == "ayuntamiento-de-segovia"
    assert llamadas["contar"]["organo_slug"] == "ayuntamiento-de-segovia"


def test_una_comunidad_bajo_el_umbral_de_los_hubs_sigue_teniendo_pagina(
    cliente: TestClient, repo: _RepoFalso
) -> None:
    """Su página existe (la enlaza la ficha) aunque no esté en el índice."""
    _listar(cliente, "ccaa=ceuta")

    assert "listar" in repo.nombres()
    assert dict(repo.llamadas)["listar"]["ccaa_slug"] == "ceuta"


def test_sin_slug_no_se_leen_los_hubs(cliente: TestClient, repo: _RepoFalso) -> None:
    """El listado de portada y el filtro por CPV no pagan la lectura de los hubs."""
    _listar(cliente)
    _listar(cliente, "cpv=72")

    assert repo.nombres() == ["listar", "contar", "listar", "contar"]


def test_si_los_hubs_no_se_pueden_leer_el_listado_se_consulta_como_antes(
    cliente: TestClient, repo: _RepoFalso
) -> None:
    repo.falla_hubs_organo = True

    respuesta = _listar(cliente, "organo=ayuntamiento-de-segovia")

    assert respuesta.status_code == 200
    assert "listar" in repo.nombres()


def test_si_la_lectura_de_los_hubs_falla_el_indice_es_un_503_y_no_se_reintenta_a_cada_visita(
    cliente: TestClient, repo: _RepoFalso
) -> None:
    """Unas listas vacías publicarían un corpus que se encogió; un 5xx, no."""
    repo.falla_hubs_organo = True

    primera = cliente.get("/api/v1/publico/hubs")
    segunda = cliente.get("/api/v1/publico/hubs")

    assert primera.status_code == segunda.status_code == 503
    assert repo.nombres().count("hubs_ccaa") == 1, "el fallo se retiene unos segundos"


def test_un_tramo_de_sitemap_conserva_su_tope_de_cincuenta_mil_entradas(
    cliente: TestClient, repo: _RepoFalso
) -> None:
    """Bajar el ``maximum`` de ``limit`` rompería el contrato público."""
    assert cliente.get("/api/v1/publico/sitemap/entradas?limit=50001").status_code == 422

    assert cliente.get("/api/v1/publico/sitemap/entradas?limit=50000").status_code == 200
    assert dict(repo.llamadas)["pagina_de_sitemap"]["tamano"] == 50_000


def test_el_sitemap_arma_su_respuesta_en_un_hilo() -> None:
    """``async def`` armaría y validaría hasta 50.000 modelos sobre el event loop."""
    assert not inspect.iscoroutinefunction(publico.entradas_sitemap)
