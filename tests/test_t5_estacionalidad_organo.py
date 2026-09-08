"""T5 — estacionalidad por órgano: el corte de ADR-014 lo decide el servicio.

Tests sin BD: la consulta mensual (``AggregateRepository.publicaciones_mensuales``)
se sustituye por una lista de filas, que es exactamente lo que el repositorio
devuelve. Lo que se afirma aquí es la regla, no el SQL:

- el resultado declara ``n_meses`` (meses de historia observados) siempre;
- por debajo de doce **no hay curva**: ``meses`` vacío y ``suficiente=False``;
- el denominador de cada casilla es el número de veces que ese mes del
  calendario cae en el tramo cubierto, no un ``n_years`` común a los doce.

El ``WHERE`` del filtro por órgano se afirma sobre ``build_licitaciones_where``,
que es una función pura de texto.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import patch

import pytest

from db.repositories.aggregates import LicitacionesFilters, build_licitaciones_where
from services.analytics import forecast_svc
from services.analytics.forecast_svc import (
    MIN_MESES_ESTACIONALIDAD,
    VENTANA_ESTACIONALIDAD_MESES,
    EstacionalidadFilters,
    get_estacionalidad_organo,
)

ORGANO = "Distrito de Chamberí"


def _mes(ordinal: int) -> str:
    return f"{ordinal // 12:04d}-{ordinal % 12 + 1:02d}"


def _serie(desde: str, meses: int, publicaciones: int = 2) -> list[dict[str, Any]]:
    """Serie mensual contigua tal y como la devuelve el repositorio."""
    anio, mes = (int(p) for p in desde.split("-"))
    inicio = anio * 12 + (mes - 1)
    return [{"mes": _mes(inicio + i), "publicaciones": publicaciones} for i in range(meses)]


def _correr(
    rows: list[dict[str, Any]], **kwargs: Any
) -> tuple[Any, list[tuple[LicitacionesFilters, str, str]]]:
    """Ejecuta el servicio con el repositorio sustituido; devuelve (resultado, llamadas)."""
    llamadas: list[tuple[LicitacionesFilters, str, str]] = []

    def _fake(
        filters: LicitacionesFilters, *, mes_desde: str, mes_hasta: str
    ) -> list[dict[str, Any]]:
        llamadas.append((filters, mes_desde, mes_hasta))
        return rows

    filtros = EstacionalidadFilters(organo=ORGANO, hasta=date(2026, 9, 8), **kwargs)
    with patch.object(forecast_svc._repo, "publicaciones_mensuales", side_effect=_fake):
        return get_estacionalidad_organo(filtros), llamadas


# ── El corte de ADR-014 ───────────────────────────────────────────────────────


def test_menos_de_doce_meses_no_pinta_curva() -> None:
    """Ocho meses de historia: se declara `n`, pero `meses` viene vacío."""
    resultado, _ = _correr(_serie("2026-02", 8))

    assert resultado.n_meses == 8
    assert resultado.suficiente is False
    assert resultado.meses == []
    assert resultado.motivo is not None
    assert "8" in resultado.motivo
    assert str(MIN_MESES_ESTACIONALIDAD) in resultado.motivo
    # El universo se declara aunque no haya curva.
    assert resultado.total_publicaciones == 16
    assert resultado.meses_con_publicaciones == 8
    assert (resultado.mes_desde, resultado.mes_hasta) == ("2026-02", "2026-09")


def test_doce_meses_justos_si_pintan() -> None:
    """Doce es el mínimo, no el primero que se rechaza."""
    resultado, _ = _correr(_serie("2025-10", 12))

    assert resultado.n_meses == 12
    assert resultado.suficiente is True
    assert resultado.motivo is None
    assert len(resultado.meses) == 12
    assert {m.mes for m in resultado.meses} == set(range(1, 13))
    # Doce meses contiguos: cada mes del calendario aparece exactamente una vez.
    assert {m.anios_observados for m in resultado.meses} == {1}


def test_once_meses_no_pintan() -> None:
    resultado, _ = _correr(_serie("2025-11", 11))

    assert resultado.n_meses == 11
    assert resultado.suficiente is False
    assert resultado.meses == []


def test_sin_publicaciones_declara_cero_y_no_inventa_ventana() -> None:
    resultado, _ = _correr([])

    assert resultado.n_meses == 0
    assert resultado.meses_con_publicaciones == 0
    assert resultado.total_publicaciones == 0
    assert resultado.mes_desde is None and resultado.mes_hasta is None
    assert resultado.suficiente is False
    assert resultado.meses == []
    assert resultado.motivo is not None


def test_organo_vacio_no_consulta_la_base() -> None:
    """Un órgano en blanco no es "todos los órganos": no se pregunta nada."""
    llamadas: list[Any] = []

    def _fake(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        llamadas.append((args, kwargs))
        return []

    with patch.object(forecast_svc._repo, "publicaciones_mensuales", side_effect=_fake):
        resultado = get_estacionalidad_organo(EstacionalidadFilters(organo="   "))

    assert llamadas == []
    assert resultado.suficiente is False
    assert resultado.meses == []


# ── El denominador ────────────────────────────────────────────────────────────


def test_denominador_por_mes_no_es_un_n_years_comun() -> None:
    """Tramo de 14 meses: enero y febrero caen dos veces; el resto, una.

    Es la regresión del patrón que sigue vivo en el drill-down de órgano
    (``services/analytics/organo_detail.py``: divide los doce meses por
    ``nunique(year)``), que infla las casillas del borde.
    """
    rows = _serie("2025-12", 14, publicaciones=3)  # 2025-12 .. 2027-01
    resultado, _ = _correr(rows)

    assert resultado.n_meses == 14
    assert resultado.suficiente is True
    por_mes = {m.mes: m for m in resultado.meses}
    assert por_mes[12].anios_observados == 2  # dic-2025 y dic-2026
    assert por_mes[1].anios_observados == 2  # ene-2026 y ene-2027
    assert por_mes[6].anios_observados == 1  # solo jun-2026
    assert por_mes[12].publicaciones == 6
    assert por_mes[12].media == 3.0
    assert por_mes[6].media == 3.0


def test_mes_cubierto_sin_publicaciones_es_un_cero_real() -> None:
    """Un hueco DENTRO del tramo cubierto cuenta en el denominador, con media 0."""
    rows = [r for r in _serie("2025-10", 12) if r["mes"] != "2026-03"]
    resultado, _ = _correr(rows)

    assert resultado.n_meses == 12  # el tramo sigue siendo de doce meses
    assert resultado.meses_con_publicaciones == 11
    assert resultado.suficiente is True
    marzo = next(m for m in resultado.meses if m.mes == 3)
    assert marzo.anios_observados == 1
    assert marzo.publicaciones == 0
    assert marzo.media == 0.0


def test_bucket_malformado_se_descarta_sin_tumbar_el_endpoint() -> None:
    """``fecha_publicacion`` es TEXT: un bucket que no sea YYYY-MM no cuenta."""
    rows = _serie("2025-10", 12)
    rows.append({"mes": "2025-13", "publicaciones": 99})  # mes imposible
    rows.append({"mes": "2025", "publicaciones": 99})  # sin mes
    resultado, _ = _correr(rows)

    assert resultado.n_meses == 12
    assert resultado.meses_con_publicaciones == 12
    assert resultado.total_publicaciones == 24  # los 99 + 99 no entran
    assert resultado.suficiente is True


def test_media_redondeada_con_denominador_declarado() -> None:
    rows = _serie("2024-01", 36, publicaciones=1)
    rows[0]["publicaciones"] = 4  # 2024-01
    resultado, _ = _correr(rows)

    assert resultado.n_meses == 36
    enero = next(m for m in resultado.meses if m.mes == 1)
    assert enero.anios_observados == 3  # 2024, 2025, 2026
    assert enero.publicaciones == 6  # 4 + 1 + 1
    assert enero.media == 2.0
    assert resultado.total_publicaciones == sum(int(r["publicaciones"]) for r in rows)


# ── La ventana y el filtro que llegan al repositorio ──────────────────────────


def test_ventana_por_defecto_son_36_meses_hasta_el_ancla() -> None:
    _, llamadas = _correr(_serie("2024-01", 36))

    assert len(llamadas) == 1
    filtros, mes_desde, mes_hasta = llamadas[0]
    assert mes_hasta == "2026-09"  # ancla = 2026-09-08
    assert mes_desde == "2023-10"  # 36 meses inclusive
    assert filtros.organo == ORGANO
    assert VENTANA_ESTACIONALIDAD_MESES == 36


def test_ventana_configurable() -> None:
    _, llamadas = _correr(_serie("2025-10", 12), meses=12)

    _, mes_desde, mes_hasta = llamadas[0]
    assert (mes_desde, mes_hasta) == ("2025-10", "2026-09")


def test_ambito_viaja_al_repositorio() -> None:
    _, llamadas = _correr(_serie("2024-01", 36), ccaa="Madrid", tecnologia="SAP")

    filtros, _, _ = llamadas[0]
    assert filtros.organo == ORGANO
    assert filtros.ccaa == "Madrid"
    assert filtros.tecnologia == "SAP"


def test_to_repo_filters_pasa_el_organo() -> None:
    """El forecast de volumen comparte el traductor de filtros."""
    repo_filters = forecast_svc._to_repo_filters(
        EstacionalidadFilters(organo=ORGANO, ccaa="Madrid")
    )
    assert repo_filters.organo == ORGANO
    assert repo_filters.ccaa == "Madrid"


# ── El WHERE del filtro por órgano ────────────────────────────────────────────


@pytest.mark.parametrize("alias", [None, "l"])
def test_where_por_organo_es_igualdad_parametrizada(alias: str | None) -> None:
    where, params = build_licitaciones_where(LicitacionesFilters(organo=ORGANO), alias=alias)
    columna = f"{alias}.organo_contratacion" if alias else "organo_contratacion"

    assert f"{columna} = %s" in where
    assert params == [ORGANO]
    # El nombre nunca se interpola en el SQL.
    assert ORGANO not in where


def test_where_ignora_un_organo_en_blanco() -> None:
    where, params = build_licitaciones_where(LicitacionesFilters(organo="  "))

    assert "organo_contratacion" not in where
    assert params == []


def test_organo_no_rompe_el_ambito_global() -> None:
    """``is_empty`` sigue reconociendo "sin filtros" tras añadir el campo."""
    assert LicitacionesFilters().is_empty() is True
    assert LicitacionesFilters(organo=ORGANO).is_empty() is False


# ── La ventana en SQL ─────────────────────────────────────────────────────────


class _CursorFalso:
    description = (("mes",), ("publicaciones",))

    def fetchall(self) -> list[tuple[str, int]]:
        return []


class _ConexionFalsa:
    def __init__(self) -> None:
        self.sql: str = ""
        self.params: list[Any] = []

    def execute(self, sql: str, params: list[Any]) -> _CursorFalso:
        self.sql = sql
        self.params = list(params)
        return _CursorFalso()

    def __enter__(self) -> _ConexionFalsa:
        return self

    def __exit__(self, *_: object) -> None:
        return None


@pytest.mark.parametrize(
    ("mes_hasta", "tras_el_fin"),
    [("2026-09", "2026-10-01"), ("2026-12", "2027-01-01"), ("2026-01", "2026-02-01")],
)
def test_ventana_mensual_es_un_rango_sargable(mes_hasta: str, tras_el_fin: str) -> None:
    """Cota superior EXCLUSIVA del día uno del mes siguiente, sin `substr` en el WHERE.

    Diciembre es el caso que rompe una implementación ingenua: el mes siguiente
    cambia de año.
    """
    from db.repositories.aggregates import AggregateRepository

    conexion = _ConexionFalsa()
    with patch("db.repositories.aggregates.connect_read", return_value=conexion):
        AggregateRepository().publicaciones_mensuales(
            LicitacionesFilters(organo=ORGANO),
            mes_desde="2024-01",
            mes_hasta=mes_hasta,
        )

    assert "fecha_publicacion >= %s AND fecha_publicacion < %s" in conexion.sql
    assert "substr(fecha_publicacion, 1, 7) >=" not in conexion.sql
    assert conexion.params[-2:] == ["2024-01-01", tras_el_fin]
    assert ORGANO in conexion.params  # el órgano viaja como parámetro, no en el SQL
    assert ORGANO not in conexion.sql
