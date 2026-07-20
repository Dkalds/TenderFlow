"""Tests unitarios para services/analytics/pipeline.py.

Parchea ``load_stats_dataframe`` con filas sintéticas; el motor real
(get_pipeline / PipelineResult) corre sin mocks de BD.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pandas as pd

from services.analytics.pipeline import PipelineFilters, get_pipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(offset_days: int) -> str:
    """Fecha ISO-8601 con timezone UTC a ``offset_days`` días de ahora."""
    return (datetime.now(UTC) + timedelta(days=offset_days)).isoformat()


def _row(id_externo: str, dias_offset: int, importe: float | None = 100_000.0) -> dict:
    """Fila mínima que satisface el pipeline (fecha_limite en el futuro).

    No incluye "score": ese campo no existe en ``load_stats_base_df()``
    (ver ``_STATS_COLUMNS`` en services/licitaciones.py) — el score real
    llega vía ``score_dataframe`` (services.analytics.scoring), mergeado
    aparte. Incluirlo aquí colisionaría con esa columna (score_x/score_y).
    """
    return {
        "id_externo": id_externo,
        "titulo": f"Licitación {id_externo}",
        "organo_contratacion": "Ministerio Test",
        "importe": importe,
        "fecha_limite": _iso(dias_offset),
        "estado": "PUB",
        "fecha_publicacion": _iso(-30),
        "tecnologia": "SAP",
        "ccaa": "Madrid",
    }


# ---------------------------------------------------------------------------
# Dataset vacío → PipelineResult con valores default
# ---------------------------------------------------------------------------


def test_pipeline_dataset_vacio_devuelve_defaults():
    """Con load_stats_dataframe vacío se devuelve PipelineResult con ceros."""
    with patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame([])):
        result = get_pipeline(PipelineFilters(dias=30, limit=50))

    assert result.total_en_plazo == 0
    assert result.vencen_7d == 0
    assert result.vencen_30d == 0
    assert result.valor_total == 0.0
    assert result.upcoming == []
    assert result.por_horizonte == []


# ---------------------------------------------------------------------------
# Sin columna fecha_limite → early return
# ---------------------------------------------------------------------------


def test_pipeline_sin_columna_fecha_limite_early_return():
    """Filas sin fecha_limite nunca generan fecha_limite_dt → PipelineResult vacío."""
    rows = [
        {
            "id_externo": "X001",
            "titulo": "Sin fecha",
            "importe": 50_000.0,
            "estado": "PUB",
            # No hay 'fecha_limite' en este dict
        }
    ]
    with patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_pipeline(PipelineFilters(dias=30, limit=50))

    assert result.total_en_plazo == 0
    assert result.upcoming == []


# ---------------------------------------------------------------------------
# Todo vencido → listas vacías
# ---------------------------------------------------------------------------


def test_pipeline_todo_vencido_devuelve_listas_vacias():
    """Filas con fecha_limite en el pasado son filtradas → upcoming vacío."""
    rows = [
        _row("VENC-001", -5),
        _row("VENC-002", -10),
        _row("VENC-003", -1),
    ]
    with patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_pipeline(PipelineFilters(dias=30, limit=50))

    assert result.upcoming == []
    assert result.total_en_plazo == 0
    assert result.vencen_7d == 0


# ---------------------------------------------------------------------------
# Buckets por horizonte (+3d / +10d / +45d / +100d)
# ---------------------------------------------------------------------------


def test_pipeline_buckets_por_horizonte():
    """4 licitaciones en distintos horizontes → conteos correctos."""
    rows = [
        _row("H-3d", 3),  # bucket <7d
        _row("H-10d", 10),  # bucket 7-30d
        _row("H-45d", 45),  # bucket 30-90d
        _row("H-100d", 100),  # bucket 90+d
    ]
    # dias=120 para incluir todos
    with patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_pipeline(PipelineFilters(dias=120, limit=50))

    assert result.total_en_plazo == 4

    horizonte_map = {h.horizonte: h.count for h in result.por_horizonte}
    assert horizonte_map.get("<7d", 0) == 1
    assert horizonte_map.get("7-30d", 0) == 1
    assert horizonte_map.get("30-90d", 0) == 1
    assert horizonte_map.get("90+d", 0) == 1


def test_pipeline_vencen_7d_y_30d():
    """vencen_7d y vencen_30d reflejan los conteos correctos."""
    rows = [
        _row("V7-A", 3),  # ≤7d → cuenta en vencen_7d y vencen_30d
        _row("V7-B", 6),  # ≤7d
        _row("V30-A", 15),  # ≤30d pero >7d → solo vencen_30d
        _row("V30-B", 29),  # ≤30d
        _row("V90", 50),  # >30d → ni vencen_7d ni vencen_30d
    ]
    with patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_pipeline(PipelineFilters(dias=120, limit=50))

    assert result.vencen_7d == 2
    assert result.vencen_30d == 4
    assert result.total_en_plazo == 5


# ---------------------------------------------------------------------------
# Parámetro limit en upcoming
# ---------------------------------------------------------------------------


def test_pipeline_limit_controla_upcoming():
    """El parámetro limit recorta upcoming sin afectar total_en_plazo ni conteos."""
    rows = [_row(f"LIM-{i:03d}", i + 1) for i in range(20)]  # 20 licitaciones en 1..20d

    with patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_pipeline(PipelineFilters(dias=30, limit=5))

    assert len(result.upcoming) == 5
    assert result.total_en_plazo == 20  # el total no se recorta


def test_pipeline_limit_mayor_que_datos_no_falla():
    """limit > nº de filas no lanza error y devuelve todas las entradas."""
    rows = [_row(f"FEW-{i}", i + 1) for i in range(3)]

    with patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_pipeline(PipelineFilters(dias=30, limit=100))

    assert len(result.upcoming) == 3


# ---------------------------------------------------------------------------
# importe None no rompe el pipeline
# ---------------------------------------------------------------------------


def test_pipeline_importe_none_no_rompe():
    """Filas con importe=None no deben lanzar excepción."""
    rows = [
        _row("NONE-IMP-1", 5, importe=None),
        _row("NONE-IMP-2", 10, importe=None),
        _row("CON-IMP", 8, importe=200_000.0),
    ]
    with patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_pipeline(PipelineFilters(dias=30, limit=50))

    assert result.total_en_plazo == 3
    # Las entradas con importe None deben aparecer en upcoming con importe=None
    ids_none = [e.id_externo for e in result.upcoming if e.importe is None]
    assert len(ids_none) == 2


# ---------------------------------------------------------------------------
# upcoming ordenado por urgencia (dias_restantes ascendente)
# ---------------------------------------------------------------------------


def test_pipeline_upcoming_ordenado_por_urgencia():
    """upcoming está ordenado de menor a mayor dias_restantes."""
    rows = [
        _row("ORD-C", 20),
        _row("ORD-A", 2),
        _row("ORD-B", 10),
    ]
    with patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_pipeline(PipelineFilters(dias=30, limit=50))

    dias = [e.dias_restantes for e in result.upcoming]
    assert dias == sorted(dias)


# ---------------------------------------------------------------------------
# valor_total refleja la suma de importes del dataset completo
# ---------------------------------------------------------------------------


def test_pipeline_valor_total_suma_importes():
    """valor_total es la suma de importe de todas las licitaciones en la ventana."""
    rows = [
        _row("VAL-1", 5, importe=100_000.0),
        _row("VAL-2", 10, importe=200_000.0),
        _row("VAL-3", 20, importe=300_000.0),
    ]
    with patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_pipeline(PipelineFilters(dias=30, limit=50))

    assert result.valor_total == 600_000.0


def test_pipeline_por_horizonte_tiene_cuatro_buckets():
    """por_horizonte siempre devuelve los 4 buckets (<7d, 7-30d, 30-90d, 90+d)."""
    rows = [_row("BK-1", 5)]
    with patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_pipeline(PipelineFilters(dias=120, limit=50))

    assert len(result.por_horizonte) == 4
    etiquetas = {h.horizonte for h in result.por_horizonte}
    assert etiquetas == {"<7d", "7-30d", "30-90d", "90+d"}


# ---------------------------------------------------------------------------
# Score / banda / calientes — wiring de score_dataframe (scoring.py se testea
# en test_analytics_scoring.py; aquí solo verificamos que pipeline.py conecta
# bien el resultado, mockeando score_dataframe para aislar la integración).
# ---------------------------------------------------------------------------


def _fake_score_dataframe(bands: dict[str, str]):
    """Doble de score_dataframe: banda determinista por id_externo (default Tibia)."""

    def _fn(base_df, target_df):
        if target_df.empty:
            return pd.DataFrame(columns=["id_externo", "score", "band"])
        ids = target_df["id_externo"].astype(str).tolist()
        band_score = {"Caliente": 80, "Atractiva": 60, "Tibia": 30, "Descarte": 10}
        rows = [
            {
                "id_externo": i,
                "score": band_score[bands.get(i, "Tibia")],
                "band": bands.get(i, "Tibia"),
            }
            for i in ids
        ]
        return pd.DataFrame(rows)

    return _fn


def test_pipeline_score_y_band_poblados_en_upcoming():
    """score/band de PipelineEntry vienen del merge con score_dataframe (ya no null)."""
    rows = [_row("SC-1", 5), _row("SC-2", 10)]
    fake = _fake_score_dataframe({"SC-1": "Caliente", "SC-2": "Atractiva"})
    with (
        patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)),
        patch("services.analytics.pipeline.score_dataframe", side_effect=fake),
    ):
        result = get_pipeline(PipelineFilters(dias=30, limit=50))

    by_id = {e.id_externo: e for e in result.upcoming}
    assert by_id["SC-1"].score == 80
    assert by_id["SC-1"].band == "Caliente"
    assert by_id["SC-2"].band == "Atractiva"


def test_pipeline_calientes_cuenta_solo_banda_caliente():
    """calientes/valor_calientes cuentan solo band=='Caliente', sobre toda la ventana."""
    rows = [
        _row("CAL-1", 5, importe=100_000.0),
        _row("CAL-2", 10, importe=200_000.0),
        _row("CAL-3", 20, importe=50_000.0),
    ]
    fake = _fake_score_dataframe({"CAL-1": "Caliente", "CAL-2": "Caliente", "CAL-3": "Tibia"})
    with (
        patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)),
        patch("services.analytics.pipeline.score_dataframe", side_effect=fake),
    ):
        result = get_pipeline(PipelineFilters(dias=30, limit=50))

    assert result.calientes == 2
    assert result.valor_calientes == 300_000.0


def test_pipeline_calientes_no_se_recorta_por_limit():
    """calientes cuenta sobre la ventana completa, no solo los `limit` items devueltos."""
    rows = [_row(f"LIMCAL-{i}", i + 1, importe=10_000.0) for i in range(10)]
    fake = _fake_score_dataframe({f"LIMCAL-{i}": "Caliente" for i in range(10)})
    with (
        patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)),
        patch("services.analytics.pipeline.score_dataframe", side_effect=fake),
    ):
        result = get_pipeline(PipelineFilters(dias=30, limit=2))

    assert len(result.upcoming) == 2
    assert result.calientes == 10


# ---------------------------------------------------------------------------
# Filtros globales (ccaa/tecnologia/estado/q/importe_min/fecha_desde/fecha_hasta)
# ---------------------------------------------------------------------------


def test_pipeline_filtro_ccaa():
    rows = [_row("CCAA-MAD", 5), _row("CCAA-CAT", 5)]
    rows[1]["ccaa"] = "Cataluña"
    with patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_pipeline(PipelineFilters(dias=30, limit=50, ccaa="Madrid"))

    assert result.total_en_plazo == 1
    assert result.upcoming[0].id_externo == "CCAA-MAD"


def test_pipeline_filtro_q_busca_en_titulo():
    rows = [_row("Q-1", 5), _row("Q-2", 5)]
    rows[0]["titulo"] = "Suministro de licencias SAP"
    rows[1]["titulo"] = "Obra de reforma de fachada"
    with patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_pipeline(PipelineFilters(dias=30, limit=50, q="sap"))

    assert result.total_en_plazo == 1
    assert result.upcoming[0].id_externo == "Q-1"


def test_pipeline_filtro_importe_min():
    rows = [
        _row("IMPMIN-LOW", 5, importe=10_000.0),
        _row("IMPMIN-HIGH", 5, importe=500_000.0),
    ]
    with patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_pipeline(PipelineFilters(dias=30, limit=50, importe_min=100_000.0))

    assert result.total_en_plazo == 1
    assert result.upcoming[0].id_externo == "IMPMIN-HIGH"


def test_pipeline_filtro_estado():
    rows = [_row("EST-PUB", 5), _row("EST-EV", 5)]
    rows[1]["estado"] = "EV"
    with patch("services.analytics.pipeline.load_stats_base_df", return_value=pd.DataFrame(rows)):
        result = get_pipeline(PipelineFilters(dias=30, limit=50, estado="EV"))

    assert result.total_en_plazo == 1
    assert result.upcoming[0].id_externo == "EST-EV"
