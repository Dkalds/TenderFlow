"""v178: ``sistema_contratacion`` y ``marco_ref`` en ``licitaciones``.

Lo que se fija sin base de datos: que encadena con v177, que no espera un lock
sin tope, y que un reintento tras fallar a medias no muere en lo que la pasada
anterior ya dejó hecho (el bloque en autocommit confirma columnas y ``CHECK``
antes de sellar la revisión).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v178_sistema_contratacion.py"
)


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v178_sistema_contratacion", _RUTA)
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


def test_encadena_con_v177() -> None:
    modulo = _cargar()
    assert modulo.revision == "v178_sistema_contratacion"
    assert modulo.down_revision == "v177_rss_autonomico_sin_tramitacion"


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []


def test_los_alter_van_con_tope_de_espera_y_lo_sueltan() -> None:
    sql = _sql_emitido("upgrade")

    assert sql[0] == "SET LOCAL lock_timeout = '5s'"
    reset = sql.index("RESET lock_timeout")
    # Todo ALTER que pide ACCESS EXCLUSIVE va antes del RESET; validar e indexar, después.
    assert all(i < reset for i, s in enumerate(sql) if "ADD COLUMN" in s or "ADD CONSTRAINT" in s)
    assert all(i > reset for i, s in enumerate(sql) if "VALIDATE" in s or "INDEX" in s)


def test_un_reintento_no_choca_con_lo_que_ya_quedo_hecho() -> None:
    sql = _sql_emitido("upgrade")
    juntas = "\n".join(sql)

    assert juntas.count("ADD COLUMN IF NOT EXISTS") == 2
    quitar = next(i for i, s in enumerate(sql) if "DROP CONSTRAINT IF EXISTS" in s)
    poner = next(i for i, s in enumerate(sql) if "ADD CONSTRAINT" in s)
    assert quitar < poner
    assert "NOT VALID" in sql[poner]
    # Un índice INVALID de la pasada anterior se quita: `IF NOT EXISTS` lo daría por bueno.
    borrar = next(i for i, s in enumerate(sql) if s.startswith("DROP INDEX CONCURRENTLY IF EXISTS"))
    crear = next(i for i, s in enumerate(sql) if s.startswith("CREATE INDEX CONCURRENTLY"))
    assert borrar < crear
    assert "IF NOT EXISTS" not in sql[crear]
    assert "WHERE marco_ref IS NOT NULL" in sql[crear]


def test_el_check_admite_los_valores_del_vocabulario() -> None:
    from shared.sistema_contratacion import SISTEMAS

    (check,) = [s for s in _sql_emitido("upgrade") if "ADD CONSTRAINT" in s]
    assert all(f"'{valor}'" in check for valor in SISTEMAS)


def test_el_downgrade_quita_indice_check_y_columnas() -> None:
    juntas = "\n".join(_sql_emitido("downgrade"))

    assert "DROP INDEX CONCURRENTLY IF EXISTS idx_lic_marco_ref" in juntas
    assert "DROP CONSTRAINT IF EXISTS ck_lic_sistema_contratacion" in juntas
    assert "DROP COLUMN IF EXISTS marco_ref" in juntas
    assert "DROP COLUMN IF EXISTS sistema_contratacion" in juntas
