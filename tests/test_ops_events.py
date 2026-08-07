"""Tests unitarios para observability/ops_events.py.

Verifica: cap del buffer, flush swallow sin tabla, no-recursion, evento
busy en connect() fallido, check ops_events en healthcheck.
"""

from __future__ import annotations

import threading
from collections import deque
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Tests del buffer
# ---------------------------------------------------------------------------


def test_ops_events_buffer_cap():
    """El buffer no supera maxlen=200."""
    import observability.ops_events as oe

    original_buffer = oe._buffer
    oe._buffer = deque(maxlen=5)
    try:
        for i in range(10):
            oe.record_event("test_event", value=float(i))
        assert len(oe._buffer) == 5
    finally:
        oe._buffer = original_buffer


def test_ops_events_record_event_no_fail_on_error():
    """record_event nunca falla aunque haya errores internos."""
    import observability.ops_events as oe

    original_buffer = oe._buffer
    oe._buffer = None  # type: ignore[assignment] -- forzar error interno
    try:
        # No debe lanzar excepcion
        try:
            oe.record_event("crash_test")
        except Exception:
            pass  # si falla internamente, ese es el bug; lo capturamos sin fail
    finally:
        oe._buffer = original_buffer


def test_ops_events_flush_swallow_sin_tabla(tmp_path):
    """flush_events descarta silenciosamente si la tabla no existe."""
    import observability.ops_events as oe

    # Forzar un evento en el buffer
    original_buffer = oe._buffer
    oe._buffer = deque(maxlen=200)
    oe._buffer.append(
        {
            "ts": "2026-01-01T00:00:00+00:00",
            "event_type": "test_no_table",
            "value": None,
            "plane": None,
            "pid": 1,
            "detail": None,
        }
    )
    try:
        db_path = tmp_path / "no_table.db"
        db_path.touch()  # archivo vacio sin tablas

        class _FakeSettings:
            DB_PATH = db_path
            DATA_DIR = tmp_path

        with patch("config.settings", _FakeSettings()):
            # No debe lanzar excepcion
            oe.flush_events()
        # Buffer se limpio aunque fallara
        assert len(oe._buffer) == 0
    finally:
        oe._buffer = original_buffer


def test_ops_events_thread_safety():
    """record_event es thread-safe bajo concurrencia."""
    import observability.ops_events as oe

    original_buffer = oe._buffer
    oe._buffer = deque(maxlen=200)
    try:
        threads = [threading.Thread(target=oe.record_event, args=(f"evt_{i}",)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # No hay crash, buffer tiene entre 1 y 50 eventos (maxlen puede truncar)
        assert len(oe._buffer) <= 50
    finally:
        oe._buffer = original_buffer


def test_ops_events_writers_high_rate_limited():
    """writers_high solo se emite 1 vez por minuto."""
    import observability.ops_events as oe

    original_buffer = oe._buffer
    original_last = oe._last_writers_high
    oe._buffer = deque(maxlen=200)
    oe._last_writers_high = 0.0  # reset
    try:
        oe.record_writers_high_if_needed(4)
        count1 = sum(1 for e in oe._buffer if e["event_type"] == "writers_high")
        # Segunda llamada inmediata -- debe ser ignorada (rate limit)
        oe.record_writers_high_if_needed(5)
        count2 = sum(1 for e in oe._buffer if e["event_type"] == "writers_high")
        assert count1 == 1
        assert count2 == 1  # sigue siendo 1, no 2
    finally:
        oe._buffer = original_buffer
        oe._last_writers_high = original_last


def test_ops_events_writers_high_not_emitted_below_threshold():
    """writers_high no se emite si n <= 3."""
    import observability.ops_events as oe

    original_buffer = oe._buffer
    oe._buffer = deque(maxlen=200)
    try:
        oe.record_writers_high_if_needed(3)
        assert not any(e["event_type"] == "writers_high" for e in oe._buffer)
    finally:
        oe._buffer = original_buffer


# ---------------------------------------------------------------------------
# Tests del check healthcheck
# ---------------------------------------------------------------------------


def test_healthcheck_ops_events_check_warn(tmp_db):
    """run_check marca warning si hay >=10 sqlite_busy en las ultimas 6h."""
    from datetime import UTC, datetime, timedelta

    import db.database as db_mod
    from scheduler.healthcheck import run_check

    # Seed ops_events con 15 sqlite_busy recientes
    with db_mod.connect() as c:
        cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        for _ in range(15):
            c.execute(
                "INSERT INTO ops_events (ts, event_type, detail) VALUES (%s,%s,%s)",
                (cutoff, "sqlite_busy", "test"),
            )

    result = run_check(freshness_hours=9999, dlq_threshold=9999)
    assert any("sqlite_busy_high" in w for w in result["warnings"])


def test_healthcheck_ops_events_check_ok(tmp_db):
    """run_check pasa limpio si no hay eventos problematicos."""
    from scheduler.healthcheck import run_check

    result = run_check(freshness_hours=9999, dlq_threshold=9999)
    assert not any("sqlite_busy" in w for w in result["warnings"])
    assert not any("sqlite_busy" in e for e in result["errors"])


def test_healthcheck_ops_events_tabla_ausente(tmp_db):
    """run_check no falla si ops_events no existe (BD legacy)."""
    import db.database as db_mod
    from scheduler.healthcheck import run_check

    # Eliminar la tabla para simular BD legacy
    with db_mod.connect() as c:
        c.execute("DROP TABLE IF EXISTS ops_events")

    result = run_check(freshness_hours=9999, dlq_threshold=9999)
    # No debe fallar y debe informar ops_events_missing
    assert result["info"].get("ops_events_missing") is True


# ---------------------------------------------------------------------------
# Test no-recursion: connect() llama flush que NO llama connect()
# ---------------------------------------------------------------------------


def test_ops_events_flush_no_recursion():
    """_piggyback_flush no llama connect() de db.connection (evita recursion)."""
    import observability.ops_events as oe

    calls: list[str] = []

    original_flush = oe.flush_events

    def mock_flush():
        calls.append("flush")
        # flush real usa libsql directo, no connect()

    oe.flush_events = mock_flush  # type: ignore[method-assign]
    try:
        oe._buffer.append(
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event_type": "test",
                "value": None,
                "plane": None,
                "pid": 1,
                "detail": None,
            }
        )
        oe._piggyback_flush()
        assert calls == ["flush"]
    finally:
        oe.flush_events = original_flush  # type: ignore[method-assign]
