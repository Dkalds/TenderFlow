"""v154: las filas de ``galicia_rss`` con importe y sin ``importe_tipo`` pasan a ``desconocido``.

Lo que se fija: que solo toca esas filas —otra fuente con el mismo defecto
tiene que seguir saltando en la auditoría, no quedar tapada—, que no inventa
una base donde ya había una, y que una segunda pasada no cambia nada.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

from db.database import connect

_RUTA = (
    Path(__file__).resolve().parents[1]
    / "db"
    / "alembic"
    / "versions"
    / "v154_importe_tipo_galicia_desconocido.py"
)


def _cargar() -> Any:
    spec = importlib.util.spec_from_file_location("v154_importe_tipo_galicia_desconocido", _RUTA)
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


def test_encadena_con_v153() -> None:
    modulo = _cargar()
    assert modulo.revision == "v154_importe_tipo_galicia_desconocido"
    assert modulo.down_revision == "v153_rekey_pscp_id_externo"


def test_el_downgrade_no_hace_nada() -> None:
    assert _sql_emitido("downgrade") == []


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []


def test_marca_solo_las_de_galicia_sin_tipo(tmp_db) -> None:
    filas = [
        ("gal:sin-tipo", "galicia_rss", 1000.0, None),
        ("gal:sin-importe", "galicia_rss", None, None),
        ("gal:con-tipo", "galicia_rss", 1000.0, "sin_iva"),
        ("eus:sin-tipo", "euskadi_rss", 1000.0, None),
    ]
    with connect() as c:
        for id_externo, fuente, importe, tipo in filas:
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, fuente, importe, importe_tipo, "
                "fecha_extraccion) VALUES (%s, 't', %s, %s, %s, '2026-09-10T00:00:00+00:00')",
                (id_externo, fuente, importe, tipo),
            )
        for _ in range(2):  # idempotente
            for sentencia in _sql_emitido("upgrade"):
                c.execute(sentencia)
        tipos = dict(c.execute("SELECT id_externo, importe_tipo FROM licitaciones").fetchall())

    assert tipos == {
        "gal:sin-tipo": "desconocido",
        "gal:sin-importe": None,
        "gal:con-tipo": "sin_iva",
        "eus:sin-tipo": None,
    }
