"""Extracción tipada y verificable de la ficha del pliego."""

from __future__ import annotations

from typing import Any, get_args

from annotated_types import MaxLen
from pydantic import ValidationError
from pydantic.fields import FieldInfo

from db.repositories.documentos import DocumentosRepository
from db.repositories.tender_fact_sheets import TenderFactSheetsRepository
from llm.client import DEFAULT_MODEL, stream_llm_response
from llm.json_utils import extract_json_object
from observability.logging import get_logger
from shared.tender_facts import EvidenceRef, TenderFactSheet, TenderFactSheetRecord

log = get_logger(__name__)

# v4: mismo esquema de datos que v3, pero la pregunta vuelve a caber en el
# límite del cliente LLM (v3 nunca llegó a producir una ficha) y los hechos se
# validan uno a uno. Se bumpea para poder distinguir en la BD una fila escrita
# por el extractor arreglado de las que dejó el roto.
EXTRACTION_VERSION = "tender-facts-v4"
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

# El texto viaja como ``question`` a ``stream_llm_response`` en modo interno
# (``extraction``), acotado por ``MAX_INTERNAL_QUESTION_LEN`` — el tope de
# plantilla, no el de usuario. La historia importa: cuando compartía el límite
# de 2000 chars de /ask, v3 (lotes/ANS/certificaciones) lo dejó en 2070 y la
# ficha falló SIEMPRE —botón «Extraer ficha» y cron nocturno por igual— con
# «La pregunta excede el máximo…», que la UI enseñaba tal cual. El tope interno
# da holgura real y `test_extraction_question_fits_llm_limit` sigue fijándolo.
#
# Los valores cerrados (`criterion_type`, `scope`), el formato de fecha y el
# techo de la cita se enuncian aquí porque el modelo los valida en
# ``shared/tender_facts.py``: un "calidad" en vez de "quality" o un
# "15/10/2026" en vez de ISO ya no tira la ficha entera (ver ``_parse_facts``),
# pero sí pierde ese hecho.
_EXTRACTION_QUESTION = """
Devuelve un objeto JSON con estas claves exactas. Cada valor es una lista de
objetos que SIEMPRE llevan description, confidence (0 a 1) y evidence, más los
campos propios de su familia:
lots: {lot_number, name, amount_eur},
award_criteria: {name, weight_pct, criterion_type},
technical_solvency: {},
economic_solvency: {amount_eur},
guarantees: {amount_eur},
penalties: {amount_eur},
service_levels: {name, target},
subcontracting: {},
team_requirements: {role, minimum_years, quantity},
certifications: {name, scope},
extensions: {},
critical_deadlines: {name, date_value},
technologies: {name}.
lots: un elemento por lote publicado, con lot_number tal como aparece ("1",
"Lote III") y su presupuesto sin IVA si es inequívoco; vacío si no hay lotes.
criterion_type: solo "price", "quality", "automatic", "judgement" u "other".
certifications: scope "company" si la acredita la empresa (ISO 27001, ENS),
"team" si la exige a personas del equipo, "other" si no está claro.
service_levels: el indicador en name y el compromiso en target ("Disponibilidad
del servicio" / "99,9% mensual"); sus penalizaciones van en penalties.
technologies: solo plataformas que el contrato implanta, mantiene, migra o
licencia ("migración a SAP S/4HANA"), nunca menciones incidentales.
date_value: fecha ISO AAAA-MM-DD, o null si el pliego no fija una exacta.
Cada evidence es {documento_id, page_number, quote}, con quote copiado
literalmente del fragmento y de menos de 400 caracteres. Usa null cuando un
valor tipado no aparezca y listas vacías cuando no haya evidencia.
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


# Ninguna familia declara un tope mayor que este; el default solo cubre que
# alguien añada una sin `max_length`.
_DEFAULT_FAMILY_LIMIT = 50


def _family_limit(field: FieldInfo) -> int:
    """Máximo de elementos que ``TenderFactSheet`` acepta en esa familia."""
    return next(
        (c.max_length for c in field.metadata if isinstance(c, MaxLen)),
        _DEFAULT_FAMILY_LIMIT,
    )


def _parse_facts(payload: dict[str, Any]) -> tuple[TenderFactSheet, int]:
    """Valida la respuesta del LLM hecho a hecho, no todo o nada.

    ``TenderFactSheet.model_validate`` sobre el objeto entero es todo-o-nada:
    una sola cita más larga de la cuenta, un ``criterion_type`` en español o
    una fecha que no es ISO —entre trece familias y decenas de elementos—
    tiraba la ficha completa, se persistía ``failed`` y el usuario veía «Aún no
    hay una ficha verificable» con el volcado de pydantic debajo. Validando
    elemento a elemento se pierde solo lo que no encaja.

    El descarte NO es silencioso: cuenta como ``rejected`` igual que una cita
    inverificable, así que la ficha queda en ``needs_review`` y la UI lo avisa.
    El tope por familia se respeta aquí porque el modelo lo valida de vuelta al
    releer la fila persistida, y un exceso rompería la lectura, no la escritura.
    """
    facts = TenderFactSheet()
    dropped = 0
    # ``extra='forbid'`` del modelo existía para que una clave inesperada no
    # pasara desapercibida. Validando por familia esa clave ya no rompe nada,
    # así que la visibilidad se conserva por log en vez de por excepción.
    if desconocidas := payload.keys() - TenderFactSheet.model_fields.keys():
        log.warning("fact_sheet_unknown_keys", keys=sorted(desconocidas))
    for name, field in TenderFactSheet.model_fields.items():
        items = payload.get(name)
        if items is None:
            continue
        if not isinstance(items, list):
            dropped += 1
            continue
        (item_model,) = get_args(field.annotation)
        limit = _family_limit(field)
        kept: list[Any] = []
        for index, item in enumerate(items):
            if len(kept) >= limit:
                dropped += len(items) - index
                break
            try:
                kept.append(item_model.model_validate(item))
            except ValidationError:
                dropped += 1
        setattr(facts, name, kept)
    return facts, dropped


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
                # Sin fallback de proveedor: la fila persiste `model`, y un
                # cambio silencioso de modelo la haría mentir sobre quién
                # extrajo. Si el proveedor está caído, la extracción falla
                # visible y el cron/botón reintentan.
                fallback=False,
            )
        )
        facts, invalid = _parse_facts(extract_json_object(raw))
        facts, unverifiable = _validate_fact_evidence(facts, pages)
        rejected = invalid + unverifiable
        if rejected:
            log.info(
                "fact_sheet_items_rejected",
                licitacion_id=licitacion_id,
                invalid=invalid,
                unverifiable=unverifiable,
            )
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


# ── Ficha verificada como contexto del resumen IA ──────────────────────────────

_SUMMARY_FAMILY_LABELS: dict[str, str] = {
    "lots": "Lotes",
    "award_criteria": "Criterios de adjudicación",
    "technical_solvency": "Solvencia técnica",
    "economic_solvency": "Solvencia económica",
    "guarantees": "Garantías",
    "penalties": "Penalizaciones",
    "service_levels": "Niveles de servicio (ANS)",
    "subcontracting": "Subcontratación",
    "team_requirements": "Equipo requerido",
    "certifications": "Certificaciones",
    "extensions": "Prórrogas",
    "critical_deadlines": "Fechas críticas",
    "technologies": "Tecnologías",
}
_SUMMARY_MAX_ITEMS_PER_FAMILY = 8


# ``Any``: recibe cualquiera de las trece familias de ``TenderFactSheet``
# (LotFact, WeightedCriterion, MonetaryFact…), que solo comparten FactItem;
# los campos extra se consultan con getattr.
def _summary_item_line(item: Any) -> str:
    """Línea compacta de un hecho: nombre + atributos tipados + descripción."""
    name = getattr(item, "name", None) or getattr(item, "role", None)
    detalles: list[str] = []
    if getattr(item, "weight_pct", None) is not None:
        detalles.append(f"peso {item.weight_pct}%")
    if getattr(item, "amount_eur", None) is not None:
        detalles.append(f"{item.amount_eur} EUR")
    if getattr(item, "target", None):
        detalles.append(f"objetivo {item.target}")
    if getattr(item, "minimum_years", None) is not None:
        detalles.append(f"{item.minimum_years} años mín.")
    if getattr(item, "date_value", None) is not None:
        detalles.append(str(item.date_value))
    cabecera = str(name) if name else ""
    if detalles:
        cabecera = f"{cabecera} ({', '.join(detalles)})" if cabecera else ", ".join(detalles)
    descripcion = str(getattr(item, "description", "") or "")[:200]
    cuerpo = f"{cabecera}: {descripcion}" if cabecera else descripcion
    return f"- {cuerpo}"


def facts_summary_text(facts: TenderFactSheet, *, max_chars: int = 2500) -> str:
    """Texto compacto de la ficha para inyectar como chunk del resumen IA.

    Son los pocos datos "confiables" del sistema (cada hecho sobrevivió a la
    validación de citas contra el texto persistido), así que el resumen los
    recibe como fragmento etiquetado — el system prompt de modo ``resumen``
    les da prioridad en '## Requisitos clave del pliego'.
    """
    lines: list[str] = []
    for family, label in _SUMMARY_FAMILY_LABELS.items():
        items = getattr(facts, family)
        if not items:
            continue
        lines.append(f"{label}:")
        lines.extend(_summary_item_line(item) for item in items[:_SUMMARY_MAX_ITEMS_PER_FAMILY])
    text = "\n".join(lines)
    return text[:max_chars]


# ── Extracción en background (botón «Extraer ficha») ───────────────────────────

# El estado ``running`` vive en cache y no en la tabla: añadirlo al CHECK de
# ``tender_fact_sheets.status`` exigiría migración, y es un estado efímero de
# proceso, no del dato. TTL de seguridad por si el worker muere sin limpiar.
_EXTRACTION_RUNNING_TTL_SECONDS = 15 * 60


# ``Any``: el backend concreto (_MemoryBackend | _RedisBackend) es privado de
# shared.cache; aquí solo se usan get/set/delete.
def _jobs_cache() -> Any:
    from shared.cache import get_cache

    return get_cache("fact_sheet_jobs")


def _running_key(licitacion_id: str) -> str:
    return f"running|{licitacion_id}"


def extraction_running(licitacion_id: str) -> bool:
    """True si hay una extracción en curso para la licitación."""
    return bool(_jobs_cache().get(_running_key(licitacion_id)))


def try_mark_extraction_running(licitacion_id: str) -> bool:
    """Marca la extracción como en curso; ``False`` si ya lo estaba.

    get+set sin atomicidad: dos clics simultáneos podrían colarse ambos, con
    el único coste de una extracción duplicada (el upsert es idempotente).
    """
    cache = _jobs_cache()
    key = _running_key(licitacion_id)
    if cache.get(key):
        return False
    cache.set(key, True, ttl=_EXTRACTION_RUNNING_TTL_SECONDS)
    return True


def clear_extraction_running(licitacion_id: str) -> None:
    _jobs_cache().delete(_running_key(licitacion_id))


def run_background_extraction(
    licitacion_id: str,
    *,
    model: str,
    budget_subject: str | None = None,
) -> None:
    """Cuerpo del BackgroundTask de ``POST …/ficha-pliego/extract-async``.

    Nunca lanza: el resultado se comunica por la fila persistida (que el
    frontend consulta por polling) y por logs. El caso «sin páginas» —el único
    en que ``extract_fact_sheet_on_demand`` falla SIN persistir— se materializa
    aquí como ``failed`` con detalle, o el polling vería un 404 mudo para
    siempre.
    """
    from llm.budget import bind_budget_subject

    try:
        bind_budget_subject(budget_subject)
        try:
            record = extract_fact_sheet_on_demand(licitacion_id, model=model)
        except ValidationError:
            # extract_fact_sheet ya persistió el estado failed con su detalle.
            log.warning("fact_sheet_background_validation_failed", licitacion_id=licitacion_id)
            return
        except ValueError as exc:
            try:
                TenderFactSheetsRepository().upsert(
                    licitacion_id=licitacion_id,
                    status="failed",
                    extraction_version=EXTRACTION_VERSION,
                    model=model,
                    facts=None,
                    field_count=0,
                    evidence_count=0,
                    error_detail=str(exc)[:2000],
                )
            except Exception:
                # El contrato de esta función es «nunca lanza»: si ni el estado
                # failed puede persistirse (p.ej. la licitación no existe y la
                # FK lo rechaza — la ruta ya lo corta con 404, esto es defensa
                # en profundidad), el detalle queda en el log y nada revienta
                # el ciclo del BackgroundTask.
                log.warning(
                    "fact_sheet_background_failed_upsert_failed",
                    licitacion_id=licitacion_id,
                    error=str(exc),
                    exc_info=True,
                )
            return
        except Exception as exc:
            log.warning(
                "fact_sheet_background_extract_failed",
                licitacion_id=licitacion_id,
                error=str(exc),
            )
            return

        try:
            from services.tech_signal import ingest_llm_technologies

            ingest_llm_technologies(record)
        except Exception as exc:
            # La ficha ya está persistida; la señal de tecnología es aditiva.
            log.warning(
                "fact_sheet_background_tech_ingest_failed",
                licitacion_id=licitacion_id,
                error=str(exc),
            )
    finally:
        clear_extraction_running(licitacion_id)
