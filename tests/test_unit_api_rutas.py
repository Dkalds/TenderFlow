"""``api/rutas.py``: la superficie no depende de cómo guarde FastAPI los routers.

Desde fastapi 0.137 ``app.routes`` deja de traer las ``APIRoute`` aplanadas y
``scope["route"].path`` pierde el prefijo del ``include_router``. Estos tests
fijan el comportamiento que tiene que salir igual con cualquier versión.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send

from api.rutas import (
    IntrospeccionRotaError,
    operaciones,
    plantilla_de_ruta,
    plantilla_openapi,
    rutas_planas,
)


def _app() -> FastAPI:
    hija = APIRouter(prefix="/hija")

    @hija.get("/{id_externo:path}/detalle")
    def detalle(id_externo: str) -> dict[str, str]:
        return {"id": id_externo}

    @hija.delete("/{item_id}")
    def borrar(item_id: int) -> None:
        return None

    madre = APIRouter(prefix="/madre")
    madre.include_router(hija)

    @madre.post("/oculta", include_in_schema=False)
    def oculta() -> None:
        return None

    app = FastAPI()
    app.include_router(madre, prefix="/api/v1")
    return app


def test_rutas_planas_aplica_todos_los_prefijos_y_conserva_el_orden() -> None:
    planas = [(r.plantilla, sorted(r.metodos)) for r in rutas_planas(_app().routes)]
    propias = [p for p in planas if p[0].startswith("/api/v1")]
    assert propias == [
        ("/api/v1/madre/hija/{id_externo:path}/detalle", ["GET"]),
        ("/api/v1/madre/hija/{item_id}", ["DELETE"]),
        ("/api/v1/madre/oculta", ["POST"]),
    ]


def test_rutas_planas_expone_el_dependant_efectivo() -> None:
    ruta = next(r for r in rutas_planas(_app().routes) if r.plantilla.endswith("/detalle"))
    assert ruta.dependant is not None
    assert ruta.endpoint is not None and ruta.endpoint.__name__ == "detalle"


def test_operaciones_incluye_lo_que_openapi_no_publica() -> None:
    ops = [op for op in operaciones(_app()) if op[1].startswith("/api/v1")]
    assert ops == [
        ("GET", "/api/v1/madre/hija/{id_externo:path}/detalle"),
        ("DELETE", "/api/v1/madre/hija/{item_id}"),
        ("POST", "/api/v1/madre/oculta"),
    ]


def test_operaciones_falla_si_el_recorrido_no_ve_el_esquema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El modo de fallo de agosto: contar 7 operaciones en vez de 154 sin avisar."""
    import api.rutas as modulo

    monkeypatch.setattr(modulo, "rutas_planas", lambda _rutas: [])
    with pytest.raises(IntrospeccionRotaError, match="no aparecen al recorrer"):
        operaciones(_app())


def test_plantilla_openapi_borra_el_conversor() -> None:
    assert plantilla_openapi("/a/{id_externo:path}/b/{n}") == "/a/{id_externo}/b/{n}"


def test_plantilla_de_ruta_lleva_el_prefijo_del_include_router() -> None:
    """Es la etiqueta del access log y de la métrica de coste: sin el prefijo,
    ``/api/v1/x`` y una ruta ``/x`` montada sin él compartirían serie."""
    app = _app()
    vistas: list[str | None] = []

    class _Captura:
        def __init__(self, inner: ASGIApp) -> None:
            self.inner = inner

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            await self.inner(scope, receive, send)
            if scope["type"] == "http":
                vistas.append(plantilla_de_ruta(scope))

    app.add_middleware(_Captura)
    cliente = TestClient(app)
    assert cliente.get("/api/v1/madre/hija/PA-S 2026/58/detalle").status_code == 200
    assert cliente.get("/no-existe").status_code == 404
    assert vistas == ["/api/v1/madre/hija/{id_externo:path}/detalle", None]


def test_plantilla_de_ruta_sin_app_cae_en_la_ruta_propia() -> None:
    class _Ruta:
        path = "/suelta"

    scope: dict[str, Any] = {"route": _Ruta()}
    assert plantilla_de_ruta(scope) == "/suelta"
    assert plantilla_de_ruta({}) is None
