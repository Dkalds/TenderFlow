"""Toda ruta deprecada dice por HTTP cuándo se apaga, y lo mismo que su resumen.

Hasta el 2026-10-23 cuatro operaciones de ``/analytics`` salían ``deprecated``
en el OpenAPI sin enviar ni ``Deprecation`` ni ``Sunset``: un integrador que no
leyera el esquema no tenía forma de enterarse. Y el listado por offset sí las
enviaba, pero su ``summary`` anunciaba otra fecha (2026-12-04) que la de la
cabecera (2027-01-15).

Dos mitades:

* **Sin BD** — el inventario. Cada operación ``deprecated`` del OpenAPI está en
  :data:`_SUNSET_ESPERADO`, y si su ``summary`` lleva ``[DEPRECADO <fecha>]`` la
  fecha es la del apagado. Una ruta nueva deprecada sin fecha falla aquí.
* **Con BD** — las cabeceras de verdad, por HTTP. En las de analítica dos
  veces: la segunda respuesta sale de la caché de ``cache_response``, que
  construye su propia ``Response`` y es justo donde una cabecera fijada en el
  handler se perdería.
"""

from __future__ import annotations

import re
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

#: Apagado que cada operación deprecada tiene que anunciar. Fuente: las RFC de
#: retirada (``docs/rfc/2026-09-06-rfc-retirada-endpoints-analitica.md`` y
#: ``docs/rfc/2026-10-23-rfc-retirada-campana-antigua-y-stream.md``).
_SUNSET_ESPERADO: dict[tuple[str, str], date] = {
    ("get", "/api/v1/licitaciones"): date(2027, 1, 15),
    ("get", "/api/v1/analytics/resumen/sankey"): date(2027, 1, 15),
    ("get", "/api/v1/analytics/resumen/top"): date(2027, 1, 15),
    ("get", "/api/v1/analytics/compare-periods"): date(2027, 1, 15),
    ("get", "/api/v1/analytics/forecast/retendering"): date(2027, 2, 1),
    ("post", "/api/v1/notifications/read"): date(2027, 2, 1),
    ("get", "/api/v1/licitaciones/stream"): date(2027, 2, 1),
}

_FECHA_EN_RESUMEN = re.compile(r"\[DEPRECADO (\d{4}-\d{2}-\d{2})\]")


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    from api.app import app

    return app.openapi()


def _deprecadas(spec: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (metodo, ruta): operacion
        for ruta, operaciones in spec["paths"].items()
        for metodo, operacion in operaciones.items()
        if isinstance(operacion, dict) and operacion.get("deprecated")
    }


def test_toda_operacion_deprecada_tiene_fecha_de_apagado(spec: dict[str, Any]) -> None:
    deprecadas = set(_deprecadas(spec))
    sin_fecha = sorted(deprecadas - set(_SUNSET_ESPERADO))
    assert not sin_fecha, (
        f"Operaciones deprecadas sin fecha de apagado: {sin_fecha}. Declarala con "
        "`sunset_anunciado()` y enviala con `deprecate_route()` (docs/api-design.md)."
    )
    no_deprecadas = sorted(set(_SUNSET_ESPERADO) - deprecadas)
    assert not no_deprecadas, f"Con fecha de apagado pero sin `deprecated=True`: {no_deprecadas}"


def test_el_resumen_anuncia_la_misma_fecha_que_la_cabecera(spec: dict[str, Any]) -> None:
    for clave, operacion in _deprecadas(spec).items():
        encontrada = _FECHA_EN_RESUMEN.search(operacion.get("summary") or "")
        if encontrada:
            assert date.fromisoformat(encontrada.group(1)) == _SUNSET_ESPERADO[clave], clave


def _sunset(respuesta: Any) -> date:
    assert respuesta.headers.get("Deprecation") == "true", respuesta.headers
    return parsedate_to_datetime(respuesta.headers["Sunset"]).date()


_ANALITICA = [
    ("/api/v1/analytics/resumen/sankey", {}),
    ("/api/v1/analytics/resumen/top", {}),
    (
        "/api/v1/analytics/compare-periods",
        {
            "range_a_desde": "2026-01-01",
            "range_a_hasta": "2026-01-31",
            "range_b_desde": "2026-02-01",
            "range_b_hasta": "2026-02-28",
        },
    ),
    ("/api/v1/analytics/forecast/retendering", {}),
]


@pytest.mark.parametrize(("ruta", "params"), _ANALITICA)
def test_la_analitica_deprecada_envia_cabeceras_tambien_desde_la_cache(
    client: TestClient, auth: dict[str, str], ruta: str, params: dict[str, str]
) -> None:
    esperado = _SUNSET_ESPERADO[("get", ruta)]
    for _ in range(2):  # la segunda sale de la caché
        respuesta = client.get(ruta, params=params, headers=auth)
        assert respuesta.status_code == 200, respuesta.text
        assert _sunset(respuesta) == esperado
        assert 'rel="deprecation"' in respuesta.headers["Link"]


def test_retendering_apunta_a_su_sucesora(client: TestClient, auth: dict[str, str]) -> None:
    respuesta = client.get("/api/v1/analytics/forecast/retendering", headers=auth)
    assert (
        '</api/v1/competitive/renovaciones>; rel="successor-version"' in (respuesta.headers["Link"])
    )


def test_marcar_novedades_leidas_esta_deprecada(client: TestClient, auth: dict[str, str]) -> None:
    respuesta = client.post("/api/v1/notifications/read", json={"ids": []}, headers=auth)
    assert respuesta.status_code == 200, respuesta.text
    assert _sunset(respuesta) == _SUNSET_ESPERADO[("post", "/api/v1/notifications/read")]
    assert "/api/v1/notifications/alerts/read" in respuesta.headers["Link"]


def test_el_stream_esta_deprecado(client: TestClient, auth: dict[str, str]) -> None:
    async def _rapido(request: Any, last_event_id: float, batch: int) -> Any:
        yield 'event: close\ndata: {"reason": "max_duration_reached"}\n\n'

    with patch("api.routes.stream._event_generator", _rapido):
        respuesta = client.get("/api/v1/licitaciones/stream", headers=auth)
    assert respuesta.status_code == 200, respuesta.text
    assert _sunset(respuesta) == _SUNSET_ESPERADO[("get", "/api/v1/licitaciones/stream")]
    assert "/api/v1/licitaciones/cursor" in respuesta.headers["Link"]
