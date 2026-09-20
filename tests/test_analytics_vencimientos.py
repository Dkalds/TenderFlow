"""Calendario de vencimientos (RFC ux-calendario #2-#4).

Dos bloques:

- **Sin BD**: la aritmética de ventanas, el día pico y el ensamblado del
  servicio con el repositorio sustituido. Es donde vive la lógica propia del
  módulo (el SQL es un ``GROUP BY``).
- **Con BD** (``tmp_db``): que cada día cuente exactamente lo que el listado
  devuelve con ``cierre_desde=cierre_hasta=D`` — la promesa del enlace del
  calendario — y que una ``fecha_limite`` con hora entre en su día.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

import services.analytics.vencimientos as v_mod
from services.analytics.vencimientos import (
    MAX_VENTANA_DIAS,
    VencimientoDia,
    VencimientosFilters,
    VentanaInvalida,
    dia_pico,
    get_vencimientos,
    validar_ventana,
    ventanas_kpi,
)

# ---------------------------------------------------------------------------
# Sin BD
# ---------------------------------------------------------------------------


def test_validar_ventana_acepta_un_anio_bisiesto_entero():
    validar_ventana(date(2028, 1, 1), date(2028, 12, 31))  # 366 días


def test_validar_ventana_rechaza_mas_de_366_dias():
    with pytest.raises(VentanaInvalida, match=str(MAX_VENTANA_DIAS)):
        validar_ventana(date(2026, 1, 1), date(2027, 1, 2))


def test_validar_ventana_rechaza_ventana_invertida():
    with pytest.raises(VentanaInvalida):
        validar_ventana(date(2026, 5, 2), date(2026, 5, 1))


def test_ventanas_kpi_son_cotas_exclusivas():
    hoy, manana, fin_7d, fin_mes = ventanas_kpi(date(2026, 9, 19))
    assert (hoy, manana, fin_7d, fin_mes) == (
        "2026-09-19",
        "2026-09-20",
        "2026-09-26",
        "2026-10-01",
    )


def test_ventanas_kpi_en_diciembre_cruza_de_anio():
    _, _, fin_7d, fin_mes = ventanas_kpi(date(2026, 12, 29))
    assert fin_7d == "2027-01-05"
    assert fin_mes == "2027-01-01"


def test_dia_pico_primer_maximo_y_vacio():
    dias = [
        VencimientoDia(fecha="2026-01-02", count=3, importe=0),
        VencimientoDia(fecha="2026-01-05", count=7, importe=0),
        VencimientoDia(fecha="2026-01-09", count=7, importe=0),
    ]
    pico = dia_pico(dias)
    assert pico is not None and pico.fecha == "2026-01-05"
    assert dia_pico([]) is None


class _RepoFalso:
    def __init__(self) -> None:
        self.llamadas: dict[str, Any] = {}

    def vencimientos_diarios(self, filters: Any, **kw: Any) -> list[dict[str, Any]]:
        self.llamadas["diarios"] = (filters, kw)
        return [
            {"dia": "2026-09-20", "count": 2, "importe": 1500.0},
            {"dia": "2026-09-22", "count": 5, "importe": None},
        ]

    def vencimientos_kpis(self, filters: Any, **kw: Any) -> dict[str, int]:
        self.llamadas["kpis"] = (filters, kw)
        return {"hoy": 1, "proximos_7d": 7, "resto_mes": 9}


def test_get_vencimientos_ensambla_serie_pico_y_kpis(monkeypatch):
    repo = _RepoFalso()
    monkeypatch.setattr(v_mod, "_repo", repo)

    res = get_vencimientos(
        VencimientosFilters(
            desde=date(2026, 1, 1),
            hasta=date(2026, 12, 31),
            ccaa="Madrid,Galicia",
            solo_abiertas=True,
        ),
        hoy=date(2026, 9, 19),
    )

    assert [d.fecha for d in res.dias] == ["2026-09-20", "2026-09-22"]
    assert res.dias[1].importe == 0.0  # importe NULL → 0, no revienta
    assert res.total == 7
    assert res.dia_pico is not None and res.dia_pico.fecha == "2026-09-22"
    assert res.kpis.hoy == "2026-09-19"
    assert (res.kpis.vencen_hoy, res.kpis.vencen_7d, res.kpis.vencen_resto_mes) == (1, 7, 9)

    filtros, kw = repo.llamadas["diarios"]
    # La cota superior es exclusiva: el día siguiente al `hasta`.
    assert kw == {"desde_iso": "2026-01-01", "hasta_exclusivo_iso": "2027-01-01"}
    # El ámbito global viaja entero al repositorio.
    assert filtros.ccaa == "Madrid,Galicia"
    assert filtros.solo_abiertas is True
    _, kw_kpis = repo.llamadas["kpis"]
    assert kw_kpis["manana_iso"] == "2026-09-20"


def test_get_vencimientos_valida_la_ventana_antes_de_consultar(monkeypatch):
    repo = _RepoFalso()
    monkeypatch.setattr(v_mod, "_repo", repo)
    with pytest.raises(VentanaInvalida):
        get_vencimientos(VencimientosFilters(desde=date(2026, 1, 1), hasta=date(2028, 1, 1)))
    assert repo.llamadas == {}


def test_ruta_traduce_ventana_invalida_a_422():
    from fastapi import HTTPException

    from api.routes.analytics import calendario_vencimientos

    # `cache_response` envuelve la función; `__wrapped__` es la ruta desnuda.
    ruta = getattr(calendario_vencimientos, "__wrapped__", calendario_vencimientos)
    with pytest.raises(HTTPException) as exc:
        ruta(
            desde=date(2026, 5, 2),
            hasta=date(2026, 5, 1),
            fecha_desde=None,
            fecha_hasta=None,
            ccaa=None,
            tecnologia=None,
            estado=None,
            q=None,
            importe_min=None,
            solo_abiertas=False,
            _user={},
        )
    assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# Con BD
# ---------------------------------------------------------------------------


def _seed(filas: list[dict[str, Any]]) -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo=f["id"],
                titulo="Contrato TI",
                importe=f.get("importe"),
                fecha_publicacion="2026-08-01",
                fecha_limite=f.get("fecha_limite"),
                ccaa=f.get("ccaa", "Madrid"),
                tecnologia=f.get("tecnologia", "SAP"),
                estado=f.get("estado", "PUB"),
            )
            for f in filas
        ]
    )


def test_vencimientos_cuentan_lo_mismo_que_el_listado_del_dia(tmp_db):
    from db.repositories.licitaciones import LicitacionRepository

    _seed(
        [
            {"id": "V1", "fecha_limite": "2026-09-20", "importe": 100.0},
            # Con hora: tiene que caer en su día, no fuera de la ventana.
            {"id": "V2", "fecha_limite": "2026-09-20T14:00:00+02:00", "importe": 50.0},
            {"id": "V3", "fecha_limite": "2026-09-21", "importe": 10.0},
            # Sin tecnología: el listado no la enseña, el calendario no la cuenta.
            {"id": "V4", "fecha_limite": "2026-09-20", "tecnologia": ""},
            {"id": "V5", "fecha_limite": "2026-10-15", "ccaa": "Galicia"},
            {"id": "V6", "fecha_limite": None},
        ]
    )

    res = get_vencimientos(
        VencimientosFilters(desde=date(2026, 9, 1), hasta=date(2026, 10, 31)),
        hoy=date(2026, 9, 20),
    )
    por_dia = {d.fecha: d for d in res.dias}
    assert por_dia["2026-09-20"].count == 2
    assert por_dia["2026-09-20"].importe == 150.0
    assert por_dia["2026-09-21"].count == 1
    assert por_dia["2026-10-15"].count == 1
    assert res.total == 4
    assert res.dia_pico is not None and res.dia_pico.fecha == "2026-09-20"

    # Paridad con el listado que abre el enlace del día.
    _items, total = LicitacionRepository().list_paginated(
        cierre_desde="2026-09-20", cierre_hasta="2026-09-20", limit=50
    )
    assert total == por_dia["2026-09-20"].count

    # KPIs relativos a hoy (2026-09-20): hoy=2, 7 días=3, resto de mes=3.
    assert res.kpis.vencen_hoy == 2
    assert res.kpis.vencen_7d == 3
    assert res.kpis.vencen_resto_mes == 3


def test_vencimientos_respetan_el_ambito_global(tmp_db):
    _seed(
        [
            {"id": "G1", "fecha_limite": "2026-09-20", "ccaa": "Madrid"},
            {"id": "G2", "fecha_limite": "2026-09-20", "ccaa": "Galicia"},
            {"id": "G3", "fecha_limite": "2026-09-20", "ccaa": "Galicia", "estado": "RES"},
        ]
    )
    res = get_vencimientos(
        VencimientosFilters(
            desde=date(2026, 9, 1),
            hasta=date(2026, 9, 30),
            ccaa="Galicia",
            solo_abiertas=True,
        ),
        hoy=date(2026, 9, 1),
    )
    assert res.total == 1
