"""Tests no dependientes del dashboard para Ronda 2."""

from __future__ import annotations


class TestMatchesCcaaCaseInsensitive:
    def test_case_mismatch_still_matches(self):
        from db.watchlist import matches_licitacion

        entry = {"cpv_prefix": "72", "keyword": None, "min_importe": None, "ccaa": "cataluña"}
        assert matches_licitacion(entry, {"cpv": "72", "ccaa": "Cataluña"})

    def test_case_mismatch_reverse(self):
        from db.watchlist import matches_licitacion

        entry = {"cpv_prefix": "72", "keyword": None, "min_importe": None, "ccaa": "MADRID"}
        assert matches_licitacion(entry, {"cpv": "72", "ccaa": "Madrid"})


class TestUserKey:
    def test_returns_stable_hash(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_PASSWORD", "test_password_123")

        from shared.user_key import user_key

        k1 = user_key()
        k2 = user_key()
        assert k1 == k2
        assert len(k1) == 16

    def test_different_password_different_key(self, monkeypatch):
        from shared.user_key import user_key

        monkeypatch.setenv("DASHBOARD_PASSWORD", "alpha")
        k1 = user_key()

        monkeypatch.setenv("DASHBOARD_PASSWORD", "beta")
        k2 = user_key()
        assert k1 != k2


class TestAtomicDownload:
    def test_tmp_file_used_during_download(self, tmp_path):
        import inspect

        from scraper.bulk_downloader import _download

        src = inspect.getsource(_download.__wrapped__)
        assert ".tmp" in src
        assert ".replace(" in src or ".rename(" in src


class TestConnectAutoReconnect:
    def test_connect_works_after_close_pool(self, tmp_db):
        db_mod, _ = tmp_db
        with db_mod.connect() as c:
            c.execute("SELECT 1")

        db_mod.close_pool()

        with db_mod.connect() as c:
            result = c.execute("SELECT 1").fetchone()
        assert result is not None


class TestLoggingIdempotency:
    def test_configure_only_runs_once(self):
        import observability.logging as log_mod

        log_mod._configured = False
        log_mod.configure_logging(level="INFO", json_logs=True)
        assert log_mod._configured is True
        log_mod.configure_logging(level="DEBUG", json_logs=False)
        assert log_mod._configured is True
