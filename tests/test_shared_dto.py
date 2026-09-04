"""Tests para shared/dto.py — DTOs Pydantic v2.

El 2026-09-03 (S4.7) se borraron de ``shared/dto.py`` cinco clases muertas:
``LicitacionSummary``, ``LicitacionDetail``, ``AdjudicacionSummary``,
``ClusterSummary`` y ``KpiSnapshotDTO``. Las tres primeras eran homónimas, con
tipos distintos, de los modelos vivos de ``api/routes/licitaciones.py``: si
alguna hubiera llegado al esquema OpenAPI, FastAPI habría renombrado ambas con
prefijo de módulo, y eso reescribe ``components["schemas"]`` en
``web/src/generated/api.d.ts`` y rompe el frontend entero.

Este fichero cubría esas cinco clases. En vez de perder las comprobaciones, cada
**propiedad** se reapunta al DTO vivo que la sigue sosteniendo dentro de este
mismo módulo:

- instanciación y campos opcionales → ``LicitacionPublica``
- ``importe`` no puede ser negativo (``ge=0``) → ``LicitacionPublica`` y ``LotePublico``
- ``from_attributes=True`` (construcción desde filas) → ``LicitacionPublica``
- las fechas aceptan ISO 8601 (``PgDateTime``) → ``LicitacionPublica``
- «el detalle extiende al resumen» → ``PursuitDetail`` / ``PursuitSummary``

Las propiedades cuyo sustituto vive fuera de ``shared/dto.py`` (los DTOs de
licitaciones, adjudicaciones, clusters y KPIs) se trasladaron a
``tests/test_contract_dto.py``, que es donde se verifica el contrato API↔web.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

import pydantic
import pytest


def test_licitacion_publica_instantiation():
    """El DTO de la superficie pública exige lo que la Ley 37/2007 obliga a citar."""
    from shared.dto import LicitacionPublica

    dto = LicitacionPublica(
        ref="abc123",
        expediente="TEST-001",
        titulo="SAP ERP",
        fuente="placsp",
    )
    assert dto.expediente == "TEST-001"
    assert dto.titulo == "SAP ERP"
    assert dto.fuente == "placsp"


def test_licitacion_publica_optional_fields():
    from shared.dto import LicitacionPublica

    dto = LicitacionPublica(ref="r", expediente="X", titulo="T", fuente="placsp")
    assert dto.importe is None
    assert dto.ccaa is None
    assert dto.descripcion is None
    assert dto.lotes == []


def test_importe_negativo_rechazado():
    """``importe`` sigue rechazando negativos (``ge=0``).

    Era lo que comprobaban ``test_summary_importe_negative_rejected`` y
    ``test_adjudicacion_importe_negative_rejected`` sobre los DTOs muertos. La
    restricción sigue viva aquí: un importe negativo no es un dato de mercado
    posible, y colarlo en la superficie pública lo publicaría como si lo fuera.
    """
    from shared.dto import LicitacionPublica, LotePublico

    with pytest.raises(pydantic.ValidationError):
        LicitacionPublica(ref="r", expediente="X", titulo="T", fuente="placsp", importe=-100.0)

    with pytest.raises(pydantic.ValidationError):
        LotePublico(numero="1", importe=-1.0)


def test_detail_extends_summary():
    """El detalle no puede perder campos del resumen.

    Traslado de ``test_licitacion_detail_extends_summary``: el par vivo dentro
    de ``shared/dto.py`` es ``PursuitDetail`` / ``PursuitSummary``. Si el
    detalle dejara de heredar, la ficha de una oportunidad perdería campos que
    el listado sí trae y el frontend los leería como ``undefined``.
    """
    from shared.dto import PursuitDetail, PursuitSummary

    assert issubclass(PursuitDetail, PursuitSummary)
    summary_fields = set(PursuitSummary.model_fields)
    detail_fields = set(PursuitDetail.model_fields)
    assert summary_fields.issubset(detail_fields), (
        f"PursuitDetail pierde campos de PursuitSummary: {summary_fields - detail_fields}"
    )


def test_detail_has_extra_fields():
    """Y el detalle aporta algo que el resumen no tiene: si no, sobra."""
    from shared.dto import PursuitDetail, PursuitSummary

    extra = set(PursuitDetail.model_fields) - set(PursuitSummary.model_fields)
    assert "events" in extra
    assert "adjudicacion" in extra


def test_paginated_response():
    from shared.dto import LicitacionPublica, PaginatedResponse

    items = [
        LicitacionPublica(ref=f"r{i}", expediente=f"T-{i}", titulo=f"T{i}", fuente="placsp")
        for i in range(3)
    ]
    resp = PaginatedResponse[LicitacionPublica](items=items, total=10, limit=3, offset=0)
    assert resp.total == 10
    assert len(resp.items) == 3


def test_paginated_response_total_desconocido():
    """``total = -1`` es parte del contrato: la página vale, el conteo no se hizo."""
    from shared.dto import LicitacionPublica, PaginatedResponse

    resp = PaginatedResponse[LicitacionPublica](items=[], total=-1, limit=50, offset=0)
    assert resp.total == -1


def test_watchlist_entry():
    from shared.dto import WatchlistEntry

    entry = WatchlistEntry(user_id="user1", licitacion_id="TEST-001")
    assert entry.licitacion_id == "TEST-001"


def test_from_attributes_orm_compat():
    """``from_attributes=True`` permite inicializar desde objetos con atributos.

    Traslado de ``test_from_attributes_orm_compat`` y de
    ``test_summary_from_orm_attributes``: los repositorios construyen estos DTOs
    desde filas, no desde dicts, así que perder ``from_attributes`` rompería la
    construcción en runtime sin que nada lo avisara en tipos.
    """
    from shared.dto import LicitacionPublica

    class FakeRow:
        ref = "ORM-001"
        expediente = "ORM-EXP"
        titulo = "ORM Test"
        descripcion = None
        organo_contratacion = None
        importe = 100.0
        moneda = None
        cpv = None
        tipo_contrato = None
        estado = None
        procedimiento = None
        tramitacion = None
        fecha_publicacion = None
        fecha_limite = None
        fecha_inicio = None
        fecha_fin = None
        duracion_valor = None
        duracion_unidad = None
        provincia = None
        ccaa = None
        nuts_code = None
        url = None
        fuente = "placsp"
        actualizado = None
        lotes: ClassVar[list[object]] = []

    dto = LicitacionPublica.model_validate(FakeRow(), from_attributes=True)
    assert dto.ref == "ORM-001"
    assert dto.importe == pytest.approx(100.0)


def test_pg_datetime_acepta_iso_8601():
    """Las fechas del contrato aceptan strings ISO 8601 y se normalizan a datetime.

    Traslado de ``test_detail_fecha_as_iso_string``: la propiedad la sostiene el
    tipo ``PgDateTime``, que es lo que usan los campos de fecha de este módulo.
    """
    from shared.dto import LicitacionPublica

    dto = LicitacionPublica(
        ref="r",
        expediente="X",
        titulo="T",
        fuente="placsp",
        fecha_publicacion="2024-01-15T10:00:00Z",
        fecha_limite="2024-02-01T00:00:00+00:00",
    )
    assert isinstance(dto.fecha_publicacion, datetime)
    assert isinstance(dto.fecha_limite, datetime)
    assert dto.fecha_publicacion.year == 2024


def test_search_request_ya_no_vive_en_shared():
    """``SearchRequest`` salió de ``shared/dto.py`` el 2026-09-04.

    Era el sexto homónimo muerto de la familia que S4.7 retiró: ``shared/dto.py``
    definía uno (``question``/``top_k``) y ``api/routes/licitaciones.py`` define
    otro con forma distinta (``q``/``estado``/``ccaa``…), y es el de la ruta el
    que llega al esquema OpenAPI y a ``api.d.ts``. Ninguna ruta importaba el de
    ``shared``, así que su único efecto posible era el malo: que algún día los
    dos llegaran al esquema y FastAPI los renombrara con prefijo de módulo,
    reescribiendo ``components["schemas"]`` y rompiendo el cliente TS en cascada.

    Este test sustituye al que lo instanciaba. Fija la ausencia en vez de
    limitarse a desaparecer con la clase: si alguien vuelve a declararlo ahí, el
    homónimo reaparece en silencio y el ratchet ``_HOMONIMOS_TOLERADOS`` de
    ``tests/test_contract_dto.py`` —hoy vacío— tendría que volver a crecer.
    """
    import shared.dto as dto

    assert not hasattr(dto, "SearchRequest"), (
        "shared/dto.py vuelve a definir SearchRequest, homónimo del de "
        "api/routes/licitaciones.py. Ver el ratchet _HOMONIMOS_TOLERADOS."
    )
