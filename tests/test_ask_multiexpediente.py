"""F2.8 — ``/ask`` con varios expedientes, sin BD.

``AskRequest.id_externo`` era un único ``str``: la bandeja de comparación podía
poner tres fichas lado a lado pero no preguntar sobre las tres. Aquí se fija el
contrato de ``ids_externos`` (hasta tres, compatible con ``id_externo``), el
reparto del contexto —que el tercer expediente llegue al modelo— y la
declaración por expediente en ``ask_meta`` y en las citas.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from api.routes.ask import (
    AskRequest,
    _prepare_ask_context,
    _presupuesto_por_expediente,
)
from llm.prompts import (
    build_context_block,
    build_system_prompt,
    context_chars_for,
    excerpt_chars_for,
    prompt_version,
)


class TestContrato:
    def test_compatible_hacia_atras(self) -> None:
        assert AskRequest(question="¿plazo?", id_externo="A").expedientes() == ["A"]
        assert AskRequest(question="¿plazo?").expedientes() == []

    def test_combina_y_deduplica_en_orden(self) -> None:
        req = AskRequest(question="¿plazo?", id_externo="A", ids_externos=["B", " A ", "C"])
        assert req.expedientes() == ["A", "B", "C"]
        assert AskRequest(question="¿plazo?", ids_externos=["", "B"]).expedientes() == ["B"]

    def test_como_mucho_tres(self) -> None:
        with pytest.raises(ValidationError):
            AskRequest(question="¿plazo?", ids_externos=["A", "B", "C", "D"])
        with pytest.raises(ValidationError):
            AskRequest(question="¿plazo?", id_externo="Z", ids_externos=["A", "B", "C"])


class TestPresupuesto:
    @pytest.mark.parametrize("n", [2, 3])
    def test_caben_todos_en_el_contexto(self, n: int) -> None:
        max_chars, max_chunks = _presupuesto_por_expediente(n)
        por_anuncio = excerpt_chars_for("comparacion") + 600
        assert n * (max_chars + por_anuncio) <= context_chars_for("comparacion")
        assert max_chunks >= 3

    def test_con_mas_expedientes_toca_menos_a_cada_uno(self) -> None:
        assert _presupuesto_por_expediente(3)[0] < _presupuesto_por_expediente(2)[0]


def _ctx(id_externo: str, *, n_chunks: int = 2, truncated: bool = False) -> dict[str, Any]:
    return {
        "detail": {
            "titulo": f"Contrato {id_externo}",
            "organo_contratacion": "Órgano",
            "descripcion": "x" * 5000,
        },
        "documentos": [],
        "chunks": [
            {
                "documento_id": ord(id_externo[0]) * 100 + i,
                "page_number": i + 1,
                "chunk_index": i,
                "texto": "t" * 900,
            }
            for i in range(n_chunks)
        ],
        "has_pliego_text": n_chunks > 0,
        "truncated": truncated,
    }


class TestContexto:
    def test_tres_expedientes_son_una_comparacion(self) -> None:
        llamadas: list[tuple[str, int, int]] = []

        def _build(id_externo: str, _q: str, *, max_chars: int, max_chunks: int) -> Any:
            llamadas.append((id_externo, max_chars, max_chunks))
            return _ctx(id_externo, truncated=id_externo == "C")

        req = AskRequest(question="¿Qué solvencia piden?", ids_externos=["A", "B", "C"])
        with patch("services.rag.context.build_licitacion_context", side_effect=_build):
            docs, mode, declarados = _prepare_ask_context(req)

        assert mode == "comparacion"
        assert [d["id_externo"] for d in docs] == ["A", "B", "C"]
        # Cada chunk sabe de qué expediente es: es lo que deja citar por expediente.
        assert {c["id_externo"] for c in docs[2]["chunks"]} == {"C"}
        # Todos con el presupuesto repartido, no el de un expediente.
        assert {(c, m) for _i, c, m in llamadas} == {_presupuesto_por_expediente(3)}
        assert [d["truncado"] for d in declarados] == [False, False, True]
        assert all(d["encontrado"] for d in declarados)

    def test_un_expediente_que_no_existe_se_declara(self) -> None:
        def _build(id_externo: str, _q: str, **_kw: Any) -> Any:
            return None if id_externo == "B" else _ctx(id_externo)

        req = AskRequest(question="¿plazo?", ids_externos=["A", "B", "C"])
        with patch("services.rag.context.build_licitacion_context", side_effect=_build):
            docs, mode, declarados = _prepare_ask_context(req)

        assert mode == "comparacion"
        assert [d["id_externo"] for d in docs] == ["A", "C"]
        assert declarados[1] == {"id_externo": "B", "encontrado": False}

    def test_si_solo_existe_uno_es_una_pregunta_sobre_ese(self) -> None:
        def _build(id_externo: str, _q: str, **_kw: Any) -> Any:
            return _ctx(id_externo) if id_externo == "A" else None

        req = AskRequest(question="¿plazo?", ids_externos=["A", "B"])
        with patch("services.rag.context.build_licitacion_context", side_effect=_build):
            docs, mode, declarados = _prepare_ask_context(req)

        assert mode == "licitacion"
        assert [d["id_externo"] for d in docs] == ["A"]
        assert [d["encontrado"] for d in declarados] == [True, False]

    def test_si_no_existe_ninguno_cae_al_corpus_y_lo_declara(self) -> None:
        req = AskRequest(question="¿plazo?", ids_externos=["A", "B"])
        with (
            patch("services.rag.context.build_licitacion_context", return_value=None),
            patch("api.routes.ask._retrieve_docs", return_value=[]),
        ):
            docs, mode, declarados = _prepare_ask_context(req)

        assert (docs, mode) == ([], "general")
        assert [d["encontrado"] for d in declarados] == [False, False]

    def test_un_solo_id_en_la_lista_es_el_camino_de_siempre(self) -> None:
        req = AskRequest(question="¿plazo?", ids_externos=["A"])
        with patch(
            "services.rag.context.build_licitacion_context", return_value=_ctx("A")
        ) as build:
            _docs, mode, declarados = _prepare_ask_context(req)

        assert mode == "licitacion"
        assert declarados == []
        # Sin reparto: el presupuesto de un expediente entero.
        assert build.call_args.kwargs == {}

    def test_el_bloque_lleva_los_tres_expedientes_sin_cortar(self) -> None:
        """Lo que el reparto protege: sin él, el tercero se quedaba fuera."""
        max_chars, max_chunks = _presupuesto_por_expediente(3)
        docs = []
        for id_externo in ("A", "B", "C"):
            ctx = _ctx(id_externo, n_chunks=max_chunks)
            usados, chunks = 0, []
            for c in ctx["chunks"]:
                if usados + len(c["texto"]) > max_chars:
                    break
                chunks.append(c)
                usados += len(c["texto"])
            docs.append({"id_externo": id_externo, **ctx["detail"], "chunks": chunks})
        bloque = build_context_block(
            docs,
            [],
            max_chars=context_chars_for("comparacion"),
            excerpt_chars=excerpt_chars_for("comparacion"),
        )
        assert "[contexto truncado]" not in bloque
        assert all(f"[{i}]" in bloque for i in ("A", "B", "C"))


class TestPromptYCitas:
    def test_prompt_propio(self) -> None:
        texto = build_system_prompt("comparacion", has_corpus_context=True)
        assert "expediente" in texto and "[doc:N p.M]" in texto
        assert prompt_version("comparacion") != prompt_version("licitacion")

    def test_las_citas_dicen_de_que_expediente_son(self) -> None:
        from services.rag.citas import evento_sources

        chunks = [
            {"documento_id": 10, "page_number": 1, "texto": "a", "id_externo": "A"},
            {"documento_id": 20, "page_number": 3, "texto": "b", "id_externo": "B"},
        ]
        evento = evento_sources("Uno [doc:10 p.1], otro [doc:20 p.3].", chunks)
        assert [s["id_externo"] for s in evento["sources"]] == ["A", "B"]

    def test_sin_expediente_la_clave_no_viaja(self) -> None:
        from services.rag.citas import evento_sources

        evento = evento_sources("x [doc:10]", [{"documento_id": 10, "texto": "a"}])
        assert "id_externo" not in evento["sources"][0]
