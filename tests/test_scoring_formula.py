"""Tests de la fórmula del score, dimensión a dimensión (unit, sin BD).

``test_analytics_scoring.py`` cubre el servicio —modos del endpoint, universo,
señales— pero las constantes que deciden el número no estaban fijadas por
nada: ningún test tocaba la dimensión importe, los cinco tramos de plazo, los
cortes de banda ni la penalización de −15, que es la mayor del sistema.

Aquí se construye el ``_ScoringContext`` a mano y se llama a ``_score_row``
directamente: cada caso fija un valor concreto, de modo que cambiar un umbral
obliga a cambiar el test que lo declara.
"""

from __future__ import annotations

import pandas as pd
import pytest

from services.analytics.scoring import (
    _band,
    _effective_weights,
    _score_row,
    _ScoringContext,
)
from services.analytics.scoring_signals import CompetenciaStats, MargenStats

_AHORA = pd.Timestamp("2026-08-12T00:00:00Z")

# Pesos planos: cada dimensión vale 100 para poder leer su aportación directa
# en el desglose sin despejar la suma ponderada.
_SOLO = {"importe": 0, "plazo": 0, "competencia": 0, "margen": 0}


def _ctx(
    *,
    weights: dict[str, int] | None = None,
    p10: float = 10_000.0,
    p90: float = 100_000.0,
    competencia: CompetenciaStats | None = None,
    margen: MargenStats | None = None,
    importe_min: float | None = None,
    importe_max: float | None = None,
    tech_signal: dict[str, float] | None = None,
) -> _ScoringContext:
    return _ScoringContext(
        imp_p10=p10,
        imp_p90=p90,
        weights=weights if weights is not None else dict(_SOLO),
        keywords=[],
        affinity_scores={},
        affinity_method="unavailable",
        competencia_stats=competencia if competencia is not None else CompetenciaStats(),
        margen_stats=margen if margen is not None else MargenStats(),
        percentiles_fuente="universo_vivo",
        tech_signal=tech_signal,
        importe_min=importe_min,
        importe_max=importe_max,
        now=_AHORA,
    )


def _row(**kwargs) -> pd.Series:
    base = {
        "id_externo": "L1",
        "titulo": "Contrato de prueba",
        "importe": 50_000.0,
        "cpv": "72000000",
        "fecha_limite_dt": _AHORA + pd.Timedelta(days=30),
    }
    base.update(kwargs)
    return pd.Series(base)


# ---------------------------------------------------------------------------
# Dimensión importe
# ---------------------------------------------------------------------------


def test_importe_por_debajo_del_p10_no_puntua():
    ctx = _ctx(weights={**_SOLO, "importe": 100})
    _, _, flags, desglose, _ = _score_row(_row(importe=500.0), ctx)

    assert desglose["importe"] == 0.0
    assert "sin_importe" not in flags


def test_importe_por_encima_del_p90_puntua_el_maximo_sin_pasarse():
    """El clamp superior evita que un contrato gigante desborde la dimensión."""
    ctx = _ctx(weights={**_SOLO, "importe": 100})
    _, _, _, desglose, _ = _score_row(_row(importe=50_000_000.0), ctx)

    assert desglose["importe"] == 100.0


def test_importe_interpola_linealmente_entre_percentiles():
    ctx = _ctx(weights={**_SOLO, "importe": 100}, p10=0.0, p90=100_000.0)
    _, _, _, desglose, _ = _score_row(_row(importe=25_000.0), ctx)

    assert desglose["importe"] == pytest.approx(25.0)


def test_importe_sin_rango_util_queda_neutral_y_sin_flag():
    """P90 == P10 no es un dato ausente: el universo no discrimina por importe."""
    ctx = _ctx(weights={**_SOLO, "importe": 100}, p10=50_000.0, p90=50_000.0)
    _, _, flags, desglose, _ = _score_row(_row(importe=50_000.0), ctx)

    assert desglose["importe"] == 50.0
    # El importe está: el hueco es del universo, no de la fila.
    assert "sin_importe" not in flags


def test_importe_ausente_es_neutral_pero_deja_rastro():
    ctx = _ctx(weights={**_SOLO, "importe": 100})
    _, _, flags, desglose, _ = _score_row(_row(importe=None), ctx)

    assert desglose["importe"] == 50.0
    assert "sin_importe" in flags


