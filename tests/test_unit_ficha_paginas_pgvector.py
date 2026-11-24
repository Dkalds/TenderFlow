"""Selección de páginas de la ficha por pgvector, detrás de ``PLIEGO_FACTS_PAGINAS_PGVECTOR``.

Sin BD: el repositorio y el codificador se sustituyen. Lo que se fija es el
cableado —apagado no toca embeddings; encendido ordena por la cercanía de los
chunks a las consultas de familia; cualquier fallo cae a los términos— y no la
calidad de la selección, que se mide contra el golden de fichas.
"""

from __future__ import annotations

from typing import Any

import pytest

from config import settings
from services.rag import fact_sheet as fs


def _pagina(doc: int, num: int, texto: str, tipo: str = "additional") -> dict[str, Any]:
    return {"documento_id": doc, "page_number": num, "texto": texto, "tipo": tipo}


#: La página 1 gana por términos («solvencia», «criterios»); la 2 no tiene ninguno.
_PAGINAS = [
    _pagina(1, 1, "Criterios de adjudicación y solvencia técnica del contratista."),
    _pagina(1, 2, "Texto que ninguna lista de términos reconoce."),
]


def _orden(paginas: list[dict[str, Any]]) -> list[tuple[int, int]]:
    return [(int(p["documento_id"]), int(p["page_number"])) for p in paginas]


def test_con_puntuacion_ordena_por_ella_y_no_por_terminos() -> None:
    elegidas = fs._select_pages(_PAGINAS, puntuacion={(1, 2): 0.9}, max_paginas=1)
    assert _orden(elegidas) == [(1, 2)]


def test_sin_puntuacion_manda_el_recuento_de_terminos() -> None:
    assert _orden(fs._select_pages(_PAGINAS, max_paginas=1)) == [(1, 1)]


def test_apagado_no_toca_los_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PLIEGO_FACTS_PAGINAS_PGVECTOR", False, raising=False)

    def _no(*_: Any, **__: Any) -> None:
        raise AssertionError("no debe llamarse")

    monkeypatch.setattr(fs, "_puntuacion_pgvector", _no)
    assert _orden(fs._seleccion_general("L", _PAGINAS)) == [(1, 1), (1, 2)]


class _RepoFalso:
    def __init__(self, filas: list[dict[str, Any]] | Exception) -> None:
        self.filas = filas
        self.llamadas = 0

    def search_chunks_by_embedding(self, *_: Any, **__: Any) -> list[dict[str, Any]]:
        self.llamadas += 1
        if isinstance(self.filas, Exception):
            raise self.filas
        return self.filas


def _puntuacion_usada(monkeypatch: pytest.MonkeyPatch) -> object:
    """La ``puntuacion`` con la que ``_seleccion_general`` llama a ``_select_pages``."""
    vista: dict[str, object] = {}

    def _espia(paginas: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
        vista["puntuacion"] = kwargs.get("puntuacion")
        return paginas

    monkeypatch.setattr(fs, "_select_pages", _espia)
    fs._seleccion_general("L", _PAGINAS)
    return vista["puntuacion"]


def _encendido(monkeypatch: pytest.MonkeyPatch, repo: _RepoFalso) -> None:
    monkeypatch.setattr(settings, "PLIEGO_FACTS_PAGINAS_PGVECTOR", True, raising=False)
    monkeypatch.setattr("services.embeddings.embeddings_available", lambda: True)
    monkeypatch.setattr(
        "services.embeddings.encode_texts", lambda textos: [[0.1, 0.2] for _ in textos]
    )
    monkeypatch.setattr(fs, "DocumentosRepository", lambda: repo)


def test_encendido_puntua_cada_pagina_con_su_mejor_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _RepoFalso(
        [
            {"documento_id": 1, "page_number": 2, "score": 0.8},
            {"documento_id": 1, "page_number": 2, "score": 0.3},
            {"documento_id": 1, "page_number": None, "score": 0.99},
        ]
    )
    _encendido(monkeypatch, repo)

    assert fs._puntuacion_pgvector("L") == {(1, 2): 0.8}
    assert repo.llamadas == len(fs._CONSULTAS_FAMILIA)
    assert _puntuacion_usada(monkeypatch) == {(1, 2): 0.8}


@pytest.mark.parametrize("filas", [[], RuntimeError("dimensión distinta")])
def test_sin_chunks_o_con_fallo_cae_a_los_terminos(
    monkeypatch: pytest.MonkeyPatch, filas: list[dict[str, Any]] | Exception
) -> None:
    _encendido(monkeypatch, _RepoFalso(filas))

    assert fs._puntuacion_pgvector("L") is None
    assert _puntuacion_usada(monkeypatch) is None


def test_sin_motor_de_embeddings_no_consulta(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _RepoFalso([])
    _encendido(monkeypatch, repo)
    monkeypatch.setattr("services.embeddings.embeddings_available", lambda: False)

    assert fs._puntuacion_pgvector("L") is None
    assert repo.llamadas == 0
