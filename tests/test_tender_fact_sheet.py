"""Ficha de pliego: contrato estricto, citas y persistencia."""

from __future__ import annotations

import json
from unittest.mock import patch

from db.database import DocumentoReferencia, connect
from db.repositories.documentos import DocumentosRepository
from services.rag.fact_sheet import extract_fact_sheet


def _seed_pages(licitacion_id: str = "FACT-1", *, texto: str | None = None) -> tuple[int, str]:
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES (%s, 'Contrato con pliego', 'placsp', CURRENT_TIMESTAMP)",
            (licitacion_id,),
        )
    repo = DocumentosRepository()
    repo.upsert_meta(
        licitacion_id,
        [DocumentoReferencia(tipo="legal", uri="https://example.test/pcap.pdf")],
    )
    doc = repo.list_pendientes()[0]
    page_text = texto or "El criterio precio tendrá una ponderación del 60 por ciento."
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


# ── v2: technologies (plan "categorización alimentada por los pliegos") ────


def _payload_with_technology(documento_id: int, quote: str, *, name: str, confidence: float) -> str:
    return json.dumps(
        {
            "award_criteria": [],
            "technical_solvency": [],
            "economic_solvency": [],
            "guarantees": [],
            "penalties": [],
            "subcontracting": [],
            "team_requirements": [],
            "extensions": [],
            "critical_deadlines": [],
            "technologies": [
                {
                    "name": name,
                    "description": f"Menciona {name}",
                    "confidence": confidence,
                    "evidence": [{"documento_id": documento_id, "page_number": 1, "quote": quote}],
                }
            ],
        }
    )


def test_extract_fact_sheet_includes_technologies_with_valid_evidence(tmp_db):
    _db_mod, _ = tmp_db
    tech_text = "El proyecto consiste en la migración e implantación de SAP S/4HANA."
    doc_id, _ = _seed_pages("FACT-TECH-1", texto=tech_text)
    quote = "migración e implantación de SAP S/4HANA"

    with patch(
        "services.rag.fact_sheet.stream_llm_response",
        return_value=iter(
            [_payload_with_technology(doc_id, quote, name="SAP S/4HANA", confidence=0.9)]
        ),
    ):
        record = extract_fact_sheet("FACT-TECH-1", model="gpt-4o-mini")

    assert record.status == "extracted"
    assert record.facts is not None
    assert len(record.facts.technologies) == 1
    mention = record.facts.technologies[0]
    assert mention.name == "SAP S/4HANA"
    assert mention.evidence[0].quote == quote


def test_pre_v2_persisted_row_without_technologies_key_still_validates(tmp_db):
    """``TenderFactSheet.technologies`` es un campo nuevo (v2) sobre un modelo
    ``extra='forbid'``; filas persistidas antes de este cambio tienen
    ``data_json`` sin esa clave en absoluto. Simula esa fila directamente
    (bypass del write path, que ya escribe siempre con la clave presente) y
    confirma que la lectura no rompe -- ``default_factory=list`` cubre una
    clave AUSENTE, no una clave con valor inesperado, y ``extra='forbid'``
    solo rechaza claves de más, no de menos."""
    _db_mod, _ = tmp_db
    from db.repositories.tender_fact_sheets import TenderFactSheetsRepository
    from services.rag.fact_sheet import get_fact_sheet

    old_shape_data_json = json.dumps(
        {
            "award_criteria": [],
            "technical_solvency": [],
            "economic_solvency": [],
            "guarantees": [],
            "penalties": [],
            "subcontracting": [],
            "team_requirements": [],
            "extensions": [],
            "critical_deadlines": [],
            # sin "technologies": así se veía data_json antes de tender-facts-v2
        }
    )
    with connect() as c:
        c.execute(
            "INSERT INTO licitaciones (id_externo, titulo, fuente, fecha_extraccion) "
            "VALUES ('OLD-SHAPE-1', 'Contrato viejo', 'placsp', CURRENT_TIMESTAMP)"
        )
        c.execute(
            "INSERT INTO tender_fact_sheets "
            "(licitacion_id, status, extraction_version, model, data_json, "
            "field_count, evidence_count, extracted_at, updated_at) "
            "VALUES (%s, 'extracted', 'tender-facts-v1', 'gpt-4o-mini', %s, 0, 0, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ("OLD-SHAPE-1", old_shape_data_json),
        )

    # Vía repo directo (sin invocar al LLM) y vía get_fact_sheet (el camino real).
    raw = TenderFactSheetsRepository().get("OLD-SHAPE-1")
    assert raw is not None
    assert "technologies" not in raw["facts"]  # confirma que la fila es genuinamente vieja

    record = get_fact_sheet("OLD-SHAPE-1")
    assert record is not None
    assert record.facts is not None
    assert record.facts.technologies == []


