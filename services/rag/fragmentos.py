"""Fragmentos de pliego relevantes para una pregunta (lo que consume el MCP interno).

Reutiliza el ranking del RAG (``rank_by_question``: puntúa los chunks ya leídos
con ``smart_match``, que sin el extra de embeddings degrada a solapamiento de
palabras). Con ``id_externo`` ordena los chunks de
ese expediente; sin él busca los expedientes por texto completo
(``search_fts_docs``) y mezcla sus chunks por posición de rango, de modo que
ningún expediente acapara la respuesta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db.repositories.documentos import DocumentosRepository
from db.repositories.licitaciones import LicitacionRepository
from services.rag.context import rank_by_question

__all__ = ["MAX_CHARS_FRAGMENTO", "Fragmento", "fragmentos_de_pliego"]

#: Tope del texto de cada fragmento devuelto.
MAX_CHARS_FRAGMENTO = 1_500
#: Expedientes que se exploran cuando la pregunta no fija uno.
_MAX_EXPEDIENTES = 5
#: Chunks leídos por expediente antes de rankear.
_MAX_CANDIDATOS = 200


@dataclass(frozen=True)
class Fragmento:
    """Un trozo de un documento de pliego."""

    id_externo: str
    documento: str | None
    tipo: str | None
    pagina: int | None
    texto: str


def _repo_documentos() -> DocumentosRepository:
    return DocumentosRepository()


def _repo_licitaciones() -> LicitacionRepository:
    return LicitacionRepository()


def _a_fragmento(id_externo: str, chunk: dict[str, Any]) -> Fragmento:
    pagina = chunk.get("page_number")
    documento = chunk.get("filename")
    tipo = chunk.get("tipo")
    return Fragmento(
        id_externo=id_externo,
        documento=str(documento) if documento is not None else None,
        tipo=str(tipo) if tipo is not None else None,
        pagina=int(pagina) if pagina is not None else None,
        texto=str(chunk.get("texto") or "").strip()[:MAX_CHARS_FRAGMENTO],
    )


def _ordenados(pregunta: str, id_externo: str) -> list[Fragmento]:
    """Chunks del expediente de más a menos relevante (los vacíos se descartan)."""
    candidatos = [
        c
        for c in _repo_documentos().list_chunks_by_licitacion(id_externo, limit=_MAX_CANDIDATOS)
        if str(c.get("texto") or "").strip()
    ]
    orden = rank_by_question(pregunta, candidatos)
    return [_a_fragmento(id_externo, candidatos[i]) for i in orden]


def fragmentos_de_pliego(
    pregunta: str, *, id_externo: str | None = None, limite: int = 10
) -> list[Fragmento]:
    """Los ``limite`` fragmentos de pliego más relevantes para ``pregunta``.

    Con ``id_externo``: los chunks de ese expediente, ordenados por relevancia.
    Sin él: los primeros 5 expedientes de la búsqueda de texto completo y sus
    chunks, mezclados por rango (el mejor de cada expediente, luego el segundo,
    etc.). Devuelve ``[]`` si no hay texto de pliego indexado.
    """
    if limite < 1:
        return []
    if id_externo is not None:
        return _ordenados(pregunta, id_externo)[:limite]

    filas = _repo_licitaciones().search_fts_docs(pregunta, limit=_MAX_EXPEDIENTES)
    por_expediente = [_ordenados(pregunta, str(f["id_externo"])) for f in filas]
    mezclados: list[Fragmento] = []
    for rango in range(max((len(lista) for lista in por_expediente), default=0)):
        for lista in por_expediente:
            if rango < len(lista):
                mezclados.append(lista[rango])
                if len(mezclados) >= limite:
                    return mezclados
    return mezclados
