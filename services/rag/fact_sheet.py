"""Extracción tipada y verificable de la ficha del pliego."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
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
#
# v5: la pregunta pide además las cuatro familias de F2.2/F2.3/F2.4
# (`price_formula`, `required_documents`, `rate_cards`, `budget_breakdown`).
# El bump es obligatorio: sin él las fichas escritas por v4 —que no las
# contienen— se darían por completas, y el simulador de precio, el kit y el
# margen implícito seguirían vacíos para siempre sobre pliegos ya extraídos.
#
# Sin bump el 2026-09-24, a propósito: la pregunta repite `description` en las
# llaves de cada familia. Los Nemotron de NVIDIA, que sustituyeron a DeepSeek
# ese día, tomaban esas llaves como el esquema completo y omitían el campo: 14
# de 17 hechos de un pliego de prueba caían por «description: Field required».
# El esquema no cambia y las fichas v5 ya guardadas son válidas, así que un
# bump solo las reencolaría para extraer lo mismo otra vez.
#
# v6 (2026-09-28): la ficha v5 con Nemotron salía vacía casi siempre —de 886
# filas, 17 `extracted` y 70 `needs_review` con 0 hechos; el resto `failed`—.
# Cuatro causas, medidas sobre pliegos reales de producción:
# 1. Contexto: 15k chars son ~5 páginas de un PCAP de 118; los criterios y la
#    fórmula de precio casi nunca entraban. Ahora 56k chars y hasta 40 páginas,
#    sin reservar la portada de cada anexo (el DEUC se comía el presupuesto).
# 2. `confidence`: Nemotron lo omite si no va en las llaves de la familia, y
#    sin él el hecho se descartaba entero. Mismo arreglo que `description`.
# 3. Salida: `max_tokens=3500` cortaba el JSON a media ficha en los pliegos con
#    contenido (el caso que importa). Ahora 8000 y descripciones acotadas.
# 4. Una cita más larga que el tope del esquema tiraba el hecho; ahora se
#    recorta (sigue siendo literal: un prefijo de la cita está en la página).
# El bump es obligatorio: las `needs_review` vacías de v5 no se reencolan solas.
EXTRACTION_VERSION = "tender-facts-v6"
# Por debajo de ``MAX_CONTEXT_CHARS_EXTRACTION`` (llm/prompts.py): cada página
# añade su cabecera ``--- Fragmento de pliego (…) ---``, y el bloque de CONTEXTO
# que se pasa del presupuesto se corta por el final — justo las últimas páginas.
_MAX_CONTEXT_CHARS = 56_000
_MAX_PAGES = 40
_MAX_OUTPUT_TOKENS = 8000
#: Tope del esquema para ``EvidenceRef.quote``; el recorte se hace aquí para
#: no perder el hecho por una cita larga.
_MAX_QUOTE_CHARS = 600
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
    # v6: las familias de F2.2-F2.4 (fórmula de precio, documentación por
    # sobre, tarifas, desglose del presupuesto) no tenían ningún término, así
    # que la página de la fórmula solo entraba si por casualidad hablaba de
    # plazos o solvencia.
    "fórmula",
    "oferta económica",
    "puntuación",
    "anormalmente baja",
    "desproporcionada",
    "temerari",
    "presupuesto base",
    "costes directos",
    "costes indirectos",
    "precio/hora",
    "tarifa",
    # No "sobre a/b/c": como substring puntúan «sobre aspectos», «sobre
    # contratación»… en cualquier página.
    "sobre electrónico",
    "archivo electrónico",
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
objetos con los campos indicados; description, confidence y evidence son
OBLIGATORIOS en todos. description es una frase corta (máx. 200 caracteres) de
lo que dice el pliego; confidence es un número de 0 a 1:
lots: {description, confidence, evidence, lot_number, name, amount_eur},
award_criteria: {description, confidence, evidence, name, weight_pct, criterion_type},
technical_solvency: {description, confidence, evidence},
economic_solvency: {description, confidence, evidence, amount_eur},
guarantees: {description, confidence, evidence, amount_eur},
penalties: {description, confidence, evidence, amount_eur},
service_levels: {description, confidence, evidence, name, target},
subcontracting: {description, confidence, evidence},
team_requirements: {description, confidence, evidence, role, minimum_years, quantity},
certifications: {description, confidence, evidence, name, scope},
extensions: {description, confidence, evidence},
critical_deadlines: {description, confidence, evidence, name, date_value},
technologies: {description, confidence, evidence, name},
price_formula: {description, confidence, evidence, formula_type, max_points,
umbral_temeridad, params},
required_documents: {description, confidence, evidence, name, scope, subsanable},
rate_cards: {description, confidence, evidence, role, max_rate_eur_hour, estimated_hours},
budget_breakdown: {description, confidence, evidence, concept, category, amount_eur, pct}.
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
formula_type: solo "proporcional_inversa" (puntos = max * baja_propia /
baja_mayor), "lineal_por_tramos", "con_umbral_temeridad" u "otra"; usa "otra"
cuando la fórmula no encaje, nunca la más parecida. params es un objeto
{nombre: número} (los tramos, el umbral), {} si no hay, jamás prosa ni lista;
umbral_temeridad en tanto por uno
(0,25 para un 25%). Una entrada por lote si el pliego publica varias.
required_documents: scope "sobre_a" (documentación administrativa), "sobre_b"
(criterios sujetos a juicio de valor), "sobre_c" (criterios automáticos) u
"otro"; subsanable solo si el pliego lo dice, si no null.
rate_cards: una entrada por perfil con tarifa máxima publicada; deja
estimated_hours a null si el pliego no da horas.
budget_breakdown: una entrada por línea del desglose del presupuesto base, con
category "salariales", "directos", "indirectos", "beneficio" u "otro".
evidence es una lista de citas [{documento_id, page_number, quote}], nunca un
objeto suelto: documento_id y page_number son los números N y M de la cabecera
[doc:N p.M] del fragmento, y quote se copia literalmente de él, en menos de 300
caracteres: la frase clave, no el párrafo entero. Usa null cuando un valor tipado no aparezca y listas vacías cuando
no haya evidencia.
""".strip()


