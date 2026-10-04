"""Tests for db/model_registry.py — model version lifecycle."""

from __future__ import annotations

from db.model_registry import (
    activate_version,
    active_model_summary,
    deactivate,
    feedbacks_since_last_train,
    get_active,
    list_active,
    list_versions,
    next_version,
    register_version,
)


def test_register_version(tmp_db):
    _db_mod, _ = tmp_db
    v = register_version(
        name="test_model",
        path="/tmp/m.pkl",  # noqa: S108
        sha256="aaa",
        metrics={"f1": 0.9},
        n_samples=100,
    )
    assert v == 1


def test_get_active(tmp_db):
    _db_mod, _ = tmp_db
    register_version(
        name="test_model",
        path="/tmp/m.pkl",  # noqa: S108
        sha256="aaa",
        activate=True,
    )
    active = get_active("test_model")
    assert active is not None
    assert active["version"] == 1
    assert active["is_active"] == 1


def test_activate_rollback(tmp_db):
    _db_mod, _ = tmp_db
    register_version(name="m", path="p1", sha256="a1", activate=True)
    register_version(name="m", path="p2", sha256="a2", activate=True)
    assert get_active("m")["version"] == 2
    assert activate_version("m", 1) is True
    assert get_active("m")["version"] == 1


def test_list_versions(tmp_db):
    _db_mod, _ = tmp_db
    for i in range(3):
        register_version(name="m", path=f"p{i}", sha256=f"s{i}")
    versions = list_versions("m")
    assert len(versions) == 3
    # Ordered DESC by version
    assert versions[0]["version"] > versions[-1]["version"]


def test_next_version_sin_filas_es_la_primera(tmp_db):
    _db_mod, _ = tmp_db
    assert next_version("m") == 1


def test_next_version_cuenta_las_versiones_inactivas(tmp_db):
    """Quien numera desde la versión activa empieza otra vez en 1 cuando no hay
    ninguna activa, y la fila que se inserta es la 2."""
    _db_mod, _ = tmp_db
    register_version(name="m", path="p1", sha256="a1")
    register_version(name="otro", path="q1", sha256="b1", activate=True)
    assert get_active("m") is None

    siguiente = next_version("m")

    assert siguiente == 2
    assert register_version(name="m", path="p2", sha256="a2") == siguiente


def test_next_version_sigue_al_maximo_aunque_la_activa_sea_anterior(tmp_db):
    _db_mod, _ = tmp_db
    register_version(name="m", path="p1", sha256="a1", activate=True)
    register_version(name="m", path="p2", sha256="a2", activate=True)
    activate_version("m", 1)

    assert next_version("m") == 3


def test_feedbacks_since_last_train(tmp_db):
    _db_mod, _ = tmp_db
    register_version(name="sap_classifier", path="p", sha256="s", activate=True)
    # Push trained_at into the past so feedbacks inserted "now" are strictly after it.
    from db.database import connect

    with connect() as c:
        c.execute(
            "UPDATE model_versions SET trained_at = '2020-01-01T00:00:00' "
            "WHERE name = 'sap_classifier'"
        )
        c.execute(
            "INSERT INTO ml_feedback (expediente, relevante, created_at) "
            "VALUES (%s, %s, CURRENT_TIMESTAMP)",
            ("EXP-001", 1),
        )
        c.execute(
            "INSERT INTO ml_feedback (expediente, relevante, created_at) "
            "VALUES (%s, %s, CURRENT_TIMESTAMP)",
            ("EXP-002", 0),
        )
    count = feedbacks_since_last_train("sap_classifier")
    assert count == 2


def test_active_model_summary_composes_loop_state(tmp_db):
    """active_model_summary expone versión activa + histórico + feedbacks (panel AL)."""
    _db_mod, _ = tmp_db
    register_version(
        name="sap_classifier", path="p1", sha256="s1", metrics={"f1": 0.80}, activate=True
    )
    register_version(
        name="sap_classifier", path="p2", sha256="s2", metrics={"f1": 0.88}, activate=True
    )

    summary = active_model_summary("sap_classifier")
    assert summary["name"] == "sap_classifier"
    assert summary["active"] is not None
    assert summary["active"]["version"] == 2  # la activa es la última
    assert summary["active"]["metrics"]["f1"] == 0.88
    # Histórico para la tendencia (DESC, ambas versiones presentes).
    versions = [h["version"] for h in summary["history"]]
    assert versions == [2, 1]
    assert summary["feedbacks_since_train"] == 0


def test_active_model_summary_sin_modelo(tmp_db):
    """Sin versión registrada, el resumen es seguro (active=None, history vacío)."""
    _db_mod, _ = tmp_db
    summary = active_model_summary("inexistente")
    assert summary["active"] is None
    assert summary["history"] == []


def test_get_active_nonexistent(tmp_db):
    _db_mod, _ = tmp_db
    assert get_active("nonexistent_model") is None


def test_activate_nonexistent_version(tmp_db):
    _db_mod, _ = tmp_db
    assert activate_version("nonexistent", 999) is False


def test_list_active_devuelve_la_activa_de_cada_modelo(tmp_db):
    """Lo que recorre el canary de artefactos: una fila por modelo, la activa."""
    _db_mod, _ = tmp_db
    register_version(name="a", path="p/a1.pkl", sha256="a1", activate=True)
    register_version(name="a", path="p/a2.pkl", sha256="a2", activate=True)
    register_version(name="b", path="p/b1.pkl", sha256="b1", activate=True)
    register_version(name="c", path="p/c1.pkl", sha256="c1")  # nunca activada

    activas = list_active()

    assert [(f["name"], f["version"], f["path"], f["sha256"]) for f in activas] == [
        ("a", 2, "p/a2.pkl", "a2"),
        ("b", 1, "p/b1.pkl", "b1"),
    ]


def test_list_active_sin_modelos(tmp_db):
    _db_mod, _ = tmp_db
    assert list_active() == []


def test_deactivate_deja_el_modelo_sin_version_activa(tmp_db):
    """Y no toca ni las filas del modelo ni la versión activa de los demás."""
    _db_mod, _ = tmp_db
    register_version(name="m", path="p1", sha256="a1", activate=True)
    register_version(name="otro", path="p2", sha256="a2", activate=True)

    assert deactivate("m") == 1

    assert get_active("m") is None
    assert len(list_versions("m")) == 1
    assert get_active("otro")["version"] == 1
    # Idempotente: sin versión activa no hay nada que tocar.
    assert deactivate("m") == 0
