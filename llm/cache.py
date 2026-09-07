"""Caché de respuestas del LLM (C5.5).

Qué corrige
-----------
``/resumen`` cachea desde hace tiempo; ``/ask`` no. Dos personas del mismo
equipo preguntando lo mismo sobre el mismo expediente —el caso normal el día que
sale una licitación que les interesa— pagaban dos veces, y la segunda esperaba
los mismos segundos que la primera. El presupuesto de LLM (``llm/budget.py``) es
por organización desde C2.9, así que ese gasto duplicado sale del mismo cubo.

La clave
--------
``modo | modelo | versión de prompt | hash del contexto``.

- **Modo y modelo** cambian la respuesta por sí solos.
- **Versión de prompt**: :data:`llm.prompts.PROMPT_VERSION`, que es un hash del
  contenido de los system prompts. No es un entero que alguien tenga que
  acordarse de subir: editar un prompt invalida la caché sola. Un contador
  manual sirve exactamente hasta el primer PR que lo olvida, y entonces la
  caché devuelve respuestas de un prompt que ya no existe.
- **Hash del contexto**: la pregunta, el historial y la **identidad** de los
  documentos de contexto, no su texto entero. Si el corpus cambia, cambian los
  ids o el estado de los documentos, y con ellos la clave.

Qué NO entra en la clave, a propósito: el usuario. Las licitaciones son
información pública y el contexto se construye sólo con ellas, así que dos
personas con la misma pregunta deben poder compartir respuesta — que es
justamente de dónde sale el ahorro. Si algún día el contexto incluyera dato
privado (notas de equipo, ficha propia), esta decisión hay que rehacerla: el
sitio es esta función, y por eso el aviso está aquí y no en un ADR aparte.

Qué no se cachea
----------------
Las respuestas degradadas. Un stream vacío, un timeout o un error del proveedor
no dejan entrada: cachear un fallo lo convierte en permanente durante 24 h, y el
usuario no tendría forma de distinguir «el proveedor está caído» de «la
respuesta a esta pregunta es un error».
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from observability.logging import get_logger
from observability.runtime_metrics import llm_cache_hit_total, llm_cache_miss_total

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

log = get_logger(__name__)

#: 24 h. Las respuestas dependen del expediente y de sus pliegos, que cambian de
#: estado en horas, no en minutos: un TTL más corto no compraría frescura real y
#: sí perdería la mayoría de los aciertos.
TTL_SEGUNDOS = 24 * 60 * 60

#: Espacio de nombres en ``shared/cache.py``. Separado del de ``/resumen``
#: (``llm_resumen``) para que invalidar uno no vacíe el otro.
NAMESPACE = "llm_ask"

#: Campos de un documento de contexto que identifican su estado. El texto no
#: entra: es grande y redundante — si cambia, cambia alguno de estos.
_CAMPOS_IDENTIDAD = ("id_externo", "id", "status", "fecha_actualizacion_fuente")


def _identidad_docs(docs: list[dict[str, Any]]) -> list[Any]:
    """Huella de los documentos de contexto: qué son, no qué dicen."""
    return [
        [d.get(campo) for campo in _CAMPOS_IDENTIDAD]
        + [len(d.get("chunks") or []), [c.get("documento_id") for c in (d.get("chunks") or [])]]
        for d in docs
    ]


def clave(
    *,
    modo: str,
    modelo: str,
    pregunta: str,
    docs: list[dict[str, Any]],
    # `Mapping[str, Any]` y no `[str, str]`: el historial llega como
    # `llm.prompts.ChatMessage`, un TypedDict, y mypy los ve como
    # `Mapping[str, object]`.
    historial: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """Clave estable para una respuesta del LLM."""
    from llm.prompts import PROMPT_VERSION

    payload = {
        "modo": modo,
        "modelo": modelo,
        "prompt": PROMPT_VERSION,
        "pregunta": pregunta.strip(),
        "docs": _identidad_docs(docs),
        "historial": [[m.get("role"), m.get("content")] for m in (historial or [])],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    return f"ask|{modo}|{digest}"


def leer(clave_cache: str, *, modo: str) -> str | None:
    """Texto cacheado, o ``None``. Nunca lanza: la caché no puede tumbar ``/ask``."""
    from shared.cache import get_cache

    try:
        crudo = get_cache(NAMESPACE).get(clave_cache)
    except Exception:
        log.debug("llm_cache_get_failed", exc_info=True)
        crudo = None
    if isinstance(crudo, str) and crudo.strip():
        llm_cache_hit_total.labels(mode=modo).inc()
        return crudo
    llm_cache_miss_total.labels(mode=modo).inc()
    return None


def guardar(clave_cache: str, texto: str) -> None:
    """Guarda una respuesta **completa y no vacía**. Best-effort."""
    if not texto.strip():
        return
    from shared.cache import get_cache

    try:
        get_cache(NAMESPACE).set(clave_cache, texto, ttl=TTL_SEGUNDOS)
    except Exception:
        log.debug("llm_cache_set_failed", exc_info=True)
