"""Tests unitarios para services/analytics/proyectos_modulos.

Parchea load_stats_dataframe con filas sintéticas; sin BD. Cubre las dos
ramas de _build_modulos (columna explícita vs detección regex en títulos),
el YoY y los agregados tipo×estado / CPV.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pandas as pd

from services.analytics.proyectos_modulos import (
    ProyectosModulosFilters,
    _detect_modules,
    get_proyectos_modulos,
)


def _dias_atras(n: int) -> str:
    return (datetime.now(UTC) - timedelta(days=n)).strftime("%Y-%m-%d")


def _rows_regex() -> list[dict]:
    """Sin columna de módulos: fuerza la detección regex sobre títulos."""
    return [
        {
            "id_externo": "L1",
            "titulo": "Implantación SAP Ariba",
            "importe": 100_000.0,
            "estado": "ADJ",
            "fecha_publicacion": _dias_atras(30),
            "tipo_contrato": "2",
            "cpv": "72000000",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L2",
            "titulo": "Ampliación SAP Ariba fase II",
            "importe": 200_000.0,
            "estado": "PUB",
            "fecha_publicacion": _dias_atras(60),
            "tipo_contrato": "2",
            "cpv": "72000000",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L3",
            "titulo": "Renovación SAP Ariba",  # año anterior → base del YoY
            "importe": 80_000.0,
            "estado": "ADJ",
            "fecha_publicacion": _dias_atras(400),
            "tipo_contrato": "2",
            "cpv": "48000000",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L4",
            "titulo": "Obra civil del edificio",  # sin módulo SAP
            "importe": 999_000.0,
            "estado": "PUB",
            "fecha_publicacion": _dias_atras(30),
            "tipo_contrato": "3",
            "cpv": "45000000",
            "tecnologia": "SAP",
        },
    ]


# ── _detect_modules ─────────────────────────────────────────────────────────


def test_detect_modules_basico():
    assert "Ariba" in _detect_modules("Implantación SAP Ariba")
    assert "SuccessFactors" in _detect_modules("Soporte SuccessFactors nómina")
    assert _detect_modules("Obra civil del edificio") == []
    assert _detect_modules("") == []


def test_detect_modules_case_insensitive():
    assert "S/4HANA" in _detect_modules("migración a s/4hana")


# ── rama regex (sin columna de módulos) ─────────────────────────────────────


def test_modulos_deteccion_regex_en_titulos():
    with patch(
        "services.analytics.proyectos_modulos.load_stats_base_df",
        return_value=pd.DataFrame(_rows_regex()),
    ):
        result = get_proyectos_modulos(ProyectosModulosFilters())

    modulos = {m.modulo: m for m in result.modulos}
    assert "Ariba" in modulos
    assert modulos["Ariba"].count == 3
    assert modulos["Ariba"].importe == 380_000.0
    # L4 no clasifica → 3 clasificadas; el importe SAP excluye la obra civil
    assert result.total_clasificados == 3
    assert result.importe_total_sap == 380_000.0
    assert result.ticket_medio_sap == round(380_000.0 / 3, 2)


def test_top_modulo_yoy_crecimiento():
    """2 menciones último año vs 1 el anterior → +100%."""
    with patch(
        "services.analytics.proyectos_modulos.load_stats_base_df",
        return_value=pd.DataFrame(_rows_regex()),
    ):
        result = get_proyectos_modulos(ProyectosModulosFilters())

    assert result.top_modulo_yoy is not None
    assert result.top_modulo_yoy.modulo == "Ariba"
    assert result.top_modulo_yoy.crecimiento_pct == 100.0
    assert result.top_modulo_yoy.n_act == 2


def test_top_modulo_yoy_nuevo_sentinel():
    """Módulo sin histórico el año anterior → sentinel 999.0 (NUEVO)."""
    rows = [
        {
            "id_externo": f"L{i}",
            "titulo": "Soporte SuccessFactors",
            "importe": 10_000.0,
            "estado": "PUB",
            "fecha_publicacion": _dias_atras(20 + i),
            "tipo_contrato": "2",
            "cpv": "72000000",
            "tecnologia": "SAP",
        }
        for i in range(2)
    ]
    with patch(
        "services.analytics.proyectos_modulos.load_stats_base_df",
        return_value=pd.DataFrame(rows),
    ):
        result = get_proyectos_modulos(ProyectosModulosFilters())

    assert result.top_modulo_yoy is not None
    assert result.top_modulo_yoy.modulo == "SuccessFactors"
    assert result.top_modulo_yoy.crecimiento_pct == 999.0


# ── rama columna explícita ──────────────────────────────────────────────────


def test_modulos_columna_explicita():
    """Con columna `modulos` no se usa la regex: agrega directo por valor."""
    rows = [
        {
            "id_externo": "L1",
            "titulo": "Contrato uno",
            "modulos": "FI",
            "importe": 100_000.0,
            "estado": "ADJ",
            "fecha_publicacion": "2025-01-10",
            "tipo_contrato": "2",
            "cpv": "72000000",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L2",
            "titulo": "Contrato dos",
            "modulos": "FI",
            "importe": 50_000.0,
            "estado": "PUB",
            "fecha_publicacion": "2025-01-15",
            "tipo_contrato": "2",
            "cpv": "72000000",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L3",
            "titulo": "Contrato tres",
            "modulos": None,  # sin clasificar
            "importe": 999_000.0,
            "estado": "PUB",
            "fecha_publicacion": "2025-02-01",
            "tipo_contrato": "3",
            "cpv": "45000000",
            "tecnologia": "SAP",
        },
    ]
    with patch(
        "services.analytics.proyectos_modulos.load_stats_base_df",
        return_value=pd.DataFrame(rows),
    ):
        result = get_proyectos_modulos(ProyectosModulosFilters())

    assert [m.modulo for m in result.modulos] == ["FI"]
    assert result.modulos[0].count == 2
    assert result.total_clasificados == 2
    assert result.importe_total_sap == 150_000.0
    assert result.ticket_medio_sap == 75_000.0


# ── agregados auxiliares ────────────────────────────────────────────────────


def test_tipos_proyecto_y_tipo_estado():
    with patch(
        "services.analytics.proyectos_modulos.load_stats_base_df",
        return_value=pd.DataFrame(_rows_regex()),
    ):
        result = get_proyectos_modulos(ProyectosModulosFilters())

    tipos = {t.tipo: t for t in result.tipos_proyecto}
    assert tipos["2"].count == 3
    assert tipos["3"].count == 1
    # Cross-tab: cada fila clasificada por tipo aparece una vez
    assert sum(e.n for e in result.tipo_estado) == 4
    assert {e.tipo for e in result.tipo_estado} == {"2", "3"}


def test_cpv_top_con_descripcion():
    with patch(
        "services.analytics.proyectos_modulos.load_stats_base_df",
        return_value=pd.DataFrame(_rows_regex()),
    ):
        result = get_proyectos_modulos(ProyectosModulosFilters())

    cpvs = {c.cpv: c for c in result.cpv}
    assert cpvs["72000000"].count == 2
    assert isinstance(cpvs["72000000"].cpv_desc, str)


def test_filtro_fechas_reduce_dataset():
    with patch(
        "services.analytics.proyectos_modulos.load_stats_base_df",
        return_value=pd.DataFrame(_rows_regex()),
    ):
        result = get_proyectos_modulos(
            ProyectosModulosFilters(fecha_desde=(datetime.now(UTC) - timedelta(days=90)).date())
        )

    # Quedan L1, L2 (Ariba) y L4 (sin módulo); L3 (400 días) fuera
    assert result.total_clasificados == 2


def test_dataset_vacio():
    with patch(
        "services.analytics.proyectos_modulos.load_stats_base_df",
        return_value=pd.DataFrame([]),
    ):
        result = get_proyectos_modulos(ProyectosModulosFilters())
    assert result.modulos == []
    assert result.total_clasificados == 0
    assert result.top_modulo_yoy is None
    assert result.cpv == []
