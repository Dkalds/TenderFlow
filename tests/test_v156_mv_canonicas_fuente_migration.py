"""v156: la vista de canónicas reordena por fuente (PLACSP con el bulk → resto → TED).

Que el cuerpo nuevo sea el que componen los fragmentos lo fija
``tests/test_mv_canonicas_definicion.py``, que apunta a esta revisión. Aquí, lo
propio de la revisión: que encadena detrás de ``v155``, que el downgrade
restaura exactamente el cuerpo de ``v102`` y que entre los dos solo cambia el
primer criterio de orden.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

from db.sql_fragments import rango_de_fuente_sql

_VERSIONES = Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions"


def _cargar(nombre: str = "v156_mv_canonicas_fuente") -> Any:
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


def test_encadena_con_v155() -> None:
    modulo = _cargar()
    assert modulo.revision == "v156_mv_canonicas_fuente"
    assert modulo.down_revision == "v155_importes_double_precision"


def test_el_downgrade_restaura_el_cuerpo_de_v102() -> None:
    assert _cargar()._CUERPO_ANTERIOR == _cargar("v102_mv_canonicas_clave_inmutable")._CUERPO


def test_solo_cambia_el_primer_criterio_de_orden() -> None:
    modulo = _cargar()
    viejo = "(l.fuente <> 'placsp')"
    assert viejo in modulo._CUERPO_ANTERIOR
    assert modulo._CUERPO_ANTERIOR.replace(viejo, rango_de_fuente_sql("l")) == modulo._CUERPO


def test_permuta_sin_dejar_la_superficie_sin_vista() -> None:
    """La vista nueva se construye entera antes de tirar la vieja."""
    emitido = _sql_emitido("upgrade")
    crear = next(i for i, s in enumerate(emitido) if s.startswith("CREATE MATERIALIZED VIEW"))
    tirar = emitido.index("DROP MATERIALIZED VIEW IF EXISTS licitaciones_canonicas")
    assert "licitaciones_canonicas_v156 AS" in emitido[crear]
    assert crear < tirar
    assert any("uq_licitaciones_canonicas_id_externo" in s for s in emitido)


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []
