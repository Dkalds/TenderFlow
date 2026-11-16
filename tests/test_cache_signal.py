"""Tests para db/cache_signal.py — señal de invalidación de caché."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch


def _patch_path(tmp_path: Path):
    """Helper: parchea _signal_path para usar tmp_path."""
    signal_file = tmp_path / ".cache_invalidation"
    return patch("db.cache_signal._signal_path", return_value=signal_file)


def test_signal_writes_file(tmp_path):
    with _patch_path(tmp_path):
        from db.cache_signal import signal_cache_invalidation

        signal_cache_invalidation()
    assert (tmp_path / ".cache_invalidation").exists()


def test_get_signal_timestamp_no_file(tmp_path):
    with _patch_path(tmp_path):
        from db.cache_signal import get_signal_timestamp

        assert get_signal_timestamp() == 0.0


def test_get_signal_timestamp_returns_mtime(tmp_path):
    with _patch_path(tmp_path):
        from db.cache_signal import get_signal_timestamp, signal_cache_invalidation

        before = time.time() - 1
        signal_cache_invalidation()
        ts = get_signal_timestamp()
    assert ts > before


def test_signal_write_failure_no_crash(tmp_path):
    """Si falla la escritura (directorio de solo lectura), no explota."""
    signal_file = tmp_path / ".cache_invalidation"
    with (
        patch("db.cache_signal._signal_path", return_value=signal_file),
        patch("pathlib.Path.write_text", side_effect=OSError("read-only")),
    ):
        from db.cache_signal import signal_cache_invalidation

        signal_cache_invalidation()  # no debe lanzar excepción


def test_signal_read_failure_returns_zero(tmp_path):
    """Si falla la lectura del mtime, no hay señal (``0.0``) y no explota."""
    signal_file = tmp_path / ".cache_invalidation"
    signal_file.write_text("0.0", encoding="utf-8")
    with (
        patch("db.cache_signal._signal_path", return_value=signal_file),
        patch("pathlib.Path.stat", side_effect=OSError("permission denied")),
    ):
        from db.cache_signal import get_signal_timestamp

        assert get_signal_timestamp() == 0.0


def test_database_signal_is_visible_without_shared_filesystem(tmp_db, tmp_path):
    """Otro proceso puede observar la señal usando solo el Postgres común."""
    from db.cache_signal import (
        _reset_signal_poll_cache,
        get_signal_timestamp,
        signal_cache_invalidation,
    )

    missing_local_file = tmp_path / "other-process" / ".cache_invalidation"
    with (
        patch("db.cache_signal._database_signal_enabled", return_value=True),
        patch("db.cache_signal._write_local_signal"),
        patch("db.cache_signal._signal_path", return_value=missing_local_file),
    ):
        _reset_signal_poll_cache()
        signal_cache_invalidation()
        _reset_signal_poll_cache()  # simula el estado inicial del proceso lector

        assert get_signal_timestamp() > 0.0

    _reset_signal_poll_cache()
