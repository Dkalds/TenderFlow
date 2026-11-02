"""v169: el descarte guarda el desglose del score, como la oportunidad.

Lo propio de la revisión: que encadena detrás de ``v168``, que la columna es
TEXT y nullable —sin default, así que el ``ADD COLUMN`` no reescribe filas—,
que se puede repetir y deshacer, y que fuera de Postgres no hace nada. Que el
desglose se escriba solo la primera vez y cuente en la propuesta de pesos lo
fija ``tests/test_decisiones_sellan_su_score.py``, contra la base.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

_VERSIONES = Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions"


def _cargar() -> Any:
    nombre = "v169_radar_dismissals_desglose"
    spec = importlib.util.spec_from_file_location(nombre, _VERSIONES / f"{nombre}.py")
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


def test_encadena_con_v168() -> None:
    modulo = _cargar()
    assert modulo.revision == "v169_radar_dismissals_desglose"
    assert modulo.down_revision == "v168_mv_canonicas_universo_producto"


def test_anade_una_columna_text_nullable_y_repetible() -> None:
    assert _sql_emitido("upgrade") == [
        "ALTER TABLE radar_dismissals ADD COLUMN IF NOT EXISTS desglose TEXT"
    ]


def test_el_downgrade_la_quita() -> None:
    assert _sql_emitido("downgrade") == [
        "ALTER TABLE radar_dismissals DROP COLUMN IF EXISTS desglose"
    ]


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []
