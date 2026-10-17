"""Contrato de ``services/investigador/search_engine.py``.

Hasta ahora el módulo solo se ejercitaba de refilón desde los tests de
búsqueda y de ``/ask``, que venían a comprobar otra cosa (backlog P3 «Suites
propias para `services/investigador/` y `extraction_runs`»). Aquí se fija lo
que el módulo promete por sí mismo:

- qué cuenta como palabra relevante (``extract_keywords``), que sigue usando el
  último recurso por subcadena de ``/ask``;
- que ``hybrid_search`` devuelve ``[]`` —y no lanza— en cada uno de sus cuatro
  modos de fallo, porque ``[]`` es la señal con la que el llamador degrada.

Sin BD: el backend vectorial se sustituye por dobles.
"""

from __future__ import annotations

from typing import Any

import pytest

import services.investigador.search_engine as se

# ── extract_keywords ─────────────────────────────────────────────────────────


def test_extract_keywords_quita_stopwords_tokens_cortos_y_metacaracteres() -> None:
    palabras = se.extract_keywords("¿Cuántas licitaciones de SAP S/4HANA hay en Madrid?")

    assert "cuántas" not in palabras
    assert "licitaciones" not in palabras, "término que define el corpus: no discrimina"
    assert "de" not in palabras
    assert "sap" in palabras
    assert "4hana" in palabras, "la barra es metacarácter y parte el token"
    assert "madrid" in palabras
    assert all(len(p) > 2 for p in palabras)


def test_extract_keywords_deduplica_y_ordena_por_longitud() -> None:
    """Heurística de especificidad: los términos más largos primero."""
    palabras = se.extract_keywords("mantenimiento sap sap Mantenimiento hana")

    assert palabras == ["mantenimiento", "hana", "sap"]


def test_extract_keywords_limita_a_doce_terminos() -> None:
    consulta = " ".join(f"termino{i:02d}" for i in range(30))

    assert len(se.extract_keywords(consulta)) == 12


def test_extract_keywords_de_una_pregunta_sin_senal_es_vacia() -> None:
    assert se.extract_keywords("¿Qué hay de las licitaciones?") == []


# ── hybrid_search: cada modo de fallo devuelve [] ────────────────────────────


@pytest.fixture
def hibrido(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import db.search_backend as backend
    import services.embeddings as embeddings

    estado: dict[str, Any] = {
        "modelo": True,
        "corpus": True,
        "encode": None,
        "sql": None,
        "kwargs": None,
    }

    class _Vector:
        def tolist(self) -> list[float]:
            return [0.1, 0.2]

    def _encode(textos: list[str]) -> list[_Vector]:
        if estado["encode"] is not None:
            raise estado["encode"]
        return [_Vector()]

    def _hybrid(question: str, embedding: list[float], **kwargs: Any) -> list[dict[str, Any]]:
        if estado["sql"] is not None:
            raise estado["sql"]
        estado["kwargs"] = {"embedding": embedding, **kwargs}
        return [{"id_externo": "A", "rrf_score": 0.03}]

    monkeypatch.setattr(embeddings, "embeddings_available", lambda: estado["modelo"])
    monkeypatch.setattr(embeddings, "encode_texts", _encode)
    monkeypatch.setattr(backend, "document_embeddings_available", lambda: estado["corpus"])
    monkeypatch.setattr(backend, "hybrid_search_docs", _hybrid)
    return estado


def test_hybrid_search_devuelve_la_fusion(hibrido: dict[str, Any]) -> None:
    docs = se.hybrid_search("sap", 5, alpha=0.3)

    assert docs == [{"id_externo": "A", "rrf_score": 0.03}]
    assert hibrido["kwargs"] == {
        "embedding": [0.1, 0.2],
        "limit": 5,
        "candidate_k": 50,
        "alpha": 0.3,
    }


def test_hybrid_search_amplia_candidatos_por_encima_de_cincuenta(
    hibrido: dict[str, Any],
) -> None:
    se.hybrid_search("sap", 80)

    assert hibrido["kwargs"]["candidate_k"] == 80


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("modelo", False),
        ("corpus", False),
        ("encode", RuntimeError("modelo roto")),
        ("sql", RuntimeError("pgvector caído")),
    ],
    ids=["sin-modelo", "sin-corpus", "encode-falla", "sql-falla"],
)
def test_hybrid_search_degrada_a_lista_vacia(
    hibrido: dict[str, Any], campo: str, valor: Any
) -> None:
    """`[]` es la señal para degradar a FTS; una excepción tumbaría la búsqueda."""
    hibrido[campo] = valor

    assert se.hybrid_search("sap", 5) == []
