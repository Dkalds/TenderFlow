"""Estacionalidad del drill-down de órgano: denominador por mes de calendario.

``services/analytics/organo_detail.py`` dividía los doce meses por el número de
años distintos con datos (``nunique(year)``). Un tramo de marzo de 2024 a
febrero de 2026 tiene tres años distintos pero solo dos marzos: todas las
casillas salían un tercio más bajas. La nota de T5
(``docs/plans/2026-09-plan-arquitectura-v2.md``) lo dejó anotado; aquí se fija
la regla que ya aplica ``forecast_svc.get_estacionalidad_organo``.
"""

from __future__ import annotations

from services.analytics.organo_detail import _estacionalidad


def _por_mes(fechas: list[tuple[int, int]]) -> dict[int, int]:
    return {e.mes_numero: e.count for e in _estacionalidad(fechas)}


def test_sin_fechas_no_hay_serie() -> None:
    assert _estacionalidad([]) == []


def test_tramo_de_dos_anios_que_cruza_tres_anios_naturales() -> None:
    """Marzo 2024 → febrero 2026: 24 meses, dos de cada mes, tres años distintos.

    Con ``n_years`` = 3, dos publicaciones cada marzo daban ``round(4/3) = 1``;
    con el denominador real son dos marzos y la media es 2.
    """
    fechas = []
    for ordinal in range(2024 * 12 + 2, 2026 * 12 + 2):  # mar-2024 .. feb-2026
        anio, mes = divmod(ordinal, 12)
        fechas.extend([(anio, mes + 1)] * 2)
    por_mes = _por_mes(fechas)
    assert set(por_mes) == set(range(1, 13))
    assert all(media == 2 for media in por_mes.values())


def test_los_meses_del_borde_no_se_diluyen() -> None:
    """Diciembre 2025 → enero 2027 (14 meses): diciembre y enero caen dos veces,
    junio una. Tres publicaciones por mes → media 3 en todos."""
    fechas = []
    for ordinal in range(2025 * 12 + 11, 2027 * 12 + 1):
        anio, mes = divmod(ordinal, 12)
        fechas.extend([(anio, mes + 1)] * 3)
    por_mes = _por_mes(fechas)
    assert por_mes[12] == 3
    assert por_mes[1] == 3
    assert por_mes[6] == 3


def test_un_solo_mes_cuenta_una_vez() -> None:
    assert _por_mes([(2026, 1)]) == {1: 1}


def test_mes_sin_publicaciones_no_aparece_y_el_orden_es_de_calendario() -> None:
    serie = _estacionalidad([(2026, 5), (2026, 1), (2026, 3)])
    assert [e.mes_numero for e in serie] == [1, 3, 5]
