"""Lecturas del clasificador (``db/repositories/licitaciones/ml.py``) contra Postgres.

Las etiquetas no circulares y la cola de etiquetado tienen sus propios tests
(``tests/test_etiquetas_no_circulares.py``, ``tests/test_reportes_dato_cola_y_prefijo.py``);
aquí se fijan los cortes y órdenes de las otras tres lecturas: scores por
tecnología, zona de incertidumbre y ventana de drift.
"""

from __future__ import annotations

from typing import Any

from db.repositories.licitaciones.ml import MlMixin

_AHORA = "2026-10-01T00:00:00+00:00"

_ml = MlMixin()


def _licitacion(
    c: Any,
    id_externo: str,
    *,
    ml_proba: float | None = None,
    importe: float | None = 100.0,
    publicada: str = "2026-09-15",
) -> None:
    c.execute(
        "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion, fuente, ml_proba, "
        "importe, fecha_publicacion) VALUES (%s, 'Soporte', %s, 'placsp', %s, %s, %s)",
        (id_externo, _AHORA, ml_proba, importe, publicada),
    )


def _score(c: Any, licitacion_id: str, tecnologia: str, probabilidad: float) -> None:
    c.execute(
        "INSERT INTO licitacion_tecnologia_score (licitacion_id, tecnologia, probabilidad, "
        "threshold_aplicado, computed_at) VALUES (%s, %s, %s, 0.5, %s)",
        (licitacion_id, tecnologia, probabilidad, _AHORA),
    )


def test_scores_de_una_licitacion_de_mayor_a_menor_probabilidad(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "L1")
        _licitacion(c, "L2")
        _score(c, "L1", "SAP", 0.4)
        _score(c, "L1", "SALESFORCE", 0.9)
        _score(c, "L2", "ORACLE", 0.99)

    filas = _ml.tech_scores_for("L1")

    assert [(r["tecnologia"], r["probabilidad"]) for r in filas] == [
        ("SALESFORCE", 0.9),
        ("SAP", 0.4),
    ]


def test_la_zona_de_incertidumbre_incluye_sus_extremos_y_no_los_nulos(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "BAJO", ml_proba=0.3)
        _licitacion(c, "ALTO", ml_proba=0.7)
        _licitacion(c, "FUERA", ml_proba=0.71)
        _licitacion(c, "SIN-PROBA", ml_proba=None)

    ids = {r["id_externo"] for r in _ml.load_uncertainty_zone(0.3, 0.7, 10)}

    assert ids == {"BAJO", "ALTO"}


def test_la_zona_de_incertidumbre_pone_primero_el_importe_mayor_y_al_final_el_nulo(
    tmp_db: Any,
) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "SIN-IMPORTE", ml_proba=0.5, importe=None)
        _licitacion(c, "PEQUENO", ml_proba=0.5, importe=10.0)
        _licitacion(c, "GRANDE", ml_proba=0.5, importe=1000.0)

    ids = [r["id_externo"] for r in _ml.load_uncertainty_zone(0.3, 0.7, 2)]

    assert ids == ["GRANDE", "PEQUENO"]


def test_la_ventana_de_drift_incluye_ambos_extremos(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "ANTES", publicada="2026-08-31")
        _licitacion(c, "PRIMERO", publicada="2026-09-01")
        _licitacion(c, "ULTIMO", publicada="2026-09-30")
        _licitacion(c, "DESPUES", publicada="2026-10-01")
        c.execute("UPDATE licitaciones SET cpv = id_externo")  # DriftRow no trae el id

    cpvs = {r["cpv"] for r in _ml.load_drift_window("2026-09-01", "2026-09-30")}

    assert cpvs == {"PRIMERO", "ULTIMO"}


def test_la_ventana_de_drift_incluye_el_ultimo_dia_aunque_la_fecha_lleve_hora(
    tmp_db: Any,
) -> None:
    """En producción quedaban filas con ``fecha_publicacion`` con hora (v172)."""
    db_mod, _ = tmp_db
    with db_mod.connect() as c:
        _licitacion(c, "CON-HORA", publicada="2026-09-30T19:30:59+02:00")
        _licitacion(c, "DESPUES", publicada="2026-10-01T00:00:00+00:00")
        c.execute("UPDATE licitaciones SET cpv = id_externo")

    cpvs = {r["cpv"] for r in _ml.load_drift_window("2026-09-01", "2026-09-30")}

    assert cpvs == {"CON-HORA"}
