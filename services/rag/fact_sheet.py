"""Extracción tipada y verificable de la ficha del pliego."""

from __future__ import annotations

from typing import Any

from db.repositories.documentos import DocumentosRepository
from db.repositories.tender_fact_sheets import TenderFactSheetsRepository
from llm.client import DEFAULT_MODEL, stream_llm_response
from llm.json_utils import extract_json_object
from observability.logging import get_logger
from shared.tender_facts import EvidenceRef, TenderFactSheet, TenderFactSheetRecord

log = get_logger(__name__)

EXTRACTION_VERSION = "tender-facts-v3"
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
    # v3: lotes, certificaciones y niveles de servicio. Sin estos términos la
    # selección de páginas puede dejar fuera el anexo de lotes o el capítulo de
    # ANS, que suelen vivir lejos de los términos administrativos clásicos.
    # Ojo al elegir términos nuevos: se cuentan como substring casefold, así
    # que "ans", "sla" o "iso" puntuarían "transporte", "legislación" y
    # "aviso" — señal falsa que roba presupuesto de contexto a páginas útiles.
    "lote",
    "certificac",
    "certificado",
    "esquema nacional de seguridad",
    "nivel de servicio",
    "niveles de servicio",
    "disponibilidad",
    "indicador",
)
# v2 (plan "categorización alimentada por los pliegos"): la selección de
# páginas también pondera menciones de tecnología, o el pliego técnico
# (frecuentemente la página más rica en estos términos) puede quedar fuera
# del presupuesto de contexto si solo se puntúa por términos administrativos.
_TECH_TERMS = ("sap", "oracle", "salesforce", "microsoft", "hana", "erp", "crm", "software")

_EXTRACTION_QUESTION = """
Extrae la ficha del pliego con estas claves JSON exactas:
lots: [{lot_number, name, description, amount_eur, confidence, evidence}],
award_criteria: [{name, description, weight_pct, criterion_type, confidence, evidence}],
technical_solvency: [{description, confidence, evidence}],
economic_solvency: [{description, amount_eur, confidence, evidence}],
guarantees: [{description, amount_eur, confidence, evidence}],
penalties: [{description, amount_eur, confidence, evidence}],
service_levels: [{name, target, description, confidence, evidence}],
subcontracting: [{description, confidence, evidence}],
team_requirements: [{description, role, minimum_years, quantity, confidence, evidence}],
certifications: [{name, scope, description, confidence, evidence}],
extensions: [{description, confidence, evidence}],
critical_deadlines: [{name, description, date_value, confidence, evidence}],
technologies: [{name, description, confidence, evidence}].
Para lots: un elemento por lote publicado, con su número tal como aparece
("1", "Lote III"), su denominación y su presupuesto sin IVA si es inequívoco;
si el pliego dice que no hay división en lotes, deja la lista vacía.
Para service_levels: acuerdos de nivel de servicio (ANS/SLA) con su indicador
en name y el objetivo comprometido en target (ej. name "Disponibilidad del
servicio", target "99,9% mensual"); las penalizaciones por incumplirlos van
en penalties, no aquí.
Para certifications: certificaciones exigidas, con scope "company" si la
acredita la empresa (ISO 27001, ENS, partner de fabricante), "team" si la
exige a personas del equipo (certificados de perfil), "other" si no está claro.
Para technologies: solo plataformas o tecnologías mencionadas explícitamente
como objeto del contrato (ej. "migración a SAP S/4HANA", "mantenimiento de
Salesforce Service Cloud") -- no incluyas menciones incidentales o genéricas
(ej. "se trabajará con herramientas ofimáticas estándar").
Cada evidence es {documento_id, page_number, quote}; usa null cuando un valor
tipado no aparezca y listas vacías cuando no haya evidencia.
""".strip()


def _page_score(page: dict[str, Any]) -> int:
    text = str(page.get("texto") or "").casefold()
    topic_hits = sum(text.count(term.casefold()) for term in _TOPIC_TERMS)
    tech_hits = sum(text.count(term.casefold()) for term in _TECH_TERMS)
    return topic_hits + tech_hits


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
    page_index = {(int(page["documento_id"]), int(page["page_number"])): page for page in pages}
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


def _pdf_extraction_available() -> bool:
    """El extra ``[pliegos]`` (pypdf) es opcional y la imagen de la API no lo
    trae. Se comprueba ANTES de intentar el fetch: sin pypdf,
    ``fetch_and_extract`` marcaría el documento como ``error`` y esa fila
    dejaría de ser elegible para el cron nocturno (que solo toma ``pending``).
    """
    import importlib.util

    return importlib.util.find_spec("pypdf") is not None


_ONDEMAND_MAX_DOCUMENTS = 8
_DOC_TIPO_PRIORITY = {"legal": 0, "technical": 1}


