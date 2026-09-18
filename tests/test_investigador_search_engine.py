"""Contrato de ``services/investigador/search_engine.py``.

Hasta ahora el módulo solo se ejercitaba de refilón desde los tests de
búsqueda y de ``/ask``, que venían a comprobar otra cosa (backlog P3 «Suites
propias para `services/investigador/` y `extraction_runs`»). Aquí se fija lo
que el módulo promete por sí mismo:

- qué cuenta como palabra relevante (``extract_keywords``) y cómo se escapa
  para el motor (``escape_fts5``);
- el orden de degradación FTS → LIKE de ``rag_query`` y la etiqueta de fuente,
  que tiene que decir el camino **ejecutado**;
- que ``hybrid_search`` devuelve ``[]`` —y no lanza— en cada uno de sus cuatro
  modos de fallo, porque ``[]`` es la señal con la que el llamador degrada.

Sin BD: el repositorio y el backend vectorial se sustituyen por dobles.
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


# ── escape_fts5 ──────────────────────────────────────────────────────────────


def test_escape_fts5_une_con_or_y_entrecomilla_cada_token() -> None:
    """AND implícito devolvía cero resultados en preguntas naturales."""
    assert se.escape_fts5("sap hana") == '"hana" OR "sap"'


def test_escape_fts5_neutraliza_operadores() -> None:
    """Un operador del motor no puede llegar vivo a la consulta."""
    escapada = se.escape_fts5('sap* NEAR(hana) -migracion "x')

    for token in escapada.split(" OR "):
        assert token.startswith('"') and token.endswith('"')
    assert "*" not in escapada
    assert "(" not in escapada


def test_escape_fts5_sin_palabras_relevantes_devuelve_frase_vacia() -> None:
    """Una frase vacía no casa con nada; una cadena vacía sería un error de sintaxis."""
    assert se.escape_fts5("de la el") == '""'


# ── rag_query ────────────────────────────────────────────────────────────────


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Repositorio de licitaciones en memoria con llamadas grabadas."""
    estado: dict[str, Any] = {"fts": [], "like": [], "docs": {}, "llamadas": []}

    class _Repo:
        def fts5_bm25_search(self, question: str, top_k: int) -> list[tuple[str, float]]:
            estado["llamadas"].append(("fts", top_k))
            return list(estado["fts"])

        def like_fallback_search(self, question: str, top_k: int) -> list[tuple[str, float]]:
            estado["llamadas"].append(("like", top_k))
            return list(estado["like"])

        def fetch_metadata_by_ids(
            self, ids: list[str], allowed_ids: set[str] | None
        ) -> dict[str, dict[str, Any]]:
            estado["llamadas"].append(("fetch", list(ids)))
            return {i: dict(estado["docs"][i]) for i in ids if i in estado["docs"]}

    monkeypatch.setattr(se, "_repo", _Repo())
    return estado


def test_rag_query_usa_fts_y_ordena_por_score(repo: dict[str, Any]) -> None:
    repo["fts"] = [("A", 0.2), ("B", 0.9), ("C", 0.5)]
    repo["docs"] = {k: {"id_externo": k} for k in "ABC"}

    docs, fuente = se.rag_query("sap hana", top_k=2)

    assert fuente == "FTS5"
    assert [d["id_externo"] for d in docs] == ["B", "C"]
    assert docs[0]["_score"] == 0.9
    assert ("fts", 4) in repo["llamadas"], "pide el doble para tener margen al filtrar"
    assert not any(llamada[0] == "like" for llamada in repo["llamadas"])


def test_rag_query_cae_a_like_si_fts_no_encuentra_nada(repo: dict[str, Any]) -> None:
    """La etiqueta dice el camino que se ejecutó, no el configurado."""
    repo["like"] = [("L1", 1.0)]
    repo["docs"] = {"L1": {"id_externo": "L1"}}

    docs, fuente = se.rag_query("sap", top_k=3)

    assert fuente == "LIKE"
    assert [d["id_externo"] for d in docs] == ["L1"]


def test_rag_query_respeta_allowed_ids(repo: dict[str, Any]) -> None:
    """El filtro de ámbito se aplica antes de cargar metadatos: un id fuera del
    ámbito no llega ni a pedirse."""
    repo["fts"] = [("A", 0.9), ("B", 0.8)]
    repo["docs"] = {k: {"id_externo": k} for k in "AB"}

    docs, _ = se.rag_query("sap", top_k=5, allowed_ids={"B"})

    assert [d["id_externo"] for d in docs] == ["B"]
    assert ("fetch", ["B"]) in repo["llamadas"]


def test_rag_query_omite_ids_sin_metadatos(repo: dict[str, Any]) -> None:
    """Un hit del índice cuya fila ya no existe no se inventa como documento."""
    repo["fts"] = [("A", 0.9), ("FANTASMA", 0.8)]
    repo["docs"] = {"A": {"id_externo": "A"}}

    docs, _ = se.rag_query("sap", top_k=5)

    assert [d["id_externo"] for d in docs] == ["A"]


def test_rag_query_sin_resultados_en_ningun_camino(repo: dict[str, Any]) -> None:
    docs, fuente = se.rag_query("sap", top_k=5)

    assert docs == []
    assert fuente == "LIKE"


def test_rag_query_no_muta_los_metadatos_del_repositorio(repo: dict[str, Any]) -> None:
    repo["fts"] = [("A", 0.5)]
    repo["docs"] = {"A": {"id_externo": "A"}}

    se.rag_query("sap", top_k=1)

    assert "_score" not in repo["docs"]["A"]


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


# ── Delegaciones ─────────────────────────────────────────────────────────────


def test_fetch_docs_pasa_el_ambito_al_repositorio(repo: dict[str, Any]) -> None:
    repo["docs"] = {"A": {"id_externo": "A"}}

    assert se.fetch_docs(["A", "B"], {"A"}) == {"A": {"id_externo": "A"}}
    assert ("fetch", ["A", "B"]) in repo["llamadas"]
