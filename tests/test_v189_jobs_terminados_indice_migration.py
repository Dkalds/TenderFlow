"""v189: ``ix_jobs_terminados`` sobre ``jobs(updated_at)`` para la purga.

Lo que se fija: encadena con ``v188``; el predicado del índice es el de la purga
(``db.retention._SOLO_SI["jobs"]``); se crea ``CONCURRENTLY`` y deja los
timeouts como estaban; y la purga de ``jobs`` lo recorre en la base migrada.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from db.database import connect

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v189_jobs_terminados_indice.py"
)


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v189_jobs_terminados_indice", _RUTA)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _emitido(funcion: str, *, dialecto: str = "postgresql") -> list[str]:
    modulo = _cargar()
    emitido: list[str] = []
    with patch.object(modulo, "op") as op_falso:
        op_falso.get_bind.return_value.dialect.name = dialecto
        op_falso.execute.side_effect = emitido.append
        getattr(modulo, funcion)()
    return emitido


def test_encadena_con_v188() -> None:
    modulo = _cargar()
    assert modulo.revision == "v189_jobs_terminados_indice"
    assert modulo.down_revision == "v188_cursor_sombra_tipada"


def test_el_predicado_es_el_de_la_purga() -> None:
    from db.retention import _SOLO_SI

    assert _SOLO_SI["jobs"] == _cargar().PREDICADO


def test_crea_el_indice_concurrente_y_resetea_los_timeouts() -> None:
    emitido = _emitido("upgrade")
    (crear,) = [s for s in emitido if "CREATE INDEX" in s]
    assert "CONCURRENTLY IF NOT EXISTS ix_jobs_terminados ON jobs (updated_at) WHERE" in crear
    assert emitido[-2:] == ["RESET lock_timeout", "RESET statement_timeout"]


def test_downgrade_y_fuera_de_postgres() -> None:
    assert _emitido("downgrade") == ["DROP INDEX CONCURRENTLY IF EXISTS ix_jobs_terminados"]
    assert _emitido("upgrade", dialecto="sqlite") == []


@pytest.mark.usefixtures("tmp_db")
def test_la_purga_de_jobs_recorre_el_indice() -> None:
    from db.retention import _SOLO_SI

    with connect() as c:
        c.execute("SET enable_seqscan = off")
        plan = "\n".join(
            str(f[0])
            for f in c.execute(
                # S608 no aplica: el predicado es una constante de db/retention.py.
                "EXPLAIN SELECT ctid FROM jobs WHERE updated_at < now() AND "  # noqa: S608
                + _SOLO_SI["jobs"]
                + " LIMIT 5000"
            ).fetchall()
        )
    assert "ix_jobs_terminados" in plan
