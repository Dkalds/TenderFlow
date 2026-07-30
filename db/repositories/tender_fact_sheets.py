"""Persistencia de fichas estructuradas de pliego."""

from __future__ import annotations

import json
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts


class TenderFactSheetsRepository:
    """Repositorio fino para ``tender_fact_sheets``."""

    def list_pending_licitaciones(self, limit: int = 20) -> list[str]:
        """Licitaciones con páginas persistidas y sin ficha procesada."""
        with connect_read() as c:
            rows = c.execute(
                "SELECT DISTINCT d.licitacion_id "
                "FROM documento_pages dp "
                "JOIN documentos d ON d.id = dp.documento_id "
                "LEFT JOIN tender_fact_sheets tf ON tf.licitacion_id = d.licitacion_id "
                "WHERE tf.licitacion_id IS NULL "
                "ORDER BY d.licitacion_id LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
            return [str(row[0]) for row in rows]

    def get(self, licitacion_id: str) -> dict[str, Any] | None:
        """Ficha persistida; ``facts`` se devuelve como objeto Python."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT licitacion_id, status, extraction_version, model, data_json, "
                "field_count, evidence_count, error_detail, extracted_at, updated_at "
                "FROM tender_fact_sheets WHERE licitacion_id = ?",
                (licitacion_id,),
            )
            rows = rows_to_dicts(cur)
        if not rows:
            return None
        row = rows[0]
        raw = row.pop("data_json", None)
        row["facts"] = json.loads(str(raw)) if raw else None
        return row

    def upsert(
        self,
        *,
        licitacion_id: str,
        status: str,
        extraction_version: str,
        model: str | None,
        facts: dict[str, Any] | None,
        field_count: int,
        evidence_count: int,
        error_detail: str | None = None,
    ) -> None:
        """Inserta o reemplaza de forma idempotente la ficha vigente."""
        now = now_utc_iso()
        data_json = (
            json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
            if facts is not None
            else None
        )
        extracted_at = now if status in ("extracted", "needs_review") else None
        with connect() as c:
            c.execute(
                "INSERT INTO tender_fact_sheets "
                "(licitacion_id, status, extraction_version, model, data_json, "
                "field_count, evidence_count, error_detail, extracted_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(licitacion_id) DO UPDATE SET "
                "status=excluded.status, extraction_version=excluded.extraction_version, "
                "model=excluded.model, data_json=excluded.data_json, "
                "field_count=excluded.field_count, evidence_count=excluded.evidence_count, "
                "error_detail=excluded.error_detail, extracted_at=excluded.extracted_at, "
                "updated_at=excluded.updated_at",
                (
                    licitacion_id,
                    status,
                    extraction_version,
                    model,
                    data_json,
                    field_count,
                    evidence_count,
                    error_detail,
                    extracted_at,
                    now,
                ),
            )
