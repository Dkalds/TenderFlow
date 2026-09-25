"""Techo de sentencia de la analítica y 503 de consulta cancelada, sin BD.

Lo que se fija:

- La dependencia de router fija el techo para toda la petición, y lo ve el
  handler aunque corra en el threadpool; el valor no sobrevive a la petición.
- Con el setting a 0 (su valor por defecto) no hay techo.
- ``/analytics`` y ``/competitive`` llevan la dependencia; los jobs, que llaman
  a las mismas funciones de ``aggregates.py``, no pasan por ella.
- Un ``QueryCanceled`` sale como 503 ``query-timeout`` —que el navegador no
  reintenta— y no como 500.
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

import db.connection as conn_mod
from api.errors import TIPO_CONSULTA_CANCELADA, register_exception_handlers
from api.techo_analitica import techo_sentencia_analitica


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    con_techo = APIRouter(dependencies=[Depends(techo_sentencia_analitica)])

    # Síncronas a propósito: corren en el threadpool, que es donde leen la BD
    # los handlers reales.
    @con_techo.get("/analitica")
    def analitica() -> dict[str, int | None]:
        return {"techo": conn_mod._techo_sentencia.get()}

    @app.get("/otra")
    def otra() -> dict[str, int | None]:
        return {"techo": conn_mod._techo_sentencia.get()}

    @app.get("/cancelada")
    def cancelada() -> None:
        from psycopg.errors import QueryCanceled

        raise QueryCanceled("canceling statement due to statement timeout")

    app.include_router(con_techo)
    return app


def test_la_ruta_de_analitica_ve_el_techo_en_su_hilo(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import settings

    monkeypatch.setattr(settings, "API_ANALYTICS_STATEMENT_TIMEOUT_MS", 15_000)
    with TestClient(_app()) as client:
        assert client.get("/analitica").json() == {"techo": 15_000}
        # Muere con la petición: otra ruta, sin la dependencia, no lo hereda.
        assert client.get("/otra").json() == {"techo": None}


def test_con_el_setting_a_cero_no_hay_techo(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import settings

    monkeypatch.setattr(settings, "API_ANALYTICS_STATEMENT_TIMEOUT_MS", 0)
    with TestClient(_app()) as client:
        assert client.get("/analitica").json() == {"techo": None}


def test_los_routers_de_analitica_llevan_el_techo() -> None:
    from api.routes.analytics import router as analytics
    from api.routes.competitive import router as competitive

    for router in (analytics, competitive):
        assert any(d.dependency is techo_sentencia_analitica for d in router.dependencies)


def test_una_consulta_cancelada_es_un_503_que_el_navegador_no_reintenta() -> None:
    with TestClient(_app(), raise_server_exceptions=False) as client:
        respuesta = client.get("/cancelada")

    assert respuesta.status_code == 503
    assert respuesta.headers["content-type"].startswith("application/problem+json")
    assert respuesta.headers["retry-after"] == "30"
    cuerpo = respuesta.json()
    assert cuerpo["type"] == TIPO_CONSULTA_CANCELADA
    assert "Acota los filtros" in cuerpo["detail"]


def test_el_tipo_del_503_coincide_con_el_que_lee_el_frontend() -> None:
    # Dos copias de la misma cadena, una por lenguaje: si divergen, el navegador
    # vuelve a reintentar cinco veces cada consulta cancelada.
    from pathlib import Path

    fuente = Path(__file__).resolve().parents[1] / "web" / "src" / "lib" / "query-feedback.ts"
    assert f'"{TIPO_CONSULTA_CANCELADA}"' in fuente.read_text(encoding="utf-8")
