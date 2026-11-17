"""v185: ``adjudicaciones.primera_extraccion`` se rellena con ``fecha_extraccion``.

Lo que se fija: encadena con ``v184``; añade la columna anulable de texto; el
relleno copia ``fecha_extraccion`` solo donde la columna está a ``NULL`` (el
mismo valor con el que la alerta ya comparó esas filas, así que no re-notifica)
y una segunda pasada no cambia nada; el downgrade la quita.
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
    / "v185_adjudicaciones_primera_extraccion.py"
)


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v185_adjudicaciones_primera_extraccion", _RUTA)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _op_falso(funcion: str, *, dialecto: str = "postgresql") -> tuple[MagicMock, list[str]]:
    modulo = _cargar()
    emitido: list[str] = []
    with patch.object(modulo, "op") as op_falso:
        op_falso.get_bind.return_value.dialect.name = dialecto
        op_falso.execute.side_effect = emitido.append
        getattr(modulo, funcion)()
    return op_falso, emitido


def test_encadena_con_v184() -> None:
    modulo = _cargar()
    assert modulo.revision == "v185_adjudicaciones_primera_extraccion"
    assert modulo.down_revision == "v184_primera_extraccion_relleno"


def test_anade_la_columna_anulable_de_texto() -> None:
    op_falso, _ = _op_falso("upgrade")
    tabla, columna = op_falso.add_column.call_args.args
    assert tabla == "adjudicaciones"
    assert columna.name == "primera_extraccion"
    assert columna.nullable is True
    assert str(columna.type) == "TEXT"


def test_el_downgrade_quita_la_columna() -> None:
    op_falso, _ = _op_falso("downgrade")
    op_falso.drop_column.assert_called_once_with("adjudicaciones", "primera_extraccion")


def test_fuera_de_postgres_no_hace_nada() -> None:
    for funcion in ("upgrade", "downgrade"):
        op_falso, emitido = _op_falso(funcion, dialecto="sqlite")
        assert emitido == []
        op_falso.add_column.assert_not_called()
        op_falso.drop_column.assert_not_called()


def test_rellena_con_fecha_extraccion_solo_las_que_estan_a_null(tmp_db) -> None:
    # La BD de test ya está en head: la columna existe y `add_column` va al mock.
    _, emitido = _op_falso("upgrade")
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES ('LIC-1', 't', 'placsp', '2026-11-16T10:00:00+00:00')"
        )
        c.execute(
            "INSERT INTO adjudicaciones (licitacion_id, nif, nombre, fecha_extraccion, "
            "primera_extraccion) VALUES "
            "('LIC-1', 'B1', 'a-null', '2026-10-01T09:00:00+00:00', NULL), "
            "('LIC-1', 'B2', 'ya-tenia', '2026-11-16T10:00:00+00:00', "
            " '2026-03-01T08:00:00+00:00')"
        )
        for _ in range(2):  # la segunda pasada no cambia nada
            for sentencia in emitido:
                c.execute(sentencia)
        filas = c.execute(
            "SELECT nombre, primera_extraccion FROM adjudicaciones ORDER BY nombre"
        ).fetchall()

    assert [tuple(f) for f in filas] == [
        ("a-null", "2026-10-01T09:00:00+00:00"),
        ("ya-tenia", "2026-03-01T08:00:00+00:00"),
    ]
