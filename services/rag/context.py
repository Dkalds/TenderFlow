"""Contexto de una licitación para el LLM (resumen y chat contextualizado).

Arma el contexto que ``/api/v1/ask`` (con ``id_externo``) y
``/api/v1/licitaciones/{id}/resumen`` inyectan como documento primario:
metadatos del anuncio + fragmentos de pliego seleccionados con presupuesto
de caracteres.

El ranking semántico frente a la pregunta corre en Python vía
``services.embeddings.smart_match`` (embeddings MiniLM si están instalados,
substring si no): un solo camino que funciona igual en Postgres y SQLite —
el embedding persistido en ``documento_chunks`` no se consulta aquí.
"""

from __future__ import annotations

from typing import Any, TypedDict

from db.repositories.documentos import DocumentosRepository
from observability.logging import get_logger

log = get_logger(__name__)

MAX_PLIEGO_CONTEXT_CHARS = 12_000
MAX_SELECTED_CHUNKS = 8
MAX_CANDIDATE_CHUNKS = 120
_RANK_THRESHOLD = 0.25


class LicitacionContext(TypedDict):
    """Contexto completo de una licitación para consumo del LLM."""

    detail: dict[str, Any]
    documentos: list[dict[str, Any]]
    chunks: list[dict[str, Any]]
    has_pliego_text: bool
    truncated: bool


def _chunks_from_textos(repo: DocumentosRepository, licitacion_id: str) -> list[dict[str, Any]]:
    """Fallback: chunkea al vuelo documentos extraídos que el job aún no procesó."""
    from services.rag.chunking import chunk_text

    out: list[dict[str, Any]] = []
    for doc in repo.list_textos_by_licitacion(licitacion_id):
        for i, texto in enumerate(chunk_text(str(doc.get("texto") or ""))):
            out.append(
                {
                    "documento_id": doc["id"],
                    "tipo": doc.get("tipo"),
                    "filename": doc.get("filename"),
                    "chunk_index": i,
                    "texto": texto,
                }
            )
            if len(out) >= MAX_CANDIDATE_CHUNKS:
                return out
    return out


def _rank_by_question(question: str, candidates: list[dict[str, Any]]) -> list[int]:
    """Índices de candidatos ordenados por relevancia; orden documental de relleno."""
    from services.embeddings import smart_match

    corpus = [str(c.get("texto") or "") for c in candidates]
    try:
        matches = smart_match(question, corpus, threshold=_RANK_THRESHOLD)
    except Exception:
        log.warning("rag_context.rank_failed", exc_info=True)
        matches = []
    ranked = [i for i, _score in matches]
    seen = set(ranked)
    return ranked + [i for i in range(len(candidates)) if i not in seen]


def _select_chunks(
    candidates: list[dict[str, Any]],
    question: str | None,
    *,
    max_chars: int,
    max_chunks: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Selecciona chunks hasta agotar presupuesto. Devuelve (selección, truncado)."""
    usable = [c for c in candidates if str(c.get("texto") or "").strip()]
    if not usable:
        return [], False

    order = _rank_by_question(question, usable) if question else list(range(len(usable)))

    selected: list[dict[str, Any]] = []
    used = 0
    for idx in order:
        chunk = usable[idx]
        size = len(str(chunk["texto"]))
        if len(selected) >= max_chunks or used + size > max_chars:
            break
        selected.append(chunk)
        used += size

    if question:
        # El ranking decide QUÉ entra; el orden documental hace el contexto legible.
        selected.sort(key=lambda c: (c.get("documento_id") or 0, c.get("chunk_index") or 0))
    return selected, len(selected) < len(usable)


def build_licitacion_context(
    id_externo: str,
    question: str | None,
    *,
    max_chars: int = MAX_PLIEGO_CONTEXT_CHARS,
    max_chunks: int = MAX_SELECTED_CHUNKS,
) -> LicitacionContext | None:
    """Contexto de la licitación ``id_externo`` para el LLM.

    Args:
        id_externo: ID externo de la licitación.
        question: Pregunta del usuario — activa el ranking semántico de chunks.
            ``None`` (modo resumen) usa orden documental: los primeros chunks de
            cada pliego, que suelen contener objeto y criterios.
        max_chars: Presupuesto de caracteres para los chunks seleccionados.
        max_chunks: Máximo de chunks seleccionados.

    Returns:
        ``None`` si la licitación no existe; si existe, el contexto con
        ``has_pliego_text=False`` cuando no hay texto de pliegos disponible.
    """
    from services.licitaciones import get_licitacion_detail

    detail = get_licitacion_detail(id_externo)
    if detail is None:
        return None

    repo = DocumentosRepository()
    documentos: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    try:
        documentos = repo.list_by_licitacion(id_externo)
        candidates = repo.list_chunks_by_licitacion(id_externo, limit=MAX_CANDIDATE_CHUNKS)
        if not candidates:
            candidates = _chunks_from_textos(repo, id_externo)
    except Exception:
        # Sin documentos no se bloquea la respuesta: se degrada a solo metadatos.
        log.warning("rag_context.documentos_failed", id_externo=id_externo, exc_info=True)

    selected, truncated = _select_chunks(
        candidates, question, max_chars=max_chars, max_chunks=max_chunks
    )
    return LicitacionContext(
        detail=detail,
        documentos=documentos,
        chunks=selected,
        has_pliego_text=bool(candidates),
        truncated=truncated,
    )


# Campos del detalle que viajan en el doc primario del contexto LLM.
_PRIMARY_DOC_FIELDS = (
    "titulo",
    "organo_contratacion",
    "importe",
    "fecha_publicacion",
    "fecha_limite",
    "cpv",
    "ccaa",
    "estado",
    "url",
)


def primary_doc_from_context(id_externo: str, ctx: LicitacionContext) -> dict[str, Any]:
    """Doc primario para ``llm.prompts.build_context_block`` y el evento SSE."""
    detail = ctx["detail"]
    doc: dict[str, Any] = {"id_externo": id_externo}
    for field in _PRIMARY_DOC_FIELDS:
        doc[field] = detail.get(field)
    doc["descripcion"] = str(detail.get("descripcion") or "")[:1000]
    doc["chunks"] = ctx["chunks"]
    doc["_score"] = 2.0
    return doc
