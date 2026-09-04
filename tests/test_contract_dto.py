"""Tests de contrato para la frontera API ↔ dashboard.

Este fichero existe para que el contrato que consume ``web/src/generated/api.d.ts``
no derive en silencio: un renombre de campo, un cambio de tipo o una colisión de
nombres en un modelo de respuesta rompe el frontend en runtime sin que mypy ni
tsc digan una palabra.

**Qué cambió el 2026-09-03 (S4.7) y por qué.** Hasta esa fecha estos tests
verificaban los DTOs de ``shared/dto.py`` llamados ``LicitacionSummary``,
``LicitacionDetail``, ``AdjudicacionSummary``, ``ClusterSummary`` y
``KpiSnapshotDTO``. Ninguno de los cinco llegaba nunca al esquema OpenAPI
—ninguna ruta los usaba como ``response_model``; los tres primeros eran además
homónimos, con tipos distintos, de los modelos vivos de
``api/routes/licitaciones.py``—. O sea: el fichero medía un contrato imaginario
mientras el real quedaba sin cubrir. La prueba está en el propio cliente
generado, que describe ``LicitacionSummary`` con ``ml_proba_max`` y
``fecha_publicacion: string`` (la forma de la ruta) y no con el ``PgDateTime``
del DTO de ``shared``.

Al borrarse las cinco clases muertas, los tests se **reapuntan** a los modelos
que sí están en el esquema, en vez de perder la comprobación:

- ``api.routes.licitaciones.{LicitacionSummary,LicitacionDetail,AdjudicacionSummary}``
- ``shared.dto.{PaginatedResponse,CursorPaginatedResponse}`` (envelopes comunes)
- ``services.analytics.clusters.ClusterEntry`` — sustituto de ``ClusterSummary``
- ``services.analytics.organo_detail.OrganoKpis`` — sustituto de ``KpiSnapshotDTO``

Y se añade el guard que faltaba, el que habría cazado el problema entero: **el
esquema no puede contener dos modelos con el mismo nombre**. Cuando los hay,
FastAPI desambigua con prefijo de módulo
(``api__routes__licitaciones__LicitacionSummary``) y eso reescribe en bloque
``components["schemas"]`` del cliente TypeScript, rompiendo en cascada todo lo
que lo referencia. Ese era exactamente el riesgo que dormía en ``shared/dto.py``.

Los tests que necesitan el esquema construyen la app real, sin base de datos:
``app.openapi()`` sólo recorre los modelos declarados en las rutas.
"""

from __future__ import annotations

import inspect
import json
import sys
from typing import Any

import pytest
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Esquema OpenAPI real (una vez por módulo: construir la app cuesta segundos)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def openapi_schema() -> dict[str, Any]:
    """``app.openapi()`` de la aplicación real. No toca Postgres."""
    from api.app import app

    schema: dict[str, Any] = app.openapi()
    return schema


@pytest.fixture(scope="module")
def schema_components(openapi_schema: dict[str, Any]) -> dict[str, Any]:
    components: dict[str, Any] = openapi_schema["components"]["schemas"]
    return components


# ---------------------------------------------------------------------------
# Guard de colisión de nombres — el incidente que motivó S4.7
# ---------------------------------------------------------------------------


def test_openapi_has_no_module_prefixed_schema_names(schema_components: dict[str, Any]) -> None:
    """Ningún componente puede llevar el prefijo de módulo de FastAPI.

    FastAPI sólo genera nombres como ``api__routes__licitaciones__LicitacionSummary``
    cuando dos modelos homónimos alcanzan el esquema. Ese renombrado no es
    cosmético: ``web/src/generated/api.d.ts`` referencia los componentes por
    nombre, así que la desambiguación reescribe el cliente entero y rompe el
    frontend. Si este test se pone rojo hay dos DTOs compitiendo por un nombre,
    y la solución es renombrar uno (sufijo de dominio, como ``LicitacionPublica``),
    no regenerar el cliente.
    """
    prefixed = sorted(name for name in schema_components if "__" in name)
    assert prefixed == [], (
        "FastAPI desambiguó estos componentes por colisión de nombres; "
        f"el cliente TypeScript se reescribe entero: {prefixed}"
    )


