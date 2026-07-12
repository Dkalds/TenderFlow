"""Tests del glue de activación del PlacspConnector (F2 flip).

Cubren la paridad operacional entre ``_run_daily_pipeline_connector`` y el
camino legacy que los 16 tests de contrato/paridad de datos no tocan:

- ``ingestion_result`` con ``inserted``/``modified`` como **listas** (contrato
  legacy; ``run_update._log_daily_summary`` hace ``len()``/``join()``).
- Errores por-entry no fallan el run; solo un fetch fatal → ``error_fetch``.
- ``log_extraccion`` + ``record_run`` escritos en el camino connector.
- Fallback one-time del cursor legacy ``place_live_atom`` → ``placsp``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scraper.connectors.placsp import PlacspAtomConnector

_EMPTY_META = {
    "newest_updated": None,
    "etag": '"etag-test"',
    "last_modified": None,
    "pages_fetched": 1,
    "entries_seen": 0,
    "stopped_reason": "exhausted",
}


def _patch_steps():
    return patch(
        "scheduler.pipeline_runs._run_post_ingestion_steps",
        return_value={},
    )


class TestDailyConnectorWrapper:
    def test_ingestion_result_shape_matches_legacy(self, tmp_db):
        """inserted/modified son listas — _log_daily_summary no debe crashear."""
        from scheduler import run_update
        from scheduler.pipeline_runs import _run_daily_pipeline_connector

        with (
            _patch_steps(),
            patch("scraper.atom_live.iter_live_entries", return_value=([], _EMPTY_META)),
        ):
            result = _run_daily_pipeline_connector()

        ingestion = result["ingestion_result"]
        assert result["status"] == "ok"
        assert isinstance(ingestion["inserted"], list)
        assert isinstance(ingestion["modified"], list)
        assert isinstance(ingestion["unchanged"], list)

        # El consumidor real no debe romper con este shape (regresión del
        # bug: el wrapper devolvía ints y len(int) → TypeError).
        run_update._log_daily_summary(result, MagicMock())

    def test_writes_log_extraccion_and_extraction_run(self, tmp_db):
        """El camino connector alimenta extracciones y extraction_runs."""
        db_mod, _ = tmp_db
        from scheduler.pipeline_runs import _run_daily_pipeline_connector

        with (
            _patch_steps(),
            patch("scraper.atom_live.iter_live_entries", return_value=([], _EMPTY_META)),
        ):
            _run_daily_pipeline_connector()

        with db_mod.connect_read() as conn:
            fuentes = [r[0] for r in conn.execute("SELECT fuente FROM extracciones").fetchall()]
            runs = conn.execute("SELECT status, notas FROM extraction_runs").fetchall()

        assert fuentes == ["placsp"]
        assert len(runs) == 1
        assert runs[0][0] == "ok"
        assert "daily_connector" in (runs[0][1] or "")

    def test_fetch_failure_maps_to_error_fetch_without_raising(self, tmp_db):
        """Fetch fatal → status error_fetch (nombre legacy), notify, sin raise."""
        from scheduler.pipeline_runs import _run_daily_pipeline_connector

        with (
            _patch_steps(),
            patch(
                "scraper.atom_live.iter_live_entries",
                side_effect=ConnectionError("PLACSP caído"),
            ),
            patch("observability.alerts.notify") as notify_mock,
        ):
            result = _run_daily_pipeline_connector()

        assert result["status"] == "error_fetch"
        assert result["ingestion_result"]["status"] == "error_fetch"
        assert notify_mock.called

    def test_parse_errors_do_not_fail_the_run(self, tmp_db):
        """Errores por-entry (DLQ) mantienen status ok — paridad con legacy."""
        from scheduler.pipeline_runs import _run_daily_pipeline_connector
        from scraper.connectors.base import ConnectorRunResult

        fake = ConnectorRunResult(source_id="placsp", fetched=10, parsed=9, errores=1)

        with (
            _patch_steps(),
            patch(
                "scraper.connectors.base.run_connector",
                return_value=fake,
            ),
        ):
            result = _run_daily_pipeline_connector()

        assert result["status"] == "ok"
        assert result["ingestion_result"]["entries_error"] == 1


class TestAtomConnectorCursorFallback:
    def test_falls_back_to_legacy_cursor_when_empty(self, tmp_db):
        """Sin cursor propio, el conector retoma desde place_live_atom."""
        db_mod, _ = tmp_db
        db_mod.set_cursor("place_live_atom", last_seen_updated="2026-07-01T00:00:00Z")

        captured: dict = {}

        def _fake_iter(last_seen_updated=None, **kwargs):
            captured["last_seen_updated"] = last_seen_updated
            return [], dict(_EMPTY_META)

        with patch("scraper.atom_live.iter_live_entries", side_effect=_fake_iter):
            list(PlacspAtomConnector().fetch(None))

        assert captured["last_seen_updated"] == "2026-07-01T00:00:00Z"

    def test_own_cursor_wins_over_legacy(self, tmp_db):
        """Con cursor propio ('placsp'), el legacy no se consulta."""
        db_mod, _ = tmp_db
        db_mod.set_cursor("place_live_atom", last_seen_updated="2026-01-01T00:00:00Z")

        captured: dict = {}

        def _fake_iter(last_seen_updated=None, **kwargs):
            captured["last_seen_updated"] = last_seen_updated
            return [], dict(_EMPTY_META)

        own_cursor = {"last_seen_updated": "2026-07-10T00:00:00Z", "etag": None}
        with patch("scraper.atom_live.iter_live_entries", side_effect=_fake_iter):
            list(PlacspAtomConnector().fetch(own_cursor))

        assert captured["last_seen_updated"] == "2026-07-10T00:00:00Z"
