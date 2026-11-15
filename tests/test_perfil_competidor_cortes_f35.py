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
from services.competitive.batallas import corte_por_procedimiento, corte_por_tramo
from shared.dto import CompetitiveCompanyProfileDTO


def _adjudicacion(
    i: int,
    *,
    procedimiento: str,
    presupuesto: float,
    adjudicado: float,
    lote: float | None = None,
) -> Any:
    return {
        "licitacion_id": f"LIC-{i}",
        "titulo": f"Expediente {i}",
        "fecha_adjudicacion": "2026-03-01",
        "importe_adjudicado": adjudicado,
        "n_ofertas_recibidas": 3,
        "presupuesto_licitacion": presupuesto,
        # `BASE_COMPARABLE_SQL`: el lote si lo hay, si no el expediente.
        "presupuesto_comparable": presupuesto if lote is None else lote,
        "organo_contratacion": "Órgano",
        "ccaa": "Madrid",
        "cpv": "72000000",
        "tecnologia": "SAP",
        "procedimiento": procedimiento,
    }


def _abiertos() -> list[Any]:
    """Cinco abiertos de 100k adjudicados a 80k: baja 0,20."""
    return [
        _adjudicacion(i, procedimiento="1", presupuesto=100_000, adjudicado=80_000)
        for i in range(5)
    ]


def _imposibles() -> list[Any]:
    """Los dos pares que no son una baja: el real de 87.095 € sobre un lote de
    100 € de un expediente de 123.504 € (contra el expediente parecería una baja
    del 29,5 %) y un adjudicado de 0."""
    return [
        _adjudicacion(20, procedimiento="1", presupuesto=123_504, lote=100, adjudicado=87_095),
        _adjudicacion(21, procedimiento="1", presupuesto=100_000, adjudicado=0),
    ]


@pytest.fixture()
def perfil(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    # Los cinco abiertos y dos negociados de 10k: la primera celda llega al
    # mínimo y la segunda no.
    actividad = _abiertos() + [
        _adjudicacion(10 + i, procedimiento="3", presupuesto=10_000, adjudicado=9_000)
        for i in range(2)
    ]
    return _perfil(monkeypatch, actividad)


def _perfil(monkeypatch: pytest.MonkeyPatch, actividad: list[Any]) -> dict[str, Any]:
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
    # Las actas son otra consulta (``tests/test_puntuaciones_acta_repo.py``).
    monkeypatch.setattr(svc, "perfil_por_criterio", lambda *a, **k: None)
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


def test_la_baja_media_del_dossier_descarta_los_pares_imposibles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    perfil = _perfil(monkeypatch, _abiertos() + _imposibles())
    # Contra el expediente y sin filtro, la media era del 32,8 %: el lote de
    # 100 € pasaba por una baja del 29,5 % y el adjudicado de 0, por una del 100 %.
    assert perfil["totales"]["baja_media_pct"] == pytest.approx(20.0)
    # Siguen siendo contratos de la empresa: solo salen de la media.
    assert perfil["totales"]["contratos"] == 7


def _filas_corte() -> list[Any]:
    return [
        {**fila, "importe": fila["presupuesto_licitacion"]} for fila in _abiertos() + _imposibles()
    ]


def test_el_corte_cuenta_los_pares_imposibles_pero_no_los_promedia() -> None:
    (celda,) = corte_por_procedimiento(_filas_corte())
    assert celda.n == 7
    assert celda.baja_media == pytest.approx(0.2)


def test_el_tramo_sigue_siendo_el_del_expediente() -> None:
    # La baja se mide contra el lote, pero el régimen LCSP lo fija el expediente:
    # el lote de 100 € de un expediente de 123.504 € no es un contrato menor.
    celdas = {c.clave: c.n for c in corte_por_tramo(_filas_corte())}
    assert celdas == {"60k-140k": 7}
