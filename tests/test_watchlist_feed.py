"""Feed Atom de las alertas (``GET /watchlist/feed.xml``) contra Postgres.

El recorrido feliz está en ``tests/test_escenario_feed_alertas.py``. Aquí van
los bordes de la credencial: el feed es la única ruta que acepta la clave en la
URL, así que es la que más fácil abre de más.
"""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from tests.escenarios import abrir_sesion, sembrar_licitacion

_RUTA = "/api/v1/watchlist/feed.xml"


def _regla_y_clave(email: str, client: TestClient, *, scopes: str | None) -> str:
    """Una persona con una regla de software y una clave con ``scopes``."""
    sesion = abrir_sesion(email, client)
    regla = sesion.post("/watchlist/rules", json={"nombre": "Software", "cpv": "72"})
    assert regla.status_code == 201, regla.text
    cuerpo: dict[str, str] = {"name": "Feed"}
    if scopes is not None:
        cuerpo["scopes"] = scopes
    creada = sesion.post("/me/keys", json=cuerpo)
    assert creada.status_code == 201, creada.text
    return str(creada.json()["api_key"])


def _lector() -> TestClient:
    from api.app import app

    return TestClient(app, raise_server_exceptions=True)


def test_la_cabecera_sigue_valiendo_igual_que_el_token(client, api_db):
    sembrar_licitacion("EXP-FEED-CAB", "Evolutivo SAP", cpv="72200000")
    token = _regla_y_clave("feed-cabecera@example.com", client, scopes="watchlist:read")

    por_cabecera = _lector().get(_RUTA, headers={"X-API-Key": token})
    assert por_cabecera.status_code == 200, por_cabecera.text
    assert "urn:licitacion:EXP-FEED-CAB" in por_cabecera.text


def test_una_clave_sin_watchlist_read_es_403(client, api_db):
    """La clave que nace por defecto (``data:read``) lee el mercado, no lo personal."""
    token = _regla_y_clave("feed-sin-scope@example.com", client, scopes=None)

    assert _lector().get(_RUTA, params={"token": token}).status_code == 403


def test_un_token_que_no_existe_es_401(client, api_db):
    assert _lector().get(_RUTA, params={"token": "no-es-una-clave"}).status_code == 401


def test_cada_clave_ve_solo_las_reglas_de_su_titular(client, api_db):
    """La identidad sale del titular de la clave, no de la clave: la de B no ve lo de A."""
    sembrar_licitacion("EXP-FEED-A", "Software de A", cpv="72000000")
    _regla_y_clave("feed-a@example.com", client, scopes="watchlist:read")

    from api.app import app

    sesion_b = abrir_sesion("feed-b@example.com", TestClient(app, raise_server_exceptions=True))
    creada = sesion_b.post("/me/keys", json={"name": "Feed", "scopes": "watchlist:read"})
    assert creada.status_code == 201, creada.text

    feed_b = _lector().get(_RUTA, params={"token": creada.json()["api_key"]})
    assert feed_b.status_code == 200, feed_b.text
    assert "urn:licitacion:EXP-FEED-A" not in feed_b.text


def test_pedir_la_organizacion_de_otro_es_403(client, api_db):
    token = _regla_y_clave("feed-org-a@example.com", client, scopes="watchlist:read")

    from api.app import app

    otra = abrir_sesion("feed-org-b@example.com", TestClient(app, raise_server_exceptions=True))

    respuesta = _lector().get(
        _RUTA, params={"token": token, "organization_id": otra.organization_id}
    )
    assert respuesta.status_code == 403


def test_el_token_no_queda_en_el_access_log_de_uvicorn():
    """La URL entera llega a la línea de acceso de uvicorn, query incluida.

    Un lector de feeds la pide cada pocos minutos: sin el filtro, el log de
    producción acumularía la clave en claro una vez por petición.
    """
    import api.routes.watchlist_feed  # noqa: F401 -- importarlo instala el filtro

    registro = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "1.2.3.4:5",
            "GET",
            "/api/v1/watchlist/feed.xml?limit=5&token=SECRETO-123",
            "1.1",
            200,
        ),
        exc_info=None,
    )
    for filtro in logging.getLogger("uvicorn.access").filters:
        assert isinstance(filtro, logging.Filter)
        filtro.filter(registro)

    linea = registro.getMessage()
    assert "SECRETO-123" not in linea
    assert "token=[REDACTED]" in linea
    assert "limit=5" in linea
