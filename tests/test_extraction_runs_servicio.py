"""``services/extraction_runs.py`` contra Postgres.

El SQL tiene sus tests con una conexión doblada (``tests/test_extraction_runs.py``);
aquí se recorre el servicio que usan observabilidad y calidad de datos de punta
a punta: lo que persiste ``persist_run`` es lo que leen las dos lecturas.
"""

from __future__ import annotations

from typing import Any

from services.extraction_runs import load_calidad_runs, load_runs, persist_run


def _run(run_id: str, started_at: str, **cambios: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": run_id,
        "started_at": started_at,
        "ended_at": None,
        "duration_ms": None,
        "status": "ok",
        "months_attempted": 3,
        "months_ok": 2,
        "months_failed": 1,
        "licitaciones_nuevas": 10,
        "licitaciones_actualizadas": 4,
        "adjudicaciones": 6,
        "errores_parseo": 2,
        "errores_descarga": 1,
        "notas": "daily|placsp",
    }
    base.update(cambios)
    return base


def test_lo_que_persiste_el_servicio_vuelve_entero(tmp_db: Any) -> None:
    run = _run("r1", "2026-09-18T06:00:00+00:00", status="error")

    persist_run(**run)

    (leido,) = load_runs()
    assert {k: leido[k] for k in run} == run


def test_las_lecturas_van_del_mas_reciente_atras_y_respetan_el_limite(tmp_db: Any) -> None:
    persist_run(**_run("viejo", "2026-09-16T06:00:00+00:00"))
    persist_run(**_run("medio", "2026-09-17T06:00:00+00:00"))
    persist_run(**_run("nuevo", "2026-09-18T06:00:00+00:00"))

    assert [r["run_id"] for r in load_runs(limit=2)] == ["nuevo", "medio"]


def test_calidad_solo_trae_las_columnas_de_calidad(tmp_db: Any) -> None:
    persist_run(**_run("r1", "2026-09-18T06:00:00+00:00"))

    (fila,) = load_calidad_runs()

    assert set(fila) == {
        "started_at",
        "status",
        "errores_parseo",
        "errores_descarga",
        "months_attempted",
        "months_ok",
        "months_failed",
    }
    assert (fila["errores_parseo"], fila["months_failed"]) == (2, 1)
