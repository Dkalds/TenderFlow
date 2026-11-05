"""Carriles de ingesta de la pipeline: diario (ATOM), bulk y backfill.

Cada carril ingiere y después cierra la pasada con
``scheduler.pipeline_cierre._run_post_ingestion_steps``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from observability.logging import get_logger
from scheduler.pipeline_cierre import _run_post_ingestion_steps
from scheduler.pipeline_pasos import LANE_BULK, LANE_DAILY, _contar_error

# El nombre de antes de partir el módulo: `logger` sale en cada línea de log.
log = get_logger("scheduler.pipeline_runs")


def run_daily_pipeline(*, con_cierre: bool = True) -> dict[str, Any]:
    """Pipeline canónica para el carril diario (feed ATOM).

    Ejecuta la ingesta diaria y todos los pasos post-ingesta en la secuencia
    oficial. Usada tanto por ``run_update.py --daily`` como por
    ``scheduler/jobs/daily_atom.py``.

    Args:
        con_cierre: si es ``False`` ingiere y **no** ejecuta los pasos
            post-ingesta, que quedan para una invocación posterior de
            :func:`run_post_ingestion_only`. Lo usa ``scrape-daily.yml`` para
            que el cierre ocurra tras los seis conectores. El default es
            ``True`` para que ningún caller pierda el cierre por omisión.

    Ingiere con ``PlacspAtomConnector`` a través de ``run_connector``. El
    flag ``PLACSP_CONNECTOR_ENABLED`` y el camino legacy (``update_daily``) se
    retiraron el 2026-09-28, tras más de dos meses con el connector en
    producción.

    Returns:
        Dict con ``ingestion_result``, ``steps`` y ``status``.

    Raises:
        RuntimeError: Solo si la ingesta falla con un status inesperado.
            Los errores ya manejados en ``process_daily`` (``error_fetch``,
            ``error_persistencia``) no relanzarán excepción para evitar
            doble-alerta — las notificaciones ya se enviaron dentro del pipeline.
    """
    return _run_daily_pipeline_connector(con_cierre=con_cierre)


def _run_daily_pipeline_connector(*, con_cierre: bool = True) -> dict[str, Any]:
    """Implementación del carril diario usando PlacspAtomConnector (F2).

    Mantiene el contrato que tenía el camino legacy (``update_daily``, retirado):

    - ``ingestion_result`` expone ``inserted``/``modified`` como **listas de
      id_externo** (mismo contrato que ``process_daily``; ``_log_daily_summary``
      hace ``len()`` y ``join()`` sobre ellas).
    - Los errores por-entry (parse → DLQ) **no** marcan el run como fallido —
      igual que ``entries_error`` en legacy. Solo un fallo fatal de ``fetch``
      produce ``status="error_fetch"`` (mismo nombre de status que legacy).
    - Deja los contadores por fuente en ``source_ingestion_health`` (vía ``run_connector``) y
      envuelve el run en ``record_run`` para que la página de observabilidad
      siga viendo los runs diarios tras el flip.
    """
    from observability import bind_run_context, record_run
    from scheduler import respaldo_zip_placsp
    from scraper.connectors.base import run_connector
    from scraper.connectors.placsp import PlacspAtomConnector

    cursor_atom_antes = respaldo_zip_placsp.cursor_atom_actual()
    run_id = bind_run_context(entrypoint="run_daily_pipeline_connector")
    with record_run(run_id) as metrics:
        connector = PlacspAtomConnector()
        run_result = run_connector(connector)

        status = "error_fetch" if run_result.fetch_failed else "ok"

        if run_result.fetch_failed:
            metrics.status = "error"
            metrics.months_failed = 1
            try:
                from observability.alerts import AlertLevel, notify

                notify(
                    AlertLevel.ERROR,
                    "Feed diario ATOM falló al descargar (connector)",
                    body="run_connector(placsp) abortó en fetch; detalle en DLQ.",
                )
            except Exception:
                _contar_error("aviso_feed_diario")
                log.warning("daily_connector_notify_failed", exc_info=True)
        else:
            metrics.status = "ok"
            metrics.licitaciones_nuevas = run_result.nuevas
            metrics.licitaciones_actualizadas = run_result.actualizadas
        metrics.notas = f"daily_connector|{status}"

    # ATOM congelado → ZIP del mes en curso tras N pasadas sin avance. Fuera del
    # `record_run` del ATOM: el bulk deja su propia salud (`bulk_YYYYMM`).
    respaldo_zip = respaldo_zip_placsp.tras_pasada_atom(
        cursor_antes=cursor_atom_antes,
        cursor_despues=respaldo_zip_placsp.cursor_atom_actual(),
        fetch_failed=run_result.fetch_failed,
    )

    step_results = _run_post_ingestion_steps(lane=LANE_DAILY) if con_cierre else {}

    return {
        "status": status,
        "ingestion_result": {
            "status": status,
            "source": run_result.source_id,
            "tech_matches": run_result.parsed,
            "inserted": list(run_result.inserted_ids),
            "modified": list(run_result.modified_ids),
            "unchanged": [],
            "entries_error": run_result.errores,
        },
        "connector_result": run_result.as_dict(),
        "respaldo_zip": respaldo_zip,
        "steps": step_results,
    }


_OK_STATUSES = frozenset({"ok", "no_publicado"})


def _notify_degraded(label: str, failed: list[dict[str, Any]]) -> None:
    """Alerta best-effort (nivel WARN) por meses con fallo recuperable."""
    try:
        from observability.alerts import AlertLevel, notify

        notify(
            AlertLevel.WARN,
            f"{label}: {len(failed)} mes(es) con fallo recuperable",
            body=(
                f"Meses fallidos: {failed}. Ya registrados en la DLQ. Los "
                "reintenta el paso post-ingesta dlq_retry del propio carril "
                "bulk, que desde 2026-08 se dispara a mano "
                "(.github/workflows/scrape-bulk.yml): el carril diario ya no "
                "reprocesa meses, así que vuelve a lanzar el bulk si estos "
                "meses importan."
            ),
            failed_months=failed,
        )
    except Exception:
        _contar_error("aviso_degradado")
        log.warning("degraded_notify_failed", label=label, exc_info=True)


def _finalize_ingestion(results: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    """Cierra una ingesta bulk/backfill tolerando fallos parciales.

    - **Fallo total** (ningún mes ingresó): se lanza ``RuntimeError`` porque no
      hay nada que post-procesar (típicamente PLACSP caído o formato incompatible).
    - **Fallo parcial** (algunos meses fallaron): los fallos ya quedaron
      registrados en la DLQ vía ``record_failure``. Se ejecutan igualmente los
      pasos post-ingesta —incluido ``dlq_retry``, que en este carril sí
      reintenta las descargas mensuales fallidas— y se devuelve
      ``status="degraded"`` en lugar de abortar toda la pipeline. Esto da
      paridad con ``run_daily_pipeline``.
    """
    failed = [r for r in results if r.get("status") not in _OK_STATUSES]
    succeeded = [r for r in results if r.get("status") in _OK_STATUSES]

    # Fallo total: ningún mes ingresó → genuinamente fatal.
    if results and not succeeded:
        raise RuntimeError(f"{label} failed for all {len(failed)} month(s): {failed}")

    if failed:
        log.warning(
            "pipeline_ingestion_degraded",
            label=label,
            failed_months=failed,
            months_ok=len(succeeded),
        )
        _notify_degraded(label, failed)

    step_results = _run_post_ingestion_steps(lane=LANE_BULK)

    return {
        "status": "degraded" if failed else "ok",
        "ingestion_results": results,
        "failed_months": failed,
        "steps": step_results,
    }


def run_bulk_pipeline(months: int = 3) -> dict[str, Any]:
    """Pipeline canónica para el carril bulk (últimos N meses).

    Siempre por ``PlacspBulkConnector`` + ``run_connector``. Hasta 2026-09
    había aquí una rama legacy (``scraper.pipeline.update_recent`` →
    ``process_month``) gobernada por el flag ya retirado ``PLACSP_CONNECTOR_ENABLED``; se retiró
    con la propia ``process_month`` (S2.1): ese camino escribía sin historial
    (``upsert_licitaciones`` en vez de ``upsert_licitaciones_with_history``),
    sin lotes, sin documentos, sin detección de duplicados y sin salud de
    fuente ni columnas de linaje, así que «hacer rollback» a él significaba
    degradar el dato en silencio, no recuperar un estado bueno.

    Un fallo transitorio en algún mes reciente **no** aborta la pipeline: se
    registra en la DLQ, se ejecutan los pasos post-ingesta (incluido el
    reintento de la DLQ) y se devuelve ``status="degraded"``. Solo se lanza
    ``RuntimeError`` si fallan todos los meses.

    Args:
        months: Número de meses recientes a refrescar.

    Returns:
        Dict con ``status`` (``ok``/``degraded``), ``ingestion_results``,
        ``failed_months`` y ``steps``.

    Raises:
        RuntimeError: Solo si fallan todos los meses de la ingesta.
    """
    return _run_bulk_pipeline_connector(months)


def run_backfill_pipeline(
    year: int,
    month: int,
    *,
    hasta: tuple[int, int] | None = None,
    solo_cpv: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Pipeline canónica para backfill histórico (desde año/mes hasta hoy, o hasta ``hasta``).

    Aplica la misma tolerancia a fallos parciales que ``run_bulk_pipeline``, y
    desde 2026-09 **el mismo camino**: ``PlacspBulkConnector`` mes a mes vía
    ``run_connector`` (S2.1). Antes delegaba en ``scraper.pipeline.backfill``,
    que paralelizaba ``process_month`` con un ``ThreadPoolExecutor`` — el
    camino legacy que no escribía historial, ni lotes, ni documentos, ni
    linaje, ni salud de fuente, y que además llamaba a la resolución de
    empresas con ámbito global tras cada mes.

    Se pierde el paralelismo por meses (``BACKFILL_MAX_WORKERS``) a cambio de
    que el backfill escriba lo mismo que la ingesta viva. Un backfill es una
    operación manual y rara; una tabla con linaje a medias no lo es.

    Args:
        year: Año de inicio del backfill.
        month: Mes de inicio del backfill.
        hasta: ``(año, mes)`` final, incluido; por defecto el mes en curso.
            Una reingesta de muchos meses se parte así en tramos que caben en
            un job (`scrape-bulk.yml`, inputs ``backfill_desde``/``backfill_hasta``).
        solo_cpv: Prefijos CPV a los que se limita el backfill (ver
            ``PlacspBulkConnector``): rellena una familia recién añadida al
            universo sin reescribir el resto del mes.

    Returns:
        Dict con ``status`` (``ok``/``degraded``), ``ingestion_results``,
        ``failed_months`` y ``steps``.

    Raises:
        ValueError: Si ``year``/``month`` no son un mes válido ≥ 2000.
        RuntimeError: Solo si fallan todos los meses del backfill.
    """
    return _run_bulk_pipeline_connector(
        desde=(year, month), hasta=hasta, solo_cpv=solo_cpv, label="backfill (connector)"
    )