# Ratchet de homónimos en el código fuente, con el mismo patrón que
# ``ALLOWED_OPAQUE`` en ``scripts/check_openapi_contract.py``: **sólo puede
# encoger**. Un nombre aquí es una bomba desactivada a medias — el homónimo
# existe, pero hoy sólo uno de los dos llega al esquema, así que el test de
# arriba no lo ve.
#
# **Está VACÍO desde el 2026-09-04 y así se queda.** Su único inquilino fue
# ``SearchRequest``: ``shared/dto.py`` definía uno (``question``/``top_k``) y
# ``api/routes/licitaciones.py`` define otro (``q``/``limit``/``offset``), y era
# el de la ruta el que llegaba al esquema y a ``api.d.ts``. Al de ``shared`` no
# lo importaba ninguna ruta — el sexto homónimo muerto de la familia que S4.7
# retiró, superviviente porque aquel barrido cubrió sólo las cinco del plan.
# Se borró al cerrar el plan, así que la bomba está desactivada del todo.
# Añadir un nombre aquí es admitir que dos modelos comparten nombre y confiar en
# que sólo uno llegue al esquema; si los dos llegan, FastAPI los renombra con
# prefijo de módulo y eso reescribe ``components["schemas"]`` del cliente TS.
_HOMONIMOS_TOLERADOS: frozenset[str] = frozenset()


def _models_defined_in(module: Any) -> set[str]:
    """Nombres de los ``BaseModel`` **definidos** en ese módulo (no importados)."""
    return {
        name
        for name, obj in vars(module).items()
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj.__module__ == module.__name__
    }


def test_shared_dto_does_not_shadow_route_models(openapi_schema: dict[str, Any]) -> None:
    """``shared/dto.py`` no puede redefinir el nombre de un modelo de ruta.

    La fixture ``openapi_schema`` se pide por su efecto: importa ``api.app``, que
    a su vez importa los 30 módulos de rutas. Sin eso ``sys.modules`` no tendría
    con quién comparar y el test pasaría vacío.

    Un homónimo aquí es una bomba con la espoleta puesta: mientras sólo uno de
    los dos modelos alcance el esquema no pasa nada, y el día que alguien use el
    de ``shared`` para tipar una ruta se renombran los dos y el cliente TS se
    reescribe entero. Es literalmente lo que estuvo a punto de pasar con
    ``LicitacionSummary``, ``LicitacionDetail`` y ``AdjudicacionSummary``.
    """
    del openapi_schema  # sólo interesa su efecto colateral: importar las rutas

    import shared.dto as shared_dto

    shared_names = _models_defined_in(shared_dto)
    colisiones: dict[str, list[str]] = {}
    for mod_name, module in sorted(sys.modules.items()):
        if not mod_name.startswith("api.routes.") or module is None:
            continue
        for dup in sorted(shared_names & _models_defined_in(module)):
            colisiones.setdefault(dup, []).append(mod_name)

    nuevas = {k: v for k, v in colisiones.items() if k not in _HOMONIMOS_TOLERADOS}
    assert nuevas == {}, (
        "Modelos homónimos entre shared/dto.py y las rutas; FastAPI los "
        f"renombrará con prefijo de módulo si ambos llegan al esquema: {nuevas}"
    )
    # El ratchet sólo encoge: si un tolerado deja de colisionar hay que sacarlo
    # de la lista, o volvería a colarse uno nuevo sin hacer ruido.
    resueltos = _HOMONIMOS_TOLERADOS - colisiones.keys()
    assert resueltos == set(), (
        f"Estos homónimos ya no existen: sacalos de _HOMONIMOS_TOLERADOS: {sorted(resueltos)}"
    )


# ---------------------------------------------------------------------------
# LicitacionSummary — contrato mínimo (api/routes/licitaciones.py)
# ---------------------------------------------------------------------------


def test_summary_required_field_id_externo() -> None:
    """``id_externo`` es el identificador único del contrato: siempre presente."""
    import pydantic

    from api.routes.licitaciones import LicitacionSummary

    with pytest.raises((pydantic.ValidationError, TypeError)):
        LicitacionSummary()  # type: ignore[call-arg]  # sin id_externo ni titulo


def test_summary_json_round_trip() -> None:
    """Serializar a JSON y deserializar produce el mismo DTO."""
    from api.routes.licitaciones import LicitacionSummary

    original = LicitacionSummary(
        id_externo="ES-2024-001",
        titulo="Licitación SAP S/4HANA",
        organo_contratacion="Ministerio de Hacienda",
        importe=150_000.0,
        estado="PUB",
        fecha_publicacion="2024-01-15T10:00:00Z",
        ccaa="MD",
        cpv="72267100",
        tecnologia="SAP",
    )
    restored = LicitacionSummary.model_validate_json(original.model_dump_json())
    assert restored.id_externo == original.id_externo
    assert restored.importe == original.importe
    assert restored.ccaa == original.ccaa


