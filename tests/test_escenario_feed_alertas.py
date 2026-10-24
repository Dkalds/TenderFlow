"""Escenario: suscribirse a las alertas desde un lector de feeds.

Recorrido completo por la API con sesión real (ver ``tests/escenarios.py``): la
persona guarda una regla en ``/mi-watchlist``, crea en Ajustes una clave con
permiso para leer su watchlist y pega en su lector la URL del feed, que lleva la
clave en ``?token=`` porque los lectores no saben mandar cabeceras.

Hasta 2026-10 el feed estaba roto por tres sitios a la vez: ignoraba
``?token=`` aunque su docstring lo prometía, derivaba la identidad del hash de
la clave cuando las reglas se guardan con la del titular, y leía la tabla
heredada ``watchlist_cpv`` en vez de ``watchlist_rules``. Devolvía un feed
vacío y nadie lo notaba porque ninguna pantalla enseñaba su URL.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.escenarios import abrir_sesion, sembrar_licitacion


def test_cu04_el_feed_de_alertas_lista_lo_que_casa_la_regla(client, api_db):
    """CU-04 — lo que casa la regla llega también al lector de feeds, con la clave en la URL."""
    from api.app import app

    sembrar_licitacion(
        "EXP-FEED-SAP", "Implantación SAP S/4HANA", cpv="72000000", importe=400_000.0
    )
    sembrar_licitacion("EXP-FEED-PEQ", "Soporte SAP menor", cpv="72500000", importe=20_000.0)
    sembrar_licitacion("EXP-FEED-OBRA", "Reforma de cubierta", cpv="45000000", importe=900_000.0)
    sesion = abrir_sesion("feed-alertas@example.com", client)

    regla = sesion.post(
        "/watchlist/rules",
        json={
            "nombre": "Software grande",
            "cpv": "72",
            "min_importe": 100_000,
            "frequency": "daily",
        },
    )
    assert regla.status_code == 201, regla.text

    creada = sesion.post(
        "/me/keys", json={"name": "Lector de feeds", "scopes": "data:read,watchlist:read"}
    )
    assert creada.status_code == 201, creada.text
    token = creada.json()["api_key"]

    # El lector no tiene cookies ni sabe mandar cabeceras: solo la URL.
    lector = TestClient(app, raise_server_exceptions=True)
    feed = lector.get("/api/v1/watchlist/feed.xml", params={"token": token})
    assert feed.status_code == 200, feed.text
    assert feed.headers["content-type"].startswith("application/atom+xml")
    # Lo mismo que cuenta la regla, con su importe mínimo aplicado: el feed no
    # es una versión más ancha de la alerta.
    assert "urn:licitacion:EXP-FEED-SAP" in feed.text
    assert "urn:licitacion:EXP-FEED-PEQ" not in feed.text
    assert "urn:licitacion:EXP-FEED-OBRA" not in feed.text

    # Sin la clave no hay feed; y la clave sigue siendo un secreto, así que la
    # respuesta no la repite.
    assert lector.get("/api/v1/watchlist/feed.xml").status_code == 401
    assert token not in feed.text