def meses_a_procesar(
    months: int = 3,
    *,
    desde: tuple[int, int] | None = None,
    hasta: tuple[int, int] | None = None,
    hoy: date | None = None,
) -> list[tuple[int, int]]:
    """Lista de ``(año, mes)`` que recorre el carril bulk.

    Dos modos, con **orden distinto a propósito**:

    - ``months=N`` (refresco bulk): los N meses más recientes, del más nuevo al
      más antiguo. Es el orden que ya tenía el bucle: si el job se corta por
      timeout, lo que sí entró es lo reciente, que es lo que mira el producto.
    - ``desde=(año, mes)`` (backfill histórico): de ese mes hasta hoy, en orden
      **cronológico ascendente**. Es el orden que construía
      ``scraper.pipeline.backfill``, y no es cosmético: el ZIP mensual de
      PLACSP no trae ``<updated>`` por entry, así que
      ``fecha_actualizacion_fuente`` va vacía y el desempate entre dos
      apariciones del mismo expediente en meses distintos lo decide el orden de
      escritura — gana el último mes procesado. Ascendente, ese último es el
      más reciente, que es la versión buena.

    Args:
        months: Número de meses recientes (ignorado si se pasa ``desde``).
        desde: ``(año, mes)`` de inicio del backfill.
        hasta: ``(año, mes)`` en el que termina el backfill, incluido; por
            defecto el mes en curso. Sirve para partir una reingesta larga en
            tramos que quepan en un job, sin perder el orden ascendente: cada
            tramo empieza donde terminó el anterior.
        hoy: Fecha de referencia; por defecto hoy en UTC. Inyectable para
            fijar el borde de fin de año en los tests sin congelar el reloj.

    Raises:
        ValueError: si ``desde`` o ``hasta`` no son un mes válido de un año
            ≥ 2000, si ``hasta`` es anterior a ``desde``, si ``hasta`` llega
            sin ``desde``, o si ``months`` no es positivo. Mismo contrato de validación que tenía
            ``scraper.pipeline.backfill``, que era donde vivía antes.
    """
    from dateutil.relativedelta import relativedelta

    referencia = hoy or datetime.now(UTC).date()

    if desde is None:
        if hasta is not None:
            raise ValueError("hasta solo tiene sentido con desde (backfill)")
        if months < 1:
            raise ValueError(f"months must be >= 1, got {months}")
        return [
            (
                (referencia - relativedelta(months=i)).year,
                (referencia - relativedelta(months=i)).month,
            )
            for i in range(months)
        ]

    start_year, start_month = desde
    if not (1 <= start_month <= 12):
        raise ValueError(f"start_month must be 1-12, got {start_month}")
    if start_year < 2000:
        raise ValueError(f"start_year must be >= 2000, got {start_year}")

    fin = date(referencia.year, referencia.month, 1)
    if hasta is not None:
        end_year, end_month = hasta
        if not (1 <= end_month <= 12):
            raise ValueError(f"end_month must be 1-12, got {end_month}")
        if (end_year, end_month) < (start_year, start_month):
            raise ValueError(f"hasta {hasta} es anterior a desde {desde}")
        fin = min(fin, date(end_year, end_month, 1))

    meses: list[tuple[int, int]] = []
    cur = date(start_year, start_month, 1)
    while cur <= fin:
        meses.append((cur.year, cur.month))
        cur += relativedelta(months=1)
    return meses


