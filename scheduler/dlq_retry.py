"""Reintento automático de extracciones fallidas en la Dead Letter Queue.

Para cada entrada no resuelta, aplica backoff exponencial antes de reintentar::

    espera = min(2^retry_count * BASE_BACKOFF_S, MAX_BACKOFF_S)

El backoff se mide desde ``last_attempt_at`` (no ``created_at``), de modo que
cada intento fallido resetea el reloj del backoff.

Cuando una entrada alcanza ``max_retries``:
  1. Se marca como ``exhausted_at = now()`` (sin más reintentos automáticos).
  2. Se lanza una alerta via ``observability.alerts.notify()``.

Configuración vía variables de entorno:
  - ``DLQ_MAX_RETRIES``  — máx. reintentos (default 5)
  - ``DLQ_BATCH_SIZE``   — entradas por ciclo (default 10)
"""

from __future__ import annotations

import os
import re as _re
from datetime import UTC, datetime, timedelta
from typing import Any

from db.dlq import (
    increment_retry,
    list_unresolved,
    mark_exhausted,
    mark_resolved,
    sweep_exhausted,
)
from observability.alerts import AlertLevel, notify
from observability.logging import bind_run_context, get_logger

log = get_logger(__name__)

# Tiempo base de espera entre reintentos (segundos): 2^retry_count * BASE_BACKOFF_S
_BASE_BACKOFF_S = 300  # 5 minutos
_MAX_BACKOFF_S = 86_400  # 24 horas
_DEFAULT_MAX_RETRIES = 5
_DEFAULT_BATCH_SIZE = 10


def _get_max_retries() -> int:
    """Lee DLQ_MAX_RETRIES del entorno; fallback a _DEFAULT_MAX_RETRIES."""
    try:
        return max(1, int(os.environ.get("DLQ_MAX_RETRIES", _DEFAULT_MAX_RETRIES)))
    except (ValueError, TypeError):
        return _DEFAULT_MAX_RETRIES


def _get_batch_size() -> int:
    """Lee DLQ_BATCH_SIZE del entorno; fallback a _DEFAULT_BATCH_SIZE."""
    try:
        return max(1, int(os.environ.get("DLQ_BATCH_SIZE", _DEFAULT_BATCH_SIZE)))
    except (ValueError, TypeError):
        return _DEFAULT_BATCH_SIZE


def _backoff_seconds(retry_count: int) -> float:
    """Calcula el tiempo de espera para un fallo con *retry_count* reintentos previos."""
    return float(min(_BASE_BACKOFF_S * (2**retry_count), _MAX_BACKOFF_S))


def _is_due(failure: dict[str, Any]) -> bool:
    """Devuelve True si ya ha pasado suficiente tiempo desde el último intento.

    Usa ``last_attempt_at`` si está disponible; cae back a ``created_at``.
    """
    raw = failure.get("last_attempt_at") or failure.get("created_at")
    if not raw:
        return True
    try:
        last_attempt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if last_attempt.tzinfo is None:
            last_attempt = last_attempt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return True
    retry_count = int(failure.get("retry_count") or 0)
    due_after = last_attempt + timedelta(seconds=_backoff_seconds(retry_count))
    return datetime.now(UTC) >= due_after


# ---------------------------------------------------------------------------
# Shared dispatch — única fuente de verdad para mapear fuente → scraper
# ---------------------------------------------------------------------------

_BULK_SOURCE_RE = _re.compile(r"^bulk_(?P<year>\d{4})(?P<month>\d{2})$")

# Prefijo de las fuentes bulk (``bulk_YYYYMM``). Reintentarlas significa
# reprocesar el mes entero con ``process_month``, que es trabajo de horas: el
# carril diario las excluye y las cubre el workflow manual `scrape-bulk.yml`.
_BULK_SOURCE_PREFIX = "bulk_"


