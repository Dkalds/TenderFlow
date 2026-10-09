"""SLA visible de cobertura y frescura por fuente."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from db.repositories.source_health import SourceHealthRepository

#: Lotes de carga histórica: ``bulk_YYYYMM`` (PLACSP) y ``<conector>_bulk_YYYYMM``.
#: Son efímeros por diseño —uno por mes reprocesado— y no tienen frescura que
#: vigilar (ver ``REGISTERED_SOURCES``), así que no entran en el recuento de
#: fuentes al día: contarlos dejaba el aviso de degradación encendido para
#: siempre por un mes que se cargó una vez.
_LOTE_HISTORICO_RE = re.compile(r"(?:^|_)bulk_\d{6}$")


class SourceFreshness(BaseModel):
    source: str
    status: str
    last_success_at: str | None = None
    last_seen_updated: str | None = None
    cursor_updated_at: str | None = None
    lag_hours: float | None = None
    detected_within_24h_pct: float | None = Field(default=None, ge=0, le=100)
    sample_size: int = Field(default=0, ge=0)
    fetched: int = Field(default=0, ge=0)
    parsed: int = Field(default=0, ge=0)
    discarded: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    is_degraded: bool = False
    #: Lote de carga histórica (``bulk_YYYYMM``), no una fuente viva: viaja con
    #: su ``status`` pero nunca cuenta como degradado ni entra en los totales.
    is_backfill: bool = False
    warning: str | None = None


class SourceFreshnessResult(BaseModel):
    sources: list[SourceFreshness]
    healthy_sources: int = Field(ge=0)
    total_sources: int = Field(ge=0)
    healthy_sources_pct: float = Field(ge=0, le=100)
    generated_at: str


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def get_source_freshness(*, degraded_after_hours: float = 36.0) -> SourceFreshnessResult:
    """Combina salud de runs, cursor y latencia observada fuente→ingesta.

    Cada fuente registrada se mide contra su propio ``max_lag_hours``, el mismo
    que usa ``scheduler/healthcheck.py`` para avisar: con un umbral único el
    panel marcaba degradada una RSS semanal que el healthcheck daba por buena.
    ``degraded_after_hours`` queda para las fuentes sin registro.
    """
    # Diferido, como el resto de usos de `scraper` desde `services/`: el registro
    # de fuentes no hace falta para importar este módulo.
    from scraper.connectors import REGISTERED_SOURCES_BY_ID

    repo = SourceHealthRepository()
    rows = repo.list_health()
    samples = repo.latency_samples()
    within: dict[str, list[bool]] = defaultdict(list)
    for sample in samples:
        source_ts = _parse_datetime(sample.get("fecha_actualizacion_fuente"))
        ingested_ts = _parse_datetime(sample.get("fecha_extraccion"))
        if source_ts is None or ingested_ts is None:
            continue
        latency_hours = (ingested_ts - source_ts).total_seconds() / 3600
        if latency_hours >= 0:
            within[str(sample.get("fuente") or "unknown")].append(latency_hours <= 24)

    now = datetime.now(UTC)
    sources: list[SourceFreshness] = []
    for row in rows:
        source = str(row["source"])
        last_success = _parse_datetime(row.get("last_success_at"))
        lag_hours = (
            round((now - last_success).total_seconds() / 3600, 2)
            if last_success is not None
            else None
        )
        observed = within.get(source, [])
        detected_pct = round(sum(observed) / len(observed) * 100, 2) if observed else None
        status = str(row.get("status") or "unknown")
        is_backfill = _LOTE_HISTORICO_RE.search(source) is not None
        registrada = REGISTERED_SOURCES_BY_ID.get(source)
        umbral = float(registrada.max_lag_hours) if registrada else degraded_after_hours
        is_degraded = not is_backfill and (
            status != "success" or lag_hours is None or lag_hours > umbral
        )
        warning: str | None = None
        if status == "running" and row.get("last_started_at"):
            warning = (
                "La fuente sigue marcada como ejecutándose; el proceso pudo quedar interrumpido."
            )
        elif is_backfill:
            # Un lote terminado no «se atrasa»: su antigüedad no es un aviso.
            warning = None
        elif lag_hours is None:
            warning = "Todavía no hay una ingesta exitosa registrada."
        elif lag_hours > umbral:
            warning = f"La última ingesta exitosa fue hace {lag_hours:.1f} horas."
        elif detected_pct is not None and detected_pct < 90:
            warning = "Menos del 90% de la muestra se detectó en menos de 24 horas."
            is_degraded = True
        sources.append(
            SourceFreshness(
                source=source,
                status=status,
                last_success_at=row.get("last_success_at"),
                last_seen_updated=row.get("last_seen_updated"),
                cursor_updated_at=row.get("cursor_updated_at"),
                lag_hours=lag_hours,
                detected_within_24h_pct=detected_pct,
                sample_size=len(observed),
                fetched=int(row.get("fetched") or 0),
                parsed=int(row.get("parsed") or 0),
                discarded=int(row.get("discarded") or 0),
                errors=int(row.get("errors") or 0),
                is_degraded=is_degraded,
                is_backfill=is_backfill,
                warning=warning,
            )
        )
    vivas = [source for source in sources if not source.is_backfill]
    healthy = sum(not source.is_degraded for source in vivas)
    total = len(vivas)
    return SourceFreshnessResult(
        sources=sources,
        healthy_sources=healthy,
        total_sources=total,
        healthy_sources_pct=round(healthy / total * 100, 2) if total else 0.0,
        generated_at=now.isoformat(),
    )