def _run_bulk_pipeline_connector(
    months: int = 3,
    *,
    desde: tuple[int, int] | None = None,
    hasta: tuple[int, int] | None = None,
    solo_cpv: tuple[str, ...] = (),
    label: str = "bulk refresh (connector)",
) -> dict[str, Any]:
    """Carril bulk y backfill sobre ``PlacspBulkConnector`` (F2 + S2.1).

    Paridad operacional con el camino legacy que sustituyó
    (``update_recent`` / ``backfill`` → ``process_month``):

    - Un fallo fatal de ``fetch`` de un mes se marca ``status="error"`` (los
      errores por-entry van a DLQ y **no** fallan el mes — igual que
      ``entries_error`` en ``process_month``).
    - ``source_ingestion_health`` por mes con la misma ``fuente`` (``bulk_YYYYMM``) que
      usaba el legacy, para continuidad de la serie en ``extracciones``.
    - El run completo va envuelto en ``record_run`` (observabilidad).

    Y lo que el legacy NO hacía y aquí sí, porque ``run_connector`` lo aporta:
    historial (``upsert_licitaciones_with_history``), lotes, metadatos de
    documentos, detección de duplicados, ``source_ingestion_health`` y las
    columnas de linaje del parser.

    Args:
        months: Meses recientes a refrescar (ignorado si se pasa ``desde``).
        desde: ``(año, mes)`` de inicio para el backfill histórico.
        hasta: ``(año, mes)`` final del backfill, incluido (ver
            :func:`meses_a_procesar`).
        solo_cpv: Prefijos CPV a los que se limita cada mes (ver
            ``PlacspBulkConnector``); vacío, el mes entero.
        label: Etiqueta del run en logs y alertas de degradación.
    """
    from observability import bind_run_context, record_run
    from scraper.connectors.base import run_connector
    from scraper.connectors.placsp import PlacspBulkConnector
    from scraper.pipeline import _summarize

    meses = meses_a_procesar(months, desde=desde, hasta=hasta)
    month_results: list[dict[str, Any]] = []

    run_id = bind_run_context(
        entrypoint="run_bulk_pipeline_connector",
        months=len(meses),
        desde=f"{desde[0]}-{desde[1]:02d}" if desde else None,
        hasta=f"{hasta[0]}-{hasta[1]:02d}" if hasta else None,
        solo_cpv=",".join(solo_cpv) or None,
    )
    with record_run(run_id) as metrics:
        for year, month in meses:
            connector = PlacspBulkConnector(year, month, solo_cpv=solo_cpv)
            try:
                r = run_connector(connector)
                status = "error" if r.fetch_failed else "ok"
                month_results.append(
                    {
                        "year": year,
                        "month": month,
                        "status": status,
                        "nuevas": r.nuevas,
                        "actualizadas": r.actualizadas,
                        "adjudicaciones": r.adjudicaciones,
                        "entries_error": r.errores,
                    }
                )
            except Exception as exc:
                log.exception(
                    "bulk_connector_month_failed",
                    year=year,
                    month=month,
                    error=str(exc),
                )
                month_results.append(
                    {
                        "year": year,
                        "month": month,
                        "status": "error",
                    }
                )
        _summarize(month_results, metrics)

    return _finalize_ingestion(month_results, label=label)