def test_technology_mention_without_valid_evidence_is_dropped(tmp_db):
    _db_mod, _ = tmp_db
    doc_id, _ = _seed_pages("FACT-TECH-2")

    with patch(
        "services.rag.fact_sheet.stream_llm_response",
        return_value=iter(
            [
                _payload_with_technology(
                    doc_id, "esta cita no aparece en la página", name="Oracle", confidence=0.8
                )
            ]
        ),
    ):
        record = extract_fact_sheet("FACT-TECH-2", model="gpt-4o-mini")

    assert record.status == "needs_review"
    assert record.facts is not None
    assert record.facts.technologies == []


class TestListPendingLicitacionesSelector:
    """Selector de tests/documentos pendientes de ficha, arreglado en v2:
    antes solo miraba "sin fila", así que un bump de ``EXTRACTION_VERSION``
    no reprocesaba nada y ``status='failed'`` quedaba bloqueado para siempre.
    """

    def test_never_attempted_is_pending(self, tmp_db):
        _db_mod, _ = tmp_db
        from db.repositories.tender_fact_sheets import TenderFactSheetsRepository

        _seed_pages("SEL-1")
        assert TenderFactSheetsRepository().list_pending_licitaciones(
            extraction_version="tender-facts-v2"
        ) == ["SEL-1"]

    def test_stale_version_is_pending(self, tmp_db):
        _db_mod, _ = tmp_db
        from db.repositories.tender_fact_sheets import TenderFactSheetsRepository

        _seed_pages("SEL-2")
        repo = TenderFactSheetsRepository()
        repo.upsert(
            licitacion_id="SEL-2",
            status="extracted",
            extraction_version="tender-facts-v1",
            model="gpt-4o-mini",
            facts={},
            field_count=0,
            evidence_count=0,
        )
        assert repo.list_pending_licitaciones(extraction_version="tender-facts-v2") == ["SEL-2"]

    def test_current_version_is_not_pending(self, tmp_db):
        _db_mod, _ = tmp_db
        from db.repositories.tender_fact_sheets import TenderFactSheetsRepository

        _seed_pages("SEL-3")
        repo = TenderFactSheetsRepository()
        repo.upsert(
            licitacion_id="SEL-3",
            status="extracted",
            extraction_version="tender-facts-v2",
            model="gpt-4o-mini",
            facts={},
            field_count=0,
            evidence_count=0,
        )
        assert repo.list_pending_licitaciones(extraction_version="tender-facts-v2") == []

    def test_failed_is_pending_regardless_of_its_version(self, tmp_db):
        _db_mod, _ = tmp_db
        from db.repositories.tender_fact_sheets import TenderFactSheetsRepository

        _seed_pages("SEL-4")
        repo = TenderFactSheetsRepository()
        repo.upsert(
            licitacion_id="SEL-4",
            status="failed",
            extraction_version="tender-facts-v2",
            model="gpt-4o-mini",
            facts=None,
            field_count=0,
            evidence_count=0,
            error_detail="boom",
        )
        assert repo.list_pending_licitaciones(extraction_version="tender-facts-v2") == ["SEL-4"]

    def test_priority_order_is_never_attempted_then_stale_then_failed(self, tmp_db):
        _db_mod, _ = tmp_db
        from db.repositories.tender_fact_sheets import TenderFactSheetsRepository

        _seed_pages("SEL-NEVER")
        _seed_pages("SEL-STALE")
        _seed_pages("SEL-FAILED")
        repo = TenderFactSheetsRepository()
        repo.upsert(
            licitacion_id="SEL-STALE",
            status="extracted",
            extraction_version="tender-facts-v1",
            model="m",
            facts={},
            field_count=0,
            evidence_count=0,
        )
        repo.upsert(
            licitacion_id="SEL-FAILED",
            status="failed",
            extraction_version="tender-facts-v2",
            model="m",
            facts=None,
            field_count=0,
            evidence_count=0,
            error_detail="x",
        )

        pendientes = repo.list_pending_licitaciones(extraction_version="tender-facts-v2", limit=10)

        assert pendientes.index("SEL-NEVER") < pendientes.index("SEL-STALE")
        assert pendientes.index("SEL-STALE") < pendientes.index("SEL-FAILED")

    def test_failed_tier_is_pure_fifo_not_starved_by_tech_priority(self, tmp_db):
        """Regresión: tech_priority se aplicaba a las tres tiers vía un único
        ORDER BY compartido, así que un backlog de 'failed' tech-relevantes
        por encima del límite del batch dejaba bloqueadas para siempre
        justo las licitaciones SIN ninguna señal de tecnología todavía --
        las que este selector existe para descubrir vía el pliego. Con la
        licitación sin tecnología insertada PRIMERO (más antigua) pero con
        tech_priority peor, un ORDER BY que no aísle tech_priority al tier 0
        la dejaría siempre última, incumpliendo el 'updated_at ASC' puro que
        el propio docstring promete para status='failed'."""
        _db_mod, _ = tmp_db
        from db.repositories.tender_fact_sheets import TenderFactSheetsRepository

        _seed_pages("SEL-NO-TECH")  # sin tecnologia/ml_tecnologias: tech_priority=2
        _seed_pages("SEL-TECH", texto="otro pliego")
        with connect() as c:
            c.execute("UPDATE licitaciones SET tecnologia = 'SAP' WHERE id_externo = 'SEL-TECH'")
        repo = TenderFactSheetsRepository()
        # SEL-NO-TECH falla PRIMERO (updated_at más antiguo) pese a tener la
        # peor tech_priority; SEL-TECH falla después.
        repo.upsert(
            licitacion_id="SEL-NO-TECH",
            status="failed",
            extraction_version="tender-facts-v2",
            model="m",
            facts=None,
            field_count=0,
            evidence_count=0,
            error_detail="boom",
        )
        repo.upsert(
            licitacion_id="SEL-TECH",
            status="failed",
            extraction_version="tender-facts-v2",
            model="m",
            facts=None,
            field_count=0,
            evidence_count=0,
            error_detail="boom",
        )

        pendientes = repo.list_pending_licitaciones(extraction_version="tender-facts-v2", limit=10)

        # Puro FIFO dentro de la tier 'failed': el que falló antes va antes,
        # sin importar tech_priority.
        assert pendientes.index("SEL-NO-TECH") < pendientes.index("SEL-TECH")


