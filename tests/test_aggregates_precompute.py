"""Tests para scheduler/aggregates_precompute.py y su paso de pipeline.

Cubre:
- run_aggregates_precompute: refresco de canónicas y tasas, cada uno en su try.
- _run_aggregates_precompute: un resultado que no es ``ok`` pone el paso en rojo.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# run_aggregates_precompute
# ---------------------------------------------------------------------------


def test_run_aggregates_precompute_returns_ok_status(tmp_db):
    """run_aggregates_precompute devuelve status=ok con BD vacía."""
    _db_mod, _ = tmp_db
    from scheduler.aggregates_precompute import run_aggregates_precompute

    result = run_aggregates_precompute()

    assert result["status"] == "ok"
    assert result["n_canonicas"] is not None


def test_ya_no_recalcula_agregados_sin_lector():
    """``mat_clusters`` (2026-11) y ``mat_top_empresas_ccaa`` (2026-07) no tenían lector."""
    import scheduler.aggregates_precompute as ap

    with (
        patch.object(ap, "refrescar_vista_canonicas", return_value=5),
        patch.object(ap, "record_event"),
        patch.object(ap, "_recalcular_tasas_anulacion", return_value=40),
    ):
        result = ap.run_aggregates_precompute()

    assert result["status"] == "ok"
    assert "n_clusters" not in result
    assert "n_empresas" not in result
    assert not hasattr(ap, "_recalcular_clusters")


def test_un_refresco_caido_es_error_y_las_tasas_corren_igual():
    """El refresco es la pieza crítica: si cae es ``error``, no ``partial``."""
    import scheduler.aggregates_precompute as ap

    with (
        patch.object(ap, "refrescar_vista_canonicas", side_effect=RuntimeError("vista bloqueada")),
        patch.object(ap, "record_event"),
        patch.object(ap, "_recalcular_tasas_anulacion", return_value=40) as tasas,
    ):
        result = ap.run_aggregates_precompute()

    assert result["status"] == "error"
    assert result["error"] == "canonicas"
    assert result["n_canonicas"] is None
    tasas.assert_called_once()
    assert result["n_tasas_anulacion"] == 40


# ---------------------------------------------------------------------------
# El paso bloqueante no puede salir verde con un precálculo roto
#
# `run_aggregates_precompute` captura sus fallos y los devuelve en `status`, y
# `ejecutar_paso` solo distingue `skipped` de lo demás: hasta 2026-11-08 un
# refresco de la vista caído dejaba la pasada verde, y la única señal era el
# healthcheck horas después.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["error", "partial"])
def test_el_paso_lanza_si_el_precalculo_no_sale_ok(status):
    import scheduler.pipeline_pasos_impl as impl

    resultado = {"status": status, "error": "canonicas"}
    with (
        patch("scheduler.aggregates_precompute.run_aggregates_precompute", return_value=resultado),
        pytest.raises(RuntimeError, match=status),
    ):
        impl._run_aggregates_precompute()


def test_un_precalculo_roto_deja_el_paso_en_error_y_la_pasada_roja():
    from scheduler import pipeline_cierre
    from scheduler.pipeline_pasos import STEP_ERROR, pasos_bloqueantes_fallidos

    roto = {"status": "error", "error": "canonicas"}
    with (
        patch.object(pipeline_cierre, "CANONICAL_STEPS", ["aggregates_precompute"]),
        patch("scheduler.aggregates_precompute.run_aggregates_precompute", return_value=roto),
        patch.object(pipeline_cierre, "_notify_step_failure") as aviso,
        patch.object(pipeline_cierre, "_cerrar_avisos_de_pasos_recuperados"),
    ):
        resultados = pipeline_cierre._run_post_ingestion_steps()

    assert resultados == {"aggregates_precompute": STEP_ERROR}
    aviso.assert_called_once()
    assert pasos_bloqueantes_fallidos(resultados) == ["aggregates_precompute"]


def test_un_precalculo_ok_deja_el_paso_ok():
    from scheduler import pipeline_cierre
    from scheduler.pipeline_pasos import STEP_OK

    with patch(
        "scheduler.aggregates_precompute.run_aggregates_precompute",
        return_value={"status": "ok", "n_canonicas": 5},
    ):
        assert pipeline_cierre.ejecutar_paso("aggregates_precompute") == STEP_OK


def test_el_refresco_deja_rastro_en_ops_events(tmp_db):
    """Sin este evento el healthcheck no puede ver una vista congelada.

    Es la única señal persistente que cruza del plano efímero de Actions al
    healthcheck: los counters de Prometheus mueren con el proceso.
    """
    _db_mod, _ = tmp_db
    import scheduler.aggregates_precompute as ap

    with patch.object(ap, "record_event") as record:
        result = ap.run_aggregates_precompute()

    assert result["status"] == "ok"
    record.assert_called_once()
    assert record.call_args.args[0] == "mv_canonicas_refresh"
    assert record.call_args.kwargs["value"] == float(result["n_canonicas"])


def test_no_se_emite_evento_si_el_refresco_falla(tmp_db):
    """Un evento emitido tras un fallo mentiría sobre la frescura de la vista."""
    _db_mod, _ = tmp_db
    import scheduler.aggregates_precompute as ap

    with (
        patch.object(ap, "refrescar_vista_canonicas", side_effect=RuntimeError("boom")),
        patch.object(ap, "record_event") as record,
    ):
        ap.run_aggregates_precompute()

    record.assert_not_called()
