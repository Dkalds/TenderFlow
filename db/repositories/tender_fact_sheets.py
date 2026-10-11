"""Persistencia de fichas estructuradas de pliego."""

from __future__ import annotations

import json
from typing import Any

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts


class TenderFactSheetsRepository:
    """Repositorio fino para ``tender_fact_sheets``."""

    def list_pending_licitaciones(self, *, extraction_version: str, limit: int = 20) -> list[str]:
        """Licitaciones con páginas persistidas y pendientes de una ficha
        vigente. "Pendiente" cubre tres casos, en este orden de prioridad
        (el lote LLM es el caro, así que nunca-intentadas van primero):

        1. Sin fila en ``tender_fact_sheets`` -- nunca se procesó. Dentro de
           este grupo, tech-relevantes primero (mismo criterio que
           ``DocumentosRepository.list_pendientes``).
        2. Fila con ``extraction_version`` distinta a la vigente y
           ``status != 'failed'`` -- un bump del extractor (ej. la pregunta
           añadió ``technologies`` en v2) la deja stale.
        3. ``status = 'failed'`` (cualquier versión), ordenadas por
           ``updated_at ASC`` -- sin columna ``attempts``, esto hace rotar
           los "poison pills" en vez de bloquearlos para siempre.
        """
        with connect_read() as c:
            rows = c.execute(
                "WITH candidatos AS ("
                "  SELECT DISTINCT d.licitacion_id FROM documento_pages dp "
                "  JOIN documentos d ON d.id = dp.documento_id"
                "), clasificados AS ("
                "  SELECT c.licitacion_id, "
                "  CASE "
                "    WHEN tf.licitacion_id IS NULL THEN 0 "
                "    WHEN tf.status != 'failed' AND tf.extraction_version != %s THEN 1 "
                "    WHEN tf.status = 'failed' THEN 2 "
                "    ELSE 99 "
                "  END AS tier, "
                "  CASE "
                "    WHEN l.tecnologia IS NOT NULL AND l.tecnologia != '' THEN 0 "
                "    WHEN l.ml_tecnologias IS NOT NULL AND l.ml_tecnologias != '' THEN 1 "
                "    ELSE 2 "
                "  END AS tech_priority, "
                # Demanda real primero: un expediente que alguien convirtió en
                # oportunidad o marcó como favorito es el que va a abrir la
                # pestaña Pliego hoy. Con 25 fichas por pasada frente a cientos de
                # documentos descargados, el orden decide si la promesa «qué pide
                # el pliego» se cumple para quien la está mirando o para nadie.
                "  CASE WHEN EXISTS (SELECT 1 FROM pursuits p "
                "        WHERE p.licitacion_id = c.licitacion_id "
                "        AND p.status NOT IN ('won', 'lost', 'withdrawn')) THEN 0 "
                "       WHEN EXISTS (SELECT 1 FROM watchlist_items w "
                "        WHERE w.id_externo = c.licitacion_id) THEN 1 "
                "       ELSE 2 END AS demanda, "
                "  tf.updated_at "
                "  FROM candidatos c "
                "  JOIN licitaciones l ON l.id_externo = c.licitacion_id "
                "  LEFT JOIN tender_fact_sheets tf ON tf.licitacion_id = c.licitacion_id "
                "  WHERE tf.licitacion_id IS NULL "
                "     OR tf.status = 'failed' "
                "     OR tf.extraction_version != %s"
                ") "
                "SELECT licitacion_id FROM clasificados "
                # tech_priority solo desempata dentro del tier 0 (nunca-intentadas):
                # en tier 1/2 debe ser updated_at ASC puro, o un backlog de failed/
                # stale tech-relevantes por encima del límite del batch deja
                # bloqueadas para siempre justo las licitaciones sin ninguna señal
                # de tecnología todavía -- las que este selector existe para descubrir.
                # `demanda` va antes que el tier: una ficha stale de una oportunidad
                # abierta importa más que una nunca intentada que nadie mira.
                "ORDER BY demanda, tier, CASE WHEN tier = 0 THEN tech_priority ELSE 0 END, "
                "updated_at ASC, licitacion_id "
                "LIMIT %s",
                (extraction_version, extraction_version, max(1, min(int(limit), 200))),
            ).fetchall()
            return [str(row[0]) for row in rows]

    def list_candidatas_golden(
        self, *, por_grupo: int = 15, fuente: str | None = None
    ) -> list[dict[str, Any]]:
        """Expedientes con texto de pliego, para elegir los casos del golden.

        Lo consume ``scripts/capturar_ficha_golden.py --listar``. Entra todo
        expediente con alguna página de texto, **tenga ficha o no**: los que no
        la tienen, o la tienen ``failed``, son justo donde hay que medir lo que
        la ficha omite (``docs/plans/2026-10-eval-ficha-pliego.md`` §3).

        El tope es **por fuente y grupo** (``sin_ficha``, ``fallida``,
        ``pobre`` con menos de cinco hechos, ``rica``), no global: con un
        ``LIMIT`` sobre la lista ordenada por fuente, la primera fuente la
        llenaba entera y ni las demás ni las fichas ricas llegaban a verse.
        ``total_grupo`` dice cuántas hay en el grupo, se enseñen o no. Dentro
        de cada grupo, primero las de más hechos y, a igualdad, las de más
        páginas.

        ``lotes`` y ``formulas`` salen del JSON de la ficha y valen 0 si no hay
        ficha, si no trae datos o si la clave no es una lista: el listado sirve
        para elegir, no para validar la fila.
        """
        with connect_read() as c:
            cur = c.execute(
                "WITH paginas AS ("
                "  SELECT d.licitacion_id, "
                "         COUNT(DISTINCT d.id) AS documentos, "
                "         COUNT(*) AS paginas, "
                "         COUNT(*) FILTER (WHERE dp.ocr) AS paginas_ocr "
                "  FROM documento_pages dp "
                "  JOIN documentos d ON d.id = dp.documento_id "
                # `octet_length` lee el tamaño sin descomprimir el texto de
                # cada página, que es lo que haría compararlo con ''.
                "  WHERE octet_length(dp.texto) > 0 "
                "  GROUP BY d.licitacion_id"
                "), candidatas AS ("
                "  SELECT p.licitacion_id, l.fuente, p.documentos, p.paginas, p.paginas_ocr, "
                "         tf.status, tf.extraction_version, tf.field_count, "
                "         CASE WHEN jsonb_typeof(f.datos -> 'lots') = 'array' "
                "              THEN jsonb_array_length(f.datos -> 'lots') ELSE 0 END AS lotes, "
                "         CASE WHEN jsonb_typeof(f.datos -> 'price_formula') = 'array' "
                "              THEN jsonb_array_length(f.datos -> 'price_formula') ELSE 0 END "
                "           AS formulas, "
                "         CASE WHEN tf.licitacion_id IS NULL THEN 'sin_ficha' "
                "              WHEN tf.status = 'failed' THEN 'fallida' "
                "              WHEN tf.field_count < 5 THEN 'pobre' "
                "              ELSE 'rica' END AS grupo "
                "  FROM paginas p "
                "  JOIN licitaciones l ON l.id_externo = p.licitacion_id "
                "  LEFT JOIN tender_fact_sheets tf ON tf.licitacion_id = p.licitacion_id "
                # `data_json` es `text`: se convierte aquí una sola vez, y una
                # cadena vacía se trata como «sin datos» en vez de romper el cast.
                "  LEFT JOIN LATERAL ("
                "    SELECT NULLIF(tf.data_json, '')::jsonb AS datos"
                "  ) f ON TRUE "
                "  WHERE (%s::text IS NULL OR l.fuente = %s)"
                "), numeradas AS ("
                "  SELECT c.*, "
                "         ROW_NUMBER() OVER ("
                "           PARTITION BY c.fuente, c.grupo "
                "           ORDER BY COALESCE(c.field_count, 0) DESC, c.paginas DESC, c.licitacion_id"
                "         ) AS orden, "
                "         COUNT(*) OVER (PARTITION BY c.fuente, c.grupo) AS total_grupo "
                "  FROM candidatas c"
                ") "
                "SELECT licitacion_id, fuente, grupo, documentos, paginas, paginas_ocr, status, "
                "       extraction_version, field_count, lotes, formulas, total_grupo "
                "FROM numeradas "
                "WHERE orden <= %s "
                "ORDER BY fuente, grupo, orden",
                (fuente, fuente, max(1, min(int(por_grupo), 200))),
            )
            return rows_to_dicts(cur)

    def get(self, licitacion_id: str) -> dict[str, Any] | None:
        """Ficha persistida; ``facts`` se devuelve como objeto Python."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT licitacion_id, status, extraction_version, model, data_json, "
                "field_count, evidence_count, error_detail, extracted_at, updated_at "
                "FROM tender_fact_sheets WHERE licitacion_id = %s",
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
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
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
