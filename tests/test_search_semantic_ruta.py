"""O0.6a (D15) — la ruta deriva ``source`` del camino que ejecutó, sin BD.

``tests/test_search_semantic_source.py`` comprueba piezas sueltas (los pesos de
la fusión, el adaptador de hits, el acuerdo con la UI) y
``tests/test_search_semantic_hybrid.py`` ejecuta el SQL de verdad contra
pgvector, pero exige Postgres. Falta el escalón de en medio, que es justo donde
viven los criterios 2 y 4 del ítem: **ejecutar la ruta entera** y afirmar qué
``source`` sale por cada camino.

``semantic_search`` es una corrutina normal —se puede llamar sin servidor ni
middleware— y las funciones del motor se sustituyen por dobles: lo que se prueba
aquí es la DERIVACIÓN de la fuente y el viaje de ``alpha``, no el SQL.
"""

from __future__ import annotations

from typing import Any

import pytest

from api.routes.search import (
    SEARCH_SOURCES,
    SOURCE_FTS,
    SOURCE_LIKE,
    SOURCE_RRF,
    SemanticSearchResponse,
)


def _doc(id_externo: str, rrf: float) -> dict[str, Any]:
    """Un documento tal como lo devuelve ``hybrid_search_docs``."""
    return {
        "id_externo": id_externo,
        "titulo": f"Licitación {id_externo}",
        "organo_contratacion": "AEAT",
        "importe": 1000.0,
        "descripcion": "texto",
        "url": None,
        "fecha_publicacion": "2026-01-01",
        "ccaa": "Madrid",
        "estado": "PUB",
        "tecnologia": "SAP",
        "rrf_score": rrf,
        "chunks": [],
    }


