"""v187: ``tender_fact_sheets.attempts``.

Lo que se fija: encadena con ``v186``; añade la columna entera ``NOT NULL`` con
``DEFAULT 0`` (constante: no reescribe la tabla); el downgrade la quita; fuera
de Postgres no hace nada; y en la base migrada a head la columna existe con
ese default.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from db.database import connect

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v187_fact_sheets_attempts.py"
)


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v187_fact_sheets_attempts", _RUTA)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _op_falso(funcion: str, *, dialecto: str = "postgresql") -> MagicMock:
    modulo = _cargar()
    with patch.object(modulo, "op") as op_falso:
        op_falso.get_bind.return_value.dialect.name = dialecto
        getattr(modulo, funcion)()
    return op_falso


def test_encadena_con_v186() -> None:
    modulo = _cargar()
    assert modulo.revision == "v187_fact_sheets_attempts"
    assert modulo.down_revision == "v186_resoluciones_llegada"


def test_anade_attempts_no_nula_con_default_cero() -> None:
    op_falso = _op_falso("upgrade")
    (llamada,) = op_falso.add_column.call_args_list
    tabla, columna = llamada.args
    assert tabla == "tender_fact_sheets"
    assert columna.name == "attempts"
    assert columna.nullable is False
    assert str(columna.server_default.arg) == "0"


def test_downgrade_quita_la_columna() -> None:
    op_falso = _op_falso("downgrade")
    op_falso.drop_column.assert_called_once_with("tender_fact_sheets", "attempts")


def test_fuera_de_postgres_no_hace_nada() -> None:
    op_falso = _op_falso("upgrade", dialecto="sqlite")
    op_falso.add_column.assert_not_called()


def test_la_base_migrada_tiene_la_columna(tmp_db: Any) -> None:
    with connect() as c:
        fila = c.execute(
            "SELECT is_nullable, column_default FROM information_schema.columns "
            "WHERE table_name = 'tender_fact_sheets' AND column_name = 'attempts'"
        ).fetchone()
    assert fila is not None
    assert fila[0] == "NO"
    assert str(fila[1]) == "0"
