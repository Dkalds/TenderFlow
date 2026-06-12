"""Tests de extracción de features predictivas (Fase 6, RFC 20260611-2)."""

from __future__ import annotations

import math

import pytest

from services.ml.features import (
    FEATURE_COLUMNS,
    _banda_importe,
    construir_dataset_baja,
    features_licitaciones_abiertas,
)


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _insert_par(
    c,
    lic_id,
    *,
    fecha,
    organo="Organo A",
    cpv="72000000",
    ccaa="Madrid",
    importe=100_000.0,
    adjudicado=85_000.0,
    n_ofertas=None,
    empresa=None,
):
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, ccaa, "
        " importe, tipo_contrato, fuente, fecha_publicacion, fecha_extraccion) "
        "VALUES (?, ?, ?, ?, ?, ?, 'Servicios', 'placsp', ?, datetime('now'))",
        (lic_id, f"Contrato {lic_id}", organo, cpv, ccaa, importe, fecha),
    )
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
        " fecha_adjudicacion, n_ofertas_recibidas, fecha_extraccion) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (lic_id, empresa or f"Empresa {lic_id}", adjudicado, fecha, n_ofertas),
    )


# ---------------------------------------------------------------------------
# Anti-fuga temporal (acceptance crítico del RFC)
# ---------------------------------------------------------------------------


def test_agregados_no_incluyen_filas_posteriores_ni_la_propia(db):
    from db.database import connect

    with connect() as c:
        # baja 15% en enero, baja 30% en marzo, fila objetivo en febrero
        _insert_par(c, "L1", fecha="2026-01-10", adjudicado=85_000.0)
        _insert_par(c, "L2", fecha="2026-02-10", adjudicado=90_000.0)  # baja 10%
        _insert_par(c, "L3", fecha="2026-03-10", adjudicado=70_000.0)  # baja 30%

    filas, _ = construir_dataset_baja()
    por_id = {f.licitacion_id: f for f in filas}

    # L1: primera observación → sin histórico
    assert por_id["L1"].features["baja_media_organo"] is None
    # L2 (febrero): solo ve L1 (15%), NUNCA su propia baja (10%) ni L3 (30%)
    assert por_id["L2"].features["baja_media_organo"] == pytest.approx(0.15)
    assert por_id["L2"].features["baja_media_cpv4"] == pytest.approx(0.15)
    # L3 (marzo): ve L1 y L2 → media (15+10)/2
    assert por_id["L3"].features["baja_media_organo"] == pytest.approx(0.125)


def test_hasta_excluye_filas_posteriores_al_corte(db):
    from db.database import connect

    with connect() as c:
        _insert_par(c, "L1", fecha="2026-01-10")
        _insert_par(c, "L2", fecha="2026-06-10")

    filas, _ = construir_dataset_baja(hasta="2026-03-01")

    assert [f.licitacion_id for f in filas] == ["L1"]


def test_ventana_movil_expira_a_24_meses(db):
    from db.database import connect

    with connect() as c:
        _insert_par(c, "VIEJA", fecha="2023-01-10", adjudicado=50_000.0)  # baja 50%
        _insert_par(c, "RECIENTE", fecha="2025-06-10", adjudicado=80_000.0)  # baja 20%
        _insert_par(c, "OBJETIVO", fecha="2026-01-10")

    filas, _ = construir_dataset_baja()
    objetivo = next(f for f in filas if f.licitacion_id == "OBJETIVO")

    # La baja del 50% de hace 3 años expiró; solo cuenta la del 20%
    assert objetivo.features["baja_media_organo"] == pytest.approx(0.20)


def test_hhi_segmento_es_estrictamente_anterior(db):
    from db.database import connect

    with connect() as c:
        _insert_par(c, "L1", fecha="2026-01-10", empresa="Alfa SL", adjudicado=80_000.0)
        _insert_par(c, "L2", fecha="2026-02-10", empresa="Beta SL", adjudicado=80_000.0)
        _insert_par(c, "L3", fecha="2026-03-10", empresa="Alfa SL")

    filas, _ = construir_dataset_baja()
    por_id = {f.licitacion_id: f for f in filas}

    assert por_id["L1"].features["hhi_segmento"] is None  # sin histórico
    assert por_id["L2"].features["hhi_segmento"] == pytest.approx(10_000.0)  # monopolio L1
    assert por_id["L3"].features["hhi_segmento"] == pytest.approx(5_000.0)  # 50/50


# ---------------------------------------------------------------------------
# Forma del dataset y features estáticas
# ---------------------------------------------------------------------------


def test_target_y_columnas(db):
    from db.database import connect

    with connect() as c:
        _insert_par(
            c, "L1", fecha="2026-02-10", importe=200_000.0, adjudicado=170_000.0, n_ofertas=5
        )

    filas, _ = construir_dataset_baja()

    assert len(filas) == 1
    fila = filas[0]
    assert fila.baja == pytest.approx(0.15)
    assert set(FEATURE_COLUMNS) == set(fila.features)
    assert fila.features["cpv2"] == "72"
    assert fila.features["cpv4"] == "7200"
    assert fila.features["banda_importe"] == "b3"  # 143k ≤ 200k < 221k
    assert fila.features["log_importe"] == pytest.approx(math.log1p(200_000.0))
    assert fila.features["n_ofertas"] == 5.0
    assert fila.features["mes"] == 2.0 and fila.features["trimestre"] == 1.0


def test_pares_invalidos_quedan_fuera(db):
    from db.database import connect

    with connect() as c:
        _insert_par(c, "OK", fecha="2026-01-10")
        _insert_par(c, "SIN_IMPORTE", fecha="2026-01-11", importe=0.0)
        _insert_par(c, "OUTLIER", fecha="2026-01-12", adjudicado=200_000.0)  # 2x presupuesto

    filas, _ = construir_dataset_baja()

    assert [f.licitacion_id for f in filas] == ["OK"]


def test_banda_importe():
    assert _banda_importe(None) == "b_na"
    assert _banda_importe(10_000) == "b0"
    assert _banda_importe(100_000) == "b2"
    assert _banda_importe(10_000_000) == "b6"


# ---------------------------------------------------------------------------
# Scoring de licitaciones abiertas
# ---------------------------------------------------------------------------


def test_features_abiertas_usa_historico_y_excluye_adjudicadas(db):
    from db.database import connect

    with connect() as c:
        _insert_par(c, "HIST", fecha="2026-01-10", adjudicado=85_000.0)
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, ccaa, "
            " importe, estado, fuente, fecha_publicacion, fecha_extraccion) "
            "VALUES ('ABIERTA', 'Nueva licitación', 'Organo A', '72000000', 'Madrid', "
            " 500000, 'PUB', 'placsp', '2026-06-01', datetime('now'))"
        )

    filas = features_licitaciones_abiertas(ahora="2026-06-10")

    assert [f.licitacion_id for f in filas] == ["ABIERTA"]
    fila = filas[0]
    assert fila.baja is None
    assert fila.features["baja_media_organo"] == pytest.approx(0.15)  # del histórico
    assert fila.features["n_ofertas"] is None  # aún desconocido
