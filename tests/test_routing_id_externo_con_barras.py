"""Enrutado de los endpoints que reciben un ``id_externo`` con '/' en la ruta.

Los expedientes de PLACSP traen ids con barras y espacios (p.ej.
``PA-S 2026/000058``). Starlette compila ``{id_externo}`` a ``[^/]+``, así que
una ruta declarada con el conversor por defecto no casa y FastAPI devuelve 404
antes de ejecutar el handler. El front manda el id con ``encodeURIComponent``,
pero uvicorn decodifica el ``%2F`` a ``/`` *antes* del enrutado, así que
escaparlo no salva la ruta.

Aquí se fija el invariante completo, que tiene dos mitades y se rompe si solo
se mira una:

1. Todo endpoint que recibe el id por la ruta **tiene que aceptar barras**.
2. El conversor ``:path`` es **voraz**. El detalle lo lleva —tiene que
   aceptar barras como cualquier otra—, y por eso su ruta se traga todas las
   sub-rutas si se declara antes que ellas: ``/documentos``, ``/explain``,
   ``/tech-scores``… resolverían a ``get_licitacion`` con un ``id_externo``
   del tipo ``"PA-S 2026/000058/documentos"``. Lo que lo impide es **el orden
   de registro**: el detalle vive en ``router_detalle``
   (``api/routes/licitaciones``) y ``api/app.py`` lo incluye el último de
   todos, detrás incluso de ``eventos``, ``predicciones`` y ``ask``, que
   cuelgan del mismo prefijo desde otros módulos.

   Hasta 2026-09 esto era un ``app.add_api_route(..., include_in_schema=False)``
   suelto al final de ``api/app.py``: el detalle funcionaba pero el **esquema**
   publicaba la variante de segmento simple —la rota—, y ``/similares`` y la
   página de un documento, que nunca tuvieron fallback, daban 404. Los
   invariantes estructurales (un solo parámetro, catch-all el último) los fija
   ``tests/test_licitaciones_identificador.py``; aquí se comprueba el
   enrutado real.

Por eso estos tests comprueban **a qué handler** resuelve cada ruta y no solo
que no haya 404: un 404 detecta la mitad 1, pero la mitad 2 falla en silencio
devolviendo 200 desde el handler equivocado.

No tocan la base de datos: el enrutado ocurre antes que la autenticación.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import pytest
from starlette.testclient import TestClient

ID_CON_BARRAS = "PA-S 2026/000058"
ID_SIN_BARRAS = "SIMPLE-123"

# (método, sub-ruta, handler que debe atenderla)
SUBRECURSOS: list[tuple[str, str, str]] = [
    ("GET", "/documentos", "get_documentos"),
    # `/similares` faltaba en esta lista y ahí sobrevivió el bug: era la única
    # sub-ruta declarada con el conversor por defecto, así que daba 404 con un
    # id con barras mientras sus hermanas funcionaban.
    ("GET", "/similares", "get_similares"),
    ("GET", "/explain", "explain_licitacion"),
    ("GET", "/ficha-pliego", "get_tender_fact_sheet"),
    ("POST", "/ficha-pliego/extract", "extract_tender_fact_sheet"),
    ("GET", "/tech-scores", "get_tech_scores"),
    ("GET", "/tecnologias", "get_tecnologias"),
    ("GET", "/eventos", "get_timeline"),
    ("GET", "/prediccion-baja", "get_prediccion_baja"),
    ("GET", "/escenarios-precio", "get_escenarios_precio"),
    ("POST", "/resumen", "resumen_licitacion"),
]


@pytest.fixture()
def resolve():
    """``(método, url) -> nombre del handler`` al que resuelve el router.

    Envuelve la app en un ASGI middleware que lee ``scope["route"]`` una vez
    que el router lo ha fijado. Devuelve ``None`` si ninguna ruta casó (404 de
    enrutado). No necesita DB ni credenciales: el 401 de ``require_any_auth``
    se emite después de resolver la ruta.
    """
    from api.app import app

    captured: dict[str, Any] = {}

    async def probe(scope, receive, send):
        await app(scope, receive, send)
        captured["route"] = scope.get("route")

    client = TestClient(probe, raise_server_exceptions=False)

    def _resolve(method: str, url: str) -> str | None:
        captured.clear()
        client.request(method, url, json={} if method in ("POST", "PUT") else None)
        route = captured.get("route")
        return getattr(getattr(route, "endpoint", None), "__name__", None)

    return _resolve


def _url(id_externo: str, sub: str = "") -> str:
    """URL tal y como la construye el front: ``encodeURIComponent(id)``."""
    return f"/api/v1/licitaciones/{quote(id_externo, safe='')}{sub}"


class TestDetalleLicitacion:
    def test_detalle_con_barras_llega_al_handler(self, resolve):
        """El detalle, registrado el último, recoge los ids con '/'.

        Es lo que sostiene la pantalla de Detalle del dashboard
        (``web/src/app/(dashboard)/detalle/page.tsx``) para los expedientes de
        PLACSP, que son mayoría.
        """
        assert resolve("GET", _url(ID_CON_BARRAS)) == "get_licitacion"

    def test_detalle_sin_barras_sigue_funcionando(self, resolve):
        assert resolve("GET", _url(ID_SIN_BARRAS)) == "get_licitacion"


class TestSubrecursosNoAbsorbidos:
    """El detalle no puede ensombrecer a sus hermanas.

    Si alguien mueve ``router_detalle`` delante de los demás routers en
    ``api/app.py`` —o declara la ruta glotona dentro del router normal— estos
    tests caen en bloque. El arreglo nunca es quitarle el ``:path`` al detalle:
    es devolverlo al final del registro.
    """

    @pytest.mark.parametrize(("metodo", "sub", "handler"), SUBRECURSOS)
    def test_con_id_con_barras(self, resolve, metodo, sub, handler):
        assert resolve(metodo, _url(ID_CON_BARRAS, sub)) == handler

    @pytest.mark.parametrize(("metodo", "sub", "handler"), SUBRECURSOS)
    def test_con_id_sin_barras(self, resolve, metodo, sub, handler):
        assert resolve(metodo, _url(ID_SIN_BARRAS, sub)) == handler


class TestOtrosEndpointsConIdExterno:
    """Las dos rutas que deshacen una acción y reciben el id por la ruta.

    Ambas son el reverso de un POST que recibe el ``id_externo`` en el *body*
    (y que por tanto sí acepta barras). Sin ``:path`` el usuario podía descartar
    una señal o marcar un favorito sobre un expediente de PLACSP y luego no
    poder deshacerlo nunca: el DELETE devolvía 404 de enrutado.
    """

    @pytest.mark.parametrize("id_externo", [ID_CON_BARRAS, ID_SIN_BARRAS])
    def test_delete_radar_dismissal(self, resolve, id_externo):
        url = f"/api/v1/radar/dismissals/{quote(id_externo, safe='')}"
        assert resolve("DELETE", url) == "delete_dismissal"

    @pytest.mark.parametrize("id_externo", [ID_CON_BARRAS, ID_SIN_BARRAS])
    def test_delete_watchlist_item(self, resolve, id_externo):
        url = f"/api/v1/watchlist/items/{quote(id_externo, safe='')}"
        assert resolve("DELETE", url) == "delete_item"

    def test_vecinas_no_quedan_ensombrecidas(self, resolve):
        """``:path`` es voraz: comprobamos que no se comió a las vecinas."""
        assert resolve("DELETE", "/api/v1/watchlist/rules/123") == "delete_rule_route"
        assert resolve("GET", "/api/v1/watchlist/rules/123/matches") == "get_rule_matches"
        assert resolve("GET", "/api/v1/watchlist/feed.xml") == "watchlist_feed"
        assert resolve("GET", "/api/v1/radar/dismissals") == "get_dismissals"
