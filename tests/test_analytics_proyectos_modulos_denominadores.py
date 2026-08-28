"""Denominadores explícitos de Proyectos & Módulos.

Fichero aparte de ``test_analytics_proyectos_modulos.py`` (que cubre la
detección regex y los agregados) porque lo que se fija aquí es otra cosa: que
los DOS ratios que la pantalla publica salen del backend, con SU denominador, y
que no vuelven a ser la misma expresión.

Contexto del arreglo: la vista calculaba «% Multi-módulo» y «% Match Portfolio»
con cuerpos idénticos carácter a carácter, sobre un campo ``total`` que el
contrato no emitía. Siempre caía al fallback —la suma de filas de módulo, donde
una licitación con módulos A+B cuenta dos veces—, así que el cociente leía MÁS
BAJO cuanto más multi-módulo era el corpus: el inverso de lo que su etiqueta
prometía.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.analytics.proyectos_modulos import (
    ProyectosModulosFilters,
    get_proyectos_modulos,
)


def _dias_atras(n: int) -> str:
    return (datetime.now(UTC) - timedelta(days=n)).strftime("%Y-%m-%d")


def _insert(rows: list[dict]) -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo=r["id_externo"],
                titulo=r["titulo"],
                importe=r.get("importe"),
                estado="PUB",
                fecha_publicacion=_dias_atras(30),
                tipo_contrato="2",
                cpv="72000000",
                tecnologia="SAP",
            )
            for r in rows
        ]
    )


def _corpus_mixto() -> list[dict]:
    """4 licitaciones: 1 multi-módulo, 2 mono-módulo, 1 sin módulo.

    «Migración SAP HANA y SAP Ariba» dispara dos patrones (HANA y Ariba) sobre
    UNA sola licitación: es la fila que rompía el KPI viejo.
    """
    return [
        {"id_externo": "P1", "titulo": "Migración SAP HANA y SAP Ariba", "importe": 100_000.0},
        {"id_externo": "P2", "titulo": "Soporte SuccessFactors", "importe": 50_000.0},
        {"id_externo": "P3", "titulo": "Implantación SAP Ariba", "importe": 30_000.0},
        {"id_externo": "P4", "titulo": "Obra civil del edificio", "importe": 900_000.0},
    ]


def test_total_del_ambito_incluye_las_no_clasificadas(tmp_db):
    """`total` es el ámbito COMPLETO, no la suma de filas de módulo."""
    _insert(_corpus_mixto())

    result = get_proyectos_modulos(ProyectosModulosFilters())

    assert result.total == 4  # P4 no tiene módulo SAP y sigue contando
    assert result.total_clasificados == 3
    # La suma de filas de módulo es 4 (P1 aparece en HANA y en Ariba): coincide
    # con `total` por accidente aritmético, y es justo el fallback que la vista
    # usaba como denominador. `menciones_modulo` lo expone para que nadie lo
    # confunda otra vez con un conteo de licitaciones.
    assert result.menciones_modulo == 4
    assert sum(m.count for m in result.modulos) == result.menciones_modulo


def test_match_portfolio_divide_por_el_ambito(tmp_db):
    _insert(_corpus_mixto())

    result = get_proyectos_modulos(ProyectosModulosFilters())

    assert result.pct_match_portfolio == 75.0  # 3 clasificadas / 4 del ámbito


def test_densidad_de_modulos_sube_con_las_multimodulo(tmp_db):
    """El signo correcto: más multi-módulo ⇒ ratio MÁS ALTO.

    El KPI viejo hacía lo contrario, y esta es la propiedad que lo delata.
    """
    _insert(_corpus_mixto())
    mixto = get_proyectos_modulos(ProyectosModulosFilters())

    # 4 menciones / 3 clasificadas
    assert mixto.modulos_por_clasificada == round(4 / 3, 2)

    # Una segunda multi-módulo sube la densidad; el match portfolio también,
    # pero son números DISTINTOS (antes eran la misma expresión).
    _insert([{"id_externo": "P5", "titulo": "Soporte SAP HANA y SAP Ariba", "importe": 10_000.0}])
    con_mas_multi = get_proyectos_modulos(ProyectosModulosFilters())

    assert con_mas_multi.menciones_modulo == 6
    assert con_mas_multi.total_clasificados == 4
    assert con_mas_multi.modulos_por_clasificada == 1.5
    assert con_mas_multi.modulos_por_clasificada > mixto.modulos_por_clasificada
    assert con_mas_multi.pct_match_portfolio != con_mas_multi.modulos_por_clasificada


def test_dataset_vacio_no_divide_por_cero(tmp_db):
    result = get_proyectos_modulos(ProyectosModulosFilters())

    assert result.total == 0
    assert result.menciones_modulo == 0
    assert result.pct_match_portfolio == 0.0
    assert result.modulos_por_clasificada == 0.0
