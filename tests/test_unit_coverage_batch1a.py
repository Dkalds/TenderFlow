"""Unit tests for clusters, i18n, clustering_persistence, sentry, rate_limit_redis."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# ═══════════════════════════════════════════════════════════════════
# 1. services/clusters.py
# ═══════════════════════════════════════════════════════════════════


class TestClusterLicitaciones:
    def test_delegates_to_clustering_engine(self):
        import pandas as pd

        mock_cl = MagicMock()
        df = pd.DataFrame({"a": [1, 2]})
        mock_cl.return_value = df
        mock_mod = MagicMock(cluster_licitaciones=mock_cl)
        with patch.dict("sys.modules", {"services.clustering_engine": mock_mod}):
            from services.clusters import cluster_licitaciones

            result = cluster_licitaciones(df, n_clusters=5)
        mock_cl.assert_called_once_with(df, n_clusters=5)
        assert result is df

    def test_default_n_clusters(self):
        import pandas as pd

        mock_cl = MagicMock(return_value=pd.DataFrame())
        mock_mod = MagicMock(cluster_licitaciones=mock_cl)
        with patch.dict("sys.modules", {"services.clustering_engine": mock_mod}):
            from services.clusters import cluster_licitaciones

            df = pd.DataFrame({"x": [1]})
            cluster_licitaciones(df)
        mock_cl.assert_called_with(df, n_clusters=8)


# ═══════════════════════════════════════════════════════════════════
# 2. shared/i18n.py
# ═══════════════════════════════════════════════════════════════════


class TestI18n:
    def setup_method(self):
        import shared.i18n as mod

        self._mod = mod
        mod.set_locale("es")
        mod._load.cache_clear()

    def test_set_locale_supported(self):
        self._mod.set_locale("en")
        assert self._mod.get_locale() == "en"

    def test_set_locale_unsupported_falls_back(self):
        self._mod.set_locale("fr")
        assert self._mod.get_locale() == "es"

    def test_supported_locales(self):
        assert self._mod.supported_locales() == ("es", "en")

    def test_t_returns_key_when_no_translation(self):
        with patch.object(self._mod, "_load", return_value={}):
            result = self._mod.t("nonexistent.key")
        assert result == "nonexistent.key"

    def test_t_with_kwargs(self):
        with patch.object(self._mod, "_load", return_value={"greet": "Hola {name}"}):
            result = self._mod.t("greet", name="World")
        assert result == "Hola World"

    def test_t_format_error_returns_template(self):
        with patch.object(self._mod, "_load", return_value={"bad": "{missing}"}):
            result = self._mod.t("bad", wrong="val")
        assert result == "{missing}"

    def test_t_fallback_to_es(self):
        self._mod.set_locale("en")

        # en returns empty, es has the key
        def fake_load(locale):
            if locale == "en":
                return {}
            return {"only_es": "valor_es"}

        with patch.object(self._mod, "_load", side_effect=fake_load):
            result = self._mod.t("only_es")
        assert result == "valor_es"

    def test_load_missing_file(self):
        self._mod._load.cache_clear()
        with patch.object(Path, "is_file", return_value=False):
            result = self._mod._load.__wrapped__("xx")
        assert result == {}

    def test_load_json_error(self):
        self._mod._load.cache_clear()
        with patch.object(Path, "is_file", return_value=True):
            with patch.object(Path, "read_text", side_effect=ValueError("bad json")):
                result = self._mod._load.__wrapped__("zz")
        assert result == {}

    def test_load_valid_json(self):
        self._mod._load.cache_clear()
        with patch.object(Path, "is_file", return_value=True):
            with patch.object(Path, "read_text", return_value='{"k":"v"}'):
                result = self._mod._load.__wrapped__("qq")
        assert result == {"k": "v"}

    def test_t_same_locale_no_fallback_dict(self):
        """When active locale == default, fallback dict should be empty."""
        self._mod.set_locale("es")
        with patch.object(self._mod, "_load", return_value={"a": "b"}):
            result = self._mod.t("a")
        assert result == "b"


# ═══════════════════════════════════════════════════════════════════
# 3. shared/clustering_persistence.py
# ═══════════════════════════════════════════════════════════════════


class TestClusteringPersistence:
    @patch("shared.clustering_persistence.register_version", return_value=42)
    @patch("shared.clustering_persistence.joblib")
    @patch("shared.clustering_persistence.np")
    def test_save_clustering_with_centroids(self, mock_np, mock_joblib, mock_register):
        model = MagicMock()
        model.cluster_centers_ = [[1, 2], [3, 4]]
        model.n_clusters = 2
        type(model).__name__ = "KMeans"
        vec = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Make joblib.dump actually create the file so _sha256_file works
            def fake_dump(bundle, path, compress=3):
                Path(path).write_bytes(b"fake")

            mock_joblib.dump.side_effect = fake_dump

            result = save_clustering_helper(
                model=model,
                vectorizer=vec,
                dataset_hash="abc",
                metrics={"s": 0.5},
                n_samples=100,
                base_dir=tmpdir,
                activate=True,
            )

        assert result["version"] == 42
        assert result["algorithm"] == "KMeans"
        assert result["n_clusters"] == 2
        mock_register.assert_called_once()

    @patch("shared.clustering_persistence.register_version", return_value=1)
    @patch("shared.clustering_persistence.joblib")
    @patch("shared.clustering_persistence.np")
    def test_save_clustering_no_centroids(self, mock_np, mock_joblib, mock_register):
        model = MagicMock(spec=[])  # no cluster_centers_
        model.n_clusters = 3
        type(model).__name__ = "FakeModel"

        # Make sure getattr returns None for cluster_centers_
        # spec=[] means no attributes, so getattr(model, 'cluster_centers_', None) -> None

        with tempfile.TemporaryDirectory() as tmpdir:

            def fake_dump(bundle, path, compress=3):
                Path(path).write_bytes(b"data")

            mock_joblib.dump.side_effect = fake_dump

            result = save_clustering_helper(
                model=model,
                vectorizer=None,
                dataset_hash="xyz",
                base_dir=tmpdir,
                activate=False,
            )

        assert result["centroids_path"] is None
        mock_np.save.assert_not_called()

    @patch("shared.clustering_persistence.get_active", return_value=None)
    def test_load_clustering_no_active(self, mock_get):
        from shared.clustering_persistence import load_clustering

        result = load_clustering()
        assert result == (None, None)

    @patch("shared.clustering_persistence.get_active")
    def test_load_clustering_missing_file(self, mock_get):
        mock_get.return_value = {"path": "/nonexistent/file.joblib"}
        from shared.clustering_persistence import load_clustering

        model, meta = load_clustering()
        assert model is None
        assert meta is not None

    @patch("shared.clustering_persistence.joblib")
    @patch("shared.clustering_persistence.get_active")
    def test_load_clustering_load_error(self, mock_get, mock_joblib):
        with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as f:
            f.write(b"x")
            fpath = f.name
        try:
            mock_get.return_value = {"path": fpath}
            mock_joblib.load.side_effect = EOFError("bad")
            from shared.clustering_persistence import load_clustering

            model, meta = load_clustering()
            assert model is None
            assert meta is not None
        finally:
            os.unlink(fpath)

    @patch("shared.clustering_persistence.joblib")
    @patch("shared.clustering_persistence.get_active")
    def test_load_clustering_success(self, mock_get, mock_joblib):
        with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as f:
            f.write(b"x")
            fpath = f.name
        try:
            mock_get.return_value = {"path": fpath}
            bundle = {"model": "km", "vectorizer": "vec"}
            mock_joblib.load.return_value = bundle
            from shared.clustering_persistence import load_clustering

            model, _meta = load_clustering()
            assert model is bundle
        finally:
            os.unlink(fpath)


def save_clustering_helper(**kwargs):
    """Helper to call save_clustering with proper imports."""
    from shared.clustering_persistence import save_clustering

    return save_clustering(**kwargs)


# ═══════════════════════════════════════════════════════════════════
# 4. observability/sentry.py
# ═══════════════════════════════════════════════════════════════════


class TestSentry:
    def setup_method(self):
        import observability.sentry as mod

        mod._configured = False
        self._mod = mod

    def test_configure_no_dsn(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SENTRY_DSN", None)
            result = self._mod.configure_sentry()
        assert result is False
        assert self._mod._configured is True

    def test_configure_already_configured(self):
        self._mod._configured = True
        assert self._mod.configure_sentry() is True

    def test_configure_import_error(self):
        with patch.dict(os.environ, {"SENTRY_DSN": "https://x@sentry.io/1"}):
            import builtins

            real_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if "sentry_sdk" in name:
                    raise ImportError("no sentry")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=fake_import):
                result = self._mod.configure_sentry()
        assert result is False

    def test_configure_success(self):
        mock_sdk = MagicMock()
        mock_logging_int = MagicMock()
        self._mod._configured = False

        with patch.dict(
            os.environ,
            {"SENTRY_DSN": "https://x@sentry.io/1", "ENVIRONMENT": "prod", "APP_VERSION": "1.0"},
        ):
            import builtins

            real_import = builtins.__import__

            def fake_import(name, *args, **kwargs):
                if name == "sentry_sdk":
                    return mock_sdk
                if "sentry_sdk.integrations.logging" in name:
                    m = MagicMock()
                    m.LoggingIntegration = mock_logging_int
                    return m
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=fake_import):
                result = self._mod.configure_sentry(service="test-svc")
        assert result is True
        mock_sdk.init.assert_called_once()
        mock_sdk.set_tag.assert_called_once_with("service", "test-svc")

    def test_strip_pii(self):
        event = {
            "request": {"headers": {"Authorization": "Bearer xxx", "Content-Type": "text/html"}},
            "user": {"id": "abc", "email": "test@test.com", "ip_address": "1.2.3.4"},
        }
        result = self._mod._strip_pii(event, {})
        assert result["request"]["headers"]["Authorization"] == "***REDACTED***"
        assert result["request"]["headers"]["Content-Type"] == "text/html"
        assert "email" not in result.get("user", {})
        assert "ip_address" not in result.get("user", {})
        assert result["user"]["id"] == "abc"

    def test_strip_pii_no_user(self):
        event = {"request": {"headers": {}}}
        result = self._mod._strip_pii(event, {})
        assert "user" not in result

    def test_strip_pii_empty_user_after_strip(self):
        event = {"user": {"email": "a@b.com", "ip_address": "1.1.1.1"}}
        result = self._mod._strip_pii(event, {})
        # user dict is empty after popping both fields, but code checks `if user:`
        # empty dict is falsy so event["user"] is NOT set back
        # But the original dict was mutated in-place via pop, so event["user"] is still {}
        assert result["user"] == {}

    def test_set_user_context_no_sdk(self):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if "sentry_sdk" in name:
                raise ImportError
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            self._mod.set_user_context("hash123")  # should not raise

    def test_set_user_context_with_sdk(self):
        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sdk}):
            self._mod.set_user_context("hash123", locale="en")
        mock_sdk.set_user.assert_called_once_with({"id": "hash123", "locale": "en"})

    def test_set_user_context_no_locale(self):
        mock_sdk = MagicMock()
        with patch.dict("sys.modules", {"sentry_sdk": mock_sdk}):
            self._mod.set_user_context("hash456")
        mock_sdk.set_user.assert_called_once_with({"id": "hash456"})


# ═══════════════════════════════════════════════════════════════════
# 5. services/rate_limit_redis.py
# ═══════════════════════════════════════════════════════════════════


class TestRateLimitRedis:
    def setup_method(self):
        import services.rate_limit_redis as mod

        self._mod = mod
        mod._client = None

    def test_has_redis_no_url(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDIS_URL", None)
            # Even if redis module available, no URL means False
            assert not self._mod.has_redis()

    @patch.object(
        __import__("services.rate_limit_redis", fromlist=["_REDIS_AVAILABLE"]),
        "_REDIS_AVAILABLE",
        True,
    )
    def test_has_redis_with_url(self):
        with patch.dict(os.environ, {"REDIS_URL": "redis://localhost"}):
            assert self._mod.has_redis()

    def test_get_client_no_redis(self):
        with patch.object(self._mod, "has_redis", return_value=False):
            assert self._mod._get_client() is None

    def test_get_client_success(self):
        mock_redis_mod = MagicMock()
        mock_client = MagicMock()
        mock_redis_mod.Redis.from_url.return_value = mock_client
        self._mod._client = None

        with patch.object(self._mod, "has_redis", return_value=True):
            with patch.object(self._mod, "redis", mock_redis_mod):
                with patch.dict(os.environ, {"REDIS_URL": "redis://localhost"}):
                    result = self._mod._get_client()
        assert result is mock_client
        mock_client.ping.assert_called_once()

    def test_get_client_connection_error(self):
        mock_redis_mod = MagicMock()
        mock_redis_mod.Redis.from_url.side_effect = Exception("conn refused")
        self._mod._client = None

        with patch.object(self._mod, "has_redis", return_value=True):
            with patch.object(self._mod, "redis", mock_redis_mod):
                with patch.dict(os.environ, {"REDIS_URL": "redis://localhost"}):
                    result = self._mod._get_client()
        assert result is None

    def test_get_client_cached(self):
        sentinel = MagicMock()
        self._mod._client = sentinel
        with patch.object(self._mod, "has_redis", return_value=True):
            result = self._mod._get_client()
        assert result is sentinel

    def test_check_rate_limit_redis_no_client(self):
        with patch.object(self._mod, "_get_client", return_value=None):
            result = self._mod.check_rate_limit_redis("key1")
        assert result is None

    def test_check_rate_limit_redis_allowed(self):
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        mock_pipe.execute.return_value = [None, None, 5, None]

        with patch.object(self._mod, "_get_client", return_value=mock_client):
            result = self._mod.check_rate_limit_redis("key1", max_calls=10)
        assert result is True

    def test_check_rate_limit_redis_exceeded(self):
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        mock_pipe.execute.return_value = [None, None, 200, None]

        with patch.object(self._mod, "_get_client", return_value=mock_client):
            result = self._mod.check_rate_limit_redis("key1", max_calls=120)
        assert result is False

    def test_check_rate_limit_redis_pipeline_error(self):
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        mock_pipe.execute.side_effect = Exception("pipe error")

        with patch.object(self._mod, "_get_client", return_value=mock_client):
            result = self._mod.check_rate_limit_redis("key1")
        assert result is None

    def test_check_rate_limit_dispatcher_redis(self):
        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "redis"}):
            with patch.object(self._mod, "check_rate_limit_redis", return_value=True):
                result = self._mod.check_rate_limit("k")
        assert result is True

    def test_check_rate_limit_dispatcher_redis_fallback(self):
        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "redis"}):
            with patch.object(self._mod, "check_rate_limit_redis", return_value=None):
                with patch("db.rate_limits.check_rate_limit_db", return_value=True) as mock_db:
                    result = self._mod.check_rate_limit("k")
        assert result is True
        mock_db.assert_called_once()

    def test_check_rate_limit_dispatcher_sqlite(self):
        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "sqlite"}):
            with patch("db.rate_limits.check_rate_limit_db", return_value=False) as mock_db:
                result = self._mod.check_rate_limit("k", max_calls=50, window_seconds=30.0)
        assert result is False
        mock_db.assert_called_once_with("k", max_calls=50, window_seconds=30.0)

    def test_check_rate_limit_dispatcher_default_sqlite(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RATE_LIMIT_BACKEND", None)
            with patch("db.rate_limits.check_rate_limit_db", return_value=True):
                result = self._mod.check_rate_limit("k")
        assert result is True
