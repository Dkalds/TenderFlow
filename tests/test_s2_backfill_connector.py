"""Bucle por meses del carril bulk/backfill sobre conectores (S2.1).

Tests de caracterización escritos **antes** de borrar
``scraper.pipeline.process_month`` / ``backfill``: fijan la lista de meses que
recorre el camino nuevo, incluido el borde de fin de año que el cálculo por
``relativedelta`` es capaz de romper en silencio.

Sin BD: se intercepta ``run_connector`` y se afirma sobre los meses con los que
se construyeron los conectores.
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scheduler.pipeline_runs import meses_a_procesar

# ---------------------------------------------------------------------------
# La lista de meses
# ---------------------------------------------------------------------------


def test_bulk_toma_los_n_meses_mas_recientes_del_mas_nuevo_al_mas_viejo() -> None:
    """Orden descendente: si el job se corta, lo que entró es lo reciente."""
    assert meses_a_procesar(3, hoy=date(2026, 9, 15)) == [
        (2026, 9),
        (2026, 8),
        (2026, 7),
    ]


def test_bulk_cruza_el_fin_de_ano_hacia_atras() -> None:
    assert meses_a_procesar(4, hoy=date(2026, 2, 3)) == [
        (2026, 2),
        (2026, 1),
        (2025, 12),
        (2025, 11),
    ]


def test_bulk_exige_al_menos_un_mes() -> None:
    with pytest.raises(ValueError, match="months must be >= 1"):
        meses_a_procesar(0, hoy=date(2026, 9, 15))


def test_backfill_va_del_mes_de_inicio_hasta_hoy_en_orden_cronologico() -> None:
    """Ascendente a propósito: gana el mes procesado en último lugar.

    El ZIP mensual de PLACSP no trae ``<updated>`` por entry, así que
    ``fecha_actualizacion_fuente`` va vacía y el desempate entre dos
    apariciones del mismo expediente lo decide el orden de escritura.
    """
    assert meses_a_procesar(desde=(2026, 7), hoy=date(2026, 9, 15)) == [
        (2026, 7),
        (2026, 8),
        (2026, 9),
    ]


def test_backfill_cruza_el_fin_de_ano_hacia_adelante() -> None:
    assert meses_a_procesar(desde=(2025, 11), hoy=date(2026, 2, 3)) == [
        (2025, 11),
        (2025, 12),
        (2026, 1),
        (2026, 2),
    ]


def test_backfill_del_mes_en_curso_devuelve_solo_ese_mes() -> None:
    assert meses_a_procesar(desde=(2026, 9), hoy=date(2026, 9, 15)) == [(2026, 9)]


def test_backfill_futuro_no_devuelve_meses() -> None:
    assert meses_a_procesar(desde=(2027, 1), hoy=date(2026, 9, 15)) == []


def test_backfill_valida_el_mes() -> None:
    """Mismo contrato que tenía ``scraper.pipeline.backfill``."""
    with pytest.raises(ValueError, match="start_month must be 1-12"):
        meses_a_procesar(desde=(2026, 13), hoy=date(2026, 9, 15))
    with pytest.raises(ValueError, match="start_month must be 1-12"):
        meses_a_procesar(desde=(2026, 0), hoy=date(2026, 9, 15))


def test_backfill_valida_el_ano() -> None:
    with pytest.raises(ValueError, match="start_year must be >= 2000"):
        meses_a_procesar(desde=(1999, 5), hoy=date(2026, 9, 15))


# ---------------------------------------------------------------------------
# El bucle: qué conectores se construyen y en qué orden
# ---------------------------------------------------------------------------


def _resultado_falso(source_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        source_id=source_id,
        fetch_failed=False,
        fetched=0,
        parsed=0,
        nuevas=0,
        actualizadas=0,
        adjudicaciones=0,
        errores=0,
    )


def _correr_bucle(**kwargs: Any) -> list[str]:
    """Ejecuta el bucle interceptando ``run_connector``; devuelve los source_id.

    ``bulk_YYYYMM`` ES el ``source_id`` del conector, así que la lista
    devuelta es a la vez la secuencia de meses y la etiqueta con la que se
    escriben ``extracciones`` y la DLQ.
    """
    from scheduler.pipeline_runs import _run_bulk_pipeline_connector

    vistos: list[str] = []

    def _fake_run_connector(connector: Any, **_: Any) -> SimpleNamespace:
        vistos.append(connector.source_id)
        return _resultado_falso(connector.source_id)

    with (
        patch("scraper.connectors.base.run_connector", side_effect=_fake_run_connector),
        patch("db.database.log_extraccion"),
        patch("observability.bind_run_context", return_value="run-test"),
        patch("observability.record_run", return_value=nullcontext(MagicMock())),
        patch("scraper.pipeline._summarize"),
        patch("scheduler.pipeline_runs._finalize_ingestion", return_value={"status": "ok"}),
    ):
        _run_bulk_pipeline_connector(**kwargs)

    return vistos


def test_el_bucle_bulk_construye_un_conector_por_mes_reciente() -> None:
    with patch("scheduler.pipeline_runs.meses_a_procesar", return_value=[(2026, 9), (2026, 8)]):
        assert _correr_bucle(months=2) == ["bulk_202609", "bulk_202608"]


def test_el_bucle_de_backfill_recorre_el_rango_completo() -> None:
    with patch(
        "scheduler.pipeline_runs.meses_a_procesar",
        return_value=[(2025, 12), (2026, 1), (2026, 2)],
    ):
        assert _correr_bucle(desde=(2025, 12)) == [
            "bulk_202512",
            "bulk_202601",
            "bulk_202602",
        ]


def test_un_mes_que_revienta_no_aborta_los_siguientes() -> None:
    """Paridad con el legacy: un mes roto se registra y el bucle continúa."""
    from scheduler.pipeline_runs import _run_bulk_pipeline_connector

    vistos: list[str] = []
    capturado: dict[str, Any] = {}

    def _fake_run_connector(connector: Any, **_: Any) -> SimpleNamespace:
        vistos.append(connector.source_id)
        if connector.source_id == "bulk_202608":
            raise RuntimeError("ZIP corrupto")
        return _resultado_falso(connector.source_id)

    def _fake_finalize(results: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
        capturado["results"] = results
        capturado["label"] = label
        return {"status": "ok"}

    with (
        patch("scraper.connectors.base.run_connector", side_effect=_fake_run_connector),
        patch("db.database.log_extraccion"),
        patch("observability.bind_run_context", return_value="run-test"),
        patch("observability.record_run", return_value=nullcontext(MagicMock())),
        patch("scraper.pipeline._summarize"),
        patch("scheduler.pipeline_runs._finalize_ingestion", side_effect=_fake_finalize),
        patch(
            "scheduler.pipeline_runs.meses_a_procesar",
            return_value=[(2026, 9), (2026, 8), (2026, 7)],
        ),
    ):
        _run_bulk_pipeline_connector(months=3)

    assert vistos == ["bulk_202609", "bulk_202608", "bulk_202607"]
    estados = {(r["year"], r["month"]): r["status"] for r in capturado["results"]}
    assert estados == {(2026, 9): "ok", (2026, 8): "error", (2026, 7): "ok"}


# ---------------------------------------------------------------------------
# Los dos callers apuntan al camino nuevo
# ---------------------------------------------------------------------------


def test_run_backfill_pipeline_delega_en_el_bucle_por_conectores() -> None:
    from scheduler.pipeline_runs import run_backfill_pipeline

    with patch("scheduler.pipeline_runs._run_bulk_pipeline_connector") as bucle:
        run_backfill_pipeline(2024, 3)

    assert bucle.call_args.kwargs["desde"] == (2024, 3)


def test_run_bulk_pipeline_delega_en_el_bucle_por_conectores() -> None:
    from scheduler.pipeline_runs import run_bulk_pipeline

    with patch("scheduler.pipeline_runs._run_bulk_pipeline_connector") as bucle:
        run_bulk_pipeline(5)

    bucle.assert_called_once_with(5)


def test_el_pipeline_legacy_ya_no_expone_los_escritores_bulk() -> None:
    """``process_month``/``backfill``/``update_recent`` se retiraron (S2.1).

    Escribían con ``upsert_licitaciones`` —sin historial— y sin lotes, sin
    documentos, sin dedupe, sin salud de fuente y sin columnas de linaje.
    """
    import scraper.pipeline as legacy

    assert not hasattr(legacy, "process_month")
    assert not hasattr(legacy, "backfill")
    assert not hasattr(legacy, "update_recent")


def test_el_dispatch_de_la_dlq_reprocesa_meses_por_el_conector() -> None:
    """Una entrada ``bulk_YYYYMM`` ya no pasa por el pipeline legacy."""
    from scheduler.dlq_retry import dispatch_retry

    construidos: list[tuple[int, int]] = []

    class _FakeBulkConnector:
        def __init__(self, year: int, month: int) -> None:
            construidos.append((year, month))
            self.source_id = f"bulk_{year}{month:02d}"

    with (
        patch("scraper.connectors.placsp.PlacspBulkConnector", _FakeBulkConnector),
        patch(
            "scraper.connectors.base.run_connector",
            return_value=_resultado_falso("bulk_202601"),
        ) as runner,
    ):
        assert dispatch_retry("bulk_202601", "download", "run-1") is True

    assert construidos == [(2026, 1)]
    runner.assert_called_once()


def test_el_dispatch_de_la_dlq_falla_si_el_fetch_del_mes_falla() -> None:
    from scheduler.dlq_retry import dispatch_retry

    fallido = _resultado_falso("bulk_202601")
    fallido.fetch_failed = True

    class _FakeBulkConnector:
        def __init__(self, year: int, month: int) -> None:
            self.source_id = f"bulk_{year}{month:02d}"

    with (
        patch("scraper.connectors.placsp.PlacspBulkConnector", _FakeBulkConnector),
        patch("scraper.connectors.base.run_connector", return_value=fallido),
    ):
        assert dispatch_retry("bulk_202601", "download", "run-1") is False
