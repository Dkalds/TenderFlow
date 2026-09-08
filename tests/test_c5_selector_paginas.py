"""C5.2 — la ficha del pliego tiene UN selector de páginas, no dos.

Hasta 2026-09 convivían dos: `_page_score` contaba apariciones de substring de
`_TOPIC_TERMS`/`_TECH_TERMS` para la ficha, mientras el resto del RAG rankeaba
por embeddings. Dos selectores sobre el mismo pliego pueden elegir páginas
distintas, y el golden de C5.1 mide una ficha sin saber cuál de los dos la
produjo.

Sin BD y sin modelo de embeddings: se sustituye `smart_match`, que es
exactamente la frontera que el ítem mueve.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from services.rag import fact_sheet

pytestmark = pytest.mark.unit


def _pagina(doc: int, numero: int, texto: str) -> dict[str, Any]:
    return {"documento_id": doc, "page_number": numero, "texto": texto}


def test_selector_unico_usa_el_recuperador_semantico() -> None:
    """`_select_pages` rankea con `smart_match`, no con un contador propio."""
    paginas = [
        _pagina(1, 1, "Portada del pliego administrativo"),
        _pagina(1, 2, "Página irrelevante sobre el registro de entrada"),
        _pagina(1, 3, "Criterios de adjudicación y su ponderación"),
    ]
    llamadas: list[tuple[str, int]] = []

    def _falso_smart_match(query: str, corpus: list[str], threshold: float = 0.5):
        llamadas.append((query, len(corpus)))
        # La 3 es la relevante; la 2, ruido por debajo del umbral.
        return [(2, 0.9)]

    with (
        patch.object(fact_sheet, "_TOPIC_TERMS", fact_sheet._TOPIC_TERMS),
        patch("services.embeddings.smart_match", _falso_smart_match),
        patch("services.embeddings.embeddings_available", lambda: True),
    ):
        seleccion = fact_sheet._select_pages(paginas)

    assert llamadas, "no se consultó al recuperador: sigue habiendo selector propio"
    query, n_corpus = llamadas[0]
    assert n_corpus == 3, "el corpus debe ser el de páginas, no una muestra"
    # La consulta son los términos, que es lo que el ítem pide: dejan de ser
    # una puntuación y pasan a ser lo que se le pregunta al recuperador.
    for termino in ("adjudicación", "ponderación", "sap"):
        assert termino in query

    numeros = [p["page_number"] for p in seleccion]
    assert 1 in numeros, "la portada del documento entra siempre"
    assert 3 in numeros, "la página que el recuperador puntuó no puede quedar fuera"


def test_el_metodo_de_ranking_se_declara() -> None:
    """El método viaja en el log: dos fichas rankeadas distinto no son comparables."""
    paginas = [_pagina(1, 1, "Portada"), _pagina(1, 2, "Criterios de adjudicación")]

    with patch("services.embeddings.embeddings_available", lambda: False):
        orden, metodo = fact_sheet._rank_pages(paginas)

    assert metodo == "substring"
    assert sorted(orden) == [0, 1], "el orden debe cubrir todas las páginas, sin perder ninguna"


def test_si_el_recuperador_revienta_la_ficha_sigue_saliendo() -> None:
    """Un fallo del ranking degrada a orden documental; no deja al pliego sin ficha."""
    paginas = [_pagina(1, 1, "Portada"), _pagina(1, 2, "Criterios")]

    def _revienta(*_a: Any, **_k: Any):
        raise RuntimeError("modelo de embeddings no cargado")

    with (
        patch("services.embeddings.smart_match", _revienta),
        patch("services.embeddings.embeddings_available", lambda: True),
    ):
        orden, metodo = fact_sheet._rank_pages(paginas)

    assert metodo == "documental"
    assert orden == [0, 1]


def test_la_seleccion_respeta_el_presupuesto_de_contexto() -> None:
    """El presupuesto sigue mandando: cambiar de ranker no puede desbordar el prompt."""
    largo = "criterio de adjudicación " * 2000  # ~50 000 caracteres
    paginas = [_pagina(1, 1, "Portada"), _pagina(1, 2, largo), _pagina(1, 3, largo)]

    with patch("services.embeddings.embeddings_available", lambda: False):
        seleccion = fact_sheet._select_pages(paginas)

    total = sum(len(str(p["texto"])) for p in seleccion)
    # La primera página entra aunque no quepa —una ficha sin contexto no es
    # ficha—; a partir de ahí el tope manda.
    assert len(seleccion) < 3
    assert total <= len(largo) + fact_sheet._MAX_CONTEXT_CHARS