# ---------------------------------------------------------------------------
# Dimensión plazo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dias", "esperado"),
    [
        (-1, 0.0),  # vencido: no hay nada que presentar
        (0, 50.0),  # vence hoy: presentable, pero sin margen para preparar
        (6, 50.0),
        (7, 100.0),  # ventana buena
        (90, 100.0),
        (91, 70.0),  # lejos: la decisión no es de hoy
        (180, 70.0),
        (181, 30.0),
    ],
)
def test_plazo_escalones(dias: int, esperado: float):
    ctx = _ctx(weights={**_SOLO, "plazo": 100})
    row = _row(fecha_limite_dt=_AHORA + pd.Timedelta(days=dias))
    _, _, _, desglose, _ = _score_row(row, ctx)

    assert desglose["plazo"] == esperado


def test_plazo_ausente_es_neutral_con_flag():
    ctx = _ctx(weights={**_SOLO, "plazo": 100})
    _, _, flags, desglose, _ = _score_row(_row(fecha_limite_dt=pd.NaT), ctx)

    assert desglose["plazo"] == 50.0
    assert "sin_plazo" in flags


# ---------------------------------------------------------------------------
# Bandas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("score", "banda"),
    [
        (0, "Descarte"),
        (24, "Descarte"),
        (25, "Tibia"),
        (49, "Tibia"),
        (50, "Atractiva"),
        (74, "Atractiva"),
        (75, "Caliente"),
        (100, "Caliente"),
    ],
)
def test_cortes_de_banda(score: int, banda: str):
    assert _band(score) == banda


# ---------------------------------------------------------------------------
# Riesgo
# ---------------------------------------------------------------------------


def test_importe_por_debajo_del_minimo_del_perfil_penaliza_quince_puntos():
    """La penalización más grande del sistema: fuera del rango que el usuario puja."""
    ctx = _ctx(weights={**_SOLO, "importe": 100}, importe_min=100_000.0)
    _, _, flags, desglose, _ = _score_row(_row(importe=5_000.0), ctx)

    assert desglose["riesgo"] == -15.0
    assert "fuera_de_rango" in flags


def test_importe_por_encima_del_maximo_del_perfil_penaliza_igual():
    ctx = _ctx(weights={**_SOLO, "importe": 100}, importe_max=100_000.0)
    _, _, flags, desglose, _ = _score_row(_row(importe=900_000.0), ctx)

    assert desglose["riesgo"] == -15.0
    assert "fuera_de_rango" in flags


def test_importe_dentro_del_rango_no_penaliza():
    ctx = _ctx(importe_min=10_000.0, importe_max=100_000.0)
    _, _, flags, desglose, _ = _score_row(_row(importe=50_000.0), ctx)

    assert desglose["riesgo"] == 0.0
    assert "fuera_de_rango" not in flags


def test_sin_importe_no_se_juzga_fuera_de_rango():
    """No se puede penalizar por salirse de un rango que no se puede evaluar."""
    ctx = _ctx(importe_min=10_000.0)
    _, _, flags, desglose, _ = _score_row(_row(importe=None), ctx)

    assert "fuera_de_rango" not in flags
    assert desglose["riesgo"] == -5.0  # solo sin_importe


def test_las_penalizaciones_se_acumulan():
    ctx = _ctx()
    row = _row(importe=None, titulo="", fecha_limite_dt=pd.NaT)
    _, _, flags, desglose, _ = _score_row(row, ctx)

    assert set(flags) >= {"sin_importe", "sin_titulo", "sin_plazo"}
    assert desglose["riesgo"] == -10.0


def test_el_score_nunca_baja_de_cero():
    """Con todo en contra, el clamp inferior evita scores negativos."""
    ctx = _ctx(weights={**_SOLO}, importe_max=1.0)
    row = _row(importe=900_000.0, titulo="", fecha_limite_dt=pd.NaT)
    score, band, _, _, _ = _score_row(row, ctx)

    assert score == 0
    assert band == "Descarte"


# ---------------------------------------------------------------------------
# Dimensión señal técnica
# ---------------------------------------------------------------------------