def dispatch_retry(fuente: str, scope: str, run_id: str) -> bool:
    """Ejecuta el scraper correspondiente a *fuente*.

    Returns:
        True si el reintento fue exitoso; False si falló de nuevo.

    Raises:
        ValueError: si *fuente* es desconocida (no se puede reintentar).
    """
    bulk_match = _BULK_SOURCE_RE.match(fuente)
    if bulk_match:
        year = int(bulk_match.group("year"))
        month = int(bulk_match.group("month"))
        from scraper.pipeline import process_month

        result = process_month(year, month, run_id=run_id)
        return result.get("status") in ("ok", "no_publicado")

    if fuente == "placsp":
        from scraper.connectors.base import run_connector
        from scraper.connectors.placsp import PlacspAtomConnector

        connector = PlacspAtomConnector()
        run_result = run_connector(connector)
        return run_result.errores == 0

    # Conectores multi-fuente (ADR-009). Hasta 2026-08 sus entradas DLQ no
    # tenían dispatch: quemaban los 5 ciclos de reintento sin hacer nada y
    # acababan en una alerta de "agotó reintentos" que atribuía mal la causa.
    if fuente == "pscp":
        from scraper.connectors.base import run_connector
        from scraper.connectors.pscp import PscpConnector

        return run_connector(PscpConnector()).errores == 0

    if fuente == "ted":
        from scraper.connectors.base import run_connector
        from scraper.connectors.ted import TedConnector

        return run_connector(TedConnector()).errores == 0

    if fuente == "galicia_rss":
        from scraper.connectors.base import run_connector
        from scraper.connectors.galicia import GaliciaRssConnector

        return run_connector(GaliciaRssConnector()).errores == 0

    if fuente == "euskadi_rss":
        from scraper.connectors.base import run_connector
        from scraper.connectors.euskadi import EuskadiRssConnector

        return run_connector(EuskadiRssConnector()).errores == 0

    if fuente == "tacrc":
        from scraper.connectors.tacrc import run as run_tacrc

        return int(run_tacrc().get("errores") or 0) == 0

    if fuente == "placsp_watched_company_awards":
        from db.repositories.watched_companies import WatchedCompanyRepository
        from scraper.connectors.base import run_connector
        from scraper.connectors.watched_company_awards import (
            PlacspWatchedCompanyAwardsConnector,
        )

        watched_nifs = WatchedCompanyRepository().list_canonical_nifs()
        watched_connector = PlacspWatchedCompanyAwardsConnector(watched_nifs)
        return run_connector(watched_connector).errores == 0

    from scraper.pipeline import _DAILY_SOURCE, process_daily

    if fuente == _DAILY_SOURCE or fuente.startswith("atom"):
        result = process_daily(run_id=run_id)
        return result.get("status") in ("ok", "no_publicado")

    raise ValueError(f"Unsupported DLQ source: {fuente!r}")


