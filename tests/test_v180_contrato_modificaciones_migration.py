"""v180: ``contrato_modificaciones``.

Lo que se fija sin base de datos: que encadena con v178, que no espera un lock
sin tope, que se puede repetir y que la escritura del repositorio casa con sus
columnas. El esquema aplicado lo recorren el escenario CU-38 y la suite con BD.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

from db.repositories.modificaciones import ModificacionContrato

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v180_contrato_modificaciones.py"
)


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v180_contrato_modificaciones", _RUTA)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _sql_emitido(funcion: str, *, dialecto: str = "postgresql") -> list[str]:
    modulo = _cargar()
    emitido: list[str] = []
    with patch.object(modulo, "op") as op_falso:
        op_falso.get_bind.return_value.dialect.name = dialecto
        op_falso.execute.side_effect = emitido.append
        getattr(modulo, funcion)()
    return emitido


def test_encadena_con_v178() -> None:
    modulo = _cargar()
    assert modulo.revision == "v180_contrato_modificaciones"
    assert modulo.down_revision == "v178_sistema_contratacion"


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []


def test_va_con_tope_de_espera_y_se_puede_repetir() -> None:
    sql = _sql_emitido("upgrade")

    assert sql[0] == "SET LOCAL lock_timeout = '5s'"
    assert sql[-1] == "RESET lock_timeout"
    assert all("IF NOT EXISTS" in s for s in sql if "CREATE" in s)


def test_las_columnas_son_las_que_escribe_el_repositorio() -> None:
    (create,) = [s for s in _sql_emitido("upgrade") if "CREATE TABLE" in s]
    columnas = set(re.findall(r"^\s+([a-z_]+) (?:text|double precision|bigint)", create, re.M))

    assert columnas - {"id"} == set(ModificacionContrato.__dataclass_fields__)
    assert "clave text NOT NULL UNIQUE" in create
    # Borrar el expediente deja la modificación sin enlazar; una re-key la arrastra.
    assert "ON DELETE SET NULL ON UPDATE CASCADE" in create


def test_el_downgrade_borra_la_tabla() -> None:
    assert "DROP TABLE IF EXISTS contrato_modificaciones" in _sql_emitido("downgrade")
