"""v188: ``idx_lic_cursor_ts`` sobre ``(fecha_publicacion_ts DESC, id_externo DESC)``.

Lo que se fija: encadena con ``v187``; crea el índice ``CONCURRENTLY`` dentro de
un bloque autocommit, sin predicado parcial; el downgrade lo retira; fuera de
Postgres no hace nada; y con la lectura tipada encendida, el keyset del
listado por cursor puede recorrerlo en orden sin ordenar.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from db.database import connect

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v188_cursor_sombra_tipada.py"
)


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v188_cursor_sombra_tipada", _RUTA)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _emitido(funcion: str, *, dialecto: str = "postgresql") -> tuple[MagicMock, list[str]]:
    modulo = _cargar()
    emitido: list[str] = []
    with patch.object(modulo, "op") as op_falso:
        op_falso.get_bind.return_value.dialect.name = dialecto
        op_falso.execute.side_effect = emitido.append
        getattr(modulo, funcion)()
    return op_falso, emitido


def test_encadena_con_v187() -> None:
    modulo = _cargar()
    assert modulo.revision == "v188_cursor_sombra_tipada"
    assert modulo.down_revision == "v187_fact_sheets_attempts"


def test_crea_el_indice_concurrente_sin_predicado() -> None:
    op_falso, emitido = _emitido("upgrade")
    op_falso.get_context.return_value.autocommit_block.assert_called_once()
    (crear,) = [s for s in emitido if "CREATE INDEX" in s]
    assert "CONCURRENTLY IF NOT EXISTS idx_lic_cursor_ts" in crear
    assert "(fecha_publicacion_ts DESC, id_externo DESC)" in crear
    assert "WHERE" not in crear


def test_downgrade_lo_retira() -> None:
    _, emitido = _emitido("downgrade")
    assert emitido == ["DROP INDEX CONCURRENTLY IF EXISTS idx_lic_cursor_ts"]


def test_fuera_de_postgres_no_hace_nada() -> None:
    _, emitido = _emitido("upgrade", dialecto="sqlite")
    assert emitido == []


@pytest.mark.usefixtures("tmp_db")
def test_el_keyset_tipado_recorre_el_indice() -> None:
    with connect() as c:
        c.execute("SET enable_seqscan = off")
        c.execute("SET enable_sort = off")
        plan = "\n".join(
            str(fila[0])
            for fila in c.execute(
                "EXPLAIN SELECT id_externo FROM licitaciones "
                "ORDER BY fecha_publicacion_ts DESC, id_externo DESC LIMIT 20"
            ).fetchall()
        )
    assert "idx_lic_cursor_ts" in plan