def ensure_documents_ready(licitacion_id: str) -> dict[str, int]:
    """Descarga+extrae bajo demanda los adjuntos pendientes de una licitación.

    El cron nocturno drena el backlog global por lotes y una licitación
    concreta puede tardar semanas en tocar turno; quien la tiene abierta no
    puede esperar. Descargar en el momento también maximiza la probabilidad
    de que el enlace PLACSP siga vivo (sus tokens rotan y caducan).

    Los documentos en ``error`` solo se reintentan si ninguno llegó a
    ``extracted``: sin eso la ficha sería imposible, y con eso reintentarlos
    en cada clic no resucita enlaces con token caducado. Fail-open por
    documento, mismo criterio que el job nocturno.
    """
    if not _pdf_extraction_available():
        log.warning("fact_sheet_ondemand_fetch_skipped_no_pliegos_extra")
        return {"attempted": 0, "extracted": 0, "error": 0, "skipped_no_extra": 1}

    from scraper.document_fetcher import fetch_and_extract

    repo = DocumentosRepository()
    rows = repo.list_by_licitacion(licitacion_id)
    pending = [row for row in rows if row.get("status") == "pending"]
    any_extracted = any(row.get("status") == "extracted" for row in rows)
    candidates = (
        pending
        if (pending or any_extracted)
        else [row for row in rows if row.get("status") == "error"]
    )
    candidates.sort(key=lambda row: _DOC_TIPO_PRIORITY.get(str(row.get("tipo")), 2))

    # ``skipped`` lo devuelve el fetcher cuando el breaker está abierto: no se
    # llegó a intentar la descarga y la fila sigue ``pending``. Se declara para
    # que el diagnóstico pueda distinguirlo de un fallo real.
    counts = {"attempted": 0, "extracted": 0, "error": 0, "skipped": 0}
    for row in candidates[:_ONDEMAND_MAX_DOCUMENTS]:
        counts["attempted"] += 1
        try:
            outcome = fetch_and_extract(row)
        except Exception as exc:
            log.warning(
                "fact_sheet_ondemand_fetch_failed",
                documento_id=row.get("id"),
                error=str(exc),
            )
            outcome = "error"
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


def _missing_pages_detail(licitacion_id: str, fetched: dict[str, int]) -> str:
    """Mensaje 422 accionable según por qué no hay texto que extraer."""
    rows = DocumentosRepository().list_by_licitacion(licitacion_id)
    if not rows:
        return (
            "La licitación no referencia ningún pliego descargable; "
            "la ficha necesita al menos un documento adjunto en PLACSP."
        )
    if fetched.get("skipped_no_extra"):
        return (
            "Los pliegos siguen en cola de procesado (el servidor no tiene "
            "instalada la extracción de PDF); el job nocturno los procesará."
        )
    if fetched.get("skipped") and not fetched.get("error"):
        # Breaker abierto: no se intentó ninguna descarga, así que hablar de
        # "descargas fallaron" mandaría a mirar los pliegos cuando el problema
        # es que PLACSP está rechazando y hay que reintentar más tarde.
        return (
            "PLACSP no está respondiendo ahora mismo, así que no se ha llegado "
            "a descargar ningún pliego. Los documentos siguen en cola: "
            "reintentá en unos minutos o esperá al job nocturno."
        )
    errores = sum(1 for row in rows if row.get("status") == "error")
    return (
        f"No se pudo extraer texto de los pliegos ({errores} de {len(rows)} "
        "descargas fallaron). Los enlaces de PLACSP caducan por tokens "
        "rotativos; suelen volver a estar disponibles tras la ingesta diaria."
    )


def extract_fact_sheet_on_demand(
    licitacion_id: str,
    *,
    model: str = DEFAULT_MODEL,
) -> TenderFactSheetRecord:
    """Ficha bajo demanda: trae los pliegos que falten y extrae después.

    Es el camino del botón «Extraer ficha» de la UI; el batch nocturno usa
    ``extract_fact_sheet`` directamente porque su selector ya garantiza
    páginas persistidas y su fase de fetch cubre las descargas.

    La falta de páginas se comprueba aquí (y no capturando el ``ValueError``
    de ``extract_fact_sheet``): ``pydantic.ValidationError`` hereda de
    ``ValueError``, y reescribir un fallo de validación del LLM como «no hay
    páginas» mandaría al usuario a mirar el documento equivocado.
    """
    fetched = ensure_documents_ready(licitacion_id)
    pages = DocumentosRepository().list_pages_by_licitacion(licitacion_id)
    if not any(str(page.get("texto") or "").strip() for page in pages):
        raise ValueError(_missing_pages_detail(licitacion_id, fetched))
    return extract_fact_sheet(licitacion_id, model=model)


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
        facts = TenderFactSheet.model_validate(extract_json_object(raw))
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
