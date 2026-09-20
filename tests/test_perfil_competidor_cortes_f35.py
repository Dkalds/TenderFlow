"""F3.5 — el perfil de competidor publica los cortes por procedimiento y tramo.

``corte_por_procedimiento`` y ``corte_por_tramo`` existían en
``services/competitive/batallas.py`` sin ninguna llamada: el perfil seguía
cortando solo por CPV, CCAA y año. Aquí se fija que el dossier los calcula
sobre la **misma actividad filtrada** que ``totales`` y que el contrato los
declara con su ``n`` y su mínimo.
"""

from __future__ import annotations

from typing import Any

import pytest

from db.repositories.mercado import FilasPerfil
from services.competitive import mercado as svc
from shared.dto import CompetitiveCompanyProfileDTO


def _adjudicacion(i: int, *, procedimiento: str, presupuesto: float, adjudicado: float) -> Any:
    return {
        "licitacion_id": f"LIC-{i}",
        "titulo": f"Expediente {i}",
        "fecha_adjudicacion": "2026-03-01",
        "importe_adjudicado": adjudicado,
        "n_ofertas_recibidas": 3,
        "presupuesto_licitacion": presupuesto,
        "organo_contratacion": "Órgano",
        "ccaa": "Madrid",
        "cpv": "72000000",
        "tecnologia": "SAP",
        "procedimiento": procedimiento,
    }


@pytest.fixture()
def perfil(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    # Cinco abiertos de 100k adjudicados a 80k (baja 0,20) y dos negociados de
    # 10k: la primera celda llega al mínimo y la segunda no.
    actividad = [
        _adjudicacion(i, procedimiento="1", presupuesto=100_000, adjudicado=80_000)
        for i in range(5)
    ] + [
        _adjudicacion(10 + i, procedimiento="3", presupuesto=10_000, adjudicado=9_000)
        for i in range(2)
    ]
    filas = FilasPerfil(
        identidades=[{"empresa_id": 1, "nombre_canonico": "Rival SA", "nif_canonico": None}],
        historia=[{"contratos": 7, "importe_total": 418_000}],
        actividad=actividad,
        base=actividad,
        posicion=[],
        utes=[],
        actividad_utes=[],
        miembros_utes=[],
    )
    monkeypatch.setattr(svc.mercado_repo, "filas_perfil_empresa", lambda *a, **k: filas)
    return svc.perfil_empresa(1)


def test_el_contrato_valida_con_los_cortes_nuevos(perfil: dict[str, Any]) -> None:
    perfil.pop("_exists", None)
    dto = CompetitiveCompanyProfileDTO.model_validate(perfil)
    assert dto.corte_min_n == 5
    assert {c.clave for c in dto.por_tramo_importe} == {"60k-140k", "< 15k"}


def test_por_procedimiento_usa_la_etiqueta_y_respeta_el_minimo(perfil: dict[str, Any]) -> None:
    celdas = {c["clave"]: c for c in perfil["por_procedimiento"]}
    assert len(celdas) == 2
    grande = max(celdas.values(), key=lambda c: c["n"])
    pequena = min(celdas.values(), key=lambda c: c["n"])
    # La etiqueta de F1.7, no el código crudo.
    assert grande["clave"] != "1"
    assert grande["n"] == 5
    assert grande["baja_media"] == pytest.approx(0.2)
    assert grande["importe_total"] == pytest.approx(400_000)
    # Por debajo del mínimo: la celda sale con su `n`, sin media.
    assert pequena["n"] == 2
    assert pequena["baja_media"] is None
    assert pequena["importe_total"] is None


def test_por_tramo_mide_contra_el_presupuesto_de_licitacion(perfil: dict[str, Any]) -> None:
    celdas = {c["clave"]: c for c in perfil["por_tramo_importe"]}
    assert celdas["60k-140k"]["n"] == 5
    assert celdas["60k-140k"]["baja_media"] == pytest.approx(0.2)
    assert celdas["< 15k"]["n"] == 2
    assert celdas["< 15k"]["baja_media"] is None