def test_summary_fields_match_generated_client(schema_components: dict[str, Any]) -> None:
    """El componente ``LicitacionSummary`` del esquema es el modelo de la ruta.

    Comparar campo a campo es lo que distingue «el nombre está» de «el nombre
    apunta a lo que el frontend cree». Si un homónimo ganara el nombre, este
    test lo vería aunque el guard de prefijos no (ese sólo dispara cuando los
    **dos** modelos llegan al esquema).
    """
    from api.routes.licitaciones import LicitacionSummary

    componente = set(schema_components["LicitacionSummary"]["properties"])
    assert componente == set(LicitacionSummary.model_fields)


def test_summary_fechas_viajan_como_string(schema_components: dict[str, Any]) -> None:
    """En este contrato las fechas son strings, no ``date-time``.

    El DTO muerto de ``shared/dto.py`` las tipaba como ``PgDateTime``; de haber
    llegado al esquema, el cliente generado las habría recibido con
    ``format: date-time``. El vivo las pasa tal cual las devuelve el
    repositorio. Fijarlo evita que un «arreglo» bienintencionado cambie el tipo
    bajo los pies del frontend.
    """
    from api.routes.licitaciones import LicitacionSummary

    dto = LicitacionSummary(
        id_externo="X",
        titulo="T",
        fecha_publicacion="2024-01-15T10:00:00Z",
        fecha_limite="2024-02-01T00:00:00+00:00",
    )
    assert dto.fecha_publicacion == "2024-01-15T10:00:00Z"
    assert isinstance(dto.fecha_limite, str)

    props = schema_components["LicitacionSummary"]["properties"]
    for campo in ("fecha_publicacion", "fecha_limite"):
        tipos = {variant.get("type") for variant in props[campo]["anyOf"]}
        assert tipos == {"string", "null"}, f"{campo} dejó de ser string en el esquema: {tipos}"


# ---------------------------------------------------------------------------
# LicitacionDetail — herencia y campos extra
# ---------------------------------------------------------------------------


def test_detail_inherits_all_summary_fields() -> None:
    """``LicitacionDetail`` incluye todos los campos de ``LicitacionSummary``."""
    from api.routes.licitaciones import LicitacionDetail, LicitacionSummary

    summary_fields = set(LicitacionSummary.model_fields)
    detail_fields = set(LicitacionDetail.model_fields)
    assert summary_fields.issubset(detail_fields), (
        f"LicitacionDetail pierde campos de LicitacionSummary: {summary_fields - detail_fields}"
    )


def test_detail_extra_fields_present() -> None:
    """``LicitacionDetail`` tiene campos adicionales sobre ``LicitacionSummary``."""
    from api.routes.licitaciones import LicitacionDetail, LicitacionSummary

    extra = set(LicitacionDetail.model_fields) - set(LicitacionSummary.model_fields)
    assert "descripcion" in extra
    assert "tipo_contrato" in extra
    assert "fecha_extraccion" in extra


def test_detail_fecha_as_iso_string() -> None:
    """Los campos de fecha del detalle aceptan y conservan strings ISO 8601."""
    from api.routes.licitaciones import LicitacionDetail

    dto = LicitacionDetail(
        id_externo="X",
        titulo="T",
        fecha_publicacion="2024-01-15T10:00:00Z",
        fecha_limite="2024-02-01T00:00:00+00:00",
        fecha_extraccion="2024-01-16T03:00:00Z",
    )
    assert dto.fecha_publicacion == "2024-01-15T10:00:00Z"
    assert dto.fecha_extraccion == "2024-01-16T03:00:00Z"


# ---------------------------------------------------------------------------
# AdjudicacionSummary
# ---------------------------------------------------------------------------


def test_adjudicacion_required_fields() -> None:
    """``id``, ``licitacion_id`` y ``nombre`` son obligatorios en el contrato.

    El DTO muerto de ``shared`` dejaba ``nombre`` opcional y no tenía ``id``; el
    vivo los exige porque el frontend enlaza la fila por ``id`` y pinta el
    adjudicatario sin comprobar nulos.
    """
    import pydantic

    from api.routes.licitaciones import AdjudicacionSummary

    with pytest.raises(pydantic.ValidationError):
        AdjudicacionSummary(licitacion_id="X")  # type: ignore[call-arg]


def test_adjudicacion_json_round_trip() -> None:
    from api.routes.licitaciones import AdjudicacionSummary

    original = AdjudicacionSummary(
        id=1,
        licitacion_id="ES-2024-001",
        nombre="Empresa SAP S.L.",
        nif="B12345678",
        importe_adjudicado=120_000.0,
        ccaa="MD",
    )
    restored = AdjudicacionSummary.model_validate_json(original.model_dump_json())
    assert restored.licitacion_id == original.licitacion_id
    assert restored.importe_adjudicado == original.importe_adjudicado


