"""Tests del enrutado por backend de ``observability/ops_events.py`` (ADR-019).

``flush_events`` traga todos los errores por diseño (nunca debe romper el
proceso que la llama). Ese diseño escondió durante meses que escribía siempre
con ``libsql`` contra un fichero SQLite local aunque el backend fuera Postgres:
en los runners de GitHub Actions los eventos se perdían con el runner y el
healthcheck los buscaba en Supabase, siempre vacíos.

Como el swallow impide detectar el fallo por su efecto, estos tests verifican
el **enrutado**: que con backend Postgres se llame al camino Postgres y no al
de SQLite.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from observability import ops_events


@pytest.fixture(autouse=True)
def _clear_buffer():
    with ops_events._lock:
        ops_events._buffer.clear()
    yield
    with ops_events._lock:
        ops_events._buffer.clear()


def test_record_event_never_touches_db():
    """Contrato de diseño: record_event solo appendea al buffer en memoria."""
    with (
        patch.object(ops_events, "_flush_postgres") as pg,
        patch.object(ops_events, "_flush_sqlite") as lite,
    ):
        ops_events.record_event("test_event", value=1.0)

    pg.assert_not_called()
    lite.assert_not_called()
    assert len(ops_events._buffer) == 1


def test_flush_routes_to_postgres_when_backend_is_postgres():
    """El fallo original: con Postgres activo se escribía igualmente en SQLite."""
    ops_events.record_event("test_event", value=1.0)

    with (
        patch("db.connection.is_postgres_backend", return_value=True),
        patch.object(ops_events, "_flush_postgres") as pg,
        patch.object(ops_events, "_flush_sqlite") as lite,
    ):
        ops_events.flush_events()

    pg.assert_called_once()
    lite.assert_not_called()
    assert pg.call_args.args[0][0]["event_type"] == "test_event"


def test_flush_routes_to_sqlite_when_backend_is_sqlite():
    ops_events.record_event("test_event")

    with (
        patch("db.connection.is_postgres_backend", return_value=False),
        patch.object(ops_events, "_flush_postgres") as pg,
        patch.object(ops_events, "_flush_sqlite") as lite,
    ):
        ops_events.flush_events()

    lite.assert_called_once()
    pg.assert_not_called()


def test_flush_swallows_backend_errors():
    """Nunca debe propagar: es el contrato que permite llamarla desde atexit."""
    ops_events.record_event("test_event")

    with (
        patch("db.connection.is_postgres_backend", return_value=True),
        patch.object(ops_events, "_flush_postgres", side_effect=RuntimeError("db down")),
    ):
        ops_events.flush_events()  # no debe lanzar


def test_flush_empty_buffer_is_noop():
    with (
        patch.object(ops_events, "_flush_postgres") as pg,
        patch.object(ops_events, "_flush_sqlite") as lite,
    ):
        ops_events.flush_events()

    pg.assert_not_called()
    lite.assert_not_called()
