"""Tests unitarios para services/analytics/resumen.py

Parchea load_stats_dataframe, load_raw_adjudicaciones y db.users.get_user_by_id
con datos sintéticos; ningún test toca la base de datos.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from services.analytics.resumen import (
    ResumenHoyFilters,
    SankeyFilters,
    TimelineScatterFilters,
    TopLicitacionesFilters,
    get_resumen_hoy,
    get_resumen_novedades,
    get_sankey_flow,
    get_timeline_scatter,
    get_top_licitaciones,
)

# ---------------------------------------------------------------------------
# Helpers de datos sintéticos
# ---------------------------------------------------------------------------


def _iso(offset_days: int = 0) -> str:
    """Fecha ISO UTC desplazada `offset_days` días desde ahora."""
    dt = datetime.now(UTC) + timedelta(days=offset_days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _row(
    id_externo: str = "L001",
    titulo: str = "Contrato TI",
    organo: str = "Ministerio",
    importe: float = 100_000.0,
    estado: str = "PUB",
    fecha_pub_offset: int = -10,
    fecha_limite_offset: int = 30,
    ccaa: str = "Madrid",
    tecnologia: str = "SAP",
    tipo_contrato: str = "2",
) -> dict:
    return {
        "id_externo": id_externo,
        "titulo": titulo,
        "organo_contratacion": organo,
        "importe": importe,
        "estado": estado,
        "fecha_publicacion": _iso(fecha_pub_offset),
        "fecha_limite": _iso(fecha_limite_offset),
        "ccaa": ccaa,
        "tecnologia": tecnologia,
        "tipo_contrato": tipo_contrato,
    }


# ---------------------------------------------------------------------------
# get_resumen_novedades
# ---------------------------------------------------------------------------


def test_novedades_user_sin_last_login():
    """User con last_login=None → count=0, sample=[]."""
    user_mock = {"id": 1, "last_login": None}
    rows = [_row("L001", fecha_pub_offset=-1), _row("L002", fecha_pub_offset=-2)]

    with (
        patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame(rows)),
        patch("db.users.get_user_by_id", return_value=user_mock),
    ):
        result = get_resumen_novedades(1)

    assert result.count == 0
    assert result.sample == []


def test_novedades_con_new_since():
    """User con last_login hace 2 días → licitaciones publicadas ayer cuentan como novedades."""
    last_login = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    user_mock = {"id": 1, "last_login": last_login}

    rows = [
        _row("NEW1", fecha_pub_offset=-1),  # después del login → novedad
        _row("NEW2", fecha_pub_offset=-1),  # después del login → novedad
        _row("OLD1", fecha_pub_offset=-5),  # antes del login → no cuenta
    ]

    with (
        patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame(rows)),
        patch("db.users.get_user_by_id", return_value=user_mock),
    ):
        result = get_resumen_novedades(1)

    assert result.count == 2
    assert len(result.sample) == 2
    ids = {s.id_externo for s in result.sample}
    assert ids == {"NEW1", "NEW2"}


def test_novedades_user_no_existe():
    """get_user_by_id devuelve None → ResumenNovedadesResult vacío."""
    with (
        patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame([])),
        patch("db.users.get_user_by_id", return_value=None),
    ):
        result = get_resumen_novedades(99)

    assert result.count == 0
    assert result.sample == []


# ---------------------------------------------------------------------------
# get_resumen_hoy
# ---------------------------------------------------------------------------


def test_hoy_dataset_vacio():
    """DataFrame vacío → todos los KPIs en 0."""
    with patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame([])):
        result = get_resumen_hoy(ResumenHoyFilters())

    assert result.calientes == 0
    assert result.vencen_48h == 0
    assert result.nuevas_24h == 0
    assert result.total_activas == 0


def test_hoy_calientes_y_vencen():
    """Licitaciones con fecha_limite próxima (≤48h) → vencen_48h > 0.

    El cálculo de ``calientes`` requiere estado PUB/EV + importe >= P75 + fecha_limite > now.
    Usamos 4 filas con importes variados para que P75 sea conocido.
    """
    rows = [
        # 2 filas que vencen en 24h (dentro de las 48h)
        _row("A1", importe=200_000.0, estado="PUB", fecha_limite_offset=1),
        _row("A2", importe=150_000.0, estado="PUB", fecha_limite_offset=1),
        # 2 filas que vencen lejos
        _row("B1", importe=50_000.0, estado="PUB", fecha_limite_offset=60),
        _row("B2", importe=10_000.0, estado="PUB", fecha_limite_offset=90),
    ]

    with patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_resumen_hoy(ResumenHoyFilters())

    assert result.vencen_48h > 0
    assert result.total_activas == 4


def test_hoy_filtro_ccaa():
    """Filtro ccaa='Madrid' → total_activas solo incluye filas de Madrid."""
    rows = [
        _row("M1", ccaa="Madrid", estado="PUB"),
        _row("M2", ccaa="Madrid", estado="PUB"),
        _row("C1", ccaa="Cataluña", estado="PUB"),
    ]

    with patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_resumen_hoy(ResumenHoyFilters(ccaa="Madrid"))

    assert result.total_activas == 2


def test_hoy_solo_estados_activos_cuentan():
    """total_activas solo cuenta estado PUB y EV; ADJ/RES no."""
    rows = [
        _row("P1", estado="PUB"),
        _row("E1", estado="EV"),
        _row("R1", estado="RES"),  # no activa
        _row("A1", estado="ADJ"),  # no activa
    ]

    with patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_resumen_hoy(ResumenHoyFilters())

    assert result.total_activas == 2


# ---------------------------------------------------------------------------
# get_timeline_scatter
# ---------------------------------------------------------------------------


def test_timeline_scatter_devuelve_items():
    """Scatter devuelve campos id_externo, importe y fecha_publicacion."""
    rows = [
        _row("T1", importe=500_000.0),
        _row("T2", importe=250_000.0),
    ]

    with patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_timeline_scatter(TimelineScatterFilters())

    assert len(result.items) == 2
    ids = {item.id_externo for item in result.items}
    assert ids == {"T1", "T2"}
    for item in result.items:
        assert item.importe is not None
        assert item.fecha_publicacion is not None


def test_timeline_scatter_vacio():
    """DataFrame vacío → items=[]."""
    with patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame([])):
        result = get_timeline_scatter(TimelineScatterFilters())

    assert result.items == []


def test_timeline_scatter_campos_completos():
    """Cada item expone todos los campos definidos en TimelineScatterItem."""
    rows = [_row("F1", organo="Ayuntamiento", ccaa="Madrid", tipo_contrato="3")]

    with patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_timeline_scatter(TimelineScatterFilters())

    item = result.items[0]
    assert item.id_externo == "F1"
    assert item.organo_contratacion == "Ayuntamiento"
    assert item.ccaa == "Madrid"
    assert item.tipo_contrato == "3"
    assert item.estado == "PUB"


# ---------------------------------------------------------------------------
# get_sankey_flow
# ---------------------------------------------------------------------------


def test_sankey_nodes_y_links():
    """2 tipo_contrato × 2 estado → nodes y links no vacíos."""
    rows = [
        _row("S1", tipo_contrato="2", estado="PUB"),
        _row("S2", tipo_contrato="2", estado="ADJ"),
        _row("S3", tipo_contrato="3", estado="PUB"),
        _row("S4", tipo_contrato="3", estado="ADJ"),
    ]

    with patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_sankey_flow(SankeyFilters())

    # Debe tener 2 nodos tipo + 2 nodos estado = 4 nodos
    assert len(result.nodes) == 4
    assert len(result.links) == 4

    node_ids = {n.id for n in result.nodes}
    assert "tipo_2" in node_ids
    assert "tipo_3" in node_ids
    assert "estado_PUB" in node_ids
    assert "estado_ADJ" in node_ids

    # Cada link tiene value >= 1
    for link in result.links:
        assert link.value >= 1


def test_sankey_sin_columna_tipo_contrato():
    """Filas sin campo tipo_contrato → SankeyResult vacío."""
    rows = [
        {
            "id_externo": "X1",
            "titulo": "Sin tipo",
            "importe": 10_000.0,
            "estado": "PUB",
            "fecha_publicacion": _iso(-5),
            "ccaa": "Madrid",
            "tecnologia": "SAP",
            # tipo_contrato ausente a propósito
        }
    ]

    with patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_sankey_flow(SankeyFilters())

    assert result.nodes == []
    assert result.links == []


def test_sankey_dataset_vacio():
    """DataFrame vacío → SankeyResult vacío."""
    with patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame([])):
        result = get_sankey_flow(SankeyFilters())

    assert result.nodes == []
    assert result.links == []


# ---------------------------------------------------------------------------
# get_top_licitaciones
# ---------------------------------------------------------------------------


def test_top_licitaciones_enriquece_con_adjudicatario():
    """Top licitación con adjudicación → adjudicatario y baja_pct presentes."""
    rows = [
        _row("TOP1", importe=1_000_000.0),
        _row("TOP2", importe=500_000.0),
    ]
    adj_rows = [
        {
            "id_externo": "TOP1",
            "nombre": "EMPRESA GANADORA S.A.",
            "importe_adjudicado": 800_000.0,
            "importe_licitacion": 1_000_000.0,
        }
    ]

    with (
        patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame(rows)),
        patch("services.analytics.resumen.load_raw_adjudicaciones", return_value=adj_rows),
    ):
        result = get_top_licitaciones(TopLicitacionesFilters(n=2))

    top1 = next(i for i in result.items if i.id_externo == "TOP1")
    assert top1.adjudicatario == "EMPRESA GANADORA S.A."
    assert top1.baja_pct == pytest.approx(20.0)  # (1 - 800k/1000k) x 100


def test_top_licitaciones_sin_adjudicaciones():
    """Sin adjudicaciones → adjudicatario=None, baja_pct=None para todas."""
    rows = [_row("T1", importe=300_000.0), _row("T2", importe=200_000.0)]

    with (
        patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame(rows)),
        patch("services.analytics.resumen.load_raw_adjudicaciones", return_value=[]),
    ):
        result = get_top_licitaciones(TopLicitacionesFilters(n=5))

    assert len(result.items) == 2
    for item in result.items:
        assert item.adjudicatario is None
        assert item.baja_pct is None


def test_top_licitaciones_dataset_vacio():
    """DataFrame vacío → items=[]."""
    with (
        patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame([])),
        patch("services.analytics.resumen.load_raw_adjudicaciones", return_value=[]),
    ):
        result = get_top_licitaciones(TopLicitacionesFilters())

    assert result.items == []


def test_top_licitaciones_respeta_n():
    """Solo devuelve las N más grandes por importe."""
    rows = [_row(f"L{i}", importe=float(i * 10_000)) for i in range(1, 11)]

    with (
        patch("services.analytics.resumen.load_stats_base_df", return_value=pd.DataFrame(rows)),
        patch("services.analytics.resumen.load_raw_adjudicaciones", return_value=[]),
    ):
        result = get_top_licitaciones(TopLicitacionesFilters(n=3))

    assert len(result.items) == 3
    importes = [item.importe for item in result.items]
    # Los 3 mayores: L10=100k, L9=90k, L8=80k
    assert importes == sorted(importes, reverse=True)
