"""Ficha de pliego: contrato estricto, citas y persistencia."""

from __future__ import annotations

import json
from unittest.mock import patch

from db.database import DocumentoReferencia, connect
from db.repositories.documentos import DocumentosRepository
from services.rag.fact_sheet import extract_fact_sheet


def _seed_pages(licitacion_id: str = "FACT-1") -> tuple[int, str]:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES (?, 'Contrato con pliego', 'placsp', datetime('now'))",
            (licitacion_id,),
        )
    repo = DocumentosRepository()
    repo.upsert_meta(
        licitacion_id,
        [DocumentoReferencia(tipo="legal", uri="https://example.test/pcap.pdf")],
    )
    doc = repo.list_pendientes()[0]
    page_text = "El criterio precio tendrá una ponderación del 60 por ciento."
    repo.mark_extracted(
        doc["id"],
        texto=page_text,
        sha256="abc",
        pages=[page_text],
    )
    return int(doc["id"]), page_text


def _payload(documento_id: int, quote: str) -> str:
    return json.dumps(
        {
            "award_criteria": [
                {
                    "name": "Precio",
                    "description": "Criterio económico",
                    "weight_pct": 60,
                    "criterion_type": "price",
                    "confidence": 0.95,
                    "evidence": [
                        {
                            "documento_id": documento_id,
                            "page_number": 1,
                            "quote": quote,
                        }
                    ],
                }
            ],
            "technical_solvency": [],
            "economic_solvency": [],
            "guarantees": [],
            "penalties": [],
            "subcontracting": [],
            "team_requirements": [],
            "extensions": [],
            "critical_deadlines": [],
        }
    )


def test_extract_fact_sheet_validates_and_anchors_quote(tmp_db):
    _db_mod, _ = tmp_db
    doc_id, page_text = _seed_pages()
    quote = "criterio precio tendrá una ponderación del 60 por ciento"

    with patch(
        "services.rag.fact_sheet.stream_llm_response",
        return_value=iter([_payload(doc_id, quote)]),
    ):
        record = extract_fact_sheet("FACT-1", model="gpt-4o-mini")

    assert record.status == "extracted"
    assert record.field_count == 1
    assert record.evidence_count == 1
    assert record.facts is not None
    evidence = record.facts.award_criteria[0].evidence[0]
    assert evidence.page_number == 1
    assert evidence.start_offset == page_text.casefold().find(quote.casefold())
    assert evidence.end_offset == evidence.start_offset + len(quote)


def test_unverifiable_llm_fact_is_removed_and_flagged(tmp_db):
    _db_mod, _ = tmp_db
    doc_id, _page_text = _seed_pages("FACT-2")

    with patch(
        "services.rag.fact_sheet.stream_llm_response",
        return_value=iter([_payload(doc_id, "Esta cita no aparece en el pliego")]),
    ):
        record = extract_fact_sheet("FACT-2", model="gpt-4o-mini")

    assert record.status == "needs_review"
    assert record.field_count == 0
    assert record.evidence_count == 0
    assert record.facts is not None
    assert record.facts.award_criteria == []


def test_document_pages_are_replaced_idempotently(tmp_db):
    _db_mod, _ = tmp_db
    doc_id, _page_text = _seed_pages("FACT-3")
    repo = DocumentosRepository()

    repo.mark_extracted(
        doc_id,
        texto="Primera\nSegunda",
        sha256="def",
        pages=["Primera", "Segunda"],
    )
    pages = repo.list_pages(doc_id)

    assert [(page["page_number"], page["start_offset"], page["end_offset"]) for page in pages] == [
        (1, 0, 7),
        (2, 8, 15),
    ]