def _retry_failure(failure: dict[str, Any], run_id: str) -> bool | None:
    """Intenta re-ejecutar la extracción correspondiente a *failure*.

    Returns:
        True si el reintento fue exitoso; False si falló de nuevo; ``None`` si
        la fuente no tiene dispatch (reintentar jamás va a funcionar — el
        caller la marca agotada de inmediato en vez de quemar ciclos).
    """
    fuente: str = str(failure.get("fuente") or "")
    scope: str = str(failure.get("scope") or "")

    try:
        return dispatch_retry(fuente, scope, run_id)
    except ValueError:
        log.warning(
            "dlq_retry_unknown_source",
            failure_id=failure["id"],
            fuente=fuente,
            scope=scope,
        )
        return None
    except Exception as exc:
        log.exception(
            "dlq_retry_exception",
            failure_id=failure["id"],
            fuente=fuente,
            error=str(exc),
        )
        return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def retry_failed_extractions(
    max_retries: int | None = None,
    batch_size: int | None = None,
    *,
    include_bulk: bool = True,
) -> int:
    """Reintenta extracciones fallidas pendientes en la DLQ.

    Flujo:
    1. Llama a ``sweep_exhausted()`` para marcar y alertar entradas que ya
       superaron ``max_retries``.
    2. Filtra las entradas aún activas cuyo backoff ha expirado.
    3. Reintenta en lotes y actualiza el estado.

    Args:
        max_retries: Máximo de reintentos (default: env ``DLQ_MAX_RETRIES`` o 5).
        batch_size:  Entradas por ciclo (default: env ``DLQ_BATCH_SIZE`` o 10).
        include_bulk: Si es False, ignora las entradas ``bulk_YYYYMM``.
            Reintentar una es ejecutar ``process_month`` completo — descarga y
            reparseo de los ZIP de un mes entero. Con el default (True) el
            carril diario se comía su propio timeout drenando meses bulk:
            ``sweep_exhausted`` sigue corriendo igual, sólo se acota **qué**
            se reintenta.

    Returns:
        Número de fallos que se han resuelto exitosamente.
    """
    if max_retries is None:
        max_retries = _get_max_retries()
    if batch_size is None:
        batch_size = _get_batch_size()

    # ── Paso 1: marcar y alertar entradas agotadas ───────────────────────────
    exhausted = sweep_exhausted(max_retries)
    if exhausted:
        for entry in exhausted:
            notify(
                AlertLevel.ERROR,
                "DLQ: entrada agotada sin resolver",
                (
                    f"La entrada fuente={entry['fuente']!r} scope={entry.get('scope')!r} "
                    f"ha agotado todos los reintentos ({entry['retry_count']} / {max_retries}).\n"
                    f"Último error: {entry.get('error_message', 'desconocido')}"
                ),
                fuente=entry["fuente"],
                scope=entry.get("scope"),
                retry_count=entry["retry_count"],
            )

    # ── Paso 2: cargar candidatos activos ────────────────────────────────────
    unresolved = list_unresolved(
        limit=batch_size * 3,
        exclude_fuente_prefix=None if include_bulk else _BULK_SOURCE_PREFIX,
    )

    if not unresolved:
        log.debug("dlq_retry_nothing_pending", include_bulk=include_bulk)
        return 0

    # Filtrar solo los que ya han cumplido el backoff
    due = [f for f in unresolved if _is_due(f)][:batch_size]

    if not due:
        log.debug("dlq_retry_all_in_backoff", total_unresolved=len(unresolved))
        return 0

    log.info(
        "dlq_retry_starting",
        due=len(due),
        total_unresolved=len(unresolved),
        include_bulk=include_bulk,
    )
    run_id = bind_run_context(entrypoint="dlq_retry", batch=len(due))

    # ── Paso 3: reintentar ───────────────────────────────────────────────────
    resolved = 0
    for failure in due:
        fid = int(failure["id"])
        success = _retry_failure(failure, run_id)
        if success is None:
            # Fuente sin dispatch: agotarla ya, con causa exacta, en vez de
            # quemar max_retries ciclos y alertar "agotó reintentos" como si
            # la extracción hubiera fallado max_retries veces.
            mark_exhausted(fid)
            notify(
                AlertLevel.WARN,
                "DLQ: entrada sin dispatch de reintento",
                (
                    f"La fuente {failure.get('fuente')!r} no tiene mapeo en "
                    f"dispatch_retry(); la entrada {fid} se marca agotada sin "
                    "reintentos. Si la fuente es legítima, añadir su dispatch "
                    "en scheduler/dlq_retry.py."
                ),
                fuente=failure.get("fuente"),
                scope=failure.get("scope"),
            )
            continue
        if success:
            mark_resolved(fid)
            resolved += 1
            log.info("dlq_retry_resolved", failure_id=fid, fuente=failure.get("fuente"))
        else:
            new_count = int(failure.get("retry_count") or 0) + 1
            increment_retry(fid)
            log.warning(
                "dlq_retry_still_failing",
                failure_id=fid,
                fuente=failure.get("fuente"),
                new_retry_count=new_count,
            )
            # Si esta actualización lo lleva a max_retries, el siguiente ciclo
            # lo capturará vía sweep_exhausted.

    log.info("dlq_retry_done", resolved=resolved, attempted=len(due))
    return resolved
