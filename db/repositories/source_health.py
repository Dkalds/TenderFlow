"""Persistencia y lectura del SLA de ingesta por fuente."""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts


class SourceHealthRepository:
    """Repositorio para ``source_ingestion_health`` y muestras de latencia."""

    def mark_started(self, source: str) -> None:
        now = now_utc_iso()
        with connect() as c:
            c.execute(
                "INSERT INTO source_ingestion_health "
                "(source, status, last_started_at, updated_at) "
                "VALUES (%s, 'running', %s, %s) "
                "ON CONFLICT(source) DO UPDATE SET "
                "status='running', last_started_at=excluded.last_started_at, "
                "updated_at=excluded.updated_at",
                (source, now, now),
            )

    def mark_completed(
        self,
        *,
        source: str,
        status: str,
        fetched: int,
        parsed: int,
        discarded: int,
        errors: int,
        cursor_value: str | None,
    ) -> None:
        now = now_utc_iso()
        success_at = now if status == "success" else None
        with connect() as c:
            c.execute(
                "INSERT INTO source_ingestion_health "
                "(source, status, last_completed_at, last_success_at, fetched, "
                "parsed, discarded, errors, cursor_value, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT(source) DO UPDATE SET "
                "status=excluded.status, "
                "last_completed_at=excluded.last_completed_at, "
                "last_success_at=COALESCE(excluded.last_success_at, "
                "source_ingestion_health.last_success_at), "
                "fetched=excluded.fetched, parsed=excluded.parsed, "
                "discarded=excluded.discarded, errors=excluded.errors, "
                "cursor_value=excluded.cursor_value, updated_at=excluded.updated_at",
                (
                    source,
                    status,
                    now,
                    success_at,
                    fetched,
                    parsed,
                    discarded,
                    errors,
                    cursor_value,
                    now,
                ),
            )

    def list_health(self) -> list[dict[str, Any]]:
        with connect_read() as c:
            cur = c.execute(
                "SELECT h.source, h.status, h.last_started_at, h.last_completed_at, "
                "h.last_success_at, h.fetched, h.parsed, h.discarded, h.errors, "
                "h.cursor_value, h.updated_at, ic.last_seen_updated, "
                "ic.updated_at AS cursor_updated_at "
                "FROM source_ingestion_health h "
                "LEFT JOIN ingestion_cursors ic ON ic.source = h.source "
                "ORDER BY h.source"
            )
            return rows_to_dicts(cur)

    def latency_samples(self, *, limit: int = 50_000) -> list[dict[str, Any]]:
        """Fechas fuente→ingesta recientes para estimar detección <24h."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT fuente, fecha_actualizacion_fuente, fecha_extraccion "
                "FROM licitaciones "
                "WHERE fecha_actualizacion_fuente IS NOT NULL "
                "AND fecha_extraccion IS NOT NULL "
                "ORDER BY fecha_extraccion DESC LIMIT %s",
                (max(1, min(int(limit), 100_000)),),
            )
            return rows_to_dicts(cur)
