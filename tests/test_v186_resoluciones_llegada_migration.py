"""v186: ``resoluciones_recurso.llegada_en`` y ``vinculada_en``.

Lo que se fija: encadena con ``v185``; añade las dos columnas ``timestamptz``
anulables y pone ``DEFAULT now()`` + ``NOT NULL`` a ``llegada_en`` **después**
del relleno (antes sellaría todo con la hora de la migración); el relleno usa
la medianoche UTC de ``fecha`` acotada por ``fecha_extraccion``, cae a
``epoch`` si ninguna se lee y no toca lo que ya tenía valor; el downgrade
quita las dos.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

from db.database import connect

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v186_resoluciones_llegada.py"
)


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v186_resoluciones_llegada", _RUTA)
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


def test_encadena_con_v185() -> None:
    modulo = _cargar()
    assert modulo.revision == "v186_resoluciones_llegada"
    assert modulo.down_revision == "v185_adjudicaciones_primera_extraccion"


def test_anade_las_dos_columnas_timestamptz_anulables() -> None:
    op_falso, _ = _op_falso("upgrade")
    columnas = {c.args[1].name: c.args[1] for c in op_falso.add_column.call_args_list}
    assert {c.args[0] for c in op_falso.add_column.call_args_list} == {"resoluciones_recurso"}
    assert set(columnas) == {"llegada_en", "vinculada_en"}
    for columna in columnas.values():
        assert columna.nullable is True
        assert columna.server_default is None
        assert columna.type.timezone is True


def test_el_default_y_el_not_null_van_despues_del_relleno() -> None:
    modulo = _cargar()
    with patch.object(modulo, "op") as op_falso:
        op_falso.get_bind.return_value.dialect.name = "postgresql"
        modulo.upgrade()
    alter = op_falso.alter_column.call_args
    assert alter.args == ("resoluciones_recurso", "llegada_en")
    assert alter.kwargs["nullable"] is False
    assert str(alter.kwargs["server_default"]) == "now()"
    posicion_relleno = op_falso.mock_calls.index(call.execute(modulo.RELLENAR))
    posicion_alter = next(i for i, c in enumerate(op_falso.mock_calls) if c[0] == "alter_column")
    assert posicion_relleno < posicion_alter


def test_el_downgrade_quita_las_dos_columnas() -> None:
    op_falso, _ = _op_falso("downgrade")
    assert sorted(c.args for c in op_falso.drop_column.call_args_list) == [
        ("resoluciones_recurso", "llegada_en"),
        ("resoluciones_recurso", "vinculada_en"),
    ]


def test_fuera_de_postgres_no_hace_nada() -> None:
    for funcion in ("upgrade", "downgrade"):
        op_falso, emitido = _op_falso(funcion, dialecto="sqlite")
        assert emitido == []
        op_falso.add_column.assert_not_called()
        op_falso.drop_column.assert_not_called()


def test_el_relleno_usa_la_fecha_acotada_por_la_extraccion(tmp_db) -> None:
    # La BD de test ya está en head: se quita el NOT NULL para sembrar filas
    # como las que encuentra el relleno, recién añadida la columna.
    modulo = _cargar()
    with connect() as c:
        c.execute("ALTER TABLE resoluciones_recurso ALTER COLUMN llegada_en DROP NOT NULL")
        c.execute(
            "INSERT INTO resoluciones_recurso "
            "(numero_resolucion, fecha, fecha_extraccion, llegada_en) VALUES "
            "('normal', '2026-10-01', '2026-11-16T10:00:00+00:00', NULL), "
            "('futura', '2062-10-01', '2026-11-16T10:00:00+00:00', NULL), "
            "('sin-fecha', NULL, '2026-11-02T09:30:00+00:00', NULL), "
            "('ilegible', '30/02/2026', 'ayer', NULL), "
            "('ya-tenia', '2026-10-01', '2026-11-16T10:00:00+00:00', "
            " '2026-10-05T12:00:00+00:00')"
        )
        for _ in range(2):  # la segunda pasada no cambia nada
            c.execute(modulo.RELLENAR)
        filas = dict(
            c.execute("SELECT numero_resolucion, llegada_en FROM resoluciones_recurso").fetchall()
        )

    assert filas == {
        "normal": datetime(2026, 10, 1, tzinfo=UTC),
        "futura": datetime(2026, 11, 16, 10, tzinfo=UTC),
        "sin-fecha": datetime(2026, 11, 2, 9, 30, tzinfo=UTC),
        "ilegible": datetime(1970, 1, 1, tzinfo=UTC),
        "ya-tenia": datetime(2026, 10, 5, 12, tzinfo=UTC),
    }