def test_adjudicacion_fields_match_generated_client(schema_components: dict[str, Any]) -> None:
    from api.routes.licitaciones import AdjudicacionSummary

    componente = set(schema_components["AdjudicacionSummary"]["properties"])
    assert componente == set(AdjudicacionSummary.model_fields)


# ---------------------------------------------------------------------------
# PaginatedResponse / CursorPaginatedResponse — envelopes comunes
# ---------------------------------------------------------------------------


def test_paginated_response_structure() -> None:
    from api.routes.licitaciones import LicitacionSummary
    from shared.dto import PaginatedResponse

    items = [LicitacionSummary(id_externo=f"ES-{i}", titulo=f"T{i}") for i in range(3)]
    resp = PaginatedResponse[LicitacionSummary](items=items, total=100, limit=3, offset=0)
    assert len(resp.items) == 3
    assert resp.total == 100
    assert resp.limit == 3
    assert resp.offset == 0


def test_paginated_response_no_more() -> None:
    from api.routes.licitaciones import LicitacionSummary
    from shared.dto import PaginatedResponse

    items = [LicitacionSummary(id_externo="ES-1", titulo="T1")]
    resp = PaginatedResponse[LicitacionSummary](items=items, total=1, limit=10, offset=0)
    assert resp.total == 1


def test_paginated_component_names_are_stable(schema_components: dict[str, Any]) -> None:
    """Los nombres que ``api.d.ts`` referencia para los envelopes no se mueven.

    ``PaginatedResponse`` y ``CursorPaginatedResponse`` se mudaron de la ruta a
    ``shared/dto.py`` conservando el nombre exacto justo por esto: FastAPI
    deriva de él el componente OpenAPI y el cliente TS lo referencia literal.
    """
    for nombre in (
        "PaginatedResponse_LicitacionSummary_",
        "PaginatedResponse_AdjudicacionSummary_",
        "CursorPaginatedResponse_LicitacionSummary_",
    ):
        assert nombre in schema_components, f"desapareció del esquema: {nombre}"


# ---------------------------------------------------------------------------
# KPIs — sustituto vivo de KpiSnapshotDTO
# ---------------------------------------------------------------------------


def test_kpis_defaults() -> None:
    """Los contadores de KPIs arrancan en cero, no en ``None``.

    Era la propiedad que cubría ``KpiSnapshotDTO`` (muerto): un tablero que
    recibe ``null`` donde espera un contador pinta «—» en vez de «0». La lleva
    ``OrganoKpis``, que sí está en el esquema.
    """
    from services.analytics.organo_detail import OrganoKpis

    kpis = OrganoKpis()
    assert kpis.total_licitaciones == 0
    assert kpis.importe_total == pytest.approx(0.0)
    assert kpis.importe_medio == pytest.approx(0.0)
    assert kpis.lead_time_medio is None


def test_kpis_serialization() -> None:
    from services.analytics.organo_detail import OrganoKpis

    kpis = OrganoKpis(
        total_licitaciones=500,
        importe_total=15_000_000.0,
        importe_medio=75_000.0,
        pct_adjudicado=40.0,
    )
    data = json.loads(kpis.model_dump_json())
    assert data["total_licitaciones"] == 500
    assert data["importe_total"] == 15_000_000.0


# ---------------------------------------------------------------------------
# Clusters — sustituto vivo de ClusterSummary
# ---------------------------------------------------------------------------


def test_cluster_entry_contract() -> None:
    """El agregado por cluster conserva id, etiqueta y tamaño.

    Traslado de ``test_cluster_summary``: el DTO muerto llamaba ``size`` a lo
    que el vivo llama ``n``, pero la propiedad protegida es la misma —cada
    cluster viaja identificado y con su tamaño— y este sí llega al esquema.
    """
    from services.analytics.clusters import ClusterEntry

    entry = ClusterEntry(
        cluster_id=0,
        label="SAP · ERP · implantación",
        n=10,
        importe_medio=100_000.0,
        importe_total=1_000_000.0,
    )
    assert entry.cluster_id == 0
    assert entry.n == 10
    assert entry.items == []  # el drill-down es opcional, no obligatorio


def test_cluster_entry_in_schema(schema_components: dict[str, Any]) -> None:
    from services.analytics.clusters import ClusterEntry

    componente = set(schema_components["ClusterEntry"]["properties"])
    assert componente == set(ClusterEntry.model_fields)
