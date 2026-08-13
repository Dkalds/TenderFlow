"""Etiquetado de tecnología por LLM sobre la metadata del anuncio.

Categorizar a mano la cola de active learning es inviable por volumen, y el
`TechnologyClassifier` solo aprende de las labels "silver" de keywords. Este
módulo añade una tercera fuente: un LLM que lee el anuncio (título,
descripción, CPV, órgano, importe) y devuelve las tecnologías con su
confianza, sin necesitar los pliegos -- que solo existen para una minoría de
licitaciones y caducan (los enlaces de PLACSP mueren).

La señal se persiste con ``method="llm_metadata"`` en
``licitacion_tecnologia_pliego`` y llega a ``licitaciones.ml_tecnologias`` por
el merge ya existente (``services/tech_signal.py::merge_doc_signals``), que es
aditivo: nunca borra la señal de título/keywords, solo añade.

``method`` propio y no ``"llm"`` a propósito: ``upsert_signals`` borra las
filas del mismo ``method`` que la corrida en curso ya no detecta, así que
compartirlo con la señal LLM de las fichas de pliego
(``tech_signal.ingest_llm_technologies``) haría que cada carril machacase al
otro.

Aquí no hay I/O de base de datos: el job (``scheduler/jobs/llm_tech_labeling``)
orquesta lectura y escritura. ``parse_labels`` y ``build_question`` son puras y
se testean sin Postgres ni red.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from config.keywords import TECH_LABELS
from db.repositories.tecnologia_pliego import TechSignal
from llm.client import stream_llm_response
from llm.json_utils import extract_json_object
from observability.logging import get_logger

log = get_logger(__name__)


class _LlmTechLabel(BaseModel):
    """Una tecnología tal como la devuelve el LLM (antes de validar vocabulario)."""

    tecnologia: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidencia: str = ""


class _LlmTechResponse(BaseModel):
    """Envoltorio de la respuesta; sin tecnologías es una respuesta válida."""

    tecnologias: list[_LlmTechLabel] = []


# ``method`` de la señal y versión del prompt. La ``signal_version`` incluye el
# modelo: cambiar de modelo (o bumpear PROMPT_VERSION) deja pendiente de nuevo
# a todo el universo, que es justo lo que se quiere para reprocesar.
METHOD = "llm_metadata"
PROMPT_VERSION = "v1"

# Por debajo de esta confianza la etiqueta es ruido y no se persiste. No se
# confunde con ``PLIEGO_TECH_MIN_SCORE`` (0.5), que decide qué entra al merge:
# entre ambos umbrales la señal queda registrada para trazabilidad y para el
# endpoint de detalle, pero no altera ``ml_tecnologias``.
_MIN_PERSIST_CONF = 0.2

# La descripción se manda entera hasta este corte. El presupuesto de contexto
# del modo (``MAX_CONTEXT_CHARS_GENERAL`` = 8k) es el tope real; esto solo
# evita mandar un anuncio kilométrico y pagarlo en tokens.
_MAX_DESC_CHARS = 3_000

_MAX_OUTPUT_TOKENS = 500

_QUESTION_TEMPLATE = """
Clasifica esta licitación por tecnología. Etiquetas permitidas (vocabulario cerrado):
{labels}
Formato de salida (JSON, sin Markdown):
{{"tecnologias": [{{"tecnologia": "<ETIQUETA>", "confidence": 0.0-1.0, "evidencia": "<cita breve del anuncio>"}}]}}
Si el anuncio no corresponde a ninguna etiqueta, devuelve {{"tecnologias": []}}.
""".strip()


def signal_version(model: str) -> str:
    """Versión de la señal: prompt + modelo que la produjo."""
    return f"llm-meta-{PROMPT_VERSION}/{model}"


def build_question() -> str:
    """Instrucción + vocabulario cerrado + esquema de salida.

    El vocabulario viaja aquí y no en el system prompt para que
    ``llm/prompts.py`` siga sin depender de ``config``. Cabe de sobra en el
    límite de 2000 chars que impone ``llm.client._validate_request``: son 11
    etiquetas cortas.
    """
    return _QUESTION_TEMPLATE.format(labels=", ".join(TECH_LABELS))


def build_docs(lic: dict[str, Any]) -> list[dict[str, Any]]:
    """Monta el único "doc" de contexto a partir de la fila de ``licitaciones``.

    La descripción va como *chunk* y no en el campo ``descripcion`` porque
    ``llm.prompts._doc_block`` recorta ese campo a un extracto de 300 chars
    centrado en keywords -- suficiente para chatear sobre un expediente,
    insuficiente para clasificarlo. Los chunks se copian íntegros y además
    pasan por la neutralización anti-inyección de delimitadores del sandbox.
    """
    descripcion = str(lic.get("descripcion") or "")[:_MAX_DESC_CHARS]
    return [
        {
            "id_externo": lic.get("id_externo", ""),
            "titulo": lic.get("titulo") or "",
            "organo_contratacion": lic.get("organo_contratacion"),
            "importe": lic.get("importe"),
            "estado": lic.get("estado"),
            "cpv": lic.get("cpv"),
            "fecha_publicacion": lic.get("fecha_publicacion"),
            # Vacío a propósito: el texto real va como chunk (ver docstring).
            "descripcion": "",
            "chunks": [{"tipo": "descripcion del anuncio", "texto": descripcion}],
        }
    ]


def parse_labels(raw: str) -> dict[str, TechSignal]:
    """Valida la respuesta del LLM y la convierte en señales persistibles.

    Vocabulario cerrado: una etiqueta que no esté en ``TECH_LABELS`` se
    descarta con log y no invalida el resto de la respuesta (mismo criterio
    que ``tech_signal.ingest_llm_technologies`` con las menciones que no
    mapean). Un JSON inválido sí lanza: el job lo cuenta como error y la
    licitación queda pendiente para la siguiente corrida.
    """
    payload = extract_json_object(raw)
    try:
        parsed = _LlmTechResponse.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Respuesta de clasificación inválida: {exc}") from exc

    scores: dict[str, TechSignal] = {}
    for label in parsed.tecnologias:
        tech = label.tecnologia.strip().upper()
        if tech not in TECH_LABELS:
            log.info("llm_tech_label_unmapped", tecnologia=label.tecnologia)
            continue
        if label.confidence < _MIN_PERSIST_CONF:
            continue
        evidence = [{"quote": label.evidencia[:500], "source": "metadata"}]
        existing = scores.get(tech)
        if existing is None or label.confidence > existing.score:
            scores[tech] = TechSignal(score=round(label.confidence, 4), evidence=evidence)
    return scores


def classify_licitacion(lic: dict[str, Any], *, model: str) -> dict[str, TechSignal]:
    """Clasifica una licitación. Lanza si el LLM no devuelve nada usable.

    Una respuesta vacía no es "sin tecnologías": es el síntoma de que falta
    ``NVIDIA_API_KEY`` o de que el provider abortó -- ``openai_provider.stream``
    loguea y devuelve sin emitir nada. Convertirla en excepción evita persistir
    el sentinel "ya procesada" sobre una licitación que nunca se clasificó.
    """
    raw = "".join(
        stream_llm_response(
            question=build_question(),
            docs=build_docs(lic),
            model=model,
            keywords=[],
            mode="clasificacion",
            max_tokens=_MAX_OUTPUT_TOKENS,
        )
    )
    if not raw.strip():
        raise RuntimeError("El LLM devolvió una respuesta vacía")
    return parse_labels(raw)
