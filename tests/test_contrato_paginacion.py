"""Contrato de paginación común del API + cota de la serie de `trends`.

Dos mitades del mismo ítem de backlog:

1. ``PaginatedResponse``/``CursorPaginatedResponse`` viven en ``shared/dto.py``
   como genéricos reutilizables (nacieron en ``api/routes/licitaciones.py``, en
   1 de los 30 módulos de rutas). Lo que se fija aquí es la **equivalencia**: el
   genérico compartido produce exactamente la misma forma —mismos campos, mismo
   nombre de componente OpenAPI— que la clase local que reemplaza, porque el
   cliente TS generado ya referencia ``PaginatedResponse_LicitacionSummary_``.

2. ``trends`` no se pagina por filas: su serie escala con la longitud del rango
   de fechas. El contrato es la granularidad del roll-up (``group_by``) más un
   techo de puntos que la respuesta declara.

No tocan Postgres a propósito: los DTOs y el recorte de la serie son funciones
puras, y esta suite tiene que poder correr sin BD.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from services.analytics.trends import (
    MAX_TREND_POINTS,
    TrendPoint,
    TrendsFilters,
    TrendsResult,
    _clip_series,
)
from shared.dto import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    CursorPaginatedResponse,
    PaginatedResponse,
)


class _Item(BaseModel):
    id_externo: str


# ── 1. Contrato de paginación común ────────────────────────────────────────


def test_paginated_response_es_generico_y_valida_el_item():
    """El envelope se parametriza con el modelo de la ruta que lo usa."""
    page = PaginatedResponse[_Item](
        total=7,
        limit=2,
        offset=4,
        items=[{"id_externo": "ES-1"}, {"id_externo": "ES-2"}],  # type: ignore[list-item]
    )
    assert [i.id_externo for i in page.items] == ["ES-1", "ES-2"]
    assert isinstance(page.items[0], _Item)
    assert (page.total, page.limit, page.offset) == (7, 2, 4)
    assert page.deprecation_notice is None


def test_paginated_response_rechaza_items_de_otra_forma():
    """Parametrizar no es decorativo: el genérico valida contra `_Item`."""
    with pytest.raises(ValueError):
        PaginatedResponse[_Item](total=1, limit=1, offset=0, items=[{"otro": "campo"}])  # type: ignore[list-item]


def test_paginated_response_campos_identicos_a_la_clase_que_reemplaza():
    """Regresión del movimiento a `shared/dto.py`.

    `web/src/generated/api.d.ts` ya declara `PaginatedResponse_LicitacionSummary_`
    con estas cinco claves. Añadir, quitar o renombrar una aquí rompe el cliente
    generado, así que la lista se congela.
    """
    assert set(PaginatedResponse[_Item].model_fields) == {
        "total",
        "limit",
        "offset",
        "items",
        "deprecation_notice",
    }
    assert set(CursorPaginatedResponse[_Item].model_fields) == {
        "items",
        "next_cursor",
        "has_more",
        "limit",
    }


def test_nombre_del_componente_openapi_no_cambia():
    """FastAPI deriva el nombre del componente del nombre de la clase."""
    assert PaginatedResponse.__name__ == "PaginatedResponse"
    assert CursorPaginatedResponse.__name__ == "CursorPaginatedResponse"


def test_total_negativo_significa_conteo_no_calculado():
    """`with_total=false` devuelve la página sin COUNT(*) → total = -1."""
    page = PaginatedResponse[_Item](total=-1, limit=50, offset=0, items=[])
    assert page.total == -1


def test_cursor_paginated_defaults():
    page = CursorPaginatedResponse[_Item](items=[], limit=100)
    assert page.next_cursor is None
    assert page.has_more is False


def test_licitaciones_usa_el_envelope_compartido():
    """La ruta que ya tenía el idioma es la que lo demuestra en esta ola."""
    from api.routes import licitaciones as lic

    assert lic.PaginatedResponse is PaginatedResponse
    assert lic.CursorPaginatedResponse is CursorPaginatedResponse


def test_cotas_de_pagina_son_las_de_siempre():
    """Mover el tope al contrato no puede cambiar su valor."""
    assert MAX_PAGE_LIMIT == 500
    assert DEFAULT_PAGE_LIMIT == 50


# ── 2. Cota de la serie de trends ──────────────────────────────────────────


def _serie(n: int) -> list[TrendPoint]:
    return [TrendPoint(period=f"p{i:05d}", count=1, importe=1.0) for i in range(n)]


def test_serie_por_debajo_del_techo_pasa_intacta():
    """El caso real de hoy: la respuesta no cambia ni un punto."""
    serie = _serie(3650)  # 10 años a granularidad diaria
    out, truncada = _clip_series(serie)
    assert out == serie
    assert truncada is False


def test_serie_en_el_techo_exacto_no_se_recorta():
    out, truncada = _clip_series(_serie(MAX_TREND_POINTS))
    assert len(out) == MAX_TREND_POINTS
    assert truncada is False


def test_serie_por_encima_del_techo_conserva_el_tramo_reciente():
    serie = _serie(MAX_TREND_POINTS + 25)
    out, truncada = _clip_series(serie)
    assert truncada is True
    assert len(out) == MAX_TREND_POINTS
    # La cola, no la cabeza: los puntos viejos son los sacrificables.
    assert out[-1] == serie[-1]
    assert out[0] == serie[25]


def test_group_by_es_el_mando_de_roll_up_y_esta_documentado():
    """AC del backlog: la frecuencia del roll-up se documenta en el DTO."""
    campo = TrendsFilters.model_fields["group_by"]
    assert campo.default == "month"
    assert campo.description is not None
    assert "roll-up" in campo.description


def test_respuesta_declara_granularidad_y_recorte():
    """Campos aditivos: sus defaults reproducen la respuesta de hoy."""
    vacio = TrendsResult()
    assert vacio.group_by == "month"
    assert vacio.serie_truncada is False
    assert TrendsResult.model_fields["serie_truncada"].description is not None
