"""Los filtros opcionales de ``services.competitive.mercado`` arman SQL válido.

Estas ramas eran las únicas líneas del módulo que ningún test recorría, y son
justo las que reescribió la migración de paramstyle (`?` → `%s`): condiciones
que sólo se añaden cuando llega su parámetro. Un placeholder mal migrado ahí no
rompe nada visible hasta que alguien usa ese filtro concreto en producción.

Dos comprobaciones distintas, a propósito:

- Sobre el constructor puro (``_scope_sql``): que el número de ``%s`` coincida
  con el de parámetros. Es la invariante que rompió el idioma ``",".join("?" *
  n)`` durante la migración — con ``%s`` producía ``%,s,%,s``, que cuenta mal.
- Sobre las funciones que ejecutan: que Postgres acepte la sentencia. Contar
  placeholders no detecta un ``LIKE %s`` dentro de un literal con ``%`` sin
  duplicar; el motor sí.
"""

from __future__ import annotations

from datetime import date

import pytest

import services.competitive.mercado as mercado


def _placeholders(sql: str) -> int:
    return sql.count("%s")


def test_scope_sql_sin_filtros_no_pide_parametros():
    where, params = mercado._scope_sql()

    assert params == []
    assert _placeholders(where) == 0


@pytest.mark.parametrize(
    ("kwargs", "esperados"),
    [
        ({"empresa_id": 7}, 1),
        ({"empresa_ids": [1, 2, 3]}, 3),
        ({"fecha_desde": date(2026, 1, 1)}, 1),
        ({"fecha_hasta": date(2026, 12, 31)}, 1),
        ({"cpv_prefix": "7220"}, 1),
        ({"ccaas": ["Madrid", "Cataluña"]}, 2),
        ({"tecnologias": ["SAP", "Cloud"]}, 2),
        ({"importe_min": 50_000.0}, 1),
    ],
)
def test_cada_filtro_aporta_sus_placeholders(kwargs, esperados):
    where, params = mercado._scope_sql(**kwargs)

    assert len(params) == esperados
    assert _placeholders(where) == esperados


def test_todos_los_filtros_a_la_vez_siguen_cuadrando():
    """El caso que un test por filtro no cubre: la suma."""
    where, params = mercado._scope_sql(
        empresa_ids=[1, 2],
        fecha_desde=date(2026, 1, 1),
        fecha_hasta=date(2026, 12, 31),
        cpv_prefix="7220",
        ccaas=["Madrid"],
        tecnologias=["SAP", "Cloud"],
        importe_min=1000.0,
    )

    # 2 empresa_ids + desde + hasta + cpv + 1 ccaa + 2 tecnologías + importe.
    assert _placeholders(where) == len(params) == 9


def test_empresa_ids_tiene_prioridad_sobre_empresa_id():
    """Documentado en el docstring de `_scope_sql`; nadie lo comprobaba."""
    where, params = mercado._scope_sql(empresa_id=9, empresa_ids=[1, 2])

    assert params == [1, 2]
    assert "a.empresa_id = %s" not in where


def test_importe_min_negativo_se_normaliza_a_cero():
    _, params = mercado._scope_sql(importe_min=-5.0)

    assert params == [0.0]


def test_cuota_mercado_acepta_sus_tres_filtros_en_postgres(tmp_db):
    """Ejecuta de verdad: valida la sentencia, no sólo su forma."""
    filas = mercado.cuota_mercado(cpv_prefix="7220", ccaa="Madrid", desde="2026-01-01")

    assert filas == []


def test_listar_adjudicaciones_acepta_busqueda_y_organo_en_postgres(tmp_db):
    """`q` y `organo` son `LIKE` con `%` alrededor: el caso propenso a fallar."""
    resultado = mercado.listar_adjudicaciones_empresa(
        1,
        q="sistema",
        organo="ministerio",
        cpv_prefix="7220",
        ccaas=["Madrid"],
        tecnologias=["SAP"],
        importe_min=1000.0,
    )

    assert resultado["items"] == []
