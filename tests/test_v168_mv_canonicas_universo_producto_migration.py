"""v168: la vista de canónicas admite lo que entra por su CPV, como el listado.

Que el cuerpo nuevo sea el que componen los fragmentos lo fija
``tests/test_mv_canonicas_definicion.py``, que apunta a esta revisión. Aquí, lo
propio de la revisión: que encadena detrás de ``v167``, que el downgrade
restaura exactamente el cuerpo de ``v157`` y que entre los dos solo cambia el
disyunto de ``inclusion_reason`` en el universo.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

_VERSIONES = Path(__file__).resolve().parents[1] / "db" / "alembic" / "versions"

#: El universo de ``v157``, congelado: el fragmento vivo puede seguir cambiando.
_UNIVERSO_V157 = (
    "(COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed' OR "
    "l.analysis_universe IN ('galicia_rss_recent_technology_observed', "
    "'euskadi_rss_recent_technology_observed') OR (l.tecnologia IS NOT NULL AND "
    "l.tecnologia <> '') OR (l.ml_tecnologias IS NOT NULL AND l.ml_tecnologias <> ''))"
)


def _cargar(nombre: str = "v168_mv_canonicas_universo_producto") -> Any:
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


def test_encadena_con_v167() -> None:
    modulo = _cargar()
    assert modulo.revision == "v168_mv_canonicas_universo_producto"
    assert modulo.down_revision == "v167_rekey_placsp_organo_reciente"


def test_el_downgrade_restaura_el_cuerpo_de_v157() -> None:
    assert _cargar()._CUERPO_ANTERIOR == _cargar("v157_mv_canonicas_fuente")._CUERPO


def test_solo_cambia_el_universo() -> None:
    modulo = _cargar()
    nuevo = f"({_UNIVERSO_V157} OR l.inclusion_reason = 'cpv_ti_universe')"
    assert _UNIVERSO_V157 in modulo._CUERPO_ANTERIOR
    assert modulo._CUERPO_ANTERIOR.replace(_UNIVERSO_V157, nuevo) == modulo._CUERPO


def test_permuta_sin_dejar_la_superficie_sin_vista() -> None:
    """La vista nueva se construye entera antes de tirar la vieja."""
    emitido = _sql_emitido("upgrade")
    crear = next(i for i, s in enumerate(emitido) if s.startswith("CREATE MATERIALIZED VIEW"))
    tirar = emitido.index("DROP MATERIALIZED VIEW IF EXISTS licitaciones_canonicas")
    assert "licitaciones_canonicas_v168 AS" in emitido[crear]
    assert crear < tirar
    assert any("uq_licitaciones_canonicas_id_externo" in s for s in emitido)


def test_fuera_de_postgres_no_emite_nada() -> None:
    assert _sql_emitido("upgrade", dialecto="sqlite") == []
    assert _sql_emitido("downgrade", dialecto="sqlite") == []
