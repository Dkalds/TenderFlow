"""Tests unit de los loaders de señales de scoring (sin BD).

El SQL real se ejercita en ``tests/test_scoring_signals_db.py``; aquí se fija
la lógica que envuelve a ese SQL: qué población acaba siendo la referencia de
la dimensión ``importe``, cuándo se cae al fallback, y qué pasa cuando la
consulta revienta.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import services.analytics.scoring_signals as sig_mod
from services.analytics.scoring_signals import (
    ImportePercentiles,
    _months_ago,
    clear_scoring_signals_cache,
    load_importe_percentiles,
)


def _patch_repo(universo: tuple[float, float, int], glob: tuple[float, float] = (0.0, 0.0)):
    return (
        patch.object(sig_mod._repo, "importe_percentiles_universo", return_value=universo),
        patch.object(sig_mod._repo, "importe_percentiles", return_value=glob),
    )


def test_percentiles_usan_el_universo_vivo_cuando_hay_muestra():
    """Con muestra suficiente, la referencia es el mercado abierto, no la tabla."""
    clear_scoring_signals_cache()
    p_uni, p_glob = _patch_repo((10_000.0, 500_000.0, 1_643), glob=(1.0, 9.0))
    with p_uni, p_glob:
        pct = load_importe_percentiles()

    assert pct == ImportePercentiles(p10=10_000.0, p90=500_000.0, fuente="universo_vivo")
    clear_scoring_signals_cache()


def test_percentiles_caen_al_global_con_muestra_insuficiente():
    """Menos de 50 importes vivos: los percentiles serían ruido, gana el global."""
    clear_scoring_signals_cache()
    p_uni, p_glob = _patch_repo((1.0, 2.0, 7), glob=(5_000.0, 900_000.0))
    with p_uni, p_glob:
        pct = load_importe_percentiles()

    assert pct == ImportePercentiles(p10=5_000.0, p90=900_000.0, fuente="global")
    clear_scoring_signals_cache()


def test_percentiles_sin_datos_cuando_ninguna_fuente_discrimina():
    """Global degenerado (p90 <= p10): sin_datos → la dimensión importe queda neutral."""
    clear_scoring_signals_cache()
    p_uni, p_glob = _patch_repo((0.0, 0.0, 0), glob=(0.0, 0.0))
    with p_uni, p_glob:
        pct = load_importe_percentiles()

    assert pct.fuente == "sin_datos"
    assert pct.p10 == 0.0
    assert pct.p90 == 0.0
    clear_scoring_signals_cache()


def test_percentiles_degradan_sin_crash_si_la_query_falla():
    """Un fallo de BD no puede tumbar el scoring: degrada a neutral con fuente visible."""
    clear_scoring_signals_cache()
    with patch.object(
        sig_mod._repo, "importe_percentiles_universo", side_effect=RuntimeError("boom")
    ):
        pct = load_importe_percentiles()

    assert pct.fuente == "sin_datos"
    clear_scoring_signals_cache()


def test_percentiles_se_cachean_entre_llamadas():
    """La caché es lo que saca los 7,4 s del seq scan del camino caliente."""
    clear_scoring_signals_cache()
    p_uni, p_glob = _patch_repo((1.0, 2.0, 100))
    with p_uni as mock_uni, p_glob:
        load_importe_percentiles()
        load_importe_percentiles()

    assert mock_uni.call_count == 1
    clear_scoring_signals_cache()


def test_months_ago_usa_meses_de_calendario_no_bloques_de_30_dias():
    """24 meses son dos años exactos, no 720 días (que se comían ~24 días de historia)."""
    now = datetime(2026, 8, 12, 10, 30, tzinfo=UTC)

    assert _months_ago(24, now=now) == datetime(2024, 8, 12, 10, 30, tzinfo=UTC)


def test_months_ago_recorta_el_dia_a_la_longitud_del_mes_destino():
    """31 de marzo menos un mes es el último día de febrero, no un 31 inexistente."""
    now = datetime(2026, 3, 31, 0, 0, tzinfo=UTC)

    assert _months_ago(1, now=now) == datetime(2026, 2, 28, 0, 0, tzinfo=UTC)
