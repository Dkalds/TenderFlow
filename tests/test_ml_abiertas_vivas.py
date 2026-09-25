"""La población de scoring de baja deja fuera los expedientes zombi.

Sin adjudicación y sin estado terminal no significa abierta: el 2026-09-24 al
menos el 5% de las 4.414 «abiertas» que puntuaba el batch era de 2019 o antes,
y anclaban en 2019-11-15 la ventana de referencia del monitor de drift.

Lo que fijan estos tests, sin base de datos:

- el repositorio solo filtra cuando se le pasa ``desde``, y conserva las filas
  sin ninguna de las dos fechas —el complemento exacto de la purga—;
- en la variante por lote el corte va dentro de la CTE, antes de su ``LIMIT``,
  para que ``limit`` siga acotando expedientes ya filtrados;
- ``features_licitaciones_abiertas`` pide la población con el corte de
  ``corte_abiertas_vivas`` sobre su ``ahora``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from db.repositories import ml_dataset
from db.repositories.ml_dataset import MlDatasetRepository
from db.sql_fragments import fecha_referencia_abierta_sql

_REFERENCIA = fecha_referencia_abierta_sql("l")
_FILTRO = f"({_REFERENCIA} IS NULL OR {_REFERENCIA} >= %s)"
_METODOS = ["licitaciones_abiertas", "licitaciones_abiertas_por_lote"]


def _capturar(metodo: str, **kwargs: Any) -> tuple[str, list[Any]]:
    """SQL y parámetros que ``metodo`` manda a la conexión de lectura."""
    conexion = MagicMock()
    conexion.execute.return_value = MagicMock(description=[], fetchall=list)
    contexto = MagicMock()
    contexto.__enter__.return_value = conexion
    with (
        patch.object(ml_dataset, "connect_read", return_value=contexto),
        patch.object(ml_dataset, "rows_to_dicts", return_value=[]),
    ):
        getattr(MlDatasetRepository(), metodo)(estados_cerrados=("ADJ", "RES"), **kwargs)
    sql, params = conexion.execute.call_args.args
    return str(sql), list(params)


@pytest.mark.parametrize("metodo", _METODOS)
def test_sin_desde_la_poblacion_es_la_de_siempre(metodo):
    sql, params = _capturar(metodo, limit=10)

    assert _REFERENCIA not in sql
    assert params == ["ADJ", "RES", 10]
    assert sql.count("%s") == len(params)


@pytest.mark.parametrize("metodo", _METODOS)
def test_con_desde_deja_fuera_las_muertas_y_conserva_las_sin_fecha(metodo):
    sql, params = _capturar(metodo, limit=10, desde="2025-09-29")

    assert _FILTRO in sql
    assert params == ["ADJ", "RES", "2025-09-29", 10]
    assert sql.count("%s") == len(params)
    # Antes del LIMIT: los %s salen en el orden de params y, por lote, el
    # LIMIT de la CTE cuenta expedientes que ya pasaron el corte.
    assert sql.index(_FILTRO) < sql.index("LIMIT %s")


class _RepoVacio:
    """Repositorio sin filas que apunta con qué parámetros se piden las abiertas."""

    def __init__(self) -> None:
        self.pedidas: list[dict[str, Any]] = []

    def pares_baja_agregada(self, hasta: str | None = None) -> list[dict[str, Any]]:
        return []

    def pares_baja_por_lote(self, hasta: str | None = None) -> list[dict[str, Any]]:
        return []

    def adjudicaciones_por_empresa(self, hasta: str | None = None) -> list[dict[str, Any]]:
        return []

    def licitaciones_abiertas(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.pedidas.append(kwargs)
        return []

    def licitaciones_abiertas_por_lote(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.pedidas.append(kwargs)
        return []


@pytest.mark.parametrize("por_lote", [False, True])
def test_features_abiertas_pide_solo_las_vivas(monkeypatch, por_lote):
    import services.ml.features as features_mod
    from services.ml.features import corte_abiertas_vivas, features_licitaciones_abiertas

    repo = _RepoVacio()
    monkeypatch.setattr(features_mod, "MlDatasetRepository", lambda: repo)

    assert features_licitaciones_abiertas(ahora="2026-09-24", por_lote=por_lote) == []

    [pedida] = repo.pedidas
    assert pedida["desde"] == corte_abiertas_vivas("2026-09-24")
