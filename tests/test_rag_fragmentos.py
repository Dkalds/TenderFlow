"""``fragmentos_de_pliego``: ranking y mezcla de chunks con repositorios falsos."""

from __future__ import annotations

from typing import Any

import pytest

from services.rag import fragmentos as modulo
from services.rag.fragmentos import Fragmento, fragmentos_de_pliego


def _chunk(doc: int, idx: int, texto: str, *, tipo: str = "legal") -> dict[str, Any]:
    return {
        "documento_id": doc,
        "tipo": tipo,
        "filename": f"pliego-{doc}.pdf",
        "chunk_index": idx,
        "texto": texto,
        "page_number": idx + 1,
    }


class _DocumentosFalso:
    def __init__(self, chunks: dict[str, list[dict[str, Any]]]) -> None:
        self._chunks = chunks
        self.limites: list[int] = []

    def list_chunks_by_licitacion(
        self, licitacion_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        self.limites.append(limit)
        return self._chunks.get(licitacion_id, [])


class _LicitacionesFalso:
    def __init__(self, ids: list[str]) -> None:
        self._ids = ids
        self.llamadas: list[tuple[str, int]] = []

    def search_fts_docs(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        self.llamadas.append((query, limit))
        return [{"id_externo": i} for i in self._ids[:limit]]


@pytest.fixture(autouse=True)
def _sin_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ranking determinista: solapamiento de palabras, sin cargar el modelo."""
    monkeypatch.setattr("services.embeddings.embeddings_available", lambda: False)


def _instalar(
    monkeypatch: pytest.MonkeyPatch,
    chunks: dict[str, list[dict[str, Any]]],
    fts: list[str] | None = None,
) -> tuple[_DocumentosFalso, _LicitacionesFalso]:
    docs = _DocumentosFalso(chunks)
    lics = _LicitacionesFalso(fts or [])
    monkeypatch.setattr(modulo, "_repo_documentos", lambda: docs)
    monkeypatch.setattr(modulo, "_repo_licitaciones", lambda: lics)
    return docs, lics


def test_fragmentos_con_expediente_ordena_por_pregunta(monkeypatch: pytest.MonkeyPatch) -> None:
    _instalar(
        monkeypatch,
        {
            "EXP-1": [
                _chunk(1, 0, "Objeto del contrato y plazo de ejecución"),
                _chunk(1, 1, "Requisitos de solvencia económica y técnica del licitador"),
                _chunk(1, 2, "Penalidades por incumplimiento"),
            ]
        },
    )
    res = fragmentos_de_pliego("solvencia técnica", id_externo="EXP-1", limite=3)
    assert isinstance(res[0], Fragmento)
    assert "solvencia" in res[0].texto
    assert res[0].id_externo == "EXP-1"
    assert res[0].documento == "pliego-1.pdf"
    assert res[0].tipo == "legal"
    assert res[0].pagina == 2
    assert len(res) == 3


def test_fragmentos_sin_expediente_mezcla_y_respeta_limite(monkeypatch: pytest.MonkeyPatch) -> None:
    ids = ["A", "B", "C"]
    _, lics = _instalar(
        monkeypatch,
        {
            i: [_chunk(n, k, f"texto {i} {k} solvencia") for k in range(6)]
            for n, i in enumerate(ids)
        },
        fts=[*ids, "D", "E", "F"],
    )
    res = fragmentos_de_pliego("solvencia", limite=10)
    assert len(res) == 10
    assert lics.llamadas == [("solvencia", 5)]
    # Mezcla por rango: los tres expedientes aportan antes de que ninguno aporte su 4.º chunk.
    assert {f.id_externo for f in res[:3]} == set(ids)


def test_fragmentos_sin_chunks_devuelve_lista_vacia(monkeypatch: pytest.MonkeyPatch) -> None:
    _instalar(monkeypatch, {}, fts=["A"])
    assert fragmentos_de_pliego("lo que sea", id_externo="NADA") == []
    assert fragmentos_de_pliego("lo que sea") == []


def test_fragmentos_recorta_el_texto_a_1500(monkeypatch: pytest.MonkeyPatch) -> None:
    _instalar(monkeypatch, {"EXP-1": [_chunk(1, 0, "solvencia " * 400)]})
    (f,) = fragmentos_de_pliego("solvencia", id_externo="EXP-1")
    assert len(f.texto) == 1500


def test_fragmentos_ignora_chunks_vacios(monkeypatch: pytest.MonkeyPatch) -> None:
    _instalar(monkeypatch, {"EXP-1": [_chunk(1, 0, "   "), _chunk(1, 1, "solvencia")]})
    res = fragmentos_de_pliego("solvencia", id_externo="EXP-1")
    assert [f.texto for f in res] == ["solvencia"]