def test_la_senal_tecnica_escala_con_la_fuerza_de_la_evidencia():
    """Una licitación con la tecnología confirmada en el pliego puntúa más."""
    ctx = _ctx(weights={**_SOLO, "senal_tecnica": 100}, tech_signal={"L1": 0.9})
    _, _, flags, desglose, _ = _score_row(_row(), ctx)

    assert desglose["senal_tecnica"] == pytest.approx(90.0)
    assert "sin_senal_tecnica" not in flags


def test_la_senal_tecnica_se_clampa_a_uno():
    """Un score fuera de rango en la tabla no puede desbordar la dimensión."""
    ctx = _ctx(weights={**_SOLO, "senal_tecnica": 100}, tech_signal={"L1": 4.2})
    _, _, _, desglose, _ = _score_row(_row(), ctx)

    assert desglose["senal_tecnica"] == 100.0


def test_sin_evidencia_la_senal_tecnica_es_neutral_con_flag():
    """Política de la casa: un hueco de cobertura propia no penaliza, se señala."""
    ctx = _ctx(weights={**_SOLO, "senal_tecnica": 100}, tech_signal={})
    _, _, flags, desglose, _ = _score_row(_row(), ctx)

    assert desglose["senal_tecnica"] == 50.0
    assert "sin_senal_tecnica" in flags


def test_si_la_consulta_de_senal_falla_no_se_culpa_a_la_fila():
    """Contexto None = avería del sistema: neutral, y sin flag que apunte a la fila."""
    ctx = _ctx(weights={**_SOLO, "senal_tecnica": 100}, tech_signal=None)
    _, _, flags, desglose, _ = _score_row(_row(), ctx)

    assert desglose["senal_tecnica"] == 50.0
    assert "sin_senal_tecnica" not in flags


def test_un_perfil_sin_la_dimension_no_ve_una_barra_muerta():
    """Perfil anterior a la dimensión: la clave se omite, no sale en cero."""
    ctx = _ctx(weights=dict(_SOLO), tech_signal={"L1": 0.9})
    _, _, _, desglose, _ = _score_row(_row(), ctx)

    assert "senal_tecnica" not in desglose


# ---------------------------------------------------------------------------
# Redistribución de pesos
# ---------------------------------------------------------------------------


def test_pesos_con_keywords_se_dejan_intactos():
    pesos = {"importe": 25, "plazo": 15, "competencia": 25, "margen": 20, "afinidad": 15}

    assert _effective_weights(pesos, ["sap"]) == pesos


def test_la_afinidad_sin_portfolio_se_reparte_y_conserva_la_suma():
    pesos = {"importe": 25, "plazo": 15, "competencia": 25, "margen": 20, "afinidad": 15}

    eff = _effective_weights(pesos, [])

    assert "afinidad" not in eff
    assert sum(eff.values()) == 100
    # El reparto es proporcional: quien más pesaba sigue pesando más.
    assert eff["importe"] >= eff["margen"] >= eff["plazo"]


def test_el_residuo_del_redondeo_cae_en_la_dimension_mayor():
    """Donde menos distorsiona en términos relativos (y donde dice el docstring)."""
    pesos = {"importe": 50, "plazo": 17, "competencia": 3, "afinidad": 30}

    eff = _effective_weights(pesos, [])

    assert sum(eff.values()) == 100
    # plazo y competencia reciben su parte proporcional redondeada...
    assert eff["competencia"] == 3 + round(30 * 3 / 70)
    assert eff["plazo"] == 17 + round(30 * 17 / 70)
    # ...e importe absorbe lo que falte para cuadrar.
    assert eff["importe"] == 100 - eff["competencia"] - eff["plazo"]


def test_la_redistribucion_conserva_una_suma_distinta_de_cien():
    """La función es pura: no reescala a 100 lo que no venía en 100."""
    pesos = {"importe": 30, "plazo": 10, "afinidad": 10}

    eff = _effective_weights(pesos, [])

    assert sum(eff.values()) == 50


def test_la_redistribucion_es_determinista_con_empates():
    pesos = {"importe": 20, "plazo": 20, "competencia": 20, "margen": 20, "afinidad": 20}

    primero = _effective_weights(pesos, [])
    segundo = _effective_weights(dict(reversed(list(pesos.items()))), [])

    assert primero == segundo
    assert sum(primero.values()) == 100


def test_un_perfil_de_solo_afinidad_no_deja_pesos_inventados():
    assert _effective_weights({"afinidad": 100}, []) == {}