class _MotorFalso:
    """Doble de ``services.investigador.search_engine`` para la ruta.

    Registra el orden de los caminos intentados y el ``alpha`` con el que se
    llamó a la fusión: que el deslizador del Investigador llegue al motor es la
    mitad de D15, y es comprobable sin BD.
    """

    def __init__(
        self,
        *,
        fused: list[dict[str, Any]] | None = None,
        fts: list[tuple[str, float]] | None = None,
        like: list[tuple[str, float]] | None = None,
    ) -> None:
        self._fused = fused or []
        self._fts = fts or []
        self._like = like or []
        self.alpha_recibido: float | None = None
        self.llamadas: list[str] = []

    def hybrid_search(
        self, question: str, top_k: int, *, alpha: float | None = None
    ) -> list[dict[str, Any]]:
        self.llamadas.append("hybrid")
        self.alpha_recibido = alpha
        return list(self._fused)

    def fts5_search(self, question: str, top_k: int) -> list[tuple[str, float]]:
        self.llamadas.append("fts")
        return list(self._fts)

    def like_search(self, question: str, top_k: int) -> list[tuple[str, float]]:
        self.llamadas.append("like")
        return list(self._like)

    def fetch_docs(
        self, ids: list[str], allowed_ids: set[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        return {
            i: {
                "id_externo": i,
                "titulo": f"Licitación {i}",
                "organo_contratacion": "AEAT",
                "importe": 1000.0,
                "descripcion": "texto",
                "url": None,
                "fecha_publicacion": "2026-01-01",
                "ccaa": "Madrid",
                "estado": "PUB",
            }
            for i in ids
        }

    def instalar(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import services.investigador.search_engine as motor

        for nombre in ("hybrid_search", "fts5_search", "like_search", "fetch_docs"):
            monkeypatch.setattr(motor, nombre, getattr(self, nombre))


def _buscar(**body: Any) -> SemanticSearchResponse:
    """Ejecuta la ruta con el motor ya sustituido y devuelve su respuesta."""
    import anyio

    from api.routes.search import SemanticSearchRequest, semantic_search

    peticion = SemanticSearchRequest(q="sap", **body)
    # ``ctx`` es lo que inyectaría ``require_any_auth``; la ruta solo lee de él
    # ``user_id``, para el log.
    return anyio.run(semantic_search, peticion, {"user_id": "test"})


class TestFuenteDerivadaDelCamino:
    """Criterios 2 y 4 de O0.6a, ejecutados aquí."""

    def test_con_fusion_la_fuente_es_rrf(self, monkeypatch: pytest.MonkeyPatch) -> None:
        motor = _MotorFalso(fused=[_doc("A", 0.03)], fts=[("Z", 1.0)], like=[("Z", 0.2)])
        motor.instalar(monkeypatch)
        resp = _buscar()
        assert resp.source == SOURCE_RRF
        assert [h.id_externo for h in resp.hits] == ["A"]
        # Y no ejecutó los caminos peores: la fuente no es una etiqueta puesta
        # encima de otro resultado.
        assert motor.llamadas == ["hybrid"]

    def test_sin_chunks_embebidos_la_fuente_es_fts_y_no_hay_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Criterio 4: con ``documento_chunks`` vacío ``hybrid_search`` devuelve
        ``[]``, la ruta sigue al FTS y responde ``source=fts`` sin error."""
        motor = _MotorFalso(fused=[], fts=[("B", 1.0), ("C", 0.5)])
        motor.instalar(monkeypatch)
        resp = _buscar()
        assert resp.source == SOURCE_FTS
        assert [h.id_externo for h in resp.hits] == ["B", "C"]
        assert motor.llamadas == ["hybrid", "fts"]

    def test_sin_fts_la_fuente_es_like(self, monkeypatch: pytest.MonkeyPatch) -> None:
        motor = _MotorFalso(fused=[], fts=[], like=[("D", 0.2)])
        motor.instalar(monkeypatch)
        resp = _buscar()
        assert resp.source == SOURCE_LIKE
        assert [h.id_externo for h in resp.hits] == ["D"]
        assert motor.llamadas == ["hybrid", "fts", "like"]

    @pytest.mark.parametrize(
        "motor",
        [
            _MotorFalso(fused=[_doc("A", 0.03)]),
            _MotorFalso(fts=[("B", 1.0)]),
            _MotorFalso(like=[("D", 0.2)]),
            _MotorFalso(),  # ningún camino encuentra nada
        ],
        ids=["rrf", "fts", "like", "vacio"],
    )
    def test_la_fuente_es_siempre_una_de_las_tres(
        self, motor: _MotorFalso, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        motor.instalar(monkeypatch)
        assert _buscar().source in SEARCH_SOURCES

    def test_el_top_k_del_cuerpo_recorta_la_fusion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        motor = _MotorFalso(fused=[_doc("A", 0.03), _doc("B", 0.02), _doc("C", 0.01)])
        motor.instalar(monkeypatch)
        resp = _buscar(top_k=2)
        assert [h.id_externo for h in resp.hits] == ["A", "B"]

    def test_la_fusion_normaliza_el_score_al_mejor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Lo que promete la descripción del campo para ``source=rrf``."""
        motor = _MotorFalso(fused=[_doc("A", 0.04), _doc("B", 0.02)])
        motor.instalar(monkeypatch)
        resp = _buscar()
        assert [h.score for h in resp.hits] == [1.0, 0.5]


class TestElDeslizadorLlegaAlMotor:
    """Criterio 6: ``alpha`` deja de morir en el DTO."""

    def test_alpha_del_cuerpo_viaja_a_la_fusion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        motor = _MotorFalso(fused=[_doc("A", 0.03)])
        motor.instalar(monkeypatch)
        _buscar(alpha=0.15)
        assert motor.alpha_recibido == pytest.approx(0.15)

    def test_sin_alpha_viaja_el_default_publicado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """El default del DTO (0.70) es el que gobierna la ruta. NO se hereda
        el ``None`` del RAG: son dos consumidores con dos comportamientos."""
        motor = _MotorFalso(fused=[_doc("A", 0.03)])
        motor.instalar(monkeypatch)
        _buscar()
        assert motor.alpha_recibido == pytest.approx(0.70)


class TestDisponibilidadDeEmbeddings:
    """``document_embeddings_available`` es lo que separa «fusioné» de «llamé a
    la fusión y me devolvió el orden del FTS»."""

    @staticmethod
    def _responde(monkeypatch: pytest.MonkeyPatch, fila: object) -> bool:
        import contextlib
        from collections.abc import Iterator

        import db.database as database

        class _Conn:
            def execute(self, sql: str, params: object = None) -> _Conn:
                assert "documento_chunks" in sql
                assert "embedding IS NOT NULL" in sql
                return self

            def fetchone(self) -> object:
                return fila

        @contextlib.contextmanager
        def _fake() -> Iterator[_Conn]:
            yield _Conn()

        monkeypatch.setattr(database, "connect_read", _fake)
        from db.search_backend import document_embeddings_available

        return document_embeddings_available()

    def test_con_un_chunk_embebido_dice_que_si(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._responde(monkeypatch, (1,)) is True

    def test_con_la_tabla_vacia_dice_que_no(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._responde(monkeypatch, None) is False

    def test_si_la_bd_falla_dice_que_no(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fail-closed: sin poder mirar, lo honesto es degradar a FTS y no
        etiquetar como ``rrf`` una fusión que quizá no ocurrió."""
        import db.database as database

        def _revienta() -> object:
            raise RuntimeError("sin BD")

        monkeypatch.setattr(database, "connect_read", _revienta)
        from db.search_backend import document_embeddings_available

        assert document_embeddings_available() is False


class TestPuertasDeLaFusion:
    """``hybrid_search`` devuelve ``[]`` en cada uno de los motivos por los que
    el camino RRF no existe hoy — y por eso el llamador puede degradar."""

    @staticmethod
    def _hybrid(
        monkeypatch: pytest.MonkeyPatch,
        *,
        modelo: bool = True,
        corpus: bool = True,
        encode_revienta: bool = False,
    ) -> list[dict[str, Any]]:
        import numpy as np

        import db.search_backend as backend
        import services.embeddings as emb
        from services.investigador.search_engine import hybrid_search

        monkeypatch.setattr(emb, "embeddings_available", lambda: modelo)

        def _encode(textos: list[str], **kw: Any) -> Any:
            if encode_revienta:
                raise RuntimeError("modelo roto")
            return np.zeros((1, 384))

        monkeypatch.setattr(emb, "encode_texts", _encode)
        monkeypatch.setattr(backend, "document_embeddings_available", lambda: corpus)
        monkeypatch.setattr(
            backend,
            "hybrid_search_docs",
            lambda *a, **k: [{"id_externo": "A", "rrf_score": 0.1}],
        )
        return hybrid_search("sap", 10, alpha=0.7)

    def test_sin_modelo_no_hay_fusion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._hybrid(monkeypatch, modelo=False) == []

    def test_sin_corpus_embebido_no_hay_fusion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._hybrid(monkeypatch, corpus=False) == []

    def test_si_no_se_puede_codificar_la_consulta_no_hay_fusion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self._hybrid(monkeypatch, encode_revienta=True) == []

    def test_con_modelo_y_corpus_si_hay_fusion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._hybrid(monkeypatch) == [{"id_externo": "A", "rrf_score": 0.1}]


class TestEscalaDelScorePublicada:
    """ADR-014 sobre el contrato público: la descripción de ``score`` no puede
    prometer una escala que dos de las tres fuentes no cumplen."""

    def test_la_descripcion_distingue_la_escala_de_cada_fuente(self) -> None:
        from api.routes.search import SemanticHit

        desc = SemanticHit.model_fields["score"].description or ""
        assert all(s in desc for s in SEARCH_SOURCES), "no nombra las tres fuentes"
        # ``like_fallback_search`` devuelve la constante 0.20 para todos los
        # resultados (db/repositories/licitaciones.py), así que "el mejor vale
        # 1 y el resto se escala contra él" era falso justo ahí.
        assert "0.2" in desc
