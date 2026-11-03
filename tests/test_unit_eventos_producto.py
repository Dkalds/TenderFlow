"""Eventos de producto contados por la API (``POST /telemetria/eventos``), sin BD.

Lo que se fija: que el catálogo de la API sea el de la web, que nada fuera de
él llegue a una etiqueta de Prometheus, y que las series tengan techo.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import shared.eventos_producto as ep
from shared.dto import EventoProductoIn

_ANALYTICS_TS = Path(__file__).resolve().parents[1] / "web" / "src" / "lib" / "analytics.ts"


def _catalogo_de_la_web() -> dict[str, tuple[str, ...]]:
    texto = _ANALYTICS_TS.read_text(encoding="utf-8")
    bloque = texto.split("export const PROPIEDADES_PERMITIDAS = {", 1)[1].split("} as const", 1)[0]
    catalogo: dict[str, tuple[str, ...]] = {}
    for evento, props in re.findall(r"(\w+):\s*\[([^\]]*)\]", bloque, flags=re.S):
        catalogo[evento] = tuple(re.findall(r'"(\w+)"', props))
    return catalogo


def test_el_catalogo_de_la_api_es_el_de_la_web() -> None:
    assert dict(ep.PROPIEDADES) == _catalogo_de_la_web()


@pytest.fixture(autouse=True)
def _series_limpias() -> None:
    ep._vistas.clear()


def test_solo_cuenta_propiedades_del_catalogo_con_forma_de_categoria() -> None:
    dims = ep.dimensiones(
        "espacio_abierto",
        {
            "espacio": "radar",
            "vista": "con espacios",  # texto, no categoría
            "email": "ana@example.com",  # fuera del catálogo
            "origen": "x" * 49,  # demasiado largo
        },
    )
    assert dims == [("espacio", "radar")]


def test_pasado_el_techo_un_valor_nuevo_cuenta_como_otro() -> None:
    with patch.object(ep, "MAX_SERIES", 2):
        assert ep.dimensiones("export_lanzado", {"formato": "csv", "recurso": "detalle"}) == [
            ("formato", "csv"),
            ("recurso", "detalle"),
        ]
        assert ep.dimensiones("export_lanzado", {"formato": "xlsx"}) == [("formato", "otro")]
        # Una serie ya vista sigue contando con su valor.
        assert ep.dimensiones("export_lanzado", {"formato": "csv"}) == [("formato", "csv")]


def _llamar(body: EventoProductoIn) -> tuple[MagicMock, MagicMock]:
    from api.routes import telemetria

    total, dimension = MagicMock(), MagicMock()
    with (
        patch.object(telemetria, "producto_eventos_total", total),
        patch.object(telemetria, "producto_eventos_dimension_total", dimension),
    ):
        respuesta = asyncio.run(telemetria.post_evento_producto(body, _ctx={}))
    assert respuesta.status_code == 204
    return total, dimension


def test_la_ruta_incrementa_evento_y_dimensiones() -> None:
    total, dimension = _llamar(
        EventoProductoIn(evento="espacio_abierto", propiedades={"espacio": "competencia"})
    )
    total.labels.assert_called_once_with(evento="espacio_abierto")
    dimension.labels.assert_called_once_with(
        evento="espacio_abierto", propiedad="espacio", valor="competencia"
    )


def test_un_evento_fuera_del_catalogo_es_422_y_no_cuenta() -> None:
    from api.routes import telemetria

    total = MagicMock()
    with (
        patch.object(telemetria, "producto_eventos_total", total),
        pytest.raises(HTTPException) as error,
    ):
        asyncio.run(telemetria.post_evento_producto(EventoProductoIn(evento="inventado"), _ctx={}))
    assert error.value.status_code == 422
    total.labels.assert_not_called()
