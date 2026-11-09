"""Exportar una sección de Competencia o Mercado baja su tabla, no el listado.

Hasta 2026-11 los botones «Exportar competidores», «Exportar UTE», etc.
mandaban un ``section`` que el backend no leía y devolvían licitaciones.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from services import exports
from services.analytics.competitors import CompetitorEntry, CompetitorFilters, CompetitorResult
from services.analytics.geography import GeoEntry, GeoFilters, GeoResult


def test_competidores_sale_de_su_servicio_con_sus_filtros(monkeypatch: pytest.MonkeyPatch) -> None:
    vistos: list[CompetitorFilters] = []

    def falso(filtros: CompetitorFilters) -> CompetitorResult:
        vistos.append(filtros)
        entrada = CompetitorEntry(
            nombre="ACME", count=3, importe=1000.0, cuota=12.5, nifs=["A1", "A2"]
        )
        return CompetitorResult(competitors=[entrada])

    monkeypatch.setattr(exports, "get_competitors", falso)
    filtros: Mapping[str, object] = {
        "ccaa": "Madrid",
        "estado": "RES",
        "q": "sap",  # la tabla de competidores no busca por texto
        "fecha_desde": "2026-01-01",
        "tecnologia": None,
        "limit": 10000,
    }

    filas = exports.filas_de_seccion("competidores", filtros)

    assert [f["Nombre"] for f in filas] == ["ACME"]
    # Las listas no caben en una celda: fuera.
    assert "nifs" not in filas[0]
    assert vistos[0].ccaa == "Madrid"
    assert vistos[0].estado == "RES"
    assert vistos[0].limit == 100


def test_geografia_ignora_los_filtros_que_su_pantalla_no_aplica(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vistos: list[GeoFilters] = []

    def falso(filtros: GeoFilters) -> GeoResult:
        vistos.append(filtros)
        return GeoResult(by_ccaa=[GeoEntry(ccaa="Galicia", count=2, importe=50.0, pct=1.0)])

    monkeypatch.setattr(exports, "get_geography", falso)

    filas = exports.filas_de_seccion("geografia", {"estado": "PUB", "tecnologia": "SAP"})

    assert filas == [
        {
            "Comunidad autónoma": "Galicia",
            "Licitaciones": 2,
            "Importe (€)": 50.0,
            "% del total": 1.0,
            "Importe medio (€)": None,
        }
    ]
    assert vistos[0].tecnologia == "SAP"


def test_una_seccion_en_pdf_es_un_422_aunque_el_limite_lo_mandara_a_la_cola() -> None:
    """Antes de este orden, un PDF grande de «competidores» encolaba el de licitaciones."""
    import asyncio

    from fastapi import HTTPException

    import api.routes.exports as rutas

    parametros: dict[str, object] = {
        "format": "pdf",
        "recurso": "competidores",
        "pursuit_status": None,
        "responsible_user_id": None,
        "q": None,
        "estado": None,
        "ccaa": None,
        "tecnologia": None,
        "fecha_desde": None,
        "fecha_hasta": None,
        "importe_min": None,
        "importe_max": None,
        "provincia": None,
        "procedimiento": None,
        "solo_abiertas": False,
        "cierre_desde": None,
        "cierre_hasta": None,
        "organo_q": None,
        "limit": 50000,
        "organization_id": None,
        "por_lote": False,
    }

    with pytest.raises(HTTPException) as error:
        asyncio.run(rutas.download_export(**parametros, _user={"user_id": 1}))  # type: ignore[arg-type]  # el dict junta parámetros de tipos distintos
    assert error.value.status_code == 422


def test_utes_organos_y_tecnologias_salen_de_sus_tablas(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.analytics.organos import OrganoEntry, OrganosFilters, OrganosResult
    from services.analytics.tecnologias import TecnologiaEntry, TecnologiasResult
    from services.analytics.utes import UTEMiembro, UTEResult

    organos_vistos: list[OrganosFilters] = []

    def organos_falso(filtros: OrganosFilters) -> OrganosResult:
        organos_vistos.append(filtros)
        return OrganosResult(
            organos=[OrganoEntry(organo_contratacion="Ayto. X", count=1, importe=9.0, pct=100.0)]
        )

    monkeypatch.setattr(
        exports,
        "get_utes",
        lambda f: UTEResult(top_miembros=[UTEMiembro(nombre="UTE A", count=2, importe=5.0)]),
    )
    monkeypatch.setattr(exports, "get_organos", organos_falso)
    monkeypatch.setattr(
        exports,
        "get_tecnologias",
        lambda f: TecnologiasResult(
            tecnologias=[
                TecnologiaEntry(
                    tecnologia="SAP",
                    count=3,
                    importe=30.0,
                    importe_medio=10.0,
                    pct=50.0,
                    pct_adjudicado=20.0,
                )
            ]
        ),
    )

    assert exports.filas_de_seccion("utes", {})[0]["Nombre"] == "UTE A"
    assert exports.filas_de_seccion("organos", {})[0]["Órgano de contratación"] == "Ayto. X"
    # Como competidores: el tope del endpoint, no el de la pantalla.
    assert organos_vistos[0].limit == 500
    assert exports.filas_de_seccion("tecnologias", {})[0]["% adjudicado"] == 20.0


def _descargar(monkeypatch: pytest.MonkeyPatch, formato: str, filas: object) -> object:
    """Llama a la ruta con una sección, sin BD: la tabla y el log van doblados."""
    import asyncio

    import api.routes.exports as rutas

    def filas_falsas(seccion: str, filtros: Mapping[str, object]) -> object:
        return filas() if callable(filas) else filas

    monkeypatch.setattr(exports, "filas_de_seccion", filas_falsas)
    monkeypatch.setattr(rutas, "log_event", lambda **_: None)
    parametros: dict[str, object] = {
        "format": formato,
        "recurso": "utes",
        "pursuit_status": None,
        "responsible_user_id": None,
        "q": None,
        "estado": None,
        "ccaa": None,
        "tecnologia": None,
        "fecha_desde": None,
        "fecha_hasta": None,
        "importe_min": None,
        "importe_max": None,
        "provincia": None,
        "procedimiento": None,
        "solo_abiertas": False,
        "cierre_desde": None,
        "cierre_hasta": None,
        "organo_q": None,
        "limit": 100,
        "organization_id": None,
        "por_lote": False,
    }
    return asyncio.run(rutas.download_export(**parametros, _user={"user_id": 1}))  # type: ignore[arg-type]  # el dict junta parámetros de tipos distintos


def test_la_ruta_baja_la_seccion_en_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    respuesta = _descargar(monkeypatch, "csv", [{"Nombre": "UTE A", "Licitaciones": 2}])

    assert respuesta.media_type.startswith("text/csv")  # type: ignore[attr-defined]  # Response
    assert "UTE A" in respuesta.body.decode("utf-8-sig")  # type: ignore[attr-defined]  # Response
    assert "utes" in respuesta.headers["content-disposition"]  # type: ignore[attr-defined]  # Response


def test_la_ruta_baja_la_seccion_en_excel(monkeypatch: pytest.MonkeyPatch) -> None:
    respuesta = _descargar(monkeypatch, "excel", [{"Nombre": "UTE A", "Licitaciones": 2}])

    assert "spreadsheetml" in respuesta.media_type  # type: ignore[attr-defined]  # Response
    assert respuesta.body[:2] == b"PK"  # type: ignore[attr-defined]  # un .xlsx es un zip


def test_un_filtro_mal_escrito_es_un_422(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    from services.analytics.utes import UTEFilters

    def invalido() -> object:
        return UTEFilters.model_validate({"fecha_desde": ["no", "es", "texto"]})

    with pytest.raises(HTTPException) as error:
        _descargar(monkeypatch, "csv", invalido)
    assert error.value.status_code == 422
