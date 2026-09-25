"""Frontera services↔db de ``services/ml/scoring.py`` (ADR-022, ratchet TID251).

El módulo tenía SQL inline en dos sitios —el upsert de
``predicciones_retencion``, duplicado en las ramas modelo y baseline, y la baja
real por expediente de ``_baja_real``— y por eso vivía en la whitelist TID251
de ``pyproject.toml``. Los dos bajaron a ``PrediccionesRepository``
(``guardar_retencion`` y ``baja_real_de_expediente``) y el módulo salió de la
whitelist el 2026-09-24. Esto fija que no vuelva: ni conexiones ni SQL, y que
la división de la baja real —dominio— siga aquí, sobre lo que da el repositorio.

Los tests contra Postgres de la regla del denominador están en
``tests/test_ml_baja_model.py`` (``test_baja_real_*``).
"""

from __future__ import annotations

import ast
import pathlib
import re
from typing import Any
from unittest.mock import patch

import pytest

import services.ml.scoring as scoring

_SQL = re.compile(
    r"\bSELECT\b[\s\S]*?\bFROM\b"
    r"|\bINSERT\s+INTO\b"
    r"|\bUPDATE\s+\w+\s+SET\b"
    r"|\bDELETE\s+FROM\b",
    re.IGNORECASE,
)


def _arbol() -> ast.Module:
    return ast.parse(pathlib.Path(scoring.__file__).read_text(encoding="utf-8"))


def test_no_importa_connect_ni_connect_read():
    importados: set[str] = set()
    for nodo in ast.walk(_arbol()):
        if isinstance(nodo, ast.ImportFrom) and (nodo.module or "").startswith("db."):
            importados.update(alias.name for alias in nodo.names)

    assert "connect" not in importados
    assert "connect_read" not in importados


def test_no_lleva_sql_crudo():
    """TID251 veta abrir la conexión, no escribir la query: esto cubre lo segundo."""
    literales = [
        n.value
        for n in ast.walk(_arbol())
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    # Los docstrings nombran tablas y columnas, pero ninguno arma una sentencia.
    assert not [lit for lit in literales if _SQL.search(lit)]


class _Repo:
    """``PrediccionesRepository`` de mentira para el camino del expediente."""

    def __init__(self, baja: dict[str, Any] | None) -> None:
        self.baja = baja
        self.pedidas: list[str] = []

    def baja_real_de_expediente(self, licitacion_id: str) -> dict[str, Any] | None:
        self.pedidas.append(licitacion_id)
        return self.baja

    def prediccion_materializada(
        self, licitacion_id: str, lote_numero: str | None = None
    ) -> dict[str, Any] | None:
        return None

    def predicciones_por_lote(self, licitacion_id: str) -> list[dict[str, Any]]:
        return []


def test_la_baja_real_divide_entre_el_presupuesto_efectivo_del_repositorio():
    """Expediente de tres lotes con dos adjudicados (20k + 30k de presupuesto).

    El repositorio devuelve el presupuesto efectivo (50k, no el 100k del
    expediente); la baja es la de lo adjudicado sobre él: 1 - 39/50.
    """
    repo = _Repo({"presupuesto_efectivo": 50_000.0, "total_adjudicado": 39_000.0})

    baja, adjudicado = scoring._baja_real(repo, "MULTI")

    assert baja == pytest.approx(1 - 39_000 / 50_000)
    assert adjudicado == 39_000.0
    assert repo.pedidas == ["MULTI"]


@pytest.mark.parametrize(
    "fila",
    [
        None,
        {"presupuesto_efectivo": None, "total_adjudicado": 1_000.0},
        {"presupuesto_efectivo": 1_000.0, "total_adjudicado": None},
        {"presupuesto_efectivo": 0.0, "total_adjudicado": 1_000.0},
    ],
)
def test_sin_denominador_o_sin_adjudicacion_no_hay_baja_real(fila):
    assert scoring._baja_real(_Repo(fila), "X") is None


def test_la_prediccion_del_expediente_pide_la_baja_real_al_repositorio():
    repo = _Repo({"presupuesto_efectivo": 100_000.0, "total_adjudicado": 75_000.0})
    with patch.object(scoring, "PrediccionesRepository", return_value=repo):
        datos = scoring.prediccion_baja("PRE-V65")

    assert datos == {
        "licitacion_id": "PRE-V65",
        "baja_real": pytest.approx(0.25),
        "importe_adjudicado": 75_000.0,
    }
    assert repo.pedidas == ["PRE-V65"]


def test_sin_prediccion_ni_baja_real_el_expediente_da_none():
    with patch.object(scoring, "PrediccionesRepository", return_value=_Repo(None)):
        assert scoring.prediccion_baja("NADA") is None