class TestIngestLlmTechnologies:
    def test_normalizes_to_tech_labels_persists_signal_and_merges(self, tmp_db):
        _db_mod, _ = tmp_db
        from db.repositories.tecnologia_pliego import TecnologiaPliegoRepository
        from services.tech_signal import ingest_llm_technologies

        tech_text = "El proyecto consiste en la migración e implantación de SAP S/4HANA."
        doc_id, _ = _seed_pages("FACT-ING-1", texto=tech_text)
        quote = "migración e implantación de SAP S/4HANA"

        with patch(
            "services.rag.fact_sheet.stream_llm_response",
            return_value=iter(
                [_payload_with_technology(doc_id, quote, name="SAP S/4HANA", confidence=0.85)]
            ),
        ):
            record = extract_fact_sheet("FACT-ING-1", model="gpt-4o-mini")

        n = ingest_llm_technologies(record)

        assert n == 1
        rows = TecnologiaPliegoRepository().list_for_licitacion("FACT-ING-1")
        assert [(r["tecnologia"], r["method"]) for r in rows] == [("SAP", "llm")]

        with connect() as c:
            row = c.execute(
                "SELECT ml_tecnologias FROM licitaciones WHERE id_externo = %s", ("FACT-ING-1",)
            ).fetchone()
        assert row[0] == "SAP"

    def test_unmapped_name_is_skipped_without_raising(self, tmp_db):
        _db_mod, _ = tmp_db
        from services.tech_signal import ingest_llm_technologies

        tech_text = "El proyecto usa una plataforma propietaria llamada Zzyzx."
        doc_id, _ = _seed_pages("FACT-ING-2", texto=tech_text)
        quote = "plataforma propietaria llamada Zzyzx"

        with patch(
            "services.rag.fact_sheet.stream_llm_response",
            return_value=iter(
                [_payload_with_technology(doc_id, quote, name="Zzyzx", confidence=0.7)]
            ),
        ):
            record = extract_fact_sheet("FACT-ING-2", model="gpt-4o-mini")

        assert ingest_llm_technologies(record) == 0

    def test_record_without_facts_is_a_noop(self):
        from services.tech_signal import ingest_llm_technologies
        from shared.tender_facts import TenderFactSheetRecord

        record = TenderFactSheetRecord(
            licitacion_id="X",
            status="pending",
            extraction_version="tender-facts-v2",
            model=None,
            facts=None,
            updated_at="2026-08-04T00:00:00+00:00",
        )
        assert ingest_llm_technologies(record) == 0
