"""Tests para scheduler/dlq_retry.py — backoff y reintento DLQ."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest


def _patch_bulk_connector(*, fetch_failed: bool = False, side_effect: Any = None) -> Any:
    """Intercepta el reproceso de un mes bulk.

    Desde S2.1 (2026-09) ``dispatch_retry`` reprocesa un ``bulk_YYYYMM`` con
    ``PlacspBulkConnector`` + ``run_connector`` en vez de con el
    ``scraper.pipeline.process_month`` legacy, que reescribía el mes sin
    historial, sin lotes, sin documentos, sin dedupe y sin linaje.
    """
    if side_effect is not None:
        return patch("scraper.connectors.base.run_connector", side_effect=side_effect)
    return patch(
        "scraper.connectors.base.run_connector",
        return_value=SimpleNamespace(
            source_id="bulk_202601",
            fetch_failed=fetch_failed,
            fetched=0,
            parsed=0,
            nuevas=0,
            actualizadas=0,
            adjudicaciones=0,
            errores=0,
        ),
    )


# ---------------------------------------------------------------------------
# _backoff_seconds
# ---------------------------------------------------------------------------


def test_backoff_seconds_base():
    from scheduler.dlq_retry import _BASE_BACKOFF_S, _backoff_seconds

    assert _backoff_seconds(0) == float(_BASE_BACKOFF_S)


def test_backoff_seconds_doubles_each_retry():
    from scheduler.dlq_retry import _BASE_BACKOFF_S, _backoff_seconds

    assert _backoff_seconds(1) == float(_BASE_BACKOFF_S * 2)
    assert _backoff_seconds(2) == float(_BASE_BACKOFF_S * 4)


def test_backoff_seconds_caps_at_max():
    from scheduler.dlq_retry import _MAX_BACKOFF_S, _backoff_seconds

    assert _backoff_seconds(20) == float(_MAX_BACKOFF_S)


# ---------------------------------------------------------------------------
# _is_due
# ---------------------------------------------------------------------------


def test_is_due_missing_created_at():
    from scheduler.dlq_retry import _is_due

    assert _is_due({"retry_count": 0}) is True


def test_is_due_invalid_date():
    from scheduler.dlq_retry import _is_due

    assert _is_due({"created_at": "not-a-date", "retry_count": 0}) is True


def test_is_due_recent_failure_not_due():
    from scheduler.dlq_retry import _is_due

    now_str = datetime.now(UTC).isoformat()
    assert _is_due({"created_at": now_str, "retry_count": 0}) is False


def test_is_due_old_failure_is_due():
    from scheduler.dlq_retry import _is_due

    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    assert _is_due({"created_at": old, "retry_count": 0}) is True


def test_is_due_naive_datetime_treated_as_utc():
    from scheduler.dlq_retry import _is_due

    old = (datetime.now(UTC) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    assert _is_due({"created_at": old, "retry_count": 0}) is True


# ---------------------------------------------------------------------------
# retry_failed_extractions — happy paths and edge cases
# ---------------------------------------------------------------------------


def test_retry_empty_queue(tmp_db):
    from scheduler.dlq_retry import retry_failed_extractions

    result = retry_failed_extractions()
    assert result == 0


def test_retry_all_in_backoff(tmp_db):
    """Fallo reciente (backoff no expirado) no se reintenta."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("err"))
    # created_at = ahora → backoff de 300s no ha expirado
    from scheduler.dlq_retry import retry_failed_extractions

    result = retry_failed_extractions()
    assert result == 0