def _page_score(page: dict[str, Any]) -> int:
    text = str(page.get("texto") or "").casefold()
    topic_hits = sum(text.count(term.casefold()) for term in _TOPIC_TERMS)
    tech_hits = sum(text.count(term.casefold()) for term in _TECH_TERMS)
    return topic_hits + tech_hits


#: Tipos de documento cuya portada entra siempre. La del PCAP suele ser el
#: cuadro resumen (importe, plazo, lotes); la de un ``additional`` es la del
#: DEUC o de un modelo de declaración, y hasta v6 se reservaba igual: en un
#: expediente con tres anexos, tres portadas inútiles se comían un tercio del
#: presupuesto antes de mirar una sola página puntuada.
_PORTADA_SIEMPRE = frozenset({"legal", "technical"})


def _select_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Selecciona portadas del pliego + páginas densas en requisitos."""
    if not pages:
        return []
    portadas: set[tuple[int, int]] = set()
    vistos: set[int] = set()
    for page in pages:
        documento_id = int(page["documento_id"])
        if documento_id in vistos:
            continue
        vistos.add(documento_id)
        if page.get("tipo") in _PORTADA_SIEMPRE:
            portadas.add((documento_id, int(page["page_number"])))
    ranked = sorted(
        pages,
        key=lambda p: (
            (int(p["documento_id"]), int(p["page_number"])) not in portadas,
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
    """Clave de comparación de citas: sin mayúsculas y **sin espacios**.

    Sin espacios, no con espacios colapsados: el extractor de PDF mete blancos
    donde el documento no los tiene («( OEmax)», «licitación  (PL)», letras
    espaciadas en cabeceras) y el modelo, que lee el texto con sentido, los
    quita al citar. Con espacios colapsados la fórmula de precio de un pliego
    real se descartaba por ese «( ». Quitar los blancos no deja pasar texto
    inventado: los caracteres tienen que estar todos, en orden.
    """
    return "".join(value.casefold().split())


#: Elipsis con la que el modelo abrevia una cita larga («el órgano podrá
#: optar... por la imposición de penalidades»). Medido el 2026-09-28 sobre un
#: pliego real: 11 de 25 citas llevaban una, y todas se descartaban.
_ELIPSIS_RE = re.compile(r"\s*(?:\.{3,}|…)\s*")
#: Un fragmento más corto que esto casa en cualquier página («de la», «1.»)
#: y no prueba nada: una cita con elipsis solo vale si su trozo más largo lo
#: supera.
_MIN_FRAGMENTO_CHARS = 20


def _fragmentos_de_cita(quote: str) -> list[str]:
    """Trozos literales de una cita, normalizados, separados por la elipsis."""
    return [f for f in (_normalize_quote(t) for t in _ELIPSIS_RE.split(quote)) if f]


def _cita_en_texto(fragmentos: list[str], texto_normalizado: str) -> bool:
    """Todos los fragmentos aparecen literalmente y en orden."""
    desde = 0
    for fragmento in fragmentos:
        pos = texto_normalizado.find(fragmento, desde)
        if pos < 0:
            return False
        desde = pos + len(fragmento)
    return True


def _validated_evidence(
    evidence: EvidenceRef,
    page_index: dict[tuple[int, int], dict[str, Any]],
) -> EvidenceRef | None:
    """La cita, si existe literalmente en el pliego; ``None`` si no.

    Literal **por fragmentos**: una elipsis del modelo separa trozos que deben
    estar todos en la página y en ese orden, y el más largo tiene que ser
    significativo. Lo que se relaja es la abreviatura, no la literalidad.

    Si la cita no está en la página citada pero sí en otra del **mismo
    documento**, se corrige la página en vez de tirar el hecho: el modelo
    confunde páginas contiguas (una tabla de criterios que empieza en la 21 y
    se cita como 22), y el texto es el del pliego igual. No se busca en otros
    documentos: la misma frase en el PCAP y en el PPT puede decir cosas
    distintas según el contexto.
    """
    fragmentos = _fragmentos_de_cita(evidence.quote)
    if not fragmentos or max(len(f) for f in fragmentos) < min(
        _MIN_FRAGMENTO_CHARS, len(_normalize_quote(evidence.quote))
    ):
        return None

    citada = (evidence.documento_id, evidence.page_number)
    candidatas = [
        citada,
        *sorted(
            (c for c in page_index if c[0] == evidence.documento_id and c != citada),
            key=lambda c: abs(c[1] - evidence.page_number),
        ),
    ]
    page = next(
        (
            page_index[clave]
            for clave in candidatas
            if clave in page_index
            and _cita_en_texto(
                fragmentos, _normalize_quote(str(page_index[clave].get("texto") or ""))
            )
        ),
        None,
    )
    if page is None:
        return None
    evidence.page_number = int(page["page_number"])

    page_text = str(page.get("texto") or "")
    # Offsets solo cuando la cita casa tal cual (sin elipsis ni saltos de línea
    # distintos): el resaltado de la UI necesita posiciones exactas, y un
    # resaltado aproximado es peor que ninguno.
    exact_pos = page_text.casefold().find(evidence.quote.casefold())
    if exact_pos >= 0:
        page_start = int(page.get("start_offset") or 0)
        evidence.start_offset = page_start + exact_pos
        evidence.end_offset = evidence.start_offset + len(evidence.quote)
    # La procedencia la pone la página persistida, no el LLM (S8.3): el modelo
    # no sabe —ni debe adivinar— si el texto que se le dio venía de un OCR.
    evidence.ocr = bool(page.get("ocr"))
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


def _params_numericos(params: Any) -> dict[str, float]:
    """Las entradas de ``params`` que son un número (o «0,25» escrito como texto)."""
    if not isinstance(params, dict):
        return {}
    numericos: dict[str, float] = {}
    for clave, valor in params.items():
        if isinstance(valor, bool):
            continue
        if isinstance(valor, int | float):
            numericos[str(clave)] = float(valor)
        elif isinstance(valor, str):
            try:
                numericos[str(clave)] = float(valor.strip().replace(",", "."))
            except ValueError:
                continue
    return numericos


def _normalizar_item(item: Any) -> Any:
    """Arregla las desviaciones de forma que no cambian el significado.

    - ``params`` de la fórmula con prosa entre los números: se quedan los
      números (ver :func:`_params_numericos`).
    - ``evidence`` como objeto suelto en vez de lista (el prompt lo prohíbe,
      pero pasa): se envuelve.
    - Una ``quote`` más larga que el tope del esquema: se recorta. Un prefijo
      de una cita literal sigue siendo literal, así que la verificación contra
      la página (``_validate_fact_evidence``) sigue valiendo igual.

    Lo demás —un ``confidence`` ausente, un enum inventado— no se rellena: sería
    inventar un dato que el modelo no dio, y el hecho se descarta como antes.
    """
    if not isinstance(item, dict):
        return item
    params = item.get("params")
    if params is not None:
        # Solo los parámetros numéricos: el modelo mezcla los tramos con la
        # leyenda de la fórmula ({"OEM": "oferta más baja"}), y por esa prosa
        # se descartaba la fórmula entera (medido en un pliego real el
        # 2026-09-28). La leyenda ya va en `description`; no se pierde nada.
        item = {**item, "params": _params_numericos(params)}
    evidencia = item.get("evidence")
    if isinstance(evidencia, dict):
        evidencia = [evidencia]
    if isinstance(evidencia, list):
        normalizada: list[Any] = []
        for ref in evidencia:
            if isinstance(ref, dict) and isinstance(ref.get("quote"), str):
                ref = {**ref, "quote": ref["quote"].strip()[:_MAX_QUOTE_CHARS]}
            normalizada.append(ref)
        item = {**item, "evidence": normalizada}
    return item


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
    motivos: Counter[str] = Counter()
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
                kept.append(item_model.model_validate(_normalizar_item(item)))
            except ValidationError as exc:
                dropped += 1
                # Qué campo y por qué. Sin esto el log solo decía `invalid=14`,
                # y averiguar que el 100% era «confidence: missing» exigió
                # reproducir la llamada a mano (2026-09-28).
                for error in exc.errors()[:3]:
                    campo = ".".join(str(p) for p in error["loc"]) or "-"
                    motivos[f"{name}.{campo}:{error['type']}"] += 1
        setattr(facts, name, kept)
    if motivos:
        log.info("fact_sheet_items_invalid", motivos=dict(motivos.most_common(10)))
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

    Lo que PLACSP ha anunciado sin publicarlo todavía (``sin_publicar``) no se
    intenta, esté ``pending`` o en ``error``: el servlet contesta 500 hasta que
    sale el pliego, y cada intento son cuatro reintentos con espera —76 s para
    un expediente de cuatro documentos, medido el 2026-10-04— para acabar
    dejando la fila en ``error``.
    """
    if not _pdf_extraction_available():
        log.warning("fact_sheet_ondemand_fetch_skipped_no_pliegos_extra")
        return {"attempted": 0, "extracted": 0, "error": 0, "skipped_no_extra": 1}

    from scraper.document_fetcher import fetch_and_extract

    repo = DocumentosRepository()
    rows = repo.list_by_licitacion(licitacion_id)
    descargables = [row for row in rows if not row.get("sin_publicar")]
    pending = [row for row in descargables if row.get("status") == "pending"]
    any_extracted = any(row.get("status") == "extracted" for row in rows)
    candidates = (
        pending
        if (pending or any_extracted)
        else [row for row in descargables if row.get("status") == "error"]
    )
    candidates.sort(key=lambda row: _DOC_TIPO_PRIORITY.get(str(row.get("tipo")), 2))

    # ``skipped`` lo devuelve el fetcher cuando el breaker está abierto: no se
    # llegó a intentar la descarga y la fila sigue ``pending``.
    # ``skipped_no_extra``, cuando el formato se sabe leer pero no en este
    # proceso (DOCX/ODT en la imagen de la API): también sigue ``pending``.
    # ``unsupported`` (S8.2) es un formato que no sabemos leer. Se declaran para
    # que el diagnóstico pueda distinguirlos de un fallo real.
    counts = {
        "attempted": 0,
        "extracted": 0,
        "error": 0,
        "skipped": 0,
        "skipped_no_extra": 0,
        "unsupported": 0,
    }
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
    if any(row.get("sin_publicar") for row in rows):
        # Va antes que el resto porque es la causa y no un síntoma: hablar de
        # descargas fallidas o de enlaces caducados mandaría a esperar a «la
        # ingesta diaria», que no arregla nada mientras PLACSP no publique.
        return (
            "PLACSP ha anunciado los pliegos de este expediente, pero todavía no "
            "ha publicado el pliego: hasta que lo haga, sus enlaces dan error. "
            "La ficha se podrá extraer cuando lo publique."
        )
    if fetched.get("skipped_no_extra"):
        # Sin pypdf no se intenta nada; sin python-docx/odfpy (la imagen de la
        # API no los trae) se descarga pero la fila sigue `pending`. En los dos
        # casos los procesa el job nocturno, que sí los tiene.
        return (
            "Los pliegos siguen en cola de procesado (este servidor no tiene "
            "instalado el extractor de su formato); el job nocturno los procesará."
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
    # S8.2: un formato que no sabemos leer no es una descarga fallida, y
    # mandar a alguien a esperar «a la ingesta diaria» por un .doc binario es
    # mandarlo a esperar para siempre. Se dice lo que pasa de verdad.
    no_soportados = [row for row in rows if row.get("status") == "unsupported"]
    if no_soportados and not any(row.get("status") == "error" for row in rows):
        formatos = sorted({str(row.get("content_type") or "desconocido") for row in no_soportados})
        return (
            f"Los pliegos de esta licitación están en un formato que todavía no "
            f"se sabe leer ({', '.join(formatos)}); no hay texto del que extraer "
            "la ficha."
        )
    errores = sum(1 for row in rows if row.get("status") == "error")
    return (
        f"No se pudo extraer texto de los pliegos ({errores} de {len(rows)} "
        "descargas fallaron). Los enlaces de PLACSP caducan por tokens "
        "rotativos; suelen volver a estar disponibles tras la ingesta diaria."
    )


class SinPaginasError(ValueError):
    """No hay texto de pliegos del que extraer la ficha.

    ``ValueError`` porque así lo traducen ya sus llamadores (422 en la ruta
    síncrona, ``failed`` con detalle en la de background). Lleva el expediente
    que se miró, que en una republicación no es el que se pidió: es donde hay
    que dejar el ``failed`` para que la siguiente lectura lo encuentre.
    """

    def __init__(self, mensaje: str, *, licitacion_id: str) -> None:
        super().__init__(mensaje)
        self.licitacion_id = licitacion_id


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

    Pedida sobre una republicación confirmada, se extrae la de su canónica:
    es la que tiene los pliegos (:func:`services.dedupe.expediente_del_pliego`).
    """
    from services.dedupe import expediente_del_pliego

    licitacion_id = expediente_del_pliego(licitacion_id)
    fetched = ensure_documents_ready(licitacion_id)
    pages = DocumentosRepository().list_pages_by_licitacion(licitacion_id)
    if not any(str(page.get("texto") or "").strip() for page in pages):
        raise SinPaginasError(
            _missing_pages_detail(licitacion_id, fetched), licitacion_id=licitacion_id
        )
    return extract_fact_sheet(licitacion_id, model=model)


_SIN_TEXTO = "No hay texto por página disponible para extraer la ficha"


@dataclass(frozen=True)
class ExtraccionHechos:
    """Lo que sale de un pliego antes de persistir nada."""

    facts: TenderFactSheet
    #: Elementos que no encajaron en el esquema (``_parse_facts``).
    invalidos: int
    #: Hechos sin ninguna cita literal en el pliego (``_validate_fact_evidence``).
    inverificables: int
    #: Las páginas que vio el modelo, en orden de documento y página.
    seleccionadas: list[dict[str, Any]]


def _extraer_de_seleccion(
    pages: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    *,
    licitacion_id: str,
    model: str,
) -> ExtraccionHechos:
    """De las páginas seleccionadas a hechos con cita validada. Sin persistencia."""
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
    raw = "".join(
        stream_llm_response(
            question=_EXTRACTION_QUESTION,
            docs=docs,
            model=model,
            keywords=list(_TOPIC_TERMS),
            mode="extraction",
            max_tokens=_MAX_OUTPUT_TOKENS,
            # Sin fallback de proveedor: la fila persiste `model`, y un
            # cambio silencioso de modelo la haría mentir sobre quién
            # extrajo. Si el proveedor está caído, la extracción falla
            # visible y el cron/botón reintentan.
            fallback=False,
        )
    )
    if not raw.strip():
        # El cliente devuelve stream vacío cuando el proveedor falló en
        # todos sus reintentos (saturación, 5xx). Dicho así, y no como «no
        # devolvió un objeto JSON», que mandaba a revisar el prompt.
        raise ValueError(
            f"El modelo {model} devolvió una respuesta vacía "
            "(proveedor saturado o caído); se reintentará en el próximo lote."
        )
    facts, invalid = _parse_facts(extract_json_object(raw))
    # Contra todas las páginas, no solo las seleccionadas: una cita que el
    # modelo atribuye a la página contigua se corrige si el texto está allí.
    facts, unverifiable = _validate_fact_evidence(facts, pages)
    return ExtraccionHechos(
        facts=facts,
        invalidos=invalid,
        inverificables=unverifiable,
        seleccionadas=selected,
    )


def extraer_hechos(
    pages: list[dict[str, Any]],
    *,
    licitacion_id: str,
    model: str = DEFAULT_MODEL,
) -> ExtraccionHechos:
    """Extrae los hechos de un pliego a partir de sus páginas, sin base de datos.

    Es el mismo camino que ``extract_fact_sheet`` —selector, pregunta, modelo y
    validación de citas— sin leer ni escribir nada: lo que ejecuta el eval de
    la ficha (``scripts/eval_ficha.py``) sobre los casos del golden, para medir
    producción y no una copia.
    """
    selected = _select_pages(pages)
    if not selected:
        raise ValueError(_SIN_TEXTO)
    return _extraer_de_seleccion(pages, selected, licitacion_id=licitacion_id, model=model)


def extract_fact_sheet(
    licitacion_id: str,
    *,
    model: str = DEFAULT_MODEL,
) -> TenderFactSheetRecord:
    """Extrae, valida citas y persiste la ficha vigente de una licitación."""
    documentos = DocumentosRepository()
    sheets = TenderFactSheetsRepository()
    pages = documentos.list_pages_by_licitacion(licitacion_id)
    # Fuera del `try` a propósito: un expediente sin páginas no es una
    # extracción fallida y no debe dejar una fila `failed`.
    selected = _select_pages(pages)
    if not selected:
        raise ValueError(_SIN_TEXTO)

    try:
        extraccion = _extraer_de_seleccion(
            pages, selected, licitacion_id=licitacion_id, model=model
        )
        facts = extraccion.facts
        rejected = extraccion.invalidos + extraccion.inverificables
        if rejected:
            log.info(
                "fact_sheet_items_rejected",
                licitacion_id=licitacion_id,
                invalid=extraccion.invalidos,
                unverifiable=extraccion.inverificables,
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
    """Lee la ficha vigente sin invocar al proveedor LLM.

    La de una republicación confirmada es la de su canónica
    (:func:`services.dedupe.expediente_del_pliego`), y el registro lo dice: su
    ``licitacion_id`` es el del expediente del que salen los pliegos.
    """
    from services.dedupe import expediente_del_pliego

    row = TenderFactSheetsRepository().get(expediente_del_pliego(licitacion_id))
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

    El ``failed`` se guarda en la ficha que se lee después: la de la canónica
    si la licitación es una republicación (:class:`SinPaginasError` dice cuál
    se miró). Guardarlo en la del anuncio TED lo dejaría en una fila que
    ``get_fact_sheet`` nunca consulta.
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
            destino = exc.licitacion_id if isinstance(exc, SinPaginasError) else licitacion_id
            try:
                TenderFactSheetsRepository().upsert(
                    licitacion_id=destino,
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
