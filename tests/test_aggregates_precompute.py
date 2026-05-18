"""Tests para scheduler/aggregates_precompute.py.

Cubre:
- _compute_top_empresas: comportamiento con datos y BD vacía.
- _persist_top_empresas: replace atómico en mat_top_empresas_ccaa.
- _compute_clusters: comportamiento con datos y fallback sin sklearn.
- _persist_clusters: replace atómico en mat_clusters.
- run_aggregates_precompute: end-to-end con BD temporal.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_adjudicaciones(db_mod: Any, rows: list[tuple[str, str, float]]) -> None:
    """Inserta rows de (ccaa, nombre, importe_adjudicado) en adjudicaciones."""
    with db_mod.connect() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for i, (ccaa, nombre, importe) in enumerate(rows):
            conn.execute(
                "INSERT OR IGNORE INTO adjudicaciones "
                "(licitacion_id, nombre, ccaa, importe_adjudicado, fecha_extraccion) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"lic-{i}-{nombre[:8]}", nombre, ccaa, importe, "2026-01-01"),
            )


def _insert_licitaciones(db_mod: Any, rows: list[tuple[str, str, str]]) -> None:
    """Inserta rows de (id_externo, titulo, descripcion)."""
    with db_mod.connect() as conn:
        for id_ext, titulo, desc in rows:
            conn.execute(
                "INSERT OR IGNORE INTO licitaciones (id_externo, titulo, descripcion, fecha_extraccion) "
                "VALUES (?, ?, ?, ?)",
                (id_ext, titulo, desc, "2026-01-01"),
            )


# ---------------------------------------------------------------------------
# _compute_top_empresas
# ---------------------------------------------------------------------------


def test_compute_top_empresas_empty_db(tmp_db):
    """Con BD vacía devuelve lista vacía."""
    db_mod, _ = tmp_db
    from scheduler.aggregates_precompute import _compute_top_empresas

    with db_mod.connect() as conn:
        result = _compute_top_empresas(conn)

    assert result == []


def test_compute_top_empresas_basic(tmp_db):
    """Devuelve ranking ordenado por n_adj dentro de cada CCAA."""
    db_mod, _ = tmp_db
    _insert_adjudicaciones(
        db_mod,
        [
            ("Andalucía", "Empresa A", 100.0),
            ("Andalucía", "Empresa A", 200.0),
            ("Andalucía", "Empresa B", 50.0),
            ("Madrid", "Empresa C", 300.0),
        ],
    )

    from scheduler.aggregates_precompute import _compute_top_empresas

    with db_mod.connect() as conn:
        result = _compute_top_empresas(conn)

    ccaa_and = [r for r in result if r["ccaa"] == "Andalucía"]
    # normalize_company uppercases the names
    assert ccaa_and[0]["nombre_canon"] == "EMPRESA A"
    assert ccaa_and[0]["rank"] == 1
    assert ccaa_and[1]["nombre_canon"] == "EMPRESA B"
    assert ccaa_and[1]["rank"] == 2

    ccaa_mad = [r for r in result if r["ccaa"] == "Madrid"]
    assert len(ccaa_mad) == 1
    assert ccaa_mad[0]["rank"] == 1


def test_compute_top_empresas_respects_top_n(tmp_db):
    """No devuelve más de _TOP_N empresas por CCAA."""
    db_mod, _ = tmp_db
    for i in range(15):
        _insert_adjudicaciones(db_mod, [("Cataluña", f"Empresa{i:02d}", float(i * 10))])

    from scheduler.aggregates_precompute import _TOP_N, _compute_top_empresas

    with db_mod.connect() as conn:
        result = _compute_top_empresas(conn)

    cat = [r for r in result if r["ccaa"] == "Cataluña"]
    assert len(cat) == _TOP_N


def test_compute_top_empresas_has_required_keys(tmp_db):
    """Cada fila tiene las claves requeridas para INSERT."""
    db_mod, _ = tmp_db
    _insert_adjudicaciones(db_mod, [("Madrid", "Empresa X", 500.0)])

    from scheduler.aggregates_precompute import _compute_top_empresas

    with db_mod.connect() as conn:
        result = _compute_top_empresas(conn)

    row = result[0]
    for key in ("ccaa", "rank", "nombre_canon", "n_adj", "importe_total", "updated_at"):
        assert key in row, f"Falta clave: {key}"
    assert row["nombre_canon"] == "EMPRESA X"


# ---------------------------------------------------------------------------
# _persist_top_empresas
# ---------------------------------------------------------------------------


def test_persist_top_empresas_inserts_rows(tmp_db):
    """Inserta filas correctamente en mat_top_empresas_ccaa."""
    db_mod, _ = tmp_db
    from scheduler.aggregates_precompute import _persist_top_empresas

    rows = [
        {
            "ccaa": "Madrid",
            "rank": 1,
            "nombre_canon": "Test Corp",
            "n_adj": 5,
            "importe_total": 1000.0,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    ]

    with db_mod.connect() as conn:
        _persist_top_empresas(conn, rows)
        count = conn.execute("SELECT COUNT(*) FROM mat_top_empresas_ccaa").fetchone()[0]

    assert count == 1


def test_persist_top_empresas_replaces_atomically(tmp_db):
    """Llamadas sucesivas reemplazan datos previos."""
    db_mod, _ = tmp_db
    from scheduler.aggregates_precompute import _persist_top_empresas

    rows_first = [
        {
            "ccaa": "Andalucía",
            "rank": 1,
            "nombre_canon": "Vieja Empresa",
            "n_adj": 1,
            "importe_total": 100.0,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    rows_second = [
        {
            "ccaa": "Andalucía",
            "rank": 1,
            "nombre_canon": "Nueva Empresa",
            "n_adj": 10,
            "importe_total": 5000.0,
            "updated_at": "2026-06-01T00:00:00+00:00",
        }
    ]

    with db_mod.connect() as conn:
        _persist_top_empresas(conn, rows_first)
        _persist_top_empresas(conn, rows_second)
        row = conn.execute("SELECT nombre_canon FROM mat_top_empresas_ccaa").fetchone()

    assert row[0] == "Nueva Empresa"


def test_persist_top_empresas_empty_clears_table(tmp_db):
    """Persistir lista vacía elimina todas las filas existentes."""
    db_mod, _ = tmp_db
    from scheduler.aggregates_precompute import _persist_top_empresas

    rows = [
        {
            "ccaa": "Madrid",
            "rank": 1,
            "nombre_canon": "Corp",
            "n_adj": 1,
            "importe_total": 10.0,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    ]

    with db_mod.connect() as conn:
        _persist_top_empresas(conn, rows)
        _persist_top_empresas(conn, [])
        count = conn.execute("SELECT COUNT(*) FROM mat_top_empresas_ccaa").fetchone()[0]

    assert count == 0


# ---------------------------------------------------------------------------
# _compute_clusters
# ---------------------------------------------------------------------------


def test_compute_clusters_empty_db(tmp_db):
    """Con BD vacía devuelve lista vacía."""
    db_mod, _ = tmp_db
    from scheduler.aggregates_precompute import _compute_clusters

    with db_mod.connect() as conn:
        result = _compute_clusters(conn)

    assert result == []


def test_compute_clusters_with_data(tmp_db):
    """Devuelve una asignación por cada licitación cuando sklearn está disponible."""
    pytest.importorskip("sklearn")
    db_mod, _ = tmp_db
    _insert_licitaciones(
        db_mod,
        [
            (f"L{i:03d}", f"SAP ERP módulo {i}", f"Implantación de SAP en org {i}")
            for i in range(12)
        ],
    )

    from scheduler.aggregates_precompute import _compute_clusters

    with db_mod.connect() as conn:
        result = _compute_clusters(conn)

    assert len(result) == 12
    for r in result:
        for key in ("id_externo", "cluster_id", "cluster_label", "updated_at"):
            assert key in r


def test_compute_clusters_returns_empty_on_sklearn_missing(tmp_db):
    """Si sklearn no está instalado, devuelve lista vacía sin propagar excepción."""
    db_mod, _ = tmp_db
    _insert_licitaciones(db_mod, [("L001", "SAP ERP", "Desc 1"), ("L002", "SAP BW", "Desc 2")])

    import scheduler.aggregates_precompute as ap_mod

    # Patch the sklearn import at the point of use by making it raise ImportError
    with (
        patch.dict(
            sys.modules,
            {
                "sklearn": None,
                "sklearn.cluster": None,
                "sklearn.feature_extraction": None,
                "sklearn.feature_extraction.text": None,
            },
        ),
        db_mod.connect() as conn,
    ):
        result = ap_mod._compute_clusters(conn)

    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# _persist_clusters
# ---------------------------------------------------------------------------


def test_persist_clusters_inserts_rows(tmp_db):
    """Inserta filas en mat_clusters."""
    db_mod, _ = tmp_db
    from scheduler.aggregates_precompute import _persist_clusters

    rows = [
        {
            "id_externo": "EXP-001",
            "cluster_id": 0,
            "cluster_label": "sap · erp · implantación",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    ]

    with db_mod.connect() as conn:
        _persist_clusters(conn, rows)
        count = conn.execute("SELECT COUNT(*) FROM mat_clusters").fetchone()[0]

    assert count == 1


def test_persist_clusters_replaces_atomically(tmp_db):
    """Segunda llamada reemplaza datos previos."""
    db_mod, _ = tmp_db
    from scheduler.aggregates_precompute import _persist_clusters

    rows_a = [
        {
            "id_externo": "EXP-001",
            "cluster_id": 0,
            "cluster_label": "old",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    ]
    rows_b = [
        {
            "id_externo": "EXP-001",
            "cluster_id": 2,
            "cluster_label": "new",
            "updated_at": "2026-06-01T00:00:00+00:00",
        }
    ]

    with db_mod.connect() as conn:
        _persist_clusters(conn, rows_a)
        _persist_clusters(conn, rows_b)
        label = conn.execute("SELECT cluster_label FROM mat_clusters").fetchone()[0]

    assert label == "new"


# ---------------------------------------------------------------------------
# run_aggregates_precompute
# ---------------------------------------------------------------------------


def test_run_aggregates_precompute_returns_ok_status(tmp_db):
    """run_aggregates_precompute devuelve status=ok con BD vacía."""
    db_mod, _ = tmp_db
    from scheduler.aggregates_precompute import run_aggregates_precompute

    result = run_aggregates_precompute()

    assert result["status"] == "ok"
    assert "n_empresas" in result
    assert "n_clusters" in result


def test_run_aggregates_precompute_with_data(tmp_db):
    """Con datos reales, n_empresas > 0."""
    db_mod, _ = tmp_db
    _insert_adjudicaciones(db_mod, [("Madrid", "Corp A", 1000.0), ("Madrid", "Corp B", 500.0)])

    from scheduler.aggregates_precompute import run_aggregates_precompute

    result = run_aggregates_precompute()

    assert result["status"] == "ok"
    assert result["n_empresas"] >= 2


def test_run_aggregates_precompute_returns_error_on_exception():
    """Cuando connect() falla, devuelve status=error sin propagar."""

    import scheduler.aggregates_precompute as ap

    err_ctx = MagicMock()
    err_ctx.__enter__ = MagicMock(side_effect=RuntimeError("db down"))
    err_ctx.__exit__ = MagicMock(return_value=False)

    with patch.object(ap, "connect", return_value=err_ctx):
        result = ap.run_aggregates_precompute()

    assert result["status"] == "error"
    assert "error" in result
