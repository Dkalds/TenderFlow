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

Cada etiqueta tiene que venir con una cita (``evidencia``) que aparezca en el
texto que el modelo recibió (``texto_enviado``); la que no la trae se descarta
(ver ``parse_labels``). Si el modelo afirmó tecnologías y ninguna sostuvo su
cita, el job no guarda «sin tecnología» sino ``SIN_EVIDENCIA_SENTINEL``.

Aquí no hay I/O de base de datos: el job (``scheduler/jobs/llm_tech_labeling``)
orquesta lectura y escritura. ``parse_labels`` y ``build_question`` son puras y
se testean sin Postgres ni red.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from pydantic import BaseModel, Field, ValidationError

from config.keywords import TECH_DEFINICIONES, TECH_LABELS
from db.repositories.tecnologia_pliego import TechSignal
from llm.client import stream_llm_response
from llm.json_utils import extract_json_object
from llm.prompts import PromptMode, build_context_block, context_chars_for, excerpt_chars_for
from observability.logging import get_logger
from services.normalization import fold_text

log = get_logger(__name__)


class _LlmTechLabel(BaseModel):
    """Una tecnología tal como la devuelve el LLM (antes de validar vocabulario)."""

    tecnologia: str
    confidence: float = Field(ge=0.0, le=1.0)
    # ``None`` se admite y cuenta como cita vacía: descarta esa etiqueta, no
    # toda la respuesta.
    evidencia: str | None = ""


class _LlmTechResponse(BaseModel):
    """Envoltorio de la respuesta; sin tecnologías es una respuesta válida."""

    tecnologias: list[_LlmTechLabel] = []


class Clasificacion(NamedTuple):
    """Lo que queda de una respuesta del LLM tras validarla.

    Attributes:
        scores: Etiquetas del vocabulario, sobre el mínimo de confianza y con
            una cita que aparece en el texto enviado. Listas para persistir.
        sin_evidencia: Etiquetas que el modelo afirmó (vocabulario y confianza
            válidos) y se descartaron porque su cita estaba vacía o no aparece
            en ese texto, sin que otra entrada con cita válida las recuperase.
    """

    scores: dict[str, TechSignal]
    sin_evidencia: tuple[str, ...] = ()


# ``method`` de la señal y versión del prompt. La ``signal_version`` incluye el
# modelo: cambiar de modelo (o bumpear PROMPT_VERSION) deja pendiente de nuevo
# a todo el universo, que es justo lo que se quiere para reprocesar.
#
# v2 (2026-09-27): definición por etiqueta y cita literal verificada contra el
# anuncio. Hasta que una licitación se reclasifica, su respuesta v1 sigue siendo
# la vigente para el entrenamiento; al reclasificarla, ``upsert_signals``
# sustituye las filas v1 de este method.
METHOD = "llm_metadata"
PROMPT_VERSION = "v2"

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

# Modo del prompt. Una sola constante para la llamada y para ``texto_enviado``:
# la cita se verifica contra el bloque que ese modo construye, y si divergieran
# se compararía contra un texto que el modelo no vio.
_MODE: PromptMode = "clasificacion"

_QUESTION_TEMPLATE = """
Clasifica esta licitación por tecnología con un vocabulario cerrado. Cada etiqueta significa lo que dice su definición, no lo que sugiere su nombre:
{definiciones}
Reglas:
- Un fabricante exige que el anuncio lo nombre a él o a uno de sus productos; una categoría describe qué se compra sin decir de quién.
- El trabajo TI genérico sin fabricante (p. ej. el mantenimiento de una aplicación a medida) lleva la categoría cuya definición lo cubre aunque su nombre no lo sugiera: ahí, DESARROLLO. Si ninguna definición lo cubre, no fuerces la más parecida.
- evidencia es una cita literal del anuncio, copiada tal cual y sin puntos suspensivos, que justifica la etiqueta. Se comprueba contra el anuncio: una etiqueta sin cita que aparezca en él se descarta.
Formato de salida (JSON, sin Markdown):
{{"tecnologias": [{{"tecnologia": "<ETIQUETA>", "confidence": 0.0-1.0, "evidencia": "<cita literal del anuncio>"}}]}}
Si el anuncio no corresponde a ninguna etiqueta, devuelve {{"tecnologias": []}}.
""".strip()

