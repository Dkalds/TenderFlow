"""Extracción tipada y verificable de la ficha del pliego."""

from __future__ import annotations

import json
import re
from typing import Any

from db.repositories.documentos import DocumentosRepository
from db.repositories.tender_fact_sheets import TenderFactSheetsRepository
from llm.client import DEFAULT_MODEL, stream_llm_response
from observability.logging import get_logger
from shared.tender_facts import EvidenceRef, TenderFactSheet, TenderFactSheetRecord

log = get_logger(__name__)

EXTRACTION_VERSION = "tender-facts-v1"
_MAX_CONTEXT_CHARS = 15_000
_MAX_PAGES = 24
_TOPIC_TERMS = (
    "criterio",
    "adjudicación",
    "ponderación",
    "solvencia",
    "garantía",
    "penalidad",
    "penalización",
    "subcontrat",
    "equipo",
    "perfil",
    "experiencia",
    "prórroga",
    "plazo",
)

_EXTRACTION_QUESTION = """
Extrae la ficha del pliego con estas claves JSON exactas:
award_criteria: [{name, description, weight_pct, criterion_type, confidence, evidence}],
technical_solvency: [{description, confidence, evidence}],
economic_solvency: [{description, amount_eur, confidence, evidence}],
guarantees: [{description, amount_eur, confidence, evidence}],
penalties: [{description, amount_eur, confidence, evidence}],
subcontracting: [{description, confidence, evidence}],
team_requirements: [{description, role, minimum_years, quantity, confidence, evidence}],
extensions: [{description, confidence, evidence}],
critical_deadlines: [{name, description, date_value, confidence, evidence}].
Cada evidence es {documento_id, page_number, quote}; usa null cuando un valor
tipado no aparezca y listas vacías cuando no haya evidencia.
""".strip()


def _page_score(page: dict[str, Any]) -> int:
    text = str(page.get("texto") or "").casefold()
    return sum(text.count(term.casefold()) for term in _TOPIC_TERMS)


def _select_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Selecciona portada + páginas densas en requisitos dentro del presupuesto."""
    if not pages:
        return []
    first_per_doc: dict[int, dict[str, Any]] = {}
    for page in pages:
        first_per_doc.setdefault(int(page["documento_id"]), page)
    ranked = sorted(
        pages,
        key=lambda p: (
            p not in first_per_doc.values(),
            -_page_score(p),
            int(p["documento_id"]),
            int(p["page_number"]),
        ),
    )
    selected: list[dict[str, Any]] = []
    used = 0
    for page in ranked:
        text = str(page.get("texto") or "").strip()
        if not text:
            continue
        if selected and used + len(text) > _MAX_CONTEXT_CHARS:
            continue
        selected.append(page)
        used += len(text)
        if len(selected) >= _MAX_PAGES:
            break
    return sorted(
        selected,
        key=lambda p: (int(p["documento_id"]), int(p["page_number"])),
    )


def _extract_json_object(raw: str) -> dict[str, Any]:
    """Acepta JSON puro o un único bloque fenced y rechaza texto sin objeto."""
    cleaned = re.sub(r"^\s*```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("El extractor no devolvió un objeto JSON")
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("La ficha extraída no es un objeto JSON")
    return value


def _normalize_quote(value: str) -> str:
    return " ".join(value.casefold().split())


def _validated_evidence(
    evidence: EvidenceRef,
    page_index: dict[tuple[int, int], dict[str, Any]],
) -> EvidenceRef | None:
    page = page_index.get((evidence.documento_id, evidence.page_number))
    if page is None:
        return None
    page_text = str(page.get("texto") or "")
    if _normalize_quote(evidence.quote) not in _normalize_quote(page_text):
        return None
    exact_pos = page_text.casefold().find(evidence.quote.casefold())
    if exact_pos >= 0:
        page_start = int(page.get("start_offset") or 0)
        evidence.start_offset = page_start + exact_pos
        evidence.end_offset = evidence.start_offset + len(evidence.quote)
    return evidence


def _validate_fact_evidence(
    facts: TenderFactSheet,
    pages: list[dict[str, Any]],
) -> tuple[TenderFactSheet, int]:
    """Descarta hechos sin una cita que exista literalmente en la página."""
    page_index = {
        (int(page["documento_id"]), int(page["page_number"])): page for page in pages
    }
    rejected = 0
    for field_name in TenderFactSheet.model_fields:
        kept: list[Any] = []
        for fact in getattr(facts, field_name):
            valid = [
                checked
                for item in fact.evidence
                if (checked := _validated_evidence(item, page_index)) is not None
            ]
            if not valid:
                rejected += 1
                continue
            fact.evidence = valid
            kept.append(fact)
        setattr(facts, field_name, kept)
    return facts, rejected


def _counts(facts: TenderFactSheet) -> tuple[int, int]:
    items = [item for name in TenderFactSheet.model_fields for item in getattr(facts, name)]
    return len(items), sum(len(item.evidence) for item in items)


def extract_fact_sheet(
    licitacion_id: str,
    *,
    model: str = DEFAULT_MODEL,
) -> TenderFactSheetRecord:
    """Extrae, valida citas y persiste la ficha vigente de una licitación."""
    documentos = DocumentosRepository()
    sheets = TenderFactSheetsRepository()
    pages = documentos.list_pages_by_licitacion(licitacion_id)
    selected = _select_pages(pages)
    if not selected:
        raise ValueError("No hay texto por página disponible para extraer la ficha")

    chunks = [
        {
            "documento_id": int(page["documento_id"]),
            "page_number": int(page["page_number"]),
            "tipo": page.get("tipo"),
            "filename": page.get("filename"),
            "texto": page["texto"],
        }
        for page in selected
    ]
    docs = [
        {
            "id_externo": licitacion_id,
            "titulo": "Ficha estructurada del pliego",
            "descripcion": "",
            "chunks": chunks,
        }
    ]

    try:
        raw = "".join(
            stream_llm_response(
                question=_EXTRACTION_QUESTION,
                docs=docs,
                model=model,
                keywords=list(_TOPIC_TERMS),
                mode="extraction",
                max_tokens=3500,
            )
        )
        facts = TenderFactSheet.model_validate(_extract_json_object(raw))
        facts, rejected = _validate_fact_evidence(facts, pages)
        field_count, evidence_count = _counts(facts)
        status = "needs_review" if rejected else "extracted"
        sheets.upsert(
            licitacion_id=licitacion_id,
            status=status,
            extraction_version=EXTRACTION_VERSION,
            model=model,
            facts=facts.model_dump(mode="json"),
            field_count=field_count,
            evidence_count=evidence_count,
        )
    except Exception as exc:
        sheets.upsert(
            licitacion_id=licitacion_id,
            status="failed",
            extraction_version=EXTRACTION_VERSION,
            model=model,
            facts=None,
            field_count=0,
            evidence_count=0,
            error_detail=str(exc)[:2000],
        )
        raise

    record = sheets.get(licitacion_id)
    if record is None:  # defensa: el upsert anterior debe ser observable
        raise RuntimeError("La ficha se extrajo pero no pudo releerse")
    return TenderFactSheetRecord.model_validate(record)


def get_fact_sheet(licitacion_id: str) -> TenderFactSheetRecord | None:
    """Lee la ficha vigente sin invocar al proveedor LLM."""
    row = TenderFactSheetsRepository().get(licitacion_id)
    return TenderFactSheetRecord.model_validate(row) if row else None
