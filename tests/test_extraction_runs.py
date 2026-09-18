"""Contrato de ``db/repositories/extraction_runs.py``.

El repositorio alimenta dos cosas que no pueden mentir: el historial de runs de
`/ops` y la alerta de fallos consecutivos del carril diario. Hasta ahora solo lo
rozaban los tests de pipeline (backlog P3 «Suites propias para
`services/investigador/` y `extraction_runs`»).

Los tests `*_bd` usan Postgres (`tmp_db`) y el conftest los marca
`integration`; el resto sustituye la conexión por un doble y fija la forma de
la consulta y los dos contratos defensivos: ni `persist_run` ni
`load_recent_daily_statuses` propagan un fallo de BD.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

import db.repositories.extraction_runs as mod
from db.repositories.extraction_runs import ExtractionRunRepository

# ── Doble de conexión ────────────────────────────────────────────────────────


class _Cursor:
    def __init__(self, filas: list[tuple[Any, ...]], columnas: list[str]) -> None:
        self._filas = filas
        self.description = [(c,) for c in columnas]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._filas)


class _Conexion:
    def __init__(self, estado: dict[str, Any]) -> None:
        self._estado = estado

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        if self._estado.get("error") is not None:
            raise self._estado["error"]
        self._estado["sentencias"].append((sql, params))
        return _Cursor(self._estado["filas"], self._estado["columnas"])


@pytest.fixture
def bd(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    estado: dict[str, Any] = {
        "sentencias": [],
        "filas": [],
        "columnas": [],
        "error": None,
        "init_db": 0,
    }

    @contextmanager
    def _connect() -> Any:
        yield _Conexion(estado)

    def _init_db() -> None:
        estado["init_db"] += 1

    monkeypatch.setattr(mod, "connect", _connect)
    monkeypatch.setattr(mod, "connect_read", _connect)
    monkeypatch.setattr(mod, "init_db", _init_db)
    return estado


def _run(**cambios: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": "run-1",
        "started_at": "2026-09-18T06:00:00+00:00",
        "ended_at": "2026-09-18T06:05:00+00:00",
        "duration_ms": 300_000,
        "status": "ok",
        "months_attempted": 2,
        "months_ok": 2,
        "months_failed": 0,
        "licitaciones_nuevas": 10,
        "licitaciones_actualizadas": 5,
        "adjudicaciones": 3,
        "errores_parseo": 0,
        "errores_descarga": 1,
        "notas": "daily|placsp",
    }
    base.update(cambios)
    return base


# ── Lecturas ─────────────────────────────────────────────────────────────────


def test_load_runs_devuelve_dicts_del_mas_reciente_atras(bd: dict[str, Any]) -> None:
    bd["columnas"] = ["run_id", "status"]
    bd["filas"] = [("run-2", "ok"), ("run-1", "error")]

    filas = ExtractionRunRepository().load_runs(limit=7)

    assert filas == [{"run_id": "run-2", "status": "ok"}, {"run_id": "run-1", "status": "error"}]
    ((sql, params),) = bd["sentencias"]
    assert "ORDER BY started_at DESC" in sql
    assert params == (7,)


def test_load_calidad_runs_pide_solo_las_columnas_de_calidad(bd: dict[str, Any]) -> None:
    ExtractionRunRepository().load_calidad_runs()

    ((sql, params),) = bd["sentencias"]
    assert "errores_parseo" in sql and "months_failed" in sql
    assert "licitaciones_nuevas" not in sql
    assert params == (90,), "el límite por defecto es el de la pantalla de calidad"


def test_load_recent_daily_statuses_filtra_el_carril_diario(bd: dict[str, Any]) -> None:
    bd["filas"] = [("error",), ("ok",)]

    assert ExtractionRunRepository().load_recent_daily_statuses(3) == ["error", "ok"]
    ((sql, params),) = bd["sentencias"]
    # `%%` y no `%`: con `LIMIT %s` en la misma sentencia, un `%` suelto rompe
    # el formateo y la alerta de fallos consecutivos no se disparaba (ADR-018).
    assert "LIKE 'daily|%%'" in sql
    assert params == [3]


def test_load_recent_daily_statuses_no_propaga_un_fallo_de_bd(bd: dict[str, Any]) -> None:
    """Quien pregunta es la alerta; un 500 aquí la dejaría ciega igual."""
    bd["error"] = RuntimeError("BD caída")

    assert ExtractionRunRepository().load_recent_daily_statuses(3) == []


# ── Escritura ────────────────────────────────────────────────────────────────


def test_persist_run_inserta_las_catorce_columnas_en_orden(bd: dict[str, Any]) -> None:
    run = _run()

    ExtractionRunRepository().persist_run(**run)

    assert bd["init_db"] == 1
    ((sql, params),) = bd["sentencias"]
    assert sql.startswith("INSERT INTO extraction_runs")
    assert params == tuple(run.values())


def test_persist_run_no_propaga_un_fallo_de_bd(bd: dict[str, Any]) -> None:
    """Las métricas del run no pueden tumbar el run que ya terminó."""
    bd["error"] = RuntimeError("BD caída")

    ExtractionRunRepository().persist_run(**_run())  # no lanza


def test_persist_run_acepta_run_sin_terminar(bd: dict[str, Any]) -> None:
    ExtractionRunRepository().persist_run(**_run(ended_at=None, duration_ms=None))

    ((_, params),) = bd["sentencias"]
    assert params[2] is None and params[3] is None


# ── Contra Postgres ──────────────────────────────────────────────────────────


def test_ida_y_vuelta_bd(tmp_db: Any) -> None:
    repo = ExtractionRunRepository()
    repo.persist_run(**_run(run_id="viejo", started_at="2026-09-17T06:00:00+00:00"))
    repo.persist_run(**_run(run_id="nuevo", status="error"))
    repo.persist_run(
        **_run(run_id="bulk", started_at="2026-09-18T07:00:00+00:00", notas="bulk|2026-08")
    )

    assert [r["run_id"] for r in repo.load_runs(limit=10)] == ["bulk", "nuevo", "viejo"]
    assert repo.load_recent_daily_statuses(5) == ["error", "ok"]
