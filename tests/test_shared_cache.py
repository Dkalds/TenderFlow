"""Tests para shared/cache.py — cache unificado con backends Memory y Redis."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_import():
    """Importa shared.cache y resetea su estado global."""
    import shared.cache as mod

    mod.reset_cache()
    return mod


# ---------------------------------------------------------------------------
# _MemoryBackend
# ---------------------------------------------------------------------------


class TestMemoryBackend:
    """Tests unitarios para _MemoryBackend."""

    def _make(self, max_size: int = 256):
        from shared.cache import _MemoryBackend

        return _MemoryBackend(max_size=max_size)

    # -- get / set básico ---------------------------------------------------

    def test_get_miss_returns_none(self):
        c = self._make()
        assert c.get("nonexistent") is None

    def test_set_and_get_roundtrip(self):
        c = self._make()
        c.set("k", {"a": 1}, ttl=60)
        assert c.get("k") == {"a": 1}

    def test_set_overwrites_existing(self):
        c = self._make()
        c.set("k", "v1", ttl=60)
        c.set("k", "v2", ttl=60)
        assert c.get("k") == "v2"

    # -- TTL ----------------------------------------------------------------

    def test_expired_entry_returns_none(self):
        c = self._make()
        c.set("k", "v", ttl=0.001)
        time.sleep(0.05)
        assert c.get("k") is None

    def test_negative_ttl_means_no_expiry(self):
        c = self._make()
        c.set("k", "v", ttl=-1)
        assert c.get("k") == "v"

    def test_zero_ttl_means_no_expiry(self):
        c = self._make()
        c.set("k", "v", ttl=0)
        assert c.get("k") == "v"

    # -- LRU eviction -------------------------------------------------------

    def test_lru_evicts_oldest_when_full(self):
        c = self._make(max_size=3)
        c.set("a", 1, ttl=60)
        c.set("b", 2, ttl=60)
        c.set("c", 3, ttl=60)
        # "a" es el más antiguo, debe ser evictado
        c.set("d", 4, ttl=60)
        assert c.get("a") is None
        assert c.get("d") == 4

    def test_lru_access_refreshes_position(self):
        c = self._make(max_size=3)
        c.set("a", 1, ttl=60)
        c.set("b", 2, ttl=60)
        c.set("c", 3, ttl=60)
        # Acceder a "a" lo mueve al final, "b" es el más antiguo ahora
        c.get("a")
        c.set("d", 4, ttl=60)
        assert c.get("b") is None
        assert c.get("a") == 1

    def test_evicts_expired_before_lru(self):
        c = self._make(max_size=3)
        c.set("expired", "x", ttl=0.001)
        c.set("b", 2, ttl=60)
        c.set("c", 3, ttl=60)
        time.sleep(0.05)
        c.set("d", 4, ttl=60)
        assert c.get("b") == 2  # "b" no se evictó
        assert c.get("d") == 4

    # -- delete -------------------------------------------------------------

    def test_delete_existing_key(self):
        c = self._make()
        c.set("k", "v", ttl=60)
        c.delete("k")
        assert c.get("k") is None

    def test_delete_nonexistent_key_no_error(self):
        c = self._make()
        c.delete("nonexistent")  # no debe lanzar

    # -- clear --------------------------------------------------------------

    def test_clear_removes_all(self):
        c = self._make()
        c.set("a", 1, ttl=60)
        c.set("b", 2, ttl=60)
        c.clear()
        assert len(c) == 0
        assert c.get("a") is None

    # -- keys ---------------------------------------------------------------

    def test_keys_returns_all_non_expired(self):
        c = self._make()
        c.set("a", 1, ttl=60)
        c.set("b", 2, ttl=60)
        c.set("expired", 0, ttl=0.001)
        time.sleep(0.05)
        assert sorted(c.keys()) == ["a", "b"]

    def test_keys_with_prefix_pattern(self):
        c = self._make()
        c.set("api:x", 1, ttl=60)
        c.set("api:y", 2, ttl=60)
        c.set("dash:z", 3, ttl=60)
        assert sorted(c.keys("api:*")) == ["api:x", "api:y"]

    def test_keys_with_exact_pattern(self):
        c = self._make()
        c.set("a", 1, ttl=60)
        c.set("b", 2, ttl=60)
        assert c.keys("a") == ["a"]

    # -- __len__ ------------------------------------------------------------

    def test_len_counts_entries(self):
        c = self._make()
        assert len(c) == 0
        c.set("k", 1, ttl=60)
        assert len(c) == 1

    # -- thread safety ------------------------------------------------------

    def test_concurrent_access_no_crash(self):
        c = self._make(max_size=50)
        errors: list[Exception] = []

        def worker(start: int) -> None:
            try:
                for i in range(100):
                    c.set(f"k{start + i}", i, ttl=60)
                    c.get(f"k{start + i}")
                    c.delete(f"k{start}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i * 100,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


# ---------------------------------------------------------------------------
# _RedisBackend (con mocks)
# ---------------------------------------------------------------------------


class TestRedisBackend:
    """Tests para _RedisBackend con Redis mockeado."""

    def _make_mocked(self):
        """Crea un _RedisBackend con redis.from_url mockeado."""
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True

        with patch.dict("sys.modules", {"redis": MagicMock()}):
            import sys

            redis_mod = sys.modules["redis"]
            redis_mod.from_url.return_value = mock_redis

            from shared.cache import _RedisBackend

            backend = _RedisBackend.__new__(_RedisBackend)
            backend._ns = "test:"
            backend._r = mock_redis

        return backend, mock_redis

    def test_get_miss(self):
        b, mock_r = self._make_mocked()
        mock_r.get.return_value = None
        assert b.get("k") is None
        mock_r.get.assert_called_once_with("test:k")

    def test_get_hit(self):
        b, mock_r = self._make_mocked()
        mock_r.get.return_value = json.dumps({"a": 1})
        assert b.get("k") == {"a": 1}

    def test_get_redis_error_returns_none(self):
        b, mock_r = self._make_mocked()
        mock_r.get.side_effect = ConnectionError("down")
        assert b.get("k") is None

    def test_set_with_ttl(self):
        b, mock_r = self._make_mocked()
        b.set("k", {"x": 1}, ttl=30)
        mock_r.setex.assert_called_once()
        args = mock_r.setex.call_args
        assert args[0][0] == "test:k"
        assert args[0][1] == 30

    def test_set_without_ttl(self):
        b, mock_r = self._make_mocked()
        b.set("k", "v", ttl=-1)
        mock_r.set.assert_called_once()

    def test_set_redis_error_no_raise(self):
        b, mock_r = self._make_mocked()
        mock_r.setex.side_effect = ConnectionError("down")
        b.set("k", "v", ttl=10)  # no debe lanzar

    def test_delete(self):
        b, mock_r = self._make_mocked()
        b.delete("k")
        mock_r.delete.assert_called_once_with("test:k")

    def test_delete_error_no_raise(self):
        b, mock_r = self._make_mocked()
        mock_r.delete.side_effect = ConnectionError("down")
        b.delete("k")  # no debe lanzar

    def test_clear_scans_and_deletes(self):
        b, mock_r = self._make_mocked()
        # scan retorna (cursor, keys) — una iteración
        mock_r.scan.return_value = (0, ["test:a", "test:b"])
        b.clear()
        mock_r.delete.assert_called_once_with("test:a", "test:b")

    def test_clear_empty_no_delete(self):
        b, mock_r = self._make_mocked()
        mock_r.scan.return_value = (0, [])
        b.clear()
        mock_r.delete.assert_not_called()

    def test_clear_error_no_raise(self):
        b, mock_r = self._make_mocked()
        mock_r.scan.side_effect = ConnectionError("down")
        b.clear()  # no debe lanzar

    def test_keys_returns_stripped_namespace(self):
        b, mock_r = self._make_mocked()
        mock_r.scan.return_value = (0, ["test:x", "test:y"])
        assert sorted(b.keys()) == ["x", "y"]

    def test_keys_error_returns_empty(self):
        b, mock_r = self._make_mocked()
        mock_r.scan.side_effect = ConnectionError("down")
        assert b.keys() == []


# ---------------------------------------------------------------------------
# get_cache / _try_redis / reset_cache
# ---------------------------------------------------------------------------


class TestGetCache:
    """Tests para la factory singleton get_cache."""

    @staticmethod
    def _patch_no_redis():
        """Mock settings con REDIS_URL vacío para forzar MemoryBackend."""
        import config as config_mod

        mock_s = MagicMock()
        mock_s.REDIS_URL = ""
        return patch.object(config_mod, "settings", mock_s)

    def setup_method(self):
        mod = _fresh_import()
        self.mod = mod

    def test_returns_memory_backend_when_no_redis_url(self):
        with self._patch_no_redis():
            self.mod.reset_cache()
            c = self.mod.get_cache("test_ns")
            from shared.cache import _MemoryBackend

            assert isinstance(c, _MemoryBackend)

    def test_same_namespace_returns_same_instance(self):
        with self._patch_no_redis():
            self.mod.reset_cache()
            c1 = self.mod.get_cache("ns1")
            c2 = self.mod.get_cache("ns1")
            assert c1 is c2

    def test_different_namespace_returns_different_instance(self):
        with self._patch_no_redis():
            self.mod.reset_cache()
            c1 = self.mod.get_cache("ns1")
            c2 = self.mod.get_cache("ns2")
            assert c1 is not c2


class TestResetCache:
    """Tests para reset_cache."""

    @staticmethod
    def _patch_no_redis():
        import config as config_mod

        mock_s = MagicMock()
        mock_s.REDIS_URL = ""
        return patch.object(config_mod, "settings", mock_s)

    def setup_method(self):
        self.mod = _fresh_import()

    def test_reset_all(self):
        with self._patch_no_redis():
            c1 = self.mod.get_cache("a")
            self.mod.reset_cache()
            c2 = self.mod.get_cache("a")
            assert c1 is not c2

    def test_reset_single_namespace(self):
        with self._patch_no_redis():
            c_a = self.mod.get_cache("a")
            c_b = self.mod.get_cache("b")
            self.mod.reset_cache("a")
            c_a2 = self.mod.get_cache("a")
            c_b2 = self.mod.get_cache("b")
            assert c_a is not c_a2
            assert c_b is c_b2


class TestTryRedis:
    """Tests para _try_redis — lógica de fallback y fail-fast en prod."""

    @staticmethod
    def _patch_settings(redis_url: str = ""):
        """Mock ``from config import settings`` dentro de ``_try_redis``.

        ``_try_redis`` hace ``from config import settings`` (el singleton real),
        por lo que necesitamos parchear el atributo ``settings`` del módulo
        ``config`` directamente.
        """
        import config as config_mod

        mock_s = MagicMock()
        mock_s.REDIS_URL = redis_url
        return patch.object(config_mod, "settings", mock_s)

    def test_no_redis_url_returns_memory(self):
        mod = _fresh_import()
        with self._patch_settings(redis_url=""):
            result = mod._try_redis("ns")
            from shared.cache import _MemoryBackend

            assert isinstance(result, _MemoryBackend)

    def test_redis_connection_failure_returns_memory_in_dev(self):
        mod = _fresh_import()
        with (
            self._patch_settings(redis_url="redis://bad:6379/0"),
            patch("shared.cache._RedisBackend", side_effect=ConnectionError("down")),
            patch.dict("os.environ", {"ENV": "dev"}, clear=False),
        ):
            result = mod._try_redis("ns")
            from shared.cache import _MemoryBackend

            assert isinstance(result, _MemoryBackend)

    def test_redis_connection_failure_returns_memory_even_in_prod(self):
        mod = _fresh_import()
        with (
            self._patch_settings(redis_url="redis://bad:6379/0"),
            patch("shared.cache._RedisBackend", side_effect=ConnectionError("down")),
            patch.dict("os.environ", {"ENV": "prod"}, clear=False),
        ):
            result = mod._try_redis("ns")
            from shared.cache import _MemoryBackend

            assert isinstance(result, _MemoryBackend)

    def test_settings_import_failure_returns_memory_in_dev(self):
        mod = _fresh_import()
        with (
            patch.dict("os.environ", {"ENV": "dev"}, clear=False),
            patch.dict("sys.modules", {"config": None}),
        ):
            result = mod._try_redis("ns")
            from shared.cache import _MemoryBackend

            assert isinstance(result, _MemoryBackend)


class TestCacheResponseIdentity:
    """Las respuestas personalizadas nunca comparten entrada entre usuarios."""

    def test_private_principal_is_part_of_cache_key(self):
        mod = _fresh_import()
        calls = 0

        @mod.cache_response(ttl=60, namespace="identity-regression")
        def personalized(*, _user):
            nonlocal calls
            calls += 1
            return {"principal": _user["user_key"], "call": calls}

        async def invoke():
            first = await personalized(_user={"user_key": "user-a"})
            second = await personalized(_user={"user_key": "user-b"})
            repeat = await personalized(_user={"user_key": "user-a"})
            return first, second, repeat

        first, second, repeat = asyncio.run(invoke())
        assert first["principal"] == "user-a"
        assert second["principal"] == "user-b"
        assert first == repeat
        assert calls == 2
