"""La purga de retención borra por lotes y no se traga los errores (2026-11).

Dos defectos que cerraba la auditoría de la cola y la retención:

1. Todas las tablas compartían una transacción con un ``DELETE`` masivo cada
   una. Ahora cada tabla se purga por su cuenta, con un commit por lote.
2. Una tabla que fallaba anotaba ``-1`` y el paso se daba por bueno: el lock
   diario de ``_run_periodic`` se quedaba puesto y nadie reintentaba. Ahora el
   job lanza ``RetencionIncompleta`` tras intentar todas.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest


def _insertar_claves(db_mod: Any, n: int, *, dias: int, prefijo: str) -> None:
    ts = (datetime.now(UTC) - timedelta(days=dias)).isoformat()
    with db_mod.connect() as c:
        for i in range(n):
            c.execute(
                "INSERT INTO idempotency_keys (idem_key, endpoint, response_json, created_at) "
                "VALUES (%s, 'feedback', '{}', %s)",
                (f"{prefijo}-{i}", ts),
            )


def _claves_restantes(db_mod: Any) -> int:
    with db_mod.connect_read() as c:
        return int(c.execute("SELECT COUNT(*) FROM idempotency_keys").fetchone()[0])


def test_borra_por_lotes_con_una_transaccion_por_lote(tmp_db, monkeypatch) -> None:
    db_mod, _ = tmp_db
    _insertar_claves(db_mod, 5, dias=3, prefijo="vieja")
    _insertar_claves(db_mod, 1, dias=0, prefijo="nueva")

    import db.retention as retention

    transacciones = 0
    connect_real = retention.connect

    @contextmanager
    def _contando() -> Iterator[Any]:
        nonlocal transacciones
        transacciones += 1
        with connect_real() as conn:
            yield conn

    monkeypatch.setattr(retention, "LOTE_BORRADO", 2)
    monkeypatch.setattr(retention, "connect", _contando)

    resultado = retention._purgar_tabla(
        "idempotency_keys", "created_at", retention._cutoff_iso(1), apply=True
    )

    assert resultado == 5
    assert transacciones == 3  # 2 + 2 + 1: el último lote corto cierra el bucle
    assert _claves_restantes(db_mod) == 1


def test_dry_run_cuenta_sin_borrar(tmp_db) -> None:
    db_mod, _ = tmp_db
    _insertar_claves(db_mod, 3, dias=3, prefijo="vieja")

    from db.retention import purgar_por_fecha

    resultado = purgar_por_fecha([("idempotency_keys", "created_at", 1)], dlq_days=30, apply=False)

    assert resultado["idempotency_keys"] == 3
    assert _claves_restantes(db_mod) == 3


def test_una_tabla_rota_no_impide_purgar_las_demas(tmp_db) -> None:
    db_mod, _ = tmp_db
    _insertar_claves(db_mod, 2, dias=3, prefijo="vieja")

    from db.retention import purgar_por_fecha

    resultado = purgar_por_fecha(
        [
            ("tabla_que_no_existe", "created_at", 1),
            ("idempotency_keys", "created_at", 1),
        ],
        dlq_days=30,
        apply=True,
    )

    assert resultado["tabla_que_no_existe"] == -1
    assert resultado["idempotency_keys"] == 2
    assert _claves_restantes(db_mod) == 0


def test_exigir_completa_falla_con_cualquier_menos_uno() -> None:
    from scheduler.retention import RetencionIncompleta, exigir_completa

    exigir_completa({"audit_log": 0, "documento_blobs": {"borrados": 0}})
    with pytest.raises(RetencionIncompleta, match="access_log, users"):
        exigir_completa({"users": -1, "audit_log": 3, "access_log": -1})


def test_purga_los_jobs_terminados_y_respeta_la_cola_viva(tmp_db) -> None:
    """La tabla ``jobs`` solo crecía: ningún paso la purgaba."""
    db_mod, _ = tmp_db
    viejo = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    with db_mod.connect() as c:
        for estado, ts in (
            ("done", viejo),
            ("failed", viejo),
            ("pending", viejo),
            ("running", viejo),
            ("done", datetime.now(UTC).isoformat()),
        ):
            c.execute(
                "INSERT INTO jobs (tipo, payload_json, estado, updated_at) "
                "VALUES ('ficha_pliego', '{}', %s, %s)",
                (estado, ts),
            )

    from scheduler.retention import run_retention

    resultado = run_retention(apply=True)

    assert resultado["jobs"] == 2
    with db_mod.connect_read() as c:
        quedan = sorted(str(f[0]) for f in c.execute("SELECT estado FROM jobs").fetchall())
    assert quedan == ["done", "pending", "running"]
