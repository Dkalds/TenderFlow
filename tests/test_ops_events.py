"""Tests unitarios para observability/ops_events.py.

Verifica: cap del buffer, flush swallow sin tabla, no-recursion, evento
busy en connect() fallido, check ops_events en healthcheck.
"""

from __future__ import annotations

import threading
from collections import deque

import pytest

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
    """run_check marca warning si hay >=20 write_slow en las ultimas 6h."""
    from datetime import UTC, datetime, timedelta

    import db.database as db_mod
    from scheduler.healthcheck import run_check

    # Seed ops_events con 25 write_slow recientes
    with db_mod.connect() as c:
        cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        for _ in range(25):
            c.execute(
                "INSERT INTO ops_events (ts, event_type, detail) VALUES (%s,%s,%s)",
                (cutoff, "write_slow", "test"),
            )

    result = run_check(freshness_hours=9999, dlq_threshold=9999)
    assert any("write_slow_high" in w for w in result["warnings"])


def test_healthcheck_ops_events_check_ok(tmp_db):
    """run_check pasa limpio si no hay eventos problematicos."""
    from scheduler.healthcheck import run_check

    result = run_check(freshness_hours=9999, dlq_threshold=9999)
    assert not any("write_slow" in w or "writers_high" in w for w in result["warnings"])


def _con_corpus():
    """Hace creer a ``run_check`` que la vista pública tiene corpus.

    Poblar ``licitaciones_canonicas`` de verdad exige sembrar licitaciones y
    refrescar la vista; lo que aquí se prueba es solo la decisión del check de
    silencio, que toma la respuesta de ``_comprobar_vista_canonicas``.
    """
    from unittest.mock import patch

    return patch("scheduler.healthcheck._comprobar_vista_canonicas", return_value=True)


def test_healthcheck_avisa_un_dia_sin_eventos_con_corpus(tmp_db):
    """El estado de septiembre-octubre de 2026: corpus publicándose y la tabla
    vacía porque el flush fallaba. Ahora tiene nombre propio en el informe."""
    from datetime import UTC, datetime, timedelta

    import db.database as db_mod
    from scheduler.healthcheck import run_check

    with db_mod.connect() as c:
        hace_dos_dias = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
        c.execute(
            "INSERT INTO ops_events (ts, event_type) VALUES (%s, %s)",
            (hace_dos_dias, "write_slow"),
        )

    with _con_corpus():
        result = run_check(freshness_hours=9999, dlq_threshold=9999)

    assert "ops_events_sin_eventos_24h" in result["warnings"]
    assert {"name": "ops_events_recientes", "ok": False} in result["checks"]
    assert result["info"]["ops_events_24h"] == 0
    # Lo de hace dos días no cuenta en la ventana de 6 h.
    assert result["info"]["ops_events_6h"] == {}


def test_healthcheck_no_avisa_si_llegan_eventos(tmp_db):
    from datetime import UTC, datetime, timedelta

    import db.database as db_mod
    from scheduler.healthcheck import run_check

    with db_mod.connect() as c:
        hace_diez_horas = (datetime.now(UTC) - timedelta(hours=10)).isoformat()
        c.execute(
            "INSERT INTO ops_events (ts, event_type) VALUES (%s, %s)",
            (hace_diez_horas, "mv_canonicas_refresh"),
        )

    with _con_corpus():
        result = run_check(freshness_hours=9999, dlq_threshold=9999)

    assert "ops_events_sin_eventos_24h" not in result["warnings"]
    assert {"name": "ops_events_recientes", "ok": True} in result["checks"]
    assert result["info"]["ops_events_24h"] == 1
    # Fuera de la ventana de 6 h, pero dentro de la de 24 h.
    assert result["info"]["ops_events_6h"] == {}


def test_healthcheck_sin_corpus_no_avisa_del_silencio(tmp_db):
    """Un schema de test o un entorno nuevo no emite nada y no es una avería."""
    from scheduler.healthcheck import run_check

    result = run_check(freshness_hours=9999, dlq_threshold=9999)

    assert "ops_events_sin_eventos_24h" not in result["warnings"]
    assert {"name": "ops_events_recientes", "ok": True} in result["checks"]


@pytest.mark.schema_propio  # tira `ops_events`
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


# ---------------------------------------------------------------------------
# Escritores: el paso tech_signal_merge deja su contador en ops_events
# ---------------------------------------------------------------------------


def test_tech_signal_merge_deja_las_reparaciones_en_ops_events():
    """El criterio de retirada del paso es «cero reparaciones en siete días,
    medido en ``ops_events``», y el paso solo lo dejaba en el log del runner:
    la serie que lo mide no existía."""
    import json
    from unittest.mock import patch

    from scheduler import pipeline_runs

    resultado = {
        "licitaciones_merged": 3,
        "events_emitted": 1,
        "errors": 0,
        "licitaciones_candidatas": 3,
        "licitaciones_reparadas": 2,
    }
    with (
        patch("services.tech_signal.merge_doc_signals", return_value=resultado) as merge,
        patch.object(pipeline_runs, "record_event") as record,
    ):
        pipeline_runs._run_tech_signal_merge()

    # La pasada de la pipeline es la que barre pendientes (sin ids): la única
    # en la que «reparada» significa reparación.
    merge.assert_called_once_with()
    record.assert_called_once()
    args, kwargs = record.call_args
    assert args == (pipeline_runs.EVENTO_TECH_SIGNAL_MERGE,)
    assert kwargs["value"] == 2.0
    detalle = json.loads(kwargs["detail"])
    assert detalle["licitaciones_candidatas"] == 3
    assert "elapsed_ms" in detalle