def test_retry_max_retries_skipped(tmp_db, monkeypatch):
    """Entradas con retry_count >= max_retries se filtran antes de intentar."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("err"))
    fid = dlq.list_unresolved()[0]["id"]
    for _ in range(5):
        dlq.increment_retry(fid)
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    from scheduler.dlq_retry import retry_failed_extractions

    result = retry_failed_extractions(max_retries=5)
    assert result == 0


def test_retry_unknown_source_marks_exhausted_immediately(tmp_db, monkeypatch):
    """Fuente sin dispatch → agotada de inmediato, sin quemar ciclos de reintento.

    Hasta 2026-08 estas entradas incrementaban retry_count durante 5 ciclos
    sin hacer nada y acababan en una alerta de "agotó reintentos" que
    atribuía mal la causa.
    """
    from db import dlq

    dlq.record_failure("run-1", "unknown_source_xyz", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    from scheduler.dlq_retry import retry_failed_extractions

    result = retry_failed_extractions()
    assert result == 0
    assert dlq.list_unresolved() == []
    exhausted = dlq.list_exhausted()
    assert len(exhausted) == 1
    assert exhausted[0]["fuente"] == "unknown_source_xyz"


def test_retry_connector_source_dispatches(tmp_db, monkeypatch):
    """Las fuentes de conectores (pscp/ted/…) SÍ tienen dispatch de reintento."""
    from unittest.mock import MagicMock

    from db import dlq

    dlq.record_failure("run-1", "pscp", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)

    ok_result = MagicMock(errores=0)
    with patch("scraper.connectors.base.run_connector", return_value=ok_result):
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()

    assert result == 1
    assert dlq.list_unresolved() == []


def test_retry_bulk_success(tmp_db, monkeypatch):
    """Reintento bulk exitoso → marcado como resuelto."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with _patch_bulk_connector():
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()
    assert result == 1
    assert dlq.list_unresolved() == []


def test_retry_bulk_failure_increments_retry(tmp_db, monkeypatch):
    """Reintento bulk fallido → no resuelto, retry_count incrementado."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with _patch_bulk_connector(fetch_failed=True):
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()
    assert result == 0
    assert dlq.list_unresolved()[0]["retry_count"] == 1


def test_retry_bulk_bad_format(tmp_db, monkeypatch):
    """Fuente bulk_ con formato inesperado → no resuelto."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_BADVAL", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    from scheduler.dlq_retry import retry_failed_extractions

    result = retry_failed_extractions()
    assert result == 0