# Variantes tipográficas que un modelo reescribe al citar: comillas y
# apóstrofos curvos (y el acento agudo que se teclea como apóstrofo) y guiones.
# Van a su forma ASCII antes del plegado NFKD, que no las toca -- y que al acento
# suelto lo convertiría en un espacio. En escapes y no en literal: los glifos se
# confunden entre sí a simple vista.
_PUNTUACION_TIPOGRAFICA = str.maketrans(
    {
        "\u201c": '"',  # comilla doble de apertura
        "\u201d": '"',  # comilla doble de cierre
        "\u201e": '"',  # comilla doble baja
        "\u201f": '"',  # comilla doble alta invertida
        "\u00ab": '"',  # comilla angular de apertura
        "\u00bb": '"',  # comilla angular de cierre
        "\u2018": "'",  # comilla simple de apertura
        "\u2019": "'",  # comilla simple de cierre / apóstrofo tipográfico
        "\u201a": "'",  # comilla simple baja
        "\u201b": "'",  # comilla simple alta invertida
        "\u00b4": "'",  # acento agudo suelto
        "\u0060": "'",  # acento grave suelto
        "\u2010": "-",  # guion
        "\u2011": "-",  # guion sin salto
        "\u2012": "-",  # guion de cifras
        "\u2013": "-",  # raya corta (en dash)
        "\u2014": "-",  # raya (em dash)
        "\u2015": "-",  # barra horizontal
        "\u2212": "-",  # signo menos
    }
)

# Lo que un modelo suele añadir alrededor de la cita sin que forme parte de
# ella: comillas envolventes y la puntuación con la que cierra la frase.
_BORDES_DE_CITA = " \"'.,;:"


def signal_version(model: str) -> str:
    """Versión de la señal: prompt + modelo que la produjo."""
    return f"llm-meta-{PROMPT_VERSION}/{model}"


def build_question() -> str:
    """Instrucción + vocabulario cerrado con su definición + esquema de salida.

    El vocabulario viaja aquí y no en el system prompt para que
    ``llm/prompts.py`` siga sin depender de ``config``. Cada etiqueta va con su
    definición (``config.keywords.TECH_DEFINICIONES``): con el nombre solo, el
    modelo decide por lo que el nombre sugiere y no por lo que la taxonomía
    cubre. Con las definiciones la pregunta pasa de los 2000 caracteres de
    /ask, pero el modo ``clasificacion`` es plantilla interna y
    ``llm.client._validate_request`` le aplica ``MAX_INTERNAL_QUESTION_LEN``.
    """
    definiciones = "\n".join(f"- {label}: {TECH_DEFINICIONES[label]}" for label in TECH_LABELS)
    return _QUESTION_TEMPLATE.format(definiciones=definiciones)


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


def texto_enviado(docs: list[dict[str, Any]]) -> str:
    """El bloque de contexto tal cual lo recibe el modelo.

    Es la misma función, con el mismo presupuesto y el mismo extracto, que
    ``llm.prompts.build_messages`` aplica al modo de la llamada (sin keywords,
    como ``classify_licitacion``): la cita se verifica contra lo que el modelo
    leyó, recortes y neutralización de delimitadores incluidos. No incluye la
    pregunta: una cita copiada de las definiciones no es evidencia del anuncio.
    """
    return build_context_block(
        docs, [], max_chars=context_chars_for(_MODE), excerpt_chars=excerpt_chars_for(_MODE)
    )


def normalizar_cita(texto: str) -> str:
    """Forma canónica para comparar una cita con el texto del que sale.

    Comillas, apóstrofos y guiones tipográficos a su forma ASCII, tildes fuera
    (NFKD sin marcas combinantes), minúsculas y el espacio en blanco colapsado:
    lo que un modelo reescribe al citar sin que la cita deje de ser literal.
    """
    return " ".join(fold_text(texto.translate(_PUNTUACION_TIPOGRAFICA)).split())


