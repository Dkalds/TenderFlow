"""El diccionario de tecnologías como dato, por sus rutas (C5.6, D28).

Antes de C5.6 añadir una keyword era un despliegue (hecho 22). Ahora manda la
tabla, y lo que hace que eso sea gobernable —y no solo editable— vive entero en
estas rutas: el `fuente` que distingue «configurado» de «sin sembrar», el
impacto medido **antes** de escribir, y el `filter_version` de antes y después
en la auditoría.

Ninguna de esas tres cosas la comprueba el SQL, y ninguna tenía test.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

RUTA = "/api/v1/tecnologias/keywords"


@pytest.fixture
def client() -> Iterator[TestClient]:
    from api.app import app
    from api.routes.dual_auth import require_admin, require_any_auth

    ctx = {"user_id": 5, "scopes": ["*"], "is_admin": True}
    app.dependency_overrides[require_any_auth] = lambda: ctx
    app.dependency_overrides[require_admin] = lambda: ctx
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.clear()


class _RepoDoble:
    def __init__(
        self,
        *,
        filas: list[dict[str, Any]] | None = None,
        impacto: dict[str, Any] | None = None,
        desactiva: bool = True,
    ) -> None:
        self._filas = filas if filas is not None else []
        self._impacto = impacto or {"keyword": "cloud", "dias": 90, "expedientes_nuevos": 4200}
        self._desactiva = desactiva
        self.upserts: list[dict[str, Any]] = []
        self.desactivados: list[dict[str, Any]] = []

    def listar(self, *, incluir_inactivas: bool = False) -> list[dict[str, Any]]:
        return self._filas

    def impacto(self, keyword: str, *, dias: int = 90) -> dict[str, Any]:
        return {**self._impacto, "keyword": keyword, "dias": dias}

    def upsert(self, **kwargs: Any) -> None:
        self.upserts.append(kwargs)

    def desactivar(self, **kwargs: Any) -> bool:
        self.desactivados.append(kwargs)
        return self._desactiva


def _montar(
    monkeypatch: pytest.MonkeyPatch,
    repo: _RepoDoble,
    *,
    versiones: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Sustituye repositorio, diccionario y auditoría. Devuelve los eventos."""
    import api.routes.tecnologias_keywords as rutas

    cola = list(versiones or ["v1", "v2"])
    eventos: list[dict[str, Any]] = []

    def _vigente(forzar: bool = False) -> tuple[dict[str, list[str]], str]:
        version = cola.pop(0) if len(cola) > 1 else cola[0]
        return {"cloud": ["cloud", "aws"]}, version

    monkeypatch.setattr(rutas, "_repo", repo)
    monkeypatch.setattr(rutas, "vigente", _vigente)
    monkeypatch.setattr(rutas, "invalidar", lambda: None)
    monkeypatch.setattr(rutas, "log_event", lambda **kw: eventos.append(kw))
    return eventos


class TestLectura:
    def test_una_tabla_vacia_se_declara_como_semilla(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sin ese campo, un entorno sin sembrar se ve idéntico a uno
        configurado y nadie sabe que sus ediciones no se aplican."""
        _montar(monkeypatch, _RepoDoble(filas=[]))

        assert client.get(RUTA).json()["fuente"] == "semilla"

    def test_con_filas_manda_la_tabla(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _montar(
            monkeypatch,
            _RepoDoble(
                filas=[
                    {
                        "tecnologia": "cloud",
                        "keyword": "aws",
                        "activa": True,
                        "origen": "manual",
                        "updated_at": "2026-09-08T10:00:00Z",
                    }
                ]
            ),
        )

        cuerpo = client.get(RUTA).json()
        assert cuerpo["fuente"] == "tabla"
        assert cuerpo["items"][0]["keyword"] == "aws"

    def test_el_recuento_sale_del_diccionario_vigente_y_no_de_las_filas(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Es lo que de verdad gobierna el filtro."""
        _montar(monkeypatch, _RepoDoble(filas=[]))

        cuerpo = client.get(RUTA).json()
        assert cuerpo["tecnologias"] == 1
        assert cuerpo["keywords"] == 2


class TestImpacto:
    def test_el_impacto_cuenta_lo_que_la_keyword_anadiria(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """«SAP» aparece en miles de expedientes que ya están dentro: ese número
        no ayudaría a decidir nada."""
        _montar(monkeypatch, _RepoDoble())

        cuerpo = client.get(f"{RUTA}/impacto", params={"keyword": "cloud", "dias": 30}).json()
        assert cuerpo["expedientes_nuevos"] == 4200
        assert cuerpo["dias"] == 30

    @pytest.mark.parametrize("params", [{"keyword": "a"}, {"keyword": "cloud", "dias": 0}])
    def test_el_contrato_acota_la_consulta(
        self, client: TestClient, params: dict[str, Any]
    ) -> None:
        assert client.get(f"{RUTA}/impacto", params=params).status_code == 422


class TestEscritura:
    def test_anadir_audita_el_impacto_y_las_dos_versiones(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """«Se añadió `cloud` y trajo 4.200 expedientes» explica por sí solo una
        degradación posterior del radar."""
        repo = _RepoDoble()
        eventos = _montar(monkeypatch, repo, versiones=["antes", "despues"])

        assert client.put(RUTA, json={"tecnologia": "cloud", "keyword": "aws"}).status_code == 200
        assert repo.upserts[0]["keyword"] == "aws"
        detalle = eventos[0]["detail"]
        assert detalle["expedientes_nuevos_estimados"] == 4200
        assert detalle["filter_version_antes"] == "antes"
        assert detalle["filter_version_despues"] == "despues"

    def test_el_impacto_se_mide_antes_de_escribir(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Después, la siguiente ingesta ya habría asignado tecnología y el
        número dejaría de ser reconstruible."""
        repo = _RepoDoble()
        orden: list[str] = []
        _montar(monkeypatch, repo, versiones=["antes", "despues"])

        impacto_original = repo.impacto

        def _impacto(keyword: str, *, dias: int = 90) -> dict[str, Any]:
            orden.append("impacto")
            return impacto_original(keyword, dias=dias)

        def _upsert(**kwargs: Any) -> None:
            orden.append("upsert")

        monkeypatch.setattr(repo, "impacto", _impacto)
        monkeypatch.setattr(repo, "upsert", _upsert)

        client.put(RUTA, json={"tecnologia": "cloud", "keyword": "aws"})
        assert orden == ["impacto", "upsert"]

    def test_retirar_desactiva_y_no_borra(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La decisión tiene que quedar revisable."""
        repo = _RepoDoble()
        eventos = _montar(monkeypatch, repo)

        respuesta = client.delete(RUTA, params={"tecnologia": "cloud", "keyword": "aws"})
        assert respuesta.status_code == 200
        assert repo.desactivados[0] == {"tecnologia": "cloud", "keyword": "aws"}
        assert eventos[0]["event_type"] == "tecnologias_keyword.removed"

    def test_retirar_lo_que_no_esta_activo_es_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        eventos = _montar(monkeypatch, _RepoDoble(desactiva=False))

        respuesta = client.delete(RUTA, params={"tecnologia": "cloud", "keyword": "aws"})
        assert respuesta.status_code == 404
        assert eventos == []

    def test_resembrar_es_idempotente_y_queda_contado(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import api.routes.tecnologias_keywords as rutas

        eventos = _montar(monkeypatch, _RepoDoble())
        monkeypatch.setattr(rutas, "sembrar_desde_semilla", lambda: 7)

        assert client.post(f"{RUTA}/sembrar").json() == {"status": "ok"}
        assert eventos[0]["detail"]["insertadas"] == 7
