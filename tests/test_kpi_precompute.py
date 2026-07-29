"""Tests para scheduler/kpi_precompute.py — pre-cálculo de KPIs en BD."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _compute_all_kpis
# ---------------------------------------------------------------------------


def test_compute_all_kpis_returns_expected_metrics(tmp_db):
    """_compute_all_kpis devuelve al menos los KPIs globales básicos."""
    db_mod, _ = tmp_db

    from scheduler.kpi_precompute import _compute_all_kpis

    with db_mod.connect() as c:
        snapshots = _compute_all_kpis(c)

    metricas = {s["metrica"] for s in snapshots}
    assert "total_licitaciones" in metricas
    assert "importe_total" in metricas
    assert "importe_medio" in metricas
    assert "n_organos" in metricas
    assert "n_ccaa" in metricas
    assert "licitaciones_30d" in metricas
    assert "licitaciones_30d_prev" in metricas
    assert "total_adjudicaciones" in metricas


def test_compute_all_kpis_all_have_computed_at(tmp_db):
    """Todos los snapshots tienen el campo computed_at."""
    db_mod, _ = tmp_db

    from scheduler.kpi_precompute import _compute_all_kpis

    with db_mod.connect() as c:
        snapshots = _compute_all_kpis(c)

    for s in snapshots:
        assert "computed_at" in s, f"Snapshot sin computed_at: {s}"


def test_compute_all_kpis_empty_db_returns_zeros(tmp_db):
    """Con BD vacía, total_licitaciones == 0."""
    db_mod, _ = tmp_db

    from scheduler.kpi_precompute import _compute_all_kpis

    with db_mod.connect() as c:
        snapshots = _compute_all_kpis(c)

    total = next(s for s in snapshots if s["metrica"] == "total_licitaciones")
    assert total["valor"] == 0


def test_compute_all_kpis_with_data(tmp_db):
    """Con datos en BD, total_licitaciones refleja el count real."""
    from db.database import Licitacion

    db_mod, _ = tmp_db
    db_mod.upsert_licitaciones(
        [
            Licitacion(id_externo="KPI-001", titulo="SAP ERP Andalucía"),
            Licitacion(id_externo="KPI-002", titulo="SAP BW Madrid"),
        ]
    )

    from scheduler.kpi_precompute import _compute_all_kpis

    with db_mod.connect() as c:
        snapshots = _compute_all_kpis(c)

    total = next(s for s in snapshots if s["metrica"] == "total_licitaciones")
    assert total["valor"] == 2


# ---------------------------------------------------------------------------
# _persist_snapshots
# ---------------------------------------------------------------------------


def test_persist_snapshots_returns_count(tmp_db):
    """_persist_snapshots devuelve el número de filas insertadas."""
    db_mod, _ = tmp_db

    from scheduler.kpi_precompute import _persist_snapshots

    snapshots = [
        {
            "metrica": "test_metric",
            "dimension": "global",
            "valor": 42,
            "valor_text": None,
            "computed_at": "2024-01-01T00:00:00",
        },
    ]

    with db_mod.connect() as c:
        n = _persist_snapshots(c, snapshots)

    assert n == 1


def test_persist_snapshots_batch_inserts_all_rows(tmp_db):
    """executemany persiste todas las filas del batch (count == len)."""
    db_mod, _ = tmp_db

    from scheduler.kpi_precompute import _persist_snapshots

    snapshots = [
        {
            "metrica": f"m{i}",
            "dimension": "global",
            "valor": i,
            "valor_text": None,
            "computed_at": "2024-01-01T00:00:00",
        }
        for i in range(5)
    ]

    with db_mod.connect() as c:
        n = _persist_snapshots(c, snapshots)
        row = c.execute("SELECT COUNT(*) FROM kpi_snapshots").fetchone()

    assert n == 5
    assert row[0] == 5


def test_persist_snapshots_empty_returns_zero(tmp_db):
    """Lista vacía: 0 filas, no inserta nada (pero limpia las previas)."""
    db_mod, _ = tmp_db

    from scheduler.kpi_precompute import _persist_snapshots

    with db_mod.connect() as c:
        n = _persist_snapshots(c, [])
        row = c.execute("SELECT COUNT(*) FROM kpi_snapshots").fetchone()

    assert n == 0
    assert row[0] == 0


def test_persist_snapshots_clears_previous(tmp_db):
    """_persist_snapshots borra los snapshots anteriores antes de insertar."""
    db_mod, _ = tmp_db

    from scheduler.kpi_precompute import _persist_snapshots

    batch1 = [
        {
            "metrica": "m1",
            "dimension": "global",
            "valor": 1,
            "valor_text": None,
            "computed_at": "2024-01-01T00:00:00",
        }
    ]
    batch2 = [
        {
            "metrica": "m2",
            "dimension": "global",
            "valor": 2,
            "valor_text": None,
            "computed_at": "2024-01-02T00:00:00",
        }
    ]

    with db_mod.connect() as c:
        _persist_snapshots(c, batch1)
        n = _persist_snapshots(c, batch2)
        row = c.execute("SELECT COUNT(*) FROM kpi_snapshots").fetchone()

    # Solo debe quedar el batch2 (1 fila)
    assert row[0] == 1
    assert n == 1


# ---------------------------------------------------------------------------
# run_kpi_precompute (integración)
# ---------------------------------------------------------------------------


def test_run_kpi_precompute_returns_summary(tmp_db):
    """run_kpi_precompute devuelve dict con n_metricas y elapsed_ms."""
    _db_mod, _ = tmp_db

    from scheduler.kpi_precompute import run_kpi_precompute

    result = run_kpi_precompute()

    assert "n_metricas" in result
    assert result["n_metricas"] > 0
    assert "elapsed_ms" in result
    assert result["elapsed_ms"] >= 0


# ---------------------------------------------------------------------------
# get_latest_snapshot
# ---------------------------------------------------------------------------


def test_get_latest_snapshot_returns_none_when_empty(tmp_db):
    """Sin datos en kpi_snapshots devuelve None."""
    _, _ = tmp_db

    from scheduler.kpi_precompute import get_latest_snapshot

    result = get_latest_snapshot("total_licitaciones")
    assert result is None


def test_get_latest_snapshot_returns_value_after_precompute(tmp_db):
    """Tras run_kpi_precompute, get_latest_snapshot devuelve datos."""
    _, _ = tmp_db

    from scheduler.kpi_precompute import get_latest_snapshot, run_kpi_precompute

    run_kpi_precompute()
    result = get_latest_snapshot("total_licitaciones")

    assert result is not None
    assert "valor" in result
    assert "computed_at" in result


# ---------------------------------------------------------------------------
# get_all_latest
# ---------------------------------------------------------------------------


def test_get_all_latest_empty_db_returns_empty_dict(tmp_db):
    """Sin snapshots, get_all_latest devuelve dict vacío."""
    _, _ = tmp_db

    from scheduler.kpi_precompute import get_all_latest

    result = get_all_latest()
    assert result == {}


def test_get_all_latest_after_precompute_has_computed_at(tmp_db):
    """Tras precompute, get_all_latest incluye _computed_at y métricas."""
    _, _ = tmp_db

    from scheduler.kpi_precompute import get_all_latest, run_kpi_precompute

    run_kpi_precompute()
    result = get_all_latest()

    assert "_computed_at" in result
    assert "total_licitaciones" in result


def test_get_all_latest_licitaciones_por_ccaa_is_list(tmp_db):
    """licitaciones_por_ccaa se deserializa como lista."""
    _, _ = tmp_db

    from scheduler.kpi_precompute import get_all_latest, run_kpi_precompute

    run_kpi_precompute()
    result = get_all_latest()

    assert isinstance(result.get("licitaciones_por_ccaa"), list)


# ---------------------------------------------------------------------------
# Variantes con mocks pesados (sin BD real) — casos límite adicionales
# ---------------------------------------------------------------------------


class TestComputeAllKpis:
    def test_compute_all_kpis(self) -> None:
        from scheduler.kpi_precompute import _compute_all_kpis

        mock_conn = MagicMock()

        # We need different return values for fetchone and fetchall calls.
        # fetchone returns (value,) and fetchall returns list of tuples.
        mock_conn.execute.return_value.fetchone.return_value = (42, 100.0)
        mock_conn.execute.return_value.fetchall.return_value = []

        result = _compute_all_kpis(mock_conn)
        assert isinstance(result, list)
        assert len(result) > 0
        for s in result:
            assert "computed_at" in s
            assert "metrica" in s


class TestPersistSnapshots:
    def test_persist_snapshots(self) -> None:
        from scheduler.kpi_precompute import _persist_snapshots

        mock_conn = MagicMock()
        snapshots = [
            {"computed_at": "2024-01-01", "metrica": "total", "dimension": "global", "valor": 42},
            {
                "computed_at": "2024-01-01",
                "metrica": "avg",
                "dimension": "global",
                "valor": 10.5,
                "valor_text": "x",
            },
        ]
        n = _persist_snapshots(mock_conn, snapshots)
        assert n == 2
        # 1 DELETE (execute) + 1 INSERT batch (executemany)
        assert mock_conn.execute.call_count == 1
        assert mock_conn.executemany.call_count == 1


class TestRunKpiPrecompute:
    @patch("db.database.connect")
    @patch("db.database.init_db")
    def test_run(self, mock_init: MagicMock, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (10, 50.0)
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.kpi_precompute import run_kpi_precompute

        result = run_kpi_precompute()
        assert "n_metricas" in result
        assert "elapsed_ms" in result
        assert result["n_metricas"] > 0


class TestGetLatestSnapshot:
    @patch("db.database.connect")
    def test_found(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (42, None, "2024-01-01")
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.kpi_precompute import get_latest_snapshot

        result = get_latest_snapshot("total_licitaciones")
        assert result == {"valor": 42, "computed_at": "2024-01-01"}

    @patch("db.database.connect")
    def test_not_found(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.kpi_precompute import get_latest_snapshot

        result = get_latest_snapshot("total_licitaciones")
        assert result is None

    @patch("db.database.connect")
    def test_with_valor_text_json(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (None, '{"a":1}', "2024-01-01")
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.kpi_precompute import get_latest_snapshot

        result = get_latest_snapshot("some_metric")
        assert result["valor_text"] == {"a": 1}

    @patch("db.database.connect")
    def test_with_valor_text_bad_json(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (None, "NOT JSON", "2024-01-01")
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.kpi_precompute import get_latest_snapshot

        result = get_latest_snapshot("some_metric")
        assert result["valor_text"] == "NOT JSON"


class TestGetAllLatest:
    @patch("db.database.connect")
    def test_empty(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (None,)
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.kpi_precompute import get_all_latest

        assert get_all_latest() == {}

    @patch("db.database.connect")
    def test_with_data(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = ("2024-01-01",)
        mock_conn.execute.return_value.fetchall.return_value = [
            ("total", "global", 42, None),
            ("by_ccaa", "madrid", None, '{"n":10}'),
            ("bad_json", "global", None, "NOT JSON"),
        ]
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.kpi_precompute import get_all_latest

        result = get_all_latest()
        assert result["_computed_at"] == "2024-01-01"
        assert result["total"] == 42
        assert result["by_ccaa__madrid"] == {"n": 10}
        assert result["bad_json"] == "NOT JSON"


class TestExportParquet:
    @patch("db.analytics.duckdb_query")
    @patch("db.analytics.has_duckdb", return_value=True)
    def test_duckdb_export(
        self, mock_has: MagicMock, mock_query: MagicMock, tmp_path: Path
    ) -> None:
        from scheduler.kpi_precompute import run_kpi_export_parquet

        result = run_kpi_export_parquet(output_dir=str(tmp_path))
        assert "exported" in result
        assert len(result["exported"]) == len(mock_query.call_args_list)

    @patch("db.analytics.duckdb_query", side_effect=RuntimeError("fail"))
    @patch("db.analytics.has_duckdb", return_value=True)
    def test_duckdb_query_fails(
        self, mock_has: MagicMock, mock_query: MagicMock, tmp_path: Path
    ) -> None:
        from scheduler.kpi_precompute import run_kpi_export_parquet

        result = run_kpi_export_parquet(output_dir=str(tmp_path))
        assert result["exported"] == []

    @patch("db.analytics.has_duckdb", return_value=False)
    @patch("scheduler.kpi_precompute._export_parquet_pandas_fallback")
    def test_fallback_to_pandas(self, mock_fallback: MagicMock, mock_has: MagicMock) -> None:
        mock_fallback.return_value = {"exported": [], "elapsed_ms": 0, "engine": "pandas"}
        from scheduler.kpi_precompute import run_kpi_export_parquet

        result = run_kpi_export_parquet()
        assert result["engine"] == "pandas"
