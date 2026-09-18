"""Resumen IA de una licitación: contexto, clave de caché y pre-generación.

Lo comparten dos llamadores que tienen que coincidir byte a byte:

- ``POST /licitaciones/{id}/resumen`` (``api/routes/ask.py``), que lo sirve en
  streaming y lo cachea al terminar.
- La fase de pre-generación del job nocturno de pliegos
  (``scheduler/jobs/documentos_embeddings.py``), que calienta ese mismo caché
  para las licitaciones que se van a abrir.

Si la clave, el prompt o el contexto se calcularan en dos sitios, bastaría con
que divergieran en un campo para que el job pagara resúmenes que la API nunca
encuentra. Por eso viven aquí y la ruta los importa.

Las importaciones de ``services.rag.context``, ``services.rag.fact_sheet`` y
``llm.client`` son tardías a propósito: los tests de la ruta parchean esos
módulos por su nombre, y una importación a nivel de módulo congelaría la
referencia antes del parche.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Literal

from observability.logging import get_logger

if TYPE_CHECKING:
    from services.rag.context import LicitacionContext

log = get_logger(__name__)

RESUMEN_QUESTION = "Genera el resumen estructurado de esta licitación."
RESUMEN_MAX_TOKENS = 1500

#: Namespace de ``shared.cache`` donde vive el resumen.
RESUMEN_CACHE_NAMESPACE = "llm_resumen"

# Caché del resumen: mismo expediente + mismos documentos + misma ficha →
# mismo texto, sin pagar otra llamada LLM ni la espera del streaming. La clave
# incorpora una firma del estado (metadatos del anuncio, status de cada
# documento, extracted_at de la ficha), así que un pliego recién procesado o
# una ficha nueva invalidan solos; el TTL solo acota el caso residual.
# ``RESUMEN_CACHE_VERSION`` se bumpea al cambiar el prompt o el contexto.
RESUMEN_CACHE_TTL_SECONDS = 7 * 24 * 3600
RESUMEN_CACHE_VERSION = "resumen-v2"

ResultadoPregeneracion = Literal["generado", "vigente", "no_encontrada", "vacio"]


def resumen_cache_key(
    id_externo: str,
    model: str,
    doc: dict[str, Any],
    documentos: list[dict[str, Any]],
    ficha_extracted_at: str | None,
) -> str:
    """Clave de caché del resumen: expediente + modelo + firma de estado.

    La firma cubre lo que puede cambiar el resumen sin que cambie el id: los
    metadatos del anuncio (importe, estado, fechas…), el ciclo de vida de cada
    documento (un pliego que pasa a ``extracted`` cambia el contexto) y la
    ficha verificada vigente.
    """
    from llm.prompts import prompt_version

    payload = {
        "v": RESUMEN_CACHE_VERSION,
        # C5.5: el hash del system prompt vigente. `RESUMEN_CACHE_VERSION` se
        # sube a mano y por eso puede olvidarse; esto no.
        "prompt": prompt_version("resumen"),
        "id": id_externo,
        "model": model,
        "doc": {k: v for k, v in doc.items() if k not in ("chunks", "_score")},
        "documentos": [
            (d.get("id"), d.get("status"), str(d.get("created_at"))) for d in documentos
        ],
        "ficha": ficha_extracted_at,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    return f"resumen|{digest}"


def cargar_contexto_resumen(
    id_externo: str,
) -> tuple[LicitacionContext, dict[str, Any], str | None] | None:
    """Contexto + documento principal + ``extracted_at`` de la ficha (van a BD).

    ``None`` si la licitación no existe. Si hay ficha verificada vigente, sus
    hechos entran como primer chunk etiquetado: son los únicos datos del sistema
    validados con cita, y el system prompt de modo ``resumen`` les da prioridad
    en la sección de requisitos. Su ``extracted_at`` forma parte de la firma de
    caché.
    """
    from services.rag.context import build_licitacion_context, primary_doc_from_context

    loaded = build_licitacion_context(id_externo, None)
    if loaded is None:
        return None
    doc = primary_doc_from_context(id_externo, loaded)
    ficha_at: str | None = None
    try:
        from services.rag.fact_sheet import facts_summary_text, get_fact_sheet

        ficha = get_fact_sheet(id_externo)
        if (
            ficha is not None
            and ficha.facts is not None
            and ficha.status in ("extracted", "needs_review")
        ):
            texto = facts_summary_text(ficha.facts)
            if texto:
                doc["chunks"] = [
                    {"tipo": "ficha estructurada verificada", "texto": texto},
                    *doc["chunks"],
                ]
                ficha_at = ficha.extracted_at
    except Exception as exc:
        # La ficha es un refuerzo del contexto, nunca un bloqueo del resumen.
        log.warning("resumen.fact_sheet_context_failed", id_externo=id_externo, error=str(exc))
    return loaded, doc, ficha_at


def pregenerar_resumen(id_externo: str, *, model: str) -> ResultadoPregeneracion:
    """Genera y cachea el resumen si no hay ya una entrada vigente.

    Mismo contexto, misma clave y mismo prompt que la ruta: lo que se escribe
    aquí es exactamente lo que la ruta leerá como ``cached``. «Vigente» es que
    la clave —que ya lleva la firma de estado— tenga entrada: un pliego nuevo o
    una ficha re-extraída cambian la clave y el resumen viejo deja de contar.

    No comprueba el presupuesto: eso lo hace quien itera, que es quien puede
    decidir cortar el lote entero en vez de fallar una licitación.
    """
    from llm.client import stream_llm_response
    from shared.cache import get_cache

    cargado = cargar_contexto_resumen(id_externo)
    if cargado is None:
        return "no_encontrada"
    ctx, doc, ficha_at = cargado

    cache = get_cache(RESUMEN_CACHE_NAMESPACE)
    clave = resumen_cache_key(id_externo, model, doc, ctx["documentos"], ficha_at)
    existente = cache.get(clave)
    if isinstance(existente, str) and existente.strip():
        return "vigente"

    texto = "".join(
        stream_llm_response(
            question=RESUMEN_QUESTION,
            docs=[doc],
            model=model,
            keywords=[],
            mode="resumen",
            max_tokens=RESUMEN_MAX_TOKENS,
        )
    ).strip()
    if not texto:
        # Proveedor sin key o respuesta vacía: no se cachea, igual que en la ruta.
        return "vacio"
    cache.set(clave, texto, ttl=RESUMEN_CACHE_TTL_SECONDS)
    return "generado"