def cita_verificable(cita: str, texto_normalizado: str) -> bool:
    """¿Aparece ``cita`` en el texto ya pasado por :func:`normalizar_cita`?

    Sin las comillas y la puntuación de cierre que el modelo añade alrededor.
    Una cita sin ningún carácter alfanumérico no prueba nada, aunque aparezca.
    """
    aguja = normalizar_cita(cita).strip(_BORDES_DE_CITA)
    if not any(ch.isalnum() for ch in aguja):
        return False
    return aguja in texto_normalizado


def parse_labels(raw: str, *, texto: str, licitacion_id: str = "") -> Clasificacion:
    """Valida la respuesta del LLM y la convierte en señales persistibles.

    Vocabulario cerrado: una etiqueta que no esté en ``TECH_LABELS`` se
    descarta con log y no invalida el resto de la respuesta (mismo criterio
    que ``tech_signal.ingest_llm_technologies`` con las menciones que no
    mapean). Un JSON inválido sí lanza: el job lo cuenta como error y la
    licitación queda pendiente para la siguiente corrida.

    Evidencia: ``texto`` es lo que el modelo recibió (:func:`texto_enviado`).
    Una etiqueta cuya ``evidencia`` está vacía o no aparece en él
    (:func:`cita_verificable`) se descarta con log y se devuelve en
    ``sin_evidencia``. La comprobación va antes de quedarse con la entrada de
    más confianza de cada etiqueta: si el modelo la repite, basta con que una
    de sus citas se sostenga. Las etiquetas por debajo de ``_MIN_PERSIST_CONF``
    son ruido y no cuentan como descartadas por falta de cita.
    """
    payload = extract_json_object(raw)
    try:
        parsed = _LlmTechResponse.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Respuesta de clasificación inválida: {exc}") from exc

    texto_normalizado = normalizar_cita(texto)
    scores: dict[str, TechSignal] = {}
    descartadas: list[str] = []
    for label in parsed.tecnologias:
        tech = label.tecnologia.strip().upper()
        if tech not in TECH_LABELS:
            log.info("llm_tech_label_unmapped", tecnologia=label.tecnologia)
            continue
        if label.confidence < _MIN_PERSIST_CONF:
            continue
        cita = label.evidencia or ""
        if not cita_verificable(cita, texto_normalizado):
            log.info(
                "llm_tech_label_sin_evidencia",
                licitacion_id=licitacion_id,
                tecnologia=tech,
                evidencia=cita[:200],
            )
            descartadas.append(tech)
            continue
        evidence = [{"quote": cita[:500], "source": "metadata"}]
        existing = scores.get(tech)
        if existing is None or label.confidence > existing.score:
            scores[tech] = TechSignal(score=round(label.confidence, 4), evidence=evidence)
    sin_evidencia = tuple(t for t in dict.fromkeys(descartadas) if t not in scores)
    return Clasificacion(scores=scores, sin_evidencia=sin_evidencia)


def classify_licitacion(lic: dict[str, Any], *, model: str) -> Clasificacion:
    """Clasifica una licitación. Lanza si el LLM no devuelve nada usable.

    Una respuesta vacía no es "sin tecnologías": es el síntoma de que falta
    ``NVIDIA_API_KEY`` o de que el provider abortó -- ``openai_provider.stream``
    loguea y devuelve sin emitir nada. Convertirla en excepción evita persistir
    el sentinel "ya procesada" sobre una licitación que nunca se clasificó.

    Las citas se verifican contra :func:`texto_enviado` de los mismos ``docs``
    que viajan en la llamada.
    """
    docs = build_docs(lic)
    raw = "".join(
        stream_llm_response(
            question=build_question(),
            docs=docs,
            model=model,
            keywords=[],
            mode=_MODE,
            max_tokens=_MAX_OUTPUT_TOKENS,
            # Sin fallback de proveedor: ``signal_version`` incluye el modelo y
            # gobierna qué se reprocesa; responder con otro modelo dejaría la
            # señal atribuida al equivocado. Mejor fallar y reintentar mañana.
            fallback=False,
        )
    )
    if not raw.strip():
        raise RuntimeError("El LLM devolvió una respuesta vacía")
    return parse_labels(
        raw, texto=texto_enviado(docs), licitacion_id=str(lic.get("id_externo") or "")
    )
