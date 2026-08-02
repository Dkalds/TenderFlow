"""Tests para shared/cache_signal.py — señal de invalidación de caché."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch


def _patch_path(tmp_path: Path):
    """Helper: parchea _signal_path para usar tmp_path."""
    signal_file = tmp_path / ".cache_invalidation"
    return patch("shared.cache_signal._signal_path", return_value=signal_file)


def test_signal_writes_file(tmp_path):
    with _patch_path(tmp_path):
        from shared.cache_signal import signal_cache_invalidation

        signal_cache_invalidation()
    assert (tmp_path / ".cache_invalidation").exists()


def test_check_cache_signal_detects_new_file(tmp_path):
    with _patch_path(tmp_path):
        from shared.cache_signal import check_cache_signal, signal_cache_invalidation

        before = time.time() - 1
        signal_cache_invalidation()
        assert check_cache_signal(before) is True


def test_check_cache_signal_no_file(tmp_path):
    with _patch_path(tmp_path):
        from shared.cache_signal import check_cache_signal

        assert check_cache_signal(0.0) is False


def test_check_cache_signal_already_seen(tmp_path):
    with _patch_path(tmp_path):
        from shared.cache_signal import check_cache_signal, signal_cache_invalidation

        signal_cache_invalidation()
        future = time.time() + 9999
        assert check_cache_signal(future) is False


def test_get_signal_timestamp_no_file(tmp_path):
    with _patch_path(tmp_path):
        from shared.cache_signal import get_signal_timestamp

        assert get_signal_timestamp() == 0.0


def test_get_signal_timestamp_returns_mtime(tmp_path):
    with _patch_path(tmp_path):
        from shared.cache_signal import get_signal_timestamp, signal_cache_invalidation

        signal_cache_invalidation()
        ts = get_signal_timestamp()
    assert ts > 0.0


def test_signal_write_failure_no_crash(tmp_path):
    """Si falla la escritura (directorio de solo lectura), no explota."""
    signal_file = tmp_path / ".cache_invalidation"
    with (
        patch("shared.cache_signal._signal_path", return_value=signal_file),
        patch("pathlib.Path.write_text", side_effect=OSError("read-only")),
    ):
        from shared.cache_signal import signal_cache_invalidation

        signal_cache_invalidation()  # no debe lanzar excepción


def test_check_signal_read_failure_returns_false(tmp_path):
    """Si falla la lectura del mtime, devuelve False sin crash."""
    signal_file = tmp_path / ".cache_invalidation"
    signal_file.write_text("0.0", encoding="utf-8")
    with (
        patch("shared.cache_signal._signal_path", return_value=signal_file),
        patch("pathlib.Path.stat", side_effect=OSError("permission denied")),
    ):
        from shared.cache_signal import check_cache_signal

        assert check_cache_signal(0.0) is False


def test_database_signal_is_visible_without_shared_filesystem(tmp_db, tmp_path):
    """Otro proceso puede observar la señal usando solo el Postgres común."""
    from shared.cache_signal import (
        _reset_signal_poll_cache,
        get_signal_timestamp,
        signal_cache_invalidation,
    )

    missing_local_file = tmp_path / "other-process" / ".cache_invalidation"
    with (
        patch("shared.cache_signal._database_signal_enabled", return_value=True),
        patch("shared.cache_signal._write_local_signal"),
        patch("shared.cache_signal._signal_path", return_value=missing_local_file),
    ):
        _reset_signal_poll_cache()
        signal_cache_invalidation()
        _reset_signal_poll_cache()  # simula el estado inicial del proceso lector

        assert get_signal_timestamp() > 0.0

    _reset_signal_poll_cache()
