"""Modo sombra del modelo de baja (v174).

El batch sirve lo de siempre (modelo activo o baseline) y, además, puntúa la
versión registrada más nueva que la activa en ``predicciones_baja_sombra``.
Cuando esas licitaciones se adjudican, la calibración del candidato se mide
contra la realidad y contra lo servido sobre los mismos expedientes.
"""

from __future__ import annotations

import pytest

import services.ml.baja_model as baja_model_mod
from services.ml.baja_model import MODEL_NAME, entrenar
from services.ml.scoring import score_predicciones_baja
from tests.test_ml_baja_model import _insertar_abierta, _sembrar_historico


@pytest.fixture()
def db(tmp_db):
    db_mod, _ = tmp_db
    return db_mod


def _filas_sombra(c) -> list[tuple[str, int]]:
    return c.execute(
        "SELECT licitacion_id, model_version FROM predicciones_baja_sombra ORDER BY 1"
    ).fetchall()


def test_el_candidato_se_puntua_en_sombra_sin_servirse(db, monkeypatch, tmp_path):
    monkeypatch.setattr(baja_model_mod, "MIN_TRAIN_SAMPLES", 40)
    with db.connect() as c:
        _sembrar_historico(c)
        _insertar_abierta(c, "AB-1")
    entrenar(activar=False, model_path=tmp_path / "baja.pkl")

    stats = score_predicciones_baja()

    assert stats["serving"] == "baseline"
    assert stats["sombra"] == {"version": 1, "filas": 1}
    with db.connect() as c:
        assert _filas_sombra(c) == [("AB-1", 1)]
        servida = c.execute(
            "SELECT model_version FROM predicciones_baja WHERE licitacion_id = 'AB-1'"
        ).fetchone()
    assert servida[0] is None, "lo servido sigue siendo el baseline"


def test_sin_candidato_mas_nuevo_que_la_activa_no_hay_sombra(db, monkeypatch, tmp_path):
    from db.model_registry import activate_version

    monkeypatch.setattr(baja_model_mod, "MIN_TRAIN_SAMPLES", 40)
    with db.connect() as c:
        _sembrar_historico(c)
        _insertar_abierta(c, "AB-1")
    entrenar(activar=False, model_path=tmp_path / "baja.pkl")
    activate_version(MODEL_NAME, 1)

    assert score_predicciones_baja()["sombra"] is None


def test_un_candidato_nuevo_retira_las_filas_del_anterior(db):
    from db.repositories.predicciones import PrediccionesRepository

    with db.connect() as c:
        _insertar_abierta(c, "AB-1")
    repo = PrediccionesRepository()
    repo.guardar_baja_sombra([("AB-1", 0.1, 0.2, 0.3, None)], model_version=1, computed_at="t1")
    repo.guardar_baja_sombra([("AB-1", 0.1, 0.2, 0.3, 0.4)], model_version=2, computed_at="t2")
    with db.connect() as c:
        assert _filas_sombra(c) == [("AB-1", 2)]


def test_la_calibracion_de_la_sombra_compara_con_lo_servido_en_los_mismos_pares(db):
    from db.repositories.ml_dataset import MlDatasetRepository
    from db.repositories.predicciones import PrediccionesRepository

    with db.connect() as c:
        _insertar_abierta(c, "AB-1")
        c.execute(
            "INSERT INTO adjudicaciones (licitacion_id, nombre, importe_adjudicado, "
            " fecha_adjudicacion, n_ofertas_recibidas, fecha_extraccion) "
            "VALUES ('AB-1', 'E', 240000, '2026-07-01', 3, CURRENT_TIMESTAMP)"
        )  # baja real = 1 - 240.000 / 300.000 = 0,20
    repo = PrediccionesRepository()
    repo.guardar_baja([("AB-1", None, 0.0, 0.10, 0.3, None, "t1", None)])
    repo.guardar_baja_sombra([("AB-1", 0.1, 0.18, 0.3, None)], model_version=3, computed_at="t1")

    (medida,) = MlDatasetRepository().calibracion_baja_sombra()

    assert medida["model_version"] == 3 and medida["n"] == 1
    assert float(medida["mae"]) == pytest.approx(0.02)
    assert float(medida["mae_servido"]) == pytest.approx(0.10)
    assert float(medida["cobertura"]) == 1.0


def test_calibracion_sombra_sin_pares_suficientes_no_juzga(db):
    from services.ml.calibration import calibracion_sombra

    assert calibracion_sombra()["status"] == "sin_candidato"
    assert calibracion_sombra({"version": 2, "filas": 10})["status"] == "sin_datos"
