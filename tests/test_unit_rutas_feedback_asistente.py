"""El voto del asistente, por sus rutas (C5.4).

Hasta C5.4 el voto del chat moría como evento de telemetría (hecho 21). La ruta
que lo persiste toma tres decisiones que no están en el SQL y que ningún test
tocaba:

- la pregunta viaja **en claro** para poder hashearla en el servidor, porque
  hashearla en el cliente dejaría la sal en el navegador;
- el texto solo se conserva con opt-in explícito;
- y un fallo al escribir la fila responde **201 con `registrado: false`**, no un
  500: quien vota nos está haciendo un favor, y devolverle un error convierte su
  cortesía en un problema en su pantalla.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

RUTA = "/api/v1/feedback/asistente"


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


def _voto(**extra: Any) -> dict[str, Any]:
    return {"pregunta": "¿Qué plazo tiene?", "modo": "pregunta", "voto": "no", **extra}


class TestRegistrarVoto:
    def test_un_voto_se_persiste_y_responde_201(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import db.repositories.asistente_feedback as repo

        monkeypatch.setattr(repo, "registrar", lambda **kw: 42)

        respuesta = client.post(RUTA, json=_voto())
        assert respuesta.status_code == 201
        assert respuesta.json() == {"registrado": True}

    def test_si_la_fila_no_se_escribe_sigue_siendo_201(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Devolver un 500 por un fallo de nuestra tabla convertiría la cortesía
        de quien vota en un error en su pantalla."""
        import db.repositories.asistente_feedback as repo

        monkeypatch.setattr(repo, "registrar", lambda **kw: None)

        respuesta = client.post(RUTA, json=_voto())
        assert respuesta.status_code == 201
        assert respuesta.json() == {"registrado": False}

    def test_el_texto_solo_se_conserva_con_opt_in(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import db.repositories.asistente_feedback as repo

        pedidos: list[dict[str, Any]] = []
        monkeypatch.setattr(repo, "registrar", lambda **kw: pedidos.append(kw) or 1)

        client.post(RUTA, json=_voto())
        client.post(RUTA, json=_voto(guardar_texto=True))

        assert pedidos[0]["texto_opt_in"] is False
        assert pedidos[1]["texto_opt_in"] is True

    def test_la_pregunta_llega_en_claro_para_hashearla_en_el_servidor(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Hashearla en el cliente dejaría la sal en el navegador, que es lo
        mismo que no tenerla."""
        import db.repositories.asistente_feedback as repo

        pedidos: list[dict[str, Any]] = []
        monkeypatch.setattr(repo, "registrar", lambda **kw: pedidos.append(kw) or 1)

        client.post(RUTA, json=_voto())
        assert pedidos[0]["pregunta"] == "¿Qué plazo tiene?"

    def test_el_voto_se_atribuye_a_quien_lo_emite(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import db.repositories.asistente_feedback as repo

        pedidos: list[dict[str, Any]] = []
        monkeypatch.setattr(repo, "registrar", lambda **kw: pedidos.append(kw) or 1)

        client.post(RUTA, json=_voto())
        assert pedidos[0]["user_id"] == 5

    @pytest.mark.parametrize(
        "invalido",
        [{"modo": "adivinanza"}, {"voto": "quizas"}, {"pregunta": ""}],
    )
    def test_el_vocabulario_es_cerrado(self, client: TestClient, invalido: dict[str, Any]) -> None:
        assert client.post(RUTA, json=_voto(**invalido)).status_code == 422


class TestPanelDeActiveLearning:
    def test_el_resumen_publica_ratio_y_poblacion(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El ratio se deriva de `utiles` y `total`, y ambos viajan: un 80 %
        sobre diez votos y un 80 % sobre mil no son lo mismo."""
        import db.repositories.asistente_feedback as repo

        monkeypatch.setattr(
            repo,
            "resumen",
            lambda dias: {
                "dias": dias,
                "modos": [{"modo": "pregunta", "utiles": 8, "no_utiles": 2, "total": 10}],
            },
        )

        cuerpo = client.get(f"{RUTA}/resumen", params={"dias": 7}).json()
        assert cuerpo["dias"] == 7
        assert (cuerpo["modos"][0]["utiles"], cuerpo["modos"][0]["total"]) == (8, 10)

    def test_las_peores_se_agrupan_por_hash(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Una respuesta mala y la misma doscientas veces no pueden leerse
        igual."""
        import db.repositories.asistente_feedback as repo

        monkeypatch.setattr(
            repo,
            "peores_preguntas",
            lambda limit, dias: [
                {
                    "pregunta_hash": "f" * 32,
                    "modo": "pregunta",
                    "negativos": 12,
                    "total": 14,
                    "ejemplo": None,
                    "ultima_vez": "2026-09-08T10:00:00Z",
                }
            ],
        )

        cuerpo = client.get(f"{RUTA}/peores").json()
        assert cuerpo[0]["negativos"] == 12
        assert cuerpo[0]["ejemplo"] is None

    @pytest.mark.parametrize("params", [{"dias": 0}, {"dias": 400}])
    def test_la_ventana_del_resumen_esta_acotada(
        self, client: TestClient, params: dict[str, Any]
    ) -> None:
        assert client.get(f"{RUTA}/resumen", params=params).status_code == 422
