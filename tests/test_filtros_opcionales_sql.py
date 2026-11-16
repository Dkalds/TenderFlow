"""Los filtros opcionales de los listados arman SQL que Postgres acepta.

Mismo hueco en cinco módulos: condiciones que sólo se concatenan cuando llega
su parámetro, así que ningún test las recorría — y son exactamente las líneas
que reescribió la migración de paramstyle (`?` → `%s`) de esta rama. Un
placeholder mal migrado en una de ellas no se nota hasta que alguien usa ese
filtro en producción.

Cada test ejecuta contra el Postgres del test en vez de inspeccionar la
cadena: contar ``%s`` no detecta un ``%`` sin duplicar dentro de un literal
—el fallo concreto que hubo que arreglar dos veces durante la migración—, y el
motor sí. Que devuelvan vacío es lo esperado: la base del test está limpia; lo
que se comprueba es que la sentencia sea válida y ligue sus parámetros.
"""

from __future__ import annotations

import services.competitive.bajas as bajas_mod
import services.competitive.renovaciones as renov_mod
import services.resoluciones as resol_mod
from db.repositories.product_metrics import ProductMetricsRepository


def test_bajas_agregadas_con_cpv_y_ccaa(tmp_db):
    filas, base = bajas_mod.bajas_agregadas(cpv_prefix="7220", ccaa="Madrid")

    assert filas == []
    assert base == "mixta"


def test_proximas_renovaciones_con_todos_sus_filtros(tmp_db):
    filas = renov_mod.proximas_renovaciones(
        empresa_id=1,
        ccaa="Madrid",
        tecnologias=["SAP", "Cloud"],
        min_importe=1000.0,
    )

    assert filas == []


def test_proximas_renovaciones_descarta_tecnologias_vacias(tmp_db):
    """El filtro limpia `''` y `None` antes de armar el fragmento: no son códigos."""
    filas = renov_mod.proximas_renovaciones(tecnologias=["", None])  # type: ignore[list-item]

    assert filas == []


def test_resoluciones_con_organo_sentido_y_desde(tmp_db):
    filas = resol_mod.resoluciones(
        organo="Ministerio",
        sentido="ESTIMADO",
        desde="2026-01-01",
    )

    assert filas == []


def test_pursuit_rows_acota_por_periodo(tmp_db):
    filas = ProductMetricsRepository().pursuit_rows(
        period_from="2026-01-01",
        period_to="2026-12-31",
    )

    assert filas == []
