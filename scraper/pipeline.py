"""Pipeline completo: descarga -> parseo -> filtrado SAP -> persistencia."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime
from typing import Any

from dateutil.relativedelta import relativedelta

from db.database import (
    UpsertResult,
    close_pool,
    get_cursor,
    init_db,
    log_extraccion,
    replace_adjudicaciones,
    set_cursor,
    upsert_licitaciones,
    upsert_licitaciones_with_history,
)
from db.dlq import record_failure
from observability import (
    AlertLevel,
    bind_run_context,
    get_logger,
    notify,
    record_run,
)
from scraper.bulk_downloader import (
    CircuitOpenError,
    download_month,
    iter_xml_files,
)
from scraper.codice_parser import parse_adjudicaciones, parse_atom_bytes, parse_entry

log = get_logger(__name__)

_DAILY_SOURCE = "place_live_atom"


def process_month(year: int, month: int, *, run_id: str | None = None, force: bool = False) -> dict:
    """Procesa un mes: descarga ZIP, parsea, filtra SAP, persiste."""
    fuente = f"bulk_{year}{month:02d}"
    try:
        zip_path = download_month(year, month, force=force)
    except CircuitOpenError as e:
        log.error("month_circuit_open", year=year, month=month, error=str(e))
        record_failure(run_id, fuente, e, scope="download")
        notify(
            AlertLevel.ERROR,
            "PLACSP circuit breaker abierto",
            "El scraper no pudo descargar por fallos consecutivos en PLACSP.",
            year=year,
            month=month,
        )
        return {"year": year, "month": month, "status": "circuit_open"}
    except Exception as e:
        log.exception("month_download_error", year=year, month=month)
        record_failure(run_id, fuente, e, scope="download")
        return {"year": year, "month": month, "status": "error_descarga"}

    if zip_path is None:
        return {"year": year, "month": month, "status": "no_publicado"}

    sap_encontradas = []
    adj_por_lic: dict[str, list] = {}
    entries_error = 0
    for filename, content in iter_xml_files(zip_path):
        log.info("xml_parse_start", filename=filename)
        try:
            for lic, adjudicaciones in parse_atom_bytes(content):
                sap_encontradas.append(lic)
                if adjudicaciones:
                    adj_por_lic[lic.id_externo] = adjudicaciones
        except Exception as e:
            log.exception("xml_parse_error", filename=filename, year=year, month=month)
            record_failure(run_id, fuente, e, scope="parse", payload_ref=filename)
            entries_error += 1

    try:
        nuevas, actualizadas = upsert_licitaciones(sap_encontradas)
    except Exception as e:
        log.exception("month_persist_error", year=year, month=month)
        record_failure(run_id, fuente, e, scope="persist_licitaciones")
        return {"year": year, "month": month, "status": "error_persistencia"}

    n_adj = 0
    n_adj_failed = 0
    for lic_id, adjs in adj_por_lic.items():
        try:
            n_adj += replace_adjudicaciones(lic_id, adjs)
        except Exception as e:
            log.exception("adj_persist_error", licitacion_id=lic_id)
            record_failure(run_id, fuente, e, scope="persist_adjudicaciones", payload_ref=lic_id)
            n_adj_failed += 1

    log_extraccion(
        fuente=fuente,
        nuevas=nuevas,
        actualizadas=actualizadas,
        total=len(sap_encontradas),
        notas=f"SAP:{len(sap_encontradas)} adj:{n_adj} adj_errors:{n_adj_failed} errors:{entries_error}",
    )

    # Instrumentación Prometheus (no bloquea si falla)
    try:
        from observability.prometheus import RunInstrumentation, _write_metrics

        prom = RunInstrumentation(source=fuente)
        prom.record_items(nuevas=nuevas, actualizadas=actualizadas)
        prom.record_parse_error(entries_error)
        _write_metrics(prom)
    except Exception:
        log.debug("prometheus_instrumentation_failed", fuente=fuente)

    return {
        "year": year,
        "month": month,
        "status": "ok",
        "sap_matches": len(sap_encontradas),
        "adjudicaciones": n_adj,
        "adj_errors": n_adj_failed,
        "nuevas": nuevas,
        "actualizadas": actualizadas,
        "entries_error": entries_error,
    }


def _summarize(results: list[dict[str, Any]], metrics: Any) -> None:
    adj_errors_total = 0
    for r in results:
        metrics.months_attempted += 1
        if r["status"] == "ok":
            metrics.months_ok += 1
            metrics.licitaciones_nuevas += r.get("nuevas", 0)
            metrics.licitaciones_actualizadas += r.get("actualizadas", 0)
            metrics.adjudicaciones += r.get("adjudicaciones", 0)
            metrics.errores_parseo += r.get("entries_error", 0)
            adj_errors_total += r.get("adj_errors", 0)
        elif r["status"] == "no_publicado":
            metrics.months_ok += 1
        else:
            metrics.months_failed += 1
            if r["status"] == "error_descarga":
                metrics.errores_descarga += 1
    if adj_errors_total:
        metrics.notas = f"adj_persist_errors:{adj_errors_total}"


def update_recent(months_back: int = 3) -> list[dict]:
    """Actualiza los últimos N meses (idempotente gracias al upsert)."""
    init_db()
    today = datetime.now(UTC).date()
    run_id = bind_run_context(entrypoint="update_recent", months_back=months_back)
    with record_run(run_id) as metrics:
        results = []
        for i in range(months_back):
            target = today - relativedelta(months=i)
            results.append(process_month(target.year, target.month, run_id=run_id))
        _summarize(results, metrics)
    return results


def backfill(start_year: int, start_month: int) -> list[dict]:
    """Backfill desde una fecha histórica hasta hoy (paralelo por meses)."""
    if not (1 <= start_month <= 12):
        raise ValueError(f"start_month must be 1-12, got {start_month}")
    if start_year < 2000:
        raise ValueError(f"start_year must be >= 2000, got {start_year}")
    from config import settings

    init_db()
    today = datetime.now(UTC).date()
    cur = date(start_year, start_month, 1)
    run_id = bind_run_context(entrypoint="backfill", start_year=start_year, start_month=start_month)

    months: list[tuple[int, int]] = []
    while cur <= today:
        months.append((cur.year, cur.month))
        cur += relativedelta(months=1)

    workers = min(settings.BACKFILL_MAX_WORKERS, len(months)) or 1
    log.info("backfill_start", months=len(months), workers=workers)

    with record_run(run_id) as metrics:
        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process_month, y, m, run_id=run_id): (y, m) for y, m in months}
            for future in as_completed(futures):
                y, m = futures[future]
                try:
                    results.append(future.result())
                except Exception:
                    log.exception("backfill_month_error", year=y, month=m)
                    results.append({"year": y, "month": m, "status": "error"})
            # Close DB connections held by worker threads
            pool.map(lambda _: close_pool(), range(workers))
        _summarize(results, metrics)
    return results


# ---------------------------------------------------------------------------
# Carril diario — feed ATOM en vivo
# ---------------------------------------------------------------------------


def process_daily(*, run_id: str | None = None) -> dict:
    """Procesa el feed ATOM en vivo: pagina, filtra SAP, persiste con historial.

    Returns:
        dict con status, contadores y listas de ids insertados/modificados.
    """
    from scraper.atom_live import iter_live_entries

    init_db()
    fuente = _DAILY_SOURCE

    # Leer cursor actual
    cursor = get_cursor(fuente)
    last_seen_updated = cursor["last_seen_updated"] if cursor else None

    try:
        entries, meta = iter_live_entries(last_seen_updated=last_seen_updated)
    except Exception as e:
        log.exception("daily_fetch_error")
        record_failure(run_id, fuente, e, scope="fetch")
        notify(
            AlertLevel.ERROR,
            "Feed diario ATOM falló al descargar",
            body=str(e),
        )
        return {"status": "error_fetch", "source": fuente}

    if not entries:
        log.info("daily_no_new_entries", stopped=meta.get("stopped_reason"))
        # Actualizar cursor etag/last_modified incluso sin entries
        if meta.get("etag") or meta.get("last_modified"):
            set_cursor(
                fuente,
                last_seen_updated=last_seen_updated,
                etag=meta.get("etag"),
                last_modified=meta.get("last_modified"),
            )
        return {
            "status": "ok",
            "source": fuente,
            "sap_matches": 0,
            "inserted": [],
            "modified": [],
            "unchanged": [],
            "pages_fetched": meta["pages_fetched"],
            "entries_seen": meta["entries_seen"],
        }

    # Parsear entries y filtrar SAP
    sap_encontradas = []
    adj_por_lic: dict[str, list] = {}
    entries_error = 0

    for entry_elem, updated_str in entries:
        try:
            lic = parse_entry(entry_elem)
            if lic:
                # Actualizar fecha_actualizacion_fuente con el <updated> de la entry
                if updated_str:
                    lic.fecha_actualizacion_fuente = updated_str
                sap_encontradas.append(lic)
                adj = parse_adjudicaciones(entry_elem, lic.id_externo)
                if adj:
                    adj_por_lic[lic.id_externo] = adj
        except Exception as e:
            log.warning("daily_entry_parse_error", error=str(e))
            record_failure(run_id, fuente, e, scope="parse")
            entries_error += 1

    # Persistir con detección de cambios
    try:
        upsert_result: UpsertResult = upsert_licitaciones_with_history(
            sap_encontradas, source=fuente
        )
    except Exception as e:
        log.exception("daily_persist_error")
        record_failure(run_id, fuente, e, scope="persist_licitaciones")
        return {"status": "error_persistencia", "source": fuente}

    # Adjudicaciones
    n_adj = 0
    for lic_id, adjs in adj_por_lic.items():
        try:
            n_adj += replace_adjudicaciones(lic_id, adjs)
        except Exception as e:
            log.exception("daily_adj_persist_error", licitacion_id=lic_id)
            record_failure(run_id, fuente, e, scope="persist_adjudicaciones", payload_ref=lic_id)

    # Actualizar cursor
    newest = meta.get("newest_updated") or last_seen_updated
    set_cursor(
        fuente,
        last_seen_updated=newest,
        etag=meta.get("etag"),
        last_modified=meta.get("last_modified"),
    )

    # Log de extracción
    log_extraccion(
        fuente=fuente,
        nuevas=upsert_result.nuevas,
        actualizadas=upsert_result.actualizadas,
        total=len(sap_encontradas),
        notas=(
            f"SAP:{len(sap_encontradas)} adj:{n_adj} "
            f"inserted:{upsert_result.nuevas} modified:{len(upsert_result.modified)} "
            f"unchanged:{len(upsert_result.unchanged)} errors:{entries_error} "
            f"pages:{meta['pages_fetched']}"
        ),
    )

    log.info(
        "daily_pipeline_done",
        sap_matches=len(sap_encontradas),
        inserted=upsert_result.nuevas,
        modified=len(upsert_result.modified),
        unchanged=len(upsert_result.unchanged),
        adjudicaciones=n_adj,
        pages=meta["pages_fetched"],
        entries_seen=meta["entries_seen"],
    )

    return {
        "status": "ok",
        "source": fuente,
        "sap_matches": len(sap_encontradas),
        "adjudicaciones": n_adj,
        "inserted": upsert_result.inserted,
        "modified": upsert_result.modified,
        "unchanged": upsert_result.unchanged,
        "entries_error": entries_error,
        "pages_fetched": meta["pages_fetched"],
        "entries_seen": meta["entries_seen"],
    }


def update_daily() -> dict:
    """Punto de entrada para el carril diario con observabilidad."""
    init_db()
    run_id = bind_run_context(entrypoint="update_daily")
    with record_run(run_id) as metrics:
        result = process_daily(run_id=run_id)
        if result["status"] == "ok":
            metrics.status = "ok"
            metrics.licitaciones_nuevas = len(result.get("inserted", []))
            metrics.licitaciones_actualizadas = len(result.get("modified", [])) + len(
                result.get("unchanged", [])
            )
        else:
            metrics.status = "error"
            metrics.months_failed = 1
        metrics.notas = f"daily|{result['status']}"
    return result
