"""Export del tablero (C6.7) y re-entrega de webhooks (C2.4), por sus rutas.

Dos rutas pequeñas que deciden cosas que no se ven en el SQL y que el plan
argumenta explícitamente: por qué el tablero **no** se exporta en PDF, y por qué
reencolar una entrega responde 202 y no 200.

La segunda es la que se equivoca fácil: 404 y 409 dicen cosas distintas —«ese
webhook no existe» frente a «esa entrega ya se completó»— y confundirlas manda
al operador a buscar un problema que no hay.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient


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


class TestExportDelTablero:
    RUTA = "/api/v1/exports/download"

    def test_el_tablero_no_se_exporta_en_pdf(self, client: TestClient) -> None:
        """Su maquetación es una tabla por expediente del corpus público, y el
        tablero es otra colección con otras columnas: reutilizarla daría un
        documento con las cabeceras de una cosa y los datos de otra."""
        respuesta = client.get(self.RUTA, params={"recurso": "pursuits", "format": "pdf"})
        assert respuesta.status_code == 400
        assert "CSV o Excel" in respuesta.json()["detail"]

    def test_el_csv_sale_como_adjunto_con_nombre_de_oportunidades(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.exports as svc

        monkeypatch.setattr(
            svc, "render_pursuits_export", lambda *a, **k: (b"id,titulo\n1,Uno\n", "text/csv", 1)
        )

        respuesta = client.get(self.RUTA, params={"recurso": "pursuits", "format": "csv"})
        assert respuesta.status_code == 200
        assert respuesta.content == b"id,titulo\n1,Uno\n"
        assert "oportunidades_" in respuesta.headers["content-disposition"]

    def test_los_filtros_del_tablero_llegan_al_servicio(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.exports as svc

        pedidos: list[dict[str, Any]] = []

        def _render(user_id: int, **kwargs: Any) -> tuple[bytes, str, int]:
            pedidos.append({"user_id": user_id, **kwargs})
            return b"", "text/csv", 0

        monkeypatch.setattr(svc, "render_pursuits_export", _render)

        client.get(
            self.RUTA,
            params={
                "recurso": "pursuits",
                "format": "csv",
                "pursuit_status": "ganada",
                "responsible_user_id": 9,
                "limit": 25,
            },
        )
        assert pedidos[0]["status"] == "ganada"
        assert pedidos[0]["responsible_user_id"] == 9
        assert pedidos[0]["limit"] == 25

    def test_sin_acceso_a_la_organizacion_es_403(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.exports as svc
        from services.organizations import OrganizationAccessError

        def _explota(*a: Any, **k: Any) -> Any:
            raise OrganizationAccessError("no sos miembro")

        monkeypatch.setattr(svc, "render_pursuits_export", _explota)

        respuesta = client.get(self.RUTA, params={"recurso": "pursuits", "format": "csv"})
        assert respuesta.status_code == 403


class TestReentregaDeWebhook:
    RUTA = "/api/v1/webhooks/1/deliveries/2/redeliver"

    def test_un_webhook_que_no_existe_es_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import api.routes.webhooks as rutas

        class _Repo:
            def get_by_id(self, wid: int) -> None:
                return None

        monkeypatch.setattr(rutas, "_repo", _Repo())

        assert client.post(self.RUTA).status_code == 404

    def test_una_entrega_ya_completada_es_409_y_no_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Decirle «no existe» al operador le haría buscar un problema que no
        hay: la entrega existe, y está `delivered`."""
        import api.routes.webhooks as rutas
        import db.repositories.webhooks as repo_mod

        class _Repo:
            def get_by_id(self, wid: int) -> dict[str, Any]:
                return {"id": wid}

        monkeypatch.setattr(rutas, "_repo", _Repo())
        monkeypatch.setattr(repo_mod, "encolar_reintento", lambda did, *, ahora: False)

        assert client.post(self.RUTA).status_code == 409

    def test_reencolar_responde_202_y_no_reenvia_en_la_request(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Abrir una conexión a un endpoint caído dejaría al operador esperando
        el timeout, y el reintento tiene que sobrevivir a que cierre la pestaña."""
        import api.routes.webhooks as rutas
        import db.repositories.webhooks as repo_mod

        class _Repo:
            def get_by_id(self, wid: int) -> dict[str, Any]:
                return {"id": wid}

        encoladas: list[int] = []
        monkeypatch.setattr(rutas, "_repo", _Repo())
        monkeypatch.setattr(
            repo_mod,
            "encolar_reintento",
            lambda did, *, ahora: encoladas.append(did) or True,
        )

        respuesta = client.post(self.RUTA)
        assert respuesta.status_code == 202
        assert respuesta.json() == {"status": "encolada"}
        assert encoladas == [2]
