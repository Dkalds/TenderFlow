"""Tests de extracción de features predictivas (Fase 6, RFC 20260611-2)."""

from __future__ import annotations

import math
from datetime import datetime

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
        "VALUES (%s, %s, %s, %s, %s, %s, 'Servicios', 'placsp', %s, CURRENT_TIMESTAMP)",
        (lic_id, f"Contrato {lic_id}", organo, cpv, ccaa, importe, fecha),
    )
    c.execute(
        "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
        " fecha_adjudicacion, n_ofertas_recibidas, fecha_extraccion) "
        "VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)",
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
    assert fila.features["mes"] == 2.0 and fila.features["trimestre"] == 1.0
    # `n_ofertas_recibidas` ya no es feature: solo existe DESPUÉS de adjudicar,
    # así que en scoring era NaN siempre. La competencia entra por el histórico
    # del segmento, que en la primera fila todavía está vacío.
    assert "n_ofertas" not in fila.features
    assert fila.features["n_ofertas_media_cpv4"] is None
    assert fila.features["n_obs_cpv4"] == 0.0
    assert fila.features["n_lotes"] == 0.0  # sin filas en `lotes`


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
        _insert_par(c, "HIST", fecha="2026-01-10", adjudicado=85_000.0, n_ofertas=4)
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, organo_contratacion, cpv, ccaa, "
            " importe, estado, fuente, fecha_publicacion, fecha_extraccion) "
            "VALUES ('ABIERTA', 'Nueva licitación', 'Organo A', '72000000', 'Madrid', "
            " 500000, 'PUB', 'placsp', '2026-06-01', CURRENT_TIMESTAMP)"
        )

    filas = features_licitaciones_abiertas(ahora="2026-06-10")

    assert [f.licitacion_id for f in filas] == ["ABIERTA"]
    fila = filas[0]
    assert fila.baja is None
    assert fila.features["baja_media_organo"] == pytest.approx(0.15)  # del histórico
    # La competencia esperada SÍ está disponible al servir: sale del histórico
    # del segmento, no de la adjudicación (que aún no existe). Es el reemplazo
    # de `n_ofertas`, que era NaN en el 100% de las filas de scoring.
    assert fila.features["n_ofertas_media_cpv4"] == pytest.approx(4.0)
    # El ancla es la publicación de la propia licitación (2026-06-01), no `ahora`.
    assert fila.fecha == "2026-06-01"
    assert fila.features["mes"] == 6.0


# ---------------------------------------------------------------------------
# Fechas con año de menos de cuatro cifras (regresión 2026-09)
# ---------------------------------------------------------------------------
#
# `%Y` NO es simétrico: `strptime` exige exactamente cuatro dígitos, pero el
# `strftime` de glibc no rellena con ceros los años < 1000 (el de Windows sí).
# Una `fecha_adjudicacion` de '0019-12-10' -- la tiene el expediente
# `19/002/5-2` en producción, y '0202-02-27' otro de PSCP -- parseaba bien,
# ganaba el `LEAST` que calcula `fecha_anchor`, se reserializaba como
# '19-12-10' y reventaba el siguiente parseo dentro de `_folds_rolling`. El
# reentrenamiento mensual de `train-predictivos.yml` llevaba desde el
# 2026-09-01 en rojo por esa única fila, y solo en Linux.


def test_fecha_opt_descarta_los_anios_de_menos_de_cuatro_cifras():
    from services.ml.features import _fecha_opt

    assert _fecha_opt("0019-12-10") is None  # expediente 19/002/5-2
    assert _fecha_opt("0202-02-27") is None  # pscp:1233348-0001
    assert _fecha_opt("2024-05-01") == datetime(2024, 5, 1)


def test_el_ancla_cae_a_la_publicacion_cuando_el_anchor_tiene_anio_corto():
    from services.ml.features import _ancla

    ancla = _ancla(
        {"fecha_anchor": "0019-12-10", "fecha_publicacion": "2024-05-01"},
        datetime(2030, 1, 1),
    )
    assert ancla == datetime(2024, 5, 1)


def test_la_fecha_serializada_siempre_se_puede_volver_a_parsear():
    """`FilaDataset.fecha` se relee con `_fecha_dt`, que exige cuatro dígitos
    de año. `isoformat` los rellena en cualquier plataforma; `strftime('%Y')`
    no lo hace en glibc."""
    from services.ml.features import _fecha_dt

    assert _fecha_dt(datetime(19, 12, 10).date().isoformat()) == datetime(19, 12, 10)


def test_una_adjudicacion_con_anio_corto_no_rompe_el_dataset(db):
    from db.database import connect
    from services.ml.features import _fecha_dt

    with connect() as c:
        _insert_par(c, "ANIO-CORTO", fecha="2026-05-01")
        c.execute(
            "UPDATE adjudicaciones SET fecha_adjudicacion = %s WHERE licitacion_id = %s",
            ("0019-12-10", "ANIO-CORTO"),
        )

    filas, _ = construir_dataset_baja()

    fila = next(f for f in filas if f.licitacion_id == "ANIO-CORTO")
    # El ancla cae a la publicación, y la cadena resultante se relee sin error
    # (que es exactamente lo que hacía `_folds_rolling` cuando reventaba).
    assert _fecha_dt(fila.fecha) == datetime(2026, 5, 1)
