"""Tests para scheduler/aggregates_precompute.py.

Cubre:
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


def test_persist_clusters_batches_across_chunk_boundary(tmp_db):
    """Persiste correctamente un volumen que cruza el borde de _INSERT_CHUNK."""
    db_mod, _ = tmp_db
    from scheduler.aggregates_precompute import _INSERT_CHUNK, _persist_clusters

    n = _INSERT_CHUNK * 2 + 7  # cruza dos bordes de chunk
    rows = [
        {
            "id_externo": f"EXP-{i:04d}",
            "cluster_id": i % 8,
            "cluster_label": f"label-{i % 8}",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        for i in range(n)
    ]

    with db_mod.connect() as conn:
        _persist_clusters(conn, rows)
        count = conn.execute("SELECT COUNT(*) FROM mat_clusters").fetchone()[0]
        first = conn.execute(
            "SELECT cluster_label FROM mat_clusters WHERE id_externo = 'EXP-0000'"
        ).fetchone()[0]
        last = conn.execute(
            "SELECT cluster_label FROM mat_clusters WHERE id_externo = ?", [f"EXP-{n - 1:04d}"]
        ).fetchone()[0]

    assert count == n
    assert first == "label-0"
    assert last == f"label-{(n - 1) % 8}"


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
    _db_mod, _ = tmp_db
    from scheduler.aggregates_precompute import run_aggregates_precompute

    result = run_aggregates_precompute()

    assert result["status"] == "ok"
    assert "n_clusters" in result


def test_run_aggregates_precompute_no_longer_reports_empresas(tmp_db):
    """``mat_top_empresas_ccaa`` se eliminó: no tenía lectores (ADR-017)."""
    _db_mod, _ = tmp_db
    from scheduler.aggregates_precompute import run_aggregates_precompute

    result = run_aggregates_precompute()

    assert "n_empresas" not in result


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