def test_retry_skips_bulk_when_include_bulk_false(tmp_db, monkeypatch):
    """Carril diario: una entrada bulk_YYYYMM no dispara el conector bulk."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with _patch_bulk_connector() as run_connector:
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions(include_bulk=False)

    run_connector.assert_not_called()
    assert result == 0
    # Sigue pendiente y sin quemar un reintento: la cubre `scrape-bulk.yml`.
    pendiente = dlq.list_unresolved()[0]
    assert pendiente["fuente"] == "bulk_202601"
    assert pendiente["retry_count"] == 0


def test_retry_without_bulk_still_drains_other_sources(tmp_db, monkeypatch):
    """El filtro va en SQL: las entradas bulk no pueden copar el LIMIT.

    Con el filtro aplicado en Python *después* del LIMIT, una DLQ con muchos
    meses bulk delante dejaba al carril diario sin candidatos que reintentar.
    """
    from db import dlq

    for i in range(1, 7):
        dlq.record_failure("run-1", f"bulk_2026{i:02d}", RuntimeError("err"))
    dlq.record_failure("run-1", "placsp", RuntimeError("err"))

    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    monkeypatch.setenv("DLQ_BATCH_SIZE", "2")
    with _patch_bulk_connector() as run_connector:
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions(include_bulk=False)

    # Un solo reintento y es el del carril diario, no el de un mes bulk.
    run_connector.assert_called_once()
    assert type(run_connector.call_args.args[0]).__name__ == "PlacspAtomConnector"
    assert result == 1
    assert {f["fuente"] for f in dlq.list_unresolved()} == {
        f"bulk_2026{i:02d}" for i in range(1, 7)
    }


def test_retry_atom_success(tmp_db, monkeypatch):
    """Una fila con la etiqueta del carril diario retirado se reintenta por el conector."""
    from db import dlq

    dlq.record_failure("run-1", "place_live_atom", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with _patch_bulk_connector() as run_connector:
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()
    assert type(run_connector.call_args.args[0]).__name__ == "PlacspAtomConnector"
    assert result == 1
    assert dlq.list_unresolved() == []


def test_retry_atom_failure(tmp_db, monkeypatch):
    """Reintento atom fallido → no resuelto."""
    from db import dlq

    dlq.record_failure("run-1", "atom_live", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with patch("scraper.connectors.base.run_connector", return_value=SimpleNamespace(errores=1)):
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()
    assert result == 0


def test_las_etiquetas_del_carril_diario_retirado_van_por_el_conector_atom():
    """``place_live_atom`` y ``atom*`` no tienen pipeline propio: mismo feed, por el conector."""
    from scheduler.dlq_retry import dispatch_retry

    for fuente in ("placsp", "place_live_atom", "atom_live"):
        with patch(
            "scraper.connectors.base.run_connector", return_value=SimpleNamespace(errores=0)
        ) as run_connector:
            assert dispatch_retry(fuente, "fetch", "run-1") is True
        assert type(run_connector.call_args.args[0]).__name__ == "PlacspAtomConnector"


def test_retry_parse_entry_of_cursor_source_is_exhausted_not_resolved(tmp_db, monkeypatch):
    """Un aviso que no parseó quedó detrás del cursor: otra pasada no lo relee.

    Hasta 2026-11 se corría el conector, salía con 0 errores y la entrada se
    daba por resuelta sin que nadie hubiera vuelto a leer ese aviso.
    """
    from db import dlq

    dlq.record_failure(None, "placsp", ValueError("x"), scope="parse", payload_ref="a1")
    dlq.record_failure(None, "placsp", ValueError("x"), scope="adjudicacion", payload_ref="b2")
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with (
        patch(
            "scraper.connectors.base.run_connector", return_value=SimpleNamespace(errores=0)
        ) as run_connector,
        patch("scheduler.dlq_retry.notify") as notify,
    ):
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()

    run_connector.assert_not_called()
    assert result == 0
    assert dlq.list_unresolved() == []
    assert {f["scope"] for f in dlq.list_exhausted()} == {"parse", "adjudicacion"}
    notify.assert_called_once()


def test_retry_parse_entry_of_bulk_month_is_reread(tmp_db, monkeypatch):
    """Reprocesar un mes bulk sí vuelve a leer el aviso: se reintenta."""
    from db import dlq

    dlq.record_failure(None, "bulk_202601", ValueError("x"), scope="parse", payload_ref="f.xml")
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with _patch_bulk_connector() as run_connector:
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()

    run_connector.assert_called_once()
    assert result == 1


@pytest.mark.parametrize("fuente", ["bulk_202601", "placsp_watched_company_awards_bulk_202601"])
def test_retry_parse_entry_failing_again_in_month_reprocess_is_exhausted(
    tmp_db, monkeypatch, fuente
):
    """El reproceso del mes vuelve a registrar el mismo aviso: no se da por resuelto.

    ``fetch_failed`` es False (el mes se descargó), pero ``record_failure``
    volvió a tocar la fila durante la pasada: el aviso sigue sin entrar. Es
    determinista (mismos bytes, mismo parser), así que se agota con su causa
    en vez de reprocesar el mes otras cuatro veces.
    """
    from db import dlq

    dlq.record_failure(None, fuente, ValueError("x"), scope="parse", payload_ref="f.xml")
    dlq.record_failure(None, fuente, RuntimeError("x"), scope="download")
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)

    def _pasada_que_recae(_conector: Any) -> SimpleNamespace:
        dlq.record_failure(None, fuente, ValueError("x"), scope="parse", payload_ref="f.xml")
        return SimpleNamespace(fetch_failed=False, errores=1)

    with (
        patch(
            "db.repositories.watched_companies.WatchedCompanyRepository.list_canonical_nifs",
            return_value={"A00000000"},
        ),
        patch("scraper.connectors.base.run_connector", side_effect=_pasada_que_recae),
        patch("scheduler.dlq_retry.notify") as notify,
    ):
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()

    # La descarga sí se arregló; el aviso, no.
    assert result == 1
    assert dlq.list_unresolved() == []
    assert [f["scope"] for f in dlq.list_exhausted()] == ["parse"]
    notify.assert_called_once()


def test_retry_groups_atom_legacy_labels_in_one_pass(tmp_db, monkeypatch):
    """``placsp``, ``place_live_atom`` y ``atom*`` son el mismo feed: una pasada."""
    from db import dlq

    for fuente in ("placsp", "place_live_atom", "atom_live"):
        dlq.record_failure(None, fuente, RuntimeError("x"), scope="fetch")
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with patch(
        "scraper.connectors.base.run_connector", return_value=SimpleNamespace(errores=0)
    ) as run_connector:
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()

    run_connector.assert_called_once()
    assert result == 3


def test_retry_switched_off_syndication_is_exhausted_with_its_cause(tmp_db, monkeypatch):
    """Una sindicación apagada no quema reintentos ni acaba en «agotó reintentos»."""
    from db import dlq

    for ref in ("p1", "p2"):
        dlq.record_failure(None, "placsp_menores", RuntimeError("x"), payload_ref=ref)
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with (
        patch("scraper.connectors.placsp_menores.ejecutar", return_value=None),
        patch("scheduler.dlq_retry.notify") as notify,
    ):
        from scheduler.dlq_retry import retry_failed_extractions

        assert retry_failed_extractions() == 0

    assert dlq.list_unresolved() == []
    assert len(dlq.list_exhausted()) == 2
    notify.assert_called_once()
    assert "apagada" in notify.call_args.args[2]


def test_retry_runs_one_connector_pass_per_source(tmp_db, monkeypatch):
    """Tres entradas de la misma fuente son una pasada del conector, no tres."""
    from db import dlq

    for ref in ("p1", "p2", "p3"):
        dlq.record_failure(None, "pscp", RuntimeError("x"), scope="fetch", payload_ref=ref)
    dlq.record_failure(None, "ted", RuntimeError("x"), scope="fetch")
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with patch(
        "scraper.connectors.base.run_connector", return_value=SimpleNamespace(errores=0)
    ) as run_connector:
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()

    assert run_connector.call_count == 2
    assert result == 4
    assert dlq.list_unresolved() == []


def test_retry_failed_source_pass_increments_every_entry(tmp_db, monkeypatch):
    """Si la pasada compartida falla, cada entrada de esa fuente quema su reintento."""
    from db import dlq

    for ref in ("p1", "p2"):
        dlq.record_failure(None, "pscp", RuntimeError("x"), scope="fetch", payload_ref=ref)
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with patch(
        "scraper.connectors.base.run_connector", return_value=SimpleNamespace(errores=1)
    ) as run_connector:
        from scheduler.dlq_retry import retry_failed_extractions

        assert retry_failed_extractions() == 0

    run_connector.assert_called_once()
    assert [f["retry_count"] for f in dlq.list_unresolved()] == [1, 1]


@pytest.mark.parametrize(
    "modulo",
    ["placsp_agregadas", "placsp_menores", "placsp_consultas"],
)
def test_dispatch_retry_sindicaciones_placsp(modulo):
    """Las tres sindicaciones de PLACSP se reintentan con su pasada incremental."""
    from scheduler.dlq_retry import dispatch_retry

    destino = f"scraper.connectors.{modulo}.ejecutar"
    with patch(destino, return_value=SimpleNamespace(errores=0)) as ejecutar:
        assert dispatch_retry(modulo, "fetch", "run-1") is True
    ejecutar.assert_called_once_with()
    with patch(destino, return_value=SimpleNamespace(errores=2)):
        assert dispatch_retry(modulo, "fetch", "run-1") is False
    # Fuente apagada (sin URL): no hay pasada que dé la entrada por buena.
    from scheduler.dlq_retry import FuenteApagadaError

    with patch(destino, return_value=None), pytest.raises(FuenteApagadaError):
        dispatch_retry(modulo, "fetch", "run-1")


def test_dispatch_retry_watched_awards_bulk_month():
    """``placsp_watched_company_awards_bulk_YYYYMM`` reprocesa ese mes para los NIF vigilados."""
    from scheduler.dlq_retry import dispatch_retry

    with (
        patch(
            "db.repositories.watched_companies.WatchedCompanyRepository.list_canonical_nifs",
            return_value={"A00000000"},
        ),
        patch(
            "scraper.connectors.base.run_connector",
            return_value=SimpleNamespace(fetch_failed=False, errores=3),
        ) as run_connector,
    ):
        assert dispatch_retry("placsp_watched_company_awards_bulk_202601", "fetch", "r") is True

    conector = run_connector.call_args.args[0]
    assert type(conector).__name__ == "PlacspWatchedCompanyAwardsBulkConnector"
    assert (conector.year, conector.month) == (2026, 1)


def test_retry_daily_lane_skips_watched_awards_bulk(tmp_db, monkeypatch):
    """El carril diario tampoco reprocesa meses del carril de empresas vigiladas."""
    from db import dlq

    dlq.record_failure(None, "placsp_watched_company_awards_bulk_202601", RuntimeError("x"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with _patch_bulk_connector() as run_connector:
        from scheduler.dlq_retry import retry_failed_extractions

        assert retry_failed_extractions(include_bulk=False) == 0

    run_connector.assert_not_called()
    assert dlq.list_unresolved()[0]["retry_count"] == 0


def test_retry_exception_in_scraper(tmp_db, monkeypatch):
    """Excepción inesperada en el scraper → no resuelto, sin crash."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with _patch_bulk_connector(side_effect=RuntimeError("scraper crash")):
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()
    assert result == 0
